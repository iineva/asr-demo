import asyncio
import json
import logging
import os
import traceback
import uuid
import wave
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.asr import get_whisper_transcriber, transcribe_audio
from app.streaming import (
    StreamingTranscriptionSession,
    append_bytes,
    iter_file_upload_events,
    mime_type_to_extension,
)
from app.utils import (
    FFmpegError,
    convert_audio_to_wav,
    ensure_directory,
    remove_file_safely,
    save_upload_file,
    validate_language,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and isinstance(record.exc_info, tuple):
            exc_type, exc_value, exc_traceback = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else "",
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
            }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root_logger.addHandler(handler)


configure_logging()
LOGGER = logging.getLogger("asr.api")


def attach_timing(result: Dict[str, Any], *, convert_ms: int, decode_ms: int) -> Dict[str, Any]:
    timing = dict(result.get("timing") or {})
    timing["convert_ms"] = convert_ms
    timing["vad_ms"] = int(timing.get("vad_ms") or 0)
    timing["decode_ms"] = decode_ms
    enriched = dict(result)
    enriched["timing"] = timing
    return enriched


async def run_transcription_with_lazy_conversion(
    source_path: Path,
    requested_language: str,
    settings: Dict[str, Any],
) -> tuple[Dict[str, Any], int, Optional[Path]]:
    if requested_language == "my":
        convert_started_at = monotonic()
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        convert_elapsed_ms = int((monotonic() - convert_started_at) * 1000)
        result = await asyncio.wait_for(
            transcribe_audio(str(wav_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
        )
        return result, convert_elapsed_ms, wav_path

    if requested_language != "auto":
        result = await asyncio.wait_for(
            transcribe_audio(str(source_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
        )
        return result, 0, None

    whisper_transcriber = await asyncio.to_thread(get_whisper_transcriber)
    detection = await whisper_transcriber.detect_language(str(source_path))
    detected_language = detection.get("language")
    detected_probability = detection.get("language_probability", 0.0)

    if detected_language == "my":
        convert_started_at = monotonic()
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        convert_elapsed_ms = int((monotonic() - convert_started_at) * 1000)
        mms_result = await asyncio.wait_for(
            transcribe_audio(str(wav_path), "my"),
            timeout=settings["transcribe_timeout_seconds"],
        )
        rerouted_result = dict(mms_result)
        rerouted_result["requested_language"] = "auto"
        rerouted_result["detected_language"] = "my"
        rerouted_result["language_probability"] = detected_probability
        return rerouted_result, convert_elapsed_ms, wav_path

    whisper_language = detected_language or "auto"
    whisper_result = await asyncio.wait_for(
        whisper_transcriber.transcribe(str(source_path), whisper_language),
        timeout=settings["transcribe_timeout_seconds"],
    )
    if detected_language is None:
        return whisper_result, 0, None

    rerouted_result = dict(whisper_result)
    rerouted_result["requested_language"] = "auto"
    rerouted_result["detected_language"] = detected_language
    rerouted_result["language_probability"] = detected_probability
    return rerouted_result, 0, None


def get_settings() -> Dict[str, Any]:
    ws_chunk_ms = max(5, int(os.getenv("WS_CHUNK_MS", "20")))
    ws_audio_sample_rate = max(8000, int(os.getenv("WS_AUDIO_SAMPLE_RATE", "16000")))
    ws_audio_channels = max(1, int(os.getenv("WS_AUDIO_CHANNELS", "1")))
    ws_audio_bytes_per_sample = max(1, int(os.getenv("WS_AUDIO_BYTES_PER_SAMPLE", "2")))
    ws_chunk_bytes = max(
        1,
        int((ws_audio_sample_rate * ws_audio_channels * ws_audio_bytes_per_sample * ws_chunk_ms) / 1000),
    )

    return {
        "service_name": os.getenv("SERVICE_NAME", "asr-service"),
        "upload_dir": os.getenv("UPLOAD_DIR", "uploads"),
        "output_dir": os.getenv("OUTPUT_DIR", "outputs"),
        "max_upload_size_bytes": int(float(os.getenv("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024),
        "ffmpeg_timeout_seconds": int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "300")),
        "transcribe_timeout_seconds": int(os.getenv("TRANSCRIBE_TIMEOUT_SECONDS", "300")),
        "ws_partial_transcribe_timeout_seconds": max(
            1,
            int(os.getenv("WS_PARTIAL_TRANSCRIBE_TIMEOUT_SECONDS", "30")),
        ),
        "ws_partial_window_seconds": max(1, int(os.getenv("WS_PARTIAL_WINDOW_SECONDS", "20"))),
        "preload_model": os.getenv("PRELOAD_MODEL_ON_STARTUP", "true").lower() == "true",
        "ws_chunk_ms": ws_chunk_ms,
        "ws_chunk_bytes": ws_chunk_bytes,
        "ws_audio_sample_rate": ws_audio_sample_rate,
        "ws_audio_channels": ws_audio_channels,
        "ws_audio_bytes_per_sample": ws_audio_bytes_per_sample,
        "ws_partial_min_bytes": max(1, int(os.getenv("WS_PARTIAL_MIN_BYTES", str(ws_chunk_bytes)))),
        "ws_partial_min_interval_ms": max(0, int(os.getenv("WS_PARTIAL_MIN_INTERVAL_MS", str(ws_chunk_ms)))),
    }


def is_pcm_stream(mime_type: str) -> bool:
    normalized = (mime_type or "").lower()
    return "pcm" in normalized or "audio/l16" in normalized


def is_opus_stream(mime_type: str) -> bool:
    normalized = (mime_type or "").lower()
    return "opus" in normalized or "audio/webm" in normalized or "audio/ogg" in normalized


def resolve_opus_container_format(mime_type: str) -> str:
    normalized = (mime_type or "").lower()
    if "audio/ogg" in normalized:
        return "ogg"
    return "webm"


def write_pcm16le_wav(
    *,
    target_path: Path,
    pcm_payload: bytes,
    sample_rate: int,
    channels: int,
    bytes_per_sample: int,
) -> None:
    with wave.open(str(target_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bytes_per_sample)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_payload)


class OpusPcmStreamDecoder:
    def __init__(self, *, mime_type: str, sample_rate: int, channels: int) -> None:
        self.mime_type = mime_type
        self.sample_rate = sample_rate
        self.channels = channels
        self.process: Optional[asyncio.subprocess.Process] = None
        self.reader_task: Optional[asyncio.Task[None]] = None
        self._pcm_buffer = bytearray()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        container_format = resolve_opus_container_format(self.mime_type)
        self.process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            container_format,
            "-i",
            "pipe:0",
            "-ac",
            str(self.channels),
            "-ar",
            str(self.sample_rate),
            "-f",
            "s16le",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.reader_task = asyncio.create_task(self._read_stdout())

    async def _read_stdout(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        while True:
            chunk = await self.process.stdout.read(4096)
            if not chunk:
                break
            async with self._lock:
                self._pcm_buffer.extend(chunk)

    async def feed(self, payload: bytes) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("opus decoder not started")
        self.process.stdin.write(payload)
        await self.process.stdin.drain()

    async def snapshot_pcm(self) -> bytes:
        async with self._lock:
            return bytes(self._pcm_buffer)

    async def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin and not self.process.stdin.is_closing():
            self.process.stdin.close()
        with suppress(Exception):
            if self.reader_task is not None:
                await self.reader_task
        with suppress(Exception):
            await self.process.wait()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    ensure_directory(settings["upload_dir"])
    ensure_directory(settings["output_dir"])
    if settings["preload_model"]:
        try:
            await asyncio.to_thread(get_whisper_transcriber)
        except Exception:
            LOGGER.exception("model preload failed")
    yield


app = FastAPI(title="ASR Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")


@app.get("/health")
async def health_legacy() -> Dict[str, Any]:
    return {"success": True, "status": "ok"}


@api_router.get("/health")
async def health() -> Dict[str, Any]:
    return {"success": True, "status": "ok"}


@api_router.get("/ready")
async def ready() -> JSONResponse:
    try:
        await asyncio.to_thread(get_whisper_transcriber)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"success": False, "status": "degraded", "detail": str(exc)})
    return JSONResponse(status_code=200, content={"success": True, "status": "ready"})


@api_router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")) -> Dict[str, Any]:
    settings = get_settings()
    request_id = uuid.uuid4().hex
    last_step = "init"
    try:
        requested_language = validate_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]

    try:
        start_time = monotonic()
        last_step = "upload_start"
        LOGGER.info(
            "transcribe request_id=%s step=upload_start filename=%s language=%s",
            request_id,
            file.filename,
            requested_language,
        )
        source_path = await save_upload_file(file, settings["upload_dir"], settings["max_upload_size_bytes"])
        last_step = "upload_done"
        upload_elapsed_ms = int((monotonic() - start_time) * 1000)
        LOGGER.info(
            "transcribe request_id=%s step=upload_done elapsed_ms=%s path=%s size_bytes=%s",
            request_id,
            upload_elapsed_ms,
            source_path,
            source_path.stat().st_size if source_path.exists() else 0,
        )
        decode_started_at = monotonic()
        last_step = "decode_start"
        LOGGER.info("transcribe request_id=%s step=decode_start source=%s language=%s", request_id, source_path, requested_language)
        result, convert_elapsed_ms, wav_path = await run_transcription_with_lazy_conversion(
            source_path,
            requested_language,
            settings,
        )
        transcribe_elapsed_ms = int((monotonic() - decode_started_at) * 1000)
        result = attach_timing(result, convert_ms=convert_elapsed_ms, decode_ms=transcribe_elapsed_ms)
        last_step = "decode_done"
        LOGGER.info(
            "transcribe request_id=%s step=conversion_summary convert_elapsed_ms=%s wav=%s",
            request_id,
            convert_elapsed_ms,
            wav_path,
        )
        LOGGER.info(
            "transcribe request_id=%s step=decode_done elapsed_ms=%s text_len=%s",
            request_id,
            transcribe_elapsed_ms,
            len(result.get("text", "")),
        )
        LOGGER.info(
            "transcribe request_id=%s timing: upload=%sms convert=%sms decode=%sms total=%sms",
            request_id,
            upload_elapsed_ms,
            convert_elapsed_ms,
            transcribe_elapsed_ms,
            int((monotonic() - start_time) * 1000),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FFmpegError as exc:
        LOGGER.warning("transcribe request_id=%s last_step=%s ffmpeg_error=%s", request_id, last_step, str(exc))
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {exc}") from exc
    except asyncio.TimeoutError as exc:
        LOGGER.warning(
            "transcribe request_id=%s last_step=%s timeout_seconds=%s",
            request_id,
            last_step,
            settings["transcribe_timeout_seconds"],
        )
        raise HTTPException(status_code=500, detail="transcription timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception(
            "transcribe request_id=%s step=failed last_step=%s total_elapsed_ms=%s",
            request_id,
            last_step,
            int((monotonic() - start_time) * 1000),
        )
        raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc
    finally:
        remove_file_safely(source_path)

    return {"success": True, "result": result}


@api_router.post("/transcribe/stream")
async def transcribe_stream(file: UploadFile = File(...), language: str = Form("auto")) -> StreamingResponse:
    settings = get_settings()
    request_id = uuid.uuid4().hex
    last_step = "init"
    try:
        requested_language = validate_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]
    session = StreamingTranscriptionSession(language=requested_language)

    stream_started_at = monotonic()
    try:
        last_step = "upload_start"
        LOGGER.info(
            "transcribe_stream request_id=%s step=upload_start filename=%s language=%s",
            request_id,
            file.filename,
            requested_language,
        )
        source_path = await save_upload_file(file, settings["upload_dir"], settings["max_upload_size_bytes"])
        last_step = "upload_done"
        LOGGER.info(
            "transcribe_stream request_id=%s step=upload_done elapsed_ms=%s path=%s size_bytes=%s",
            request_id,
            int((monotonic() - stream_started_at) * 1000),
            source_path,
            source_path.stat().st_size if source_path.exists() else 0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def run_transcription() -> Dict[str, Any]:
        nonlocal wav_path
        convert_started_at = monotonic()
        nonlocal last_step
        last_step = "convert_start"
        LOGGER.info("transcribe_stream request_id=%s step=convert_start source=%s", request_id, source_path)
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        LOGGER.info(
            "transcribe_stream request_id=%s step=convert_done elapsed_ms=%s wav=%s",
            request_id,
            int((monotonic() - convert_started_at) * 1000),
            wav_path,
        )
        decode_started_at = monotonic()
        last_step = "decode_start"
        LOGGER.info("transcribe_stream request_id=%s step=decode_start wav=%s", request_id, wav_path)
        result = await asyncio.wait_for(
            transcribe_audio(str(wav_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
        )
        result = attach_timing(
            result,
            convert_ms=int((monotonic() - convert_started_at) * 1000),
            decode_ms=int((monotonic() - decode_started_at) * 1000),
        )
        LOGGER.info(
            "transcribe_stream request_id=%s step=decode_done elapsed_ms=%s text_len=%s total_elapsed_ms=%s",
            request_id,
            result["timing"]["decode_ms"],
            len(result.get("text", "")),
            int((monotonic() - stream_started_at) * 1000),
        )
        last_step = "decode_done"
        return result

    async def event_stream():
        try:
            async for event in iter_file_upload_events(session=session, transcribe_result=run_transcription):
                yield event
        except ValueError as exc:
            yield (json.dumps(session.emit_error(str(exc)), ensure_ascii=False) + "\n").encode("utf-8")
        except FFmpegError as exc:
            LOGGER.warning("transcribe_stream request_id=%s last_step=%s ffmpeg_error=%s", request_id, last_step, str(exc))
            yield (json.dumps(session.emit_error(f"ffmpeg failed: {exc}"), ensure_ascii=False) + "\n").encode("utf-8")
        except asyncio.TimeoutError:
            LOGGER.warning(
                "transcribe_stream request_id=%s last_step=%s timeout_seconds=%s",
                request_id,
                last_step,
                settings["transcribe_timeout_seconds"],
            )
            yield (json.dumps(session.emit_error("transcription timed out"), ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as exc:
            LOGGER.exception(
                "transcribe_stream request_id=%s step=failed last_step=%s total_elapsed_ms=%s",
                request_id,
                last_step,
                int((monotonic() - stream_started_at) * 1000),
            )
            yield (json.dumps(session.emit_error(f"transcription failed: {exc}"), ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
        finally:
            remove_file_safely(wav_path)
            remove_file_safely(source_path)

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@api_router.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]
    session: Optional[StreamingTranscriptionSession] = None
    requested_language = "auto"
    mime_type = "audio/webm"
    received_bytes = 0
    last_partial_bytes = 0
    last_partial_at = 0.0
    is_pcm_input = False
    is_opus_input = False
    pcm_buffer = bytearray()
    partial_wav_path = None  # type: Optional[Path]
    opus_decoder = None  # type: Optional[OpusPcmStreamDecoder]

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                payload = json.loads(message["text"])
                if payload.get("type") == "start":
                    if opus_decoder is not None:
                        await opus_decoder.close()
                        opus_decoder = None
                    requested_language = validate_language(payload.get("language", "auto"))
                    mime_type = payload.get("mime_type", "audio/webm")
                    session = StreamingTranscriptionSession(language=requested_language)
                    is_pcm_input = is_pcm_stream(mime_type)
                    is_opus_input = is_opus_stream(mime_type) and not is_pcm_input
                    pcm_buffer = bytearray()
                    if is_pcm_input or is_opus_input:
                        source_path = None
                    else:
                        source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"
                        source_path.touch(exist_ok=False)
                    if is_opus_input:
                        opus_decoder = OpusPcmStreamDecoder(
                            mime_type=mime_type,
                            sample_rate=settings["ws_audio_sample_rate"],
                            channels=settings["ws_audio_channels"],
                        )
                        await opus_decoder.start()
                    LOGGER.info(
                        "ws_transcribe step=session_started session_id=%s language=%s mime_type=%s stream_mode=%s",
                        session.session_id,
                        requested_language,
                        mime_type,
                        "pcm" if is_pcm_input else ("opus" if is_opus_input else "container"),
                    )
                    received_bytes = 0
                    last_partial_bytes = 0
                    last_partial_at = 0.0
                    await websocket.send_json(session.emit_progress("queued"))
                    continue

                if payload.get("type") == "finish":
                    if session is None:
                        await websocket.send_json(
                            StreamingTranscriptionSession(language=requested_language).emit_error("session not started")
                        )
                        break

                    if source_path is None and not is_pcm_input and not is_opus_input:
                        source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"
                        source_path.touch(exist_ok=False)
                    if received_bytes <= 0:
                        await websocket.send_json(session.emit_error("audio stream is empty"))
                        break
                    convert_started_at = monotonic()
                    if is_pcm_input or is_opus_input:
                        if is_opus_input and opus_decoder is not None:
                            await opus_decoder.close()
                            pcm_buffer = bytearray(await opus_decoder.snapshot_pcm())
                            opus_decoder = None
                        if is_opus_input and not pcm_buffer:
                            await websocket.send_json(session.emit_error("opus stream decode produced empty pcm"))
                            break
                        wav_path = Path(settings["output_dir"]) / f"{uuid.uuid4().hex}.wav"
                        write_pcm16le_wav(
                            target_path=wav_path,
                            pcm_payload=bytes(pcm_buffer),
                            sample_rate=settings["ws_audio_sample_rate"],
                            channels=settings["ws_audio_channels"],
                            bytes_per_sample=settings["ws_audio_bytes_per_sample"],
                        )
                        LOGGER.info(
                            "ws_transcribe step=final_pcm_ready session_id=%s elapsed_ms=%s wav=%s",
                            session.session_id,
                            int((monotonic() - convert_started_at) * 1000),
                            wav_path,
                        )
                    else:
                        LOGGER.info("ws_transcribe step=final_convert_start session_id=%s source=%s", session.session_id, source_path)
                        wav_path = await convert_audio_to_wav(
                            str(source_path),
                            settings["output_dir"],
                            settings["ffmpeg_timeout_seconds"],
                        )
                        LOGGER.info(
                            "ws_transcribe step=final_convert_done session_id=%s elapsed_ms=%s wav=%s",
                            session.session_id,
                            int((monotonic() - convert_started_at) * 1000),
                            wav_path,
                        )
                    decode_started_at = monotonic()
                    LOGGER.info("ws_transcribe step=final_decode_start session_id=%s", session.session_id)
                    result = await asyncio.wait_for(
                        transcribe_audio(str(wav_path), requested_language),
                        timeout=settings["transcribe_timeout_seconds"],
                    )
                    result = attach_timing(
                        result,
                        convert_ms=int((monotonic() - convert_started_at) * 1000),
                        decode_ms=int((monotonic() - decode_started_at) * 1000),
                    )
                    LOGGER.info(
                        "ws_transcribe step=final_decode_done session_id=%s elapsed_ms=%s text_len=%s",
                        session.session_id,
                        result["timing"]["decode_ms"],
                        len(result.get("text", "")),
                    )
                    final_segments = result.get("segments", [])
                    detected_language = result.get("detected_language") or requested_language
                    session.latest_language = detected_language
                    pending_segments = final_segments[len(session.final_segments) :]
                    if pending_segments:
                        session.final_segments.extend(segment.copy() for segment in pending_segments)
                        tail_segment = pending_segments[-1]
                        await websocket.send_json(
                            {
                                "type": "final_segment",
                                "sequence": session._next_sequence(),
                                "session_id": session.session_id,
                                "text": result.get("text", tail_segment.get("text", "")),
                                "start": float(pending_segments[0].get("start", 0.0) or 0.0),
                                "end": float(tail_segment.get("end", 0.0) or 0.0),
                                "is_final": True,
                                "language": detected_language,
                                "detail": None,
                            }
                        )
                    await websocket.send_json(session.emit_completed(result))
                    break

                continue

            if "bytes" in message and message["bytes"] is not None:
                if session is None:
                    await websocket.send_json(
                        StreamingTranscriptionSession(language=requested_language).emit_error("session not started")
                    )
                    break
                chunk = message["bytes"]
                if not chunk:
                    continue
                if source_path is None:
                    if is_pcm_input:
                        pcm_buffer.extend(chunk)
                    elif is_opus_input:
                        if opus_decoder is None:
                            await websocket.send_json(session.emit_error("opus decoder not initialized"))
                            break
                        await opus_decoder.feed(chunk)
                        pcm_buffer = bytearray(await opus_decoder.snapshot_pcm())
                    else:
                        source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"
                        source_path.touch(exist_ok=False)
                        append_bytes(source_path, chunk)
                else:
                    if is_pcm_input:
                        pcm_buffer.extend(chunk)
                    elif is_opus_input:
                        if opus_decoder is None:
                            await websocket.send_json(session.emit_error("opus decoder not initialized"))
                            break
                        await opus_decoder.feed(chunk)
                        pcm_buffer = bytearray(await opus_decoder.snapshot_pcm())
                    else:
                        append_bytes(source_path, chunk)
                received_bytes += len(chunk)
                current_size = received_bytes
                LOGGER.info(
                    "ws_transcribe step=chunk_received session_id=%s bytes_received=%s chunk_size=%s",
                    session.session_id,
                    current_size,
                    len(chunk),
                )

                bytes_since_last_partial = current_size - last_partial_bytes
                elapsed_since_last_partial_ms = int((monotonic() - last_partial_at) * 1000) if last_partial_at else None
                if (
                    bytes_since_last_partial < settings["ws_partial_min_bytes"]
                    and (
                        elapsed_since_last_partial_ms is None
                        or elapsed_since_last_partial_ms < settings["ws_partial_min_interval_ms"]
                    )
                ):
                    await websocket.send_json(session.emit_progress("partial_segment", detail={"bytes_received": current_size}))
                    continue

                try:
                    partial_convert_started_at = monotonic()
                    if is_pcm_input or is_opus_input:
                        if is_opus_input and opus_decoder is not None:
                            pcm_buffer = bytearray(await opus_decoder.snapshot_pcm())
                        bytes_per_second = (
                            settings["ws_audio_sample_rate"]
                            * settings["ws_audio_channels"]
                            * settings["ws_audio_bytes_per_sample"]
                        )
                        tail_bytes = max(1, bytes_per_second * settings["ws_partial_window_seconds"])
                        partial_payload = bytes(pcm_buffer[-tail_bytes:])
                        partial_wav_path = Path(settings["output_dir"]) / f"{uuid.uuid4().hex}.wav"
                        write_pcm16le_wav(
                            target_path=partial_wav_path,
                            pcm_payload=partial_payload,
                            sample_rate=settings["ws_audio_sample_rate"],
                            channels=settings["ws_audio_channels"],
                            bytes_per_sample=settings["ws_audio_bytes_per_sample"],
                        )
                        wav_path = partial_wav_path
                    else:
                        wav_path = await convert_audio_to_wav(
                            str(source_path),
                            settings["output_dir"],
                            settings["ffmpeg_timeout_seconds"],
                            tail_seconds=settings["ws_partial_window_seconds"],
                        )
                    partial_convert_elapsed_ms = int((monotonic() - partial_convert_started_at) * 1000)
                    partial_decode_started_at = monotonic()
                    result = await asyncio.wait_for(
                        transcribe_audio(str(wav_path), requested_language),
                        timeout=settings["ws_partial_transcribe_timeout_seconds"],
                    )
                    partial_decode_elapsed_ms = int((monotonic() - partial_decode_started_at) * 1000)
                    emitted = session.apply_transcription_result(result)
                    LOGGER.info(
                        "ws_transcribe step=partial_decoded session_id=%s convert_ms=%s decode_ms=%s emitted_events=%s bytes_received=%s",
                        session.session_id,
                        partial_convert_elapsed_ms,
                        partial_decode_elapsed_ms,
                        len(emitted),
                        current_size,
                    )
                    if emitted:
                        for event in emitted:
                            await websocket.send_json(event)
                    else:
                        await websocket.send_json(
                            session.emit_progress("partial_segment", detail={"bytes_received": current_size})
                        )
                    last_partial_bytes = current_size
                    last_partial_at = monotonic()
                except FFmpegError:
                    await websocket.send_json(
                        session.emit_progress("partial_segment", detail={"bytes_received": current_size})
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        session.emit_progress("partial_segment", detail={"bytes_received": current_size})
                    )
                finally:
                    if partial_wav_path is not None:
                        remove_file_safely(partial_wav_path)
                        partial_wav_path = None
    except WebSocketDisconnect:
        return
    except ValueError as exc:
        if session is not None:
            await websocket.send_json(session.emit_error(str(exc)))
    except FFmpegError as exc:
        if session is not None:
            await websocket.send_json(session.emit_error(f"ffmpeg failed: {exc}"))
    except asyncio.TimeoutError:
        if session is not None:
            await websocket.send_json(session.emit_error("transcription timed out"))
    except Exception as exc:
        LOGGER.exception("websocket transcription failed")
        if session is not None:
            await websocket.send_json(session.emit_error(f"transcription failed: {exc}"))
    finally:
        if opus_decoder is not None:
            with suppress(Exception):
                await opus_decoder.close()
        remove_file_safely(partial_wav_path)
        remove_file_safely(wav_path)
        remove_file_safely(source_path)
        await websocket.close()


app.include_router(api_router)
