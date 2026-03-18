import asyncio
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from time import monotonic
from threading import Lock
from typing import Any, Dict, Optional

from app.utils import normalize_text


LOGGER = logging.getLogger("asr.model")
_MODEL_LOCK = Lock()
_MODEL_INSTANCE = None  # type: Optional["ASRTranscriber"]
_DEFAULT_MYANMAR_SCRIPT_PROMPT = "ကျေးဇူးပြု၍ မြန်မာဘာသာ စာသားကို မြန်မာအက္ခရာဖြင့်သာ ပြန်ရေးပါ။"


@dataclass(frozen=True)
class ModelSettings:
    model_size: str
    device_preference: str
    cuda_compute_type: str
    cpu_compute_type: str
    beam_size: int
    vad_filter: bool


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    return ModelSettings(
        model_size=os.getenv("WHISPER_MODEL_SIZE", "large-v3"),
        device_preference=os.getenv("WHISPER_DEVICE", "auto").lower(),
        cuda_compute_type=os.getenv("WHISPER_COMPUTE_TYPE_CUDA", "float16"),
        cpu_compute_type=os.getenv("WHISPER_COMPUTE_TYPE_CPU", "int8"),
        beam_size=max(1, int(os.getenv("WHISPER_BEAM_SIZE", "5"))),
        vad_filter=_read_bool_env("WHISPER_VAD_FILTER", True),
    )


class ASRTranscriber:
    def __init__(self, model: Any, device: str) -> None:
        self.model = model
        self.device = device

    async def transcribe(self, file_path: str, language: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._transcribe_sync, file_path, language)

    def _transcribe_sync(self, file_path: str, language: str) -> Dict[str, Any]:
        started_at = monotonic()
        settings = get_model_settings()
        kwargs = {"beam_size": settings.beam_size, "vad_filter": settings.vad_filter, "task": "transcribe"}
        if language != "auto":
            kwargs["language"] = language
        if language == "my":
            kwargs["initial_prompt"] = os.getenv("WHISPER_INITIAL_PROMPT_MY", _DEFAULT_MYANMAR_SCRIPT_PROMPT)

        LOGGER.info(
            "decode step=start file=%s language=%s device=%s beam=%s vad=%s",
            file_path,
            language,
            self.device,
            settings.beam_size,
            settings.vad_filter,
        )
        model_started_at = monotonic()
        segments, info = self.model.transcribe(file_path, **kwargs)
        model_prepare_elapsed_ms = int((monotonic() - model_started_at) * 1000)
        LOGGER.info("decode step=model_transcribe_ready elapsed_ms=%s", model_prepare_elapsed_ms)

        collect_started_at = monotonic()
        normalized_segments = []
        collected = []
        for segment in segments:
            segment_text = normalize_text(segment.text)
            if not segment_text:
                continue
            normalized_segments.append(
                {
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": segment_text.strip(),
                }
            )
            collected.append(segment_text)
        collect_elapsed_ms = int((monotonic() - collect_started_at) * 1000)
        total_elapsed_ms = int((monotonic() - started_at) * 1000)
        LOGGER.info(
            "decode step=segments_collected elapsed_ms=%s total_elapsed_ms=%s segment_count=%s",
            collect_elapsed_ms,
            total_elapsed_ms,
            len(normalized_segments),
        )

        return {
            "requested_language": language,
            "detected_language": getattr(info, "language", None),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
            "text": normalize_text(" ".join(collected)),
            "segments": normalized_segments,
        }


def _is_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def _build_whisper_model(device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    settings = get_model_settings()
    return WhisperModel(settings.model_size, device=device, compute_type=compute_type)


def get_transcriber() -> ASRTranscriber:
    global _MODEL_INSTANCE

    if _MODEL_INSTANCE is not None:
        return _MODEL_INSTANCE

    with _MODEL_LOCK:
        if _MODEL_INSTANCE is not None:
            return _MODEL_INSTANCE

        settings = get_model_settings()
        preferred_device = settings.device_preference
        if preferred_device == "auto":
            preferred_device = "cuda" if _is_cuda_available() else "cpu"

        try:
            if preferred_device == "cuda":
                model = _build_whisper_model("cuda", settings.cuda_compute_type)
                _MODEL_INSTANCE = ASRTranscriber(model=model, device="cuda")
            else:
                model = _build_whisper_model("cpu", settings.cpu_compute_type)
                _MODEL_INSTANCE = ASRTranscriber(model=model, device="cpu")
        except Exception:
            if preferred_device != "cuda":
                raise

            LOGGER.exception("cuda model initialization failed, falling back to cpu")
            model = _build_whisper_model("cpu", settings.cpu_compute_type)
            _MODEL_INSTANCE = ASRTranscriber(model=model, device="cpu")

        return _MODEL_INSTANCE


async def transcribe_audio(file_path: str, language: str) -> Dict[str, Any]:
    transcriber = get_transcriber()
    return await transcriber.transcribe(file_path=file_path, language=language)
