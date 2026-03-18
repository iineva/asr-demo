import asyncio
import logging
import os
import wave
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import Any, Dict, Optional

from app.utils import normalize_text


LOGGER = logging.getLogger("asr.model")
_MODEL_LOCK = Lock()
_WHISPER_MODEL_INSTANCE = None  # type: Optional["ASRTranscriber"]
_MMS_MODEL_INSTANCE = None  # type: Optional["MmsTranscriber"]
_ROUTER_INSTANCE = None  # type: Optional["TranscriberRouter"]
_DEFAULT_MYANMAR_SCRIPT_PROMPT = "ကျေးဇူးပြု၍ မြန်မာဘာသာ စာသားကို မြန်မာအက္ခရာဖြင့်သာ ပြန်ရေးပါ။"
_CPU_SLOW_MODEL_WARNED = False
_MMS_TARGET_LANG_MY = "mya"


@dataclass(frozen=True)
class ModelSettings:
    model_size: str
    device_preference: str
    cuda_compute_type: str
    cpu_compute_type: str
    beam_size: int
    vad_filter: bool


@dataclass(frozen=True)
class MmsSettings:
    model_id: str
    device: str
    torch_dtype: str


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_model_size() -> str:
    configured_model_size = os.getenv("WHISPER_MODEL_SIZE")
    if configured_model_size:
        return configured_model_size

    default_model_size = "large-v3"
    cpu_default_model_size = os.getenv("WHISPER_MODEL_SIZE_CPU_DEFAULT", "medium")
    if _is_cuda_available():
        return default_model_size
    return cpu_default_model_size


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    global _CPU_SLOW_MODEL_WARNED
    model_size = _resolve_model_size()
    if not _is_cuda_available() and model_size == "large-v3" and not _CPU_SLOW_MODEL_WARNED:
        LOGGER.warning(
            "running large-v3 on cpu may be very slow; consider WHISPER_MODEL_SIZE=medium or small for faster responses"
        )
        _CPU_SLOW_MODEL_WARNED = True

    return ModelSettings(
        model_size=model_size,
        device_preference=os.getenv("WHISPER_DEVICE", "auto").lower(),
        cuda_compute_type=os.getenv("WHISPER_COMPUTE_TYPE_CUDA", "float16"),
        cpu_compute_type=os.getenv("WHISPER_COMPUTE_TYPE_CPU", "int8"),
        beam_size=max(1, int(os.getenv("WHISPER_BEAM_SIZE", "2"))),
        vad_filter=_read_bool_env("WHISPER_VAD_FILTER", True),
    )


@lru_cache(maxsize=1)
def get_mms_settings() -> MmsSettings:
    preferred_device = os.getenv("MMS_DEVICE", "auto").lower()
    if preferred_device == "auto":
        if _is_cuda_available():
            preferred_device = "cuda"
        elif _is_mps_available():
            preferred_device = "mps"
        else:
            preferred_device = "cpu"

    return MmsSettings(
        model_id=os.getenv("MMS_MODEL_ID", "facebook/mms-1b-all"),
        device=preferred_device,
        torch_dtype=os.getenv("MMS_TORCH_DTYPE", "float32").lower(),
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
        kwargs = self._build_transcribe_kwargs(language, settings)

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
        if language == "auto" and getattr(info, "language", None) == "my":
            first_pass_text, _ = self._collect_segments(segments)
            if not first_pass_text:
                LOGGER.info("decode step=retry_with_myanmar_prompt file=%s", file_path)
                segments, info = self.model.transcribe(file_path, **self._build_transcribe_kwargs("my", settings))

        model_prepare_elapsed_ms = int((monotonic() - model_started_at) * 1000)
        LOGGER.info("decode step=model_transcribe_ready elapsed_ms=%s", model_prepare_elapsed_ms)
        if settings.vad_filter:
            vad_metrics = self.build_vad_metrics(info=info, vad_elapsed_ms=model_prepare_elapsed_ms)
            if vad_metrics is not None:
                LOGGER.info(
                    "decode step=vad_done elapsed_ms=%s input_duration_ms=%s speech_duration_ms=%s removed_silence_ms=%s",
                    vad_metrics["vad_elapsed_ms"],
                    vad_metrics["input_duration_ms"],
                    vad_metrics["speech_duration_ms"],
                    vad_metrics["removed_silence_ms"],
                )

        collect_started_at = monotonic()
        text, normalized_segments = self._collect_segments(segments)
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
            "text": text,
            "segments": normalized_segments,
            "timing": {
                "vad_ms": vad_metrics["vad_elapsed_ms"] if settings.vad_filter and vad_metrics is not None else 0,
            },
        }

    def _build_transcribe_kwargs(self, language: str, settings: ModelSettings) -> Dict[str, Any]:
        kwargs = {"beam_size": settings.beam_size, "vad_filter": settings.vad_filter, "task": "transcribe"}
        if language != "auto":
            kwargs["language"] = language
        if language == "my":
            kwargs["initial_prompt"] = os.getenv("WHISPER_INITIAL_PROMPT_MY", _DEFAULT_MYANMAR_SCRIPT_PROMPT)
        return kwargs

    def _collect_segments(self, segments: Any) -> tuple[str, list[Dict[str, Any]]]:
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
        return normalize_text(" ".join(collected)), normalized_segments

    @staticmethod
    def build_vad_metrics(info: Any, vad_elapsed_ms: int) -> Optional[Dict[str, int]]:
        input_duration = getattr(info, "duration", None)
        speech_duration = getattr(info, "duration_after_vad", None)
        if input_duration is None or speech_duration is None:
            return None

        input_duration_ms = max(0, int(round(float(input_duration) * 1000)))
        speech_duration_ms = max(0, int(round(float(speech_duration) * 1000)))
        return {
            "vad_elapsed_ms": max(0, int(vad_elapsed_ms)),
            "input_duration_ms": input_duration_ms,
            "speech_duration_ms": speech_duration_ms,
            "removed_silence_ms": max(0, input_duration_ms - speech_duration_ms),
        }


class MmsTranscriber:
    def __init__(
        self,
        processor: Any,
        model: Any,
        device: str,
        *,
        audio_loader: Optional[Any] = None,
        duration_getter: Optional[Any] = None,
    ) -> None:
        self.processor = processor
        self.model = model
        self.device = device
        self.audio_loader = audio_loader or _load_audio_waveform
        self.duration_getter = duration_getter or _get_audio_duration_seconds

    async def transcribe(self, file_path: str, language: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._transcribe_sync, file_path, language)

    def _transcribe_sync(self, file_path: str, language: str) -> Dict[str, Any]:
        started_at = monotonic()
        LOGGER.info("mms decode step=start file=%s language=%s device=%s", file_path, language, self.device)
        waveform, sample_rate = self.audio_loader(file_path)
        inputs = self.processor(waveform.squeeze(0), sampling_rate=sample_rate, return_tensors="pt")
        prepared_inputs = _prepare_model_inputs(inputs, self.device)
        outputs = self.model(**prepared_inputs)
        generated_ids = outputs.logits.argmax(dim=-1)

        text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        result = self._normalize_result(text, self.duration_getter(file_path), language)
        LOGGER.info(
            "mms decode step=done elapsed_ms=%s text_len=%s",
            int((monotonic() - started_at) * 1000),
            len(result.get("text", "")),
        )
        return result

    def _normalize_result(self, text: str, duration_seconds: float, language: str) -> Dict[str, Any]:
        normalized_text = normalize_text(text)
        segments = []
        if normalized_text:
            segments.append(
                {
                    "start": 0.0,
                    "end": round(float(duration_seconds), 3),
                    "text": normalized_text,
                }
            )

        return {
            "requested_language": language,
            "detected_language": "my",
            "language_probability": 1.0,
            "text": normalized_text,
            "segments": segments,
            "timing": {
                "vad_ms": 0,
            },
        }


class TranscriberRouter:
    def __init__(self, whisper_getter: Any, mms_getter: Any) -> None:
        self.whisper_getter = whisper_getter
        self.mms_getter = mms_getter

    async def transcribe(self, file_path: str, language: str) -> Dict[str, Any]:
        if language == "my":
            return await self.mms_getter().transcribe(file_path, language)
        return await self.whisper_getter().transcribe(file_path, language)


def _is_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def _is_mps_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())


def _build_whisper_model(device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    settings = get_model_settings()
    return WhisperModel(settings.model_size, device=device, compute_type=compute_type)


def _load_audio_waveform(file_path: str) -> Any:
    import torchaudio

    return torchaudio.load(file_path)


def _get_audio_duration_seconds(file_path: str) -> float:
    with wave.open(file_path, "rb") as audio_file:
        frame_count = audio_file.getnframes()
        frame_rate = audio_file.getframerate()
    if frame_rate <= 0:
        return 0.0
    return frame_count / frame_rate


def _prepare_model_inputs(inputs: Any, device: str) -> Dict[str, Any]:
    prepared = {}
    for key, value in dict(inputs).items():
        if hasattr(value, "to"):
            prepared[key] = value.to(device)
        else:
            prepared[key] = value
    return prepared


def _create_whisper_transcriber() -> ASRTranscriber:
    settings = get_model_settings()
    preferred_device = settings.device_preference
    if preferred_device == "auto":
        preferred_device = "cuda" if _is_cuda_available() else "cpu"

    try:
        started_at = monotonic()
        LOGGER.info("whisper runtime init step=start preferred_device=%s model_size=%s", preferred_device, settings.model_size)
        if preferred_device == "cuda":
            model = _build_whisper_model("cuda", settings.cuda_compute_type)
            transcriber = ASRTranscriber(model=model, device="cuda")
        else:
            model = _build_whisper_model("cpu", settings.cpu_compute_type)
            transcriber = ASRTranscriber(model=model, device="cpu")
        LOGGER.info(
            "whisper runtime init step=done elapsed_ms=%s device=%s model_size=%s",
            int((monotonic() - started_at) * 1000),
            transcriber.device,
            settings.model_size,
        )
        return transcriber
    except Exception:
        if preferred_device != "cuda":
            raise

        LOGGER.exception("cuda model initialization failed, falling back to cpu")
        started_at = monotonic()
        LOGGER.info("whisper runtime init step=retry_cpu_start model_size=%s", settings.model_size)
        model = _build_whisper_model("cpu", settings.cpu_compute_type)
        transcriber = ASRTranscriber(model=model, device="cpu")
        LOGGER.info(
            "whisper runtime init step=retry_cpu_done elapsed_ms=%s device=%s model_size=%s",
            int((monotonic() - started_at) * 1000),
            transcriber.device,
            settings.model_size,
        )
        return transcriber


def _load_mms_processor(model_id: str, target_lang: str) -> Any:
    from transformers import AutoProcessor

    return AutoProcessor.from_pretrained(model_id, target_lang=target_lang)


def _load_mms_model(model_id: str, target_lang: str) -> Any:
    from transformers import AutoModelForCTC

    return AutoModelForCTC.from_pretrained(model_id, target_lang=target_lang, ignore_mismatched_sizes=True)


def _create_mms_transcriber() -> MmsTranscriber:
    settings = get_mms_settings()
    target_lang = _MMS_TARGET_LANG_MY
    started_at = monotonic()
    LOGGER.info(
        "mms runtime init step=start model_id=%s device=%s target_lang=%s",
        settings.model_id,
        settings.device,
        target_lang,
    )
    processor = _load_mms_processor(settings.model_id, target_lang)
    model = _load_mms_model(settings.model_id, target_lang)
    if hasattr(model, "load_adapter"):
        model.load_adapter(target_lang)
    if hasattr(model, "to"):
        model = model.to(settings.device)
    LOGGER.info(
        "mms runtime init step=done elapsed_ms=%s model_id=%s device=%s torch_dtype=%s target_lang=%s",
        int((monotonic() - started_at) * 1000),
        settings.model_id,
        settings.device,
        settings.torch_dtype,
        target_lang,
    )
    return MmsTranscriber(processor=processor, model=model, device=settings.device)


def get_whisper_transcriber() -> ASRTranscriber:
    global _WHISPER_MODEL_INSTANCE

    if _WHISPER_MODEL_INSTANCE is not None:
        return _WHISPER_MODEL_INSTANCE

    with _MODEL_LOCK:
        if _WHISPER_MODEL_INSTANCE is None:
            _WHISPER_MODEL_INSTANCE = _create_whisper_transcriber()
        return _WHISPER_MODEL_INSTANCE


def get_mms_transcriber() -> MmsTranscriber:
    global _MMS_MODEL_INSTANCE

    if _MMS_MODEL_INSTANCE is not None:
        return _MMS_MODEL_INSTANCE

    with _MODEL_LOCK:
        if _MMS_MODEL_INSTANCE is None:
            _MMS_MODEL_INSTANCE = _create_mms_transcriber()
        return _MMS_MODEL_INSTANCE


def get_transcriber_router() -> TranscriberRouter:
    global _ROUTER_INSTANCE

    if _ROUTER_INSTANCE is not None:
        return _ROUTER_INSTANCE

    with _MODEL_LOCK:
        if _ROUTER_INSTANCE is None:
            _ROUTER_INSTANCE = TranscriberRouter(
                whisper_getter=get_whisper_transcriber,
                mms_getter=get_mms_transcriber,
            )
        return _ROUTER_INSTANCE


def get_transcriber() -> TranscriberRouter:
    return get_transcriber_router()


async def transcribe_audio(file_path: str, language: str) -> Dict[str, Any]:
    transcriber = get_transcriber()
    return await transcriber.transcribe(file_path=file_path, language=language)
