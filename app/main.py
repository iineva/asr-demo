import asyncio
import json
import logging
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.asr import get_transcriber, transcribe_audio
from app.streaming import (
    StreamingTranscriptionSession,
    iter_file_upload_events,
    mime_type_to_extension,
    write_bytes,
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


def get_settings() -> Dict[str, Any]:
    return {
        "service_name": os.getenv("SERVICE_NAME", "asr-service"),
        "upload_dir": os.getenv("UPLOAD_DIR", "uploads"),
        "output_dir": os.getenv("OUTPUT_DIR", "outputs"),
        "max_upload_size_bytes": int(float(os.getenv("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024),
        "ffmpeg_timeout_seconds": int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "300")),
        "transcribe_timeout_seconds": int(os.getenv("TRANSCRIBE_TIMEOUT_SECONDS", "1800")),
        "preload_model": os.getenv("PRELOAD_MODEL_ON_STARTUP", "true").lower() == "true",
        "ws_partial_min_bytes": max(1, int(os.getenv("WS_PARTIAL_MIN_BYTES", "131072"))),
        "ws_partial_min_interval_ms": max(0, int(os.getenv("WS_PARTIAL_MIN_INTERVAL_MS", "1200"))),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    ensure_directory(settings["upload_dir"])
    ensure_directory(settings["output_dir"])
    if settings["preload_model"]:
        try:
            await asyncio.to_thread(get_transcriber)
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


@api_router.get("/health")
async def health() -> Dict[str, Any]:
    return {"success": True, "status": "ok"}


@api_router.get("/ready")
async def ready() -> JSONResponse:
    try:
        await asyncio.to_thread(get_transcriber)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"success": False, "status": "degraded", "detail": str(exc)})
    return JSONResponse(status_code=200, content={"success": True, "status": "ready"})


@api_router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")) -> Dict[str, Any]:
    settings = get_settings()
    try:
        requested_language = validate_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]

    try:
        start_time = monotonic()
        source_path = await save_upload_file(file, settings["upload_dir"], settings["max_upload_size_bytes"])
        upload_elapsed_ms = int((monotonic() - start_time) * 1000)
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        convert_elapsed_ms = int((monotonic() - start_time) * 1000) - upload_elapsed_ms
        result = await asyncio.wait_for(
            transcribe_audio(str(wav_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
        )
        transcribe_elapsed_ms = int((monotonic() - start_time) * 1000) - upload_elapsed_ms - convert_elapsed_ms
        LOGGER.info(
            "transcribe timing: upload=%sms convert=%sms decode=%sms total=%sms",
            upload_elapsed_ms,
            convert_elapsed_ms,
            transcribe_elapsed_ms,
            int((monotonic() - start_time) * 1000),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FFmpegError as exc:
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=500, detail="transcription timed out") from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("transcription failed")
        raise HTTPException(status_code=500, detail=f"transcription failed: {exc}") from exc
    finally:
        remove_file_safely(source_path)

    return {"success": True, "result": result}


@api_router.post("/transcribe/stream")
async def transcribe_stream(file: UploadFile = File(...), language: str = Form("auto")) -> StreamingResponse:
    settings = get_settings()
    try:
        requested_language = validate_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]
    session = StreamingTranscriptionSession(language=requested_language)

    try:
        source_path = await save_upload_file(file, settings["upload_dir"], settings["max_upload_size_bytes"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def run_transcription() -> Dict[str, Any]:
        nonlocal wav_path
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        return await asyncio.wait_for(
            transcribe_audio(str(wav_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
        )

    async def event_stream():
        try:
            async for event in iter_file_upload_events(session=session, transcribe_result=run_transcription):
                yield event
        except ValueError as exc:
            yield (json.dumps(session.emit_error(str(exc)), ensure_ascii=False) + "\n").encode("utf-8")
        except FFmpegError as exc:
            yield (json.dumps(session.emit_error(f"ffmpeg failed: {exc}"), ensure_ascii=False) + "\n").encode("utf-8")
        except asyncio.TimeoutError:
            yield (json.dumps(session.emit_error("transcription timed out"), ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as exc:
            LOGGER.exception("streaming transcription failed")
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
    audio_buffer = bytearray()
    last_partial_bytes = 0
    last_partial_at = 0.0

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                payload = json.loads(message["text"])
                if payload.get("type") == "start":
                    requested_language = validate_language(payload.get("language", "auto"))
                    mime_type = payload.get("mime_type", "audio/webm")
                    session = StreamingTranscriptionSession(language=requested_language)
                    source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"
                    audio_buffer.clear()
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

                    if source_path is None:
                        source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"
                    write_bytes(source_path, audio_buffer)
                    wav_path = await convert_audio_to_wav(
                        str(source_path),
                        settings["output_dir"],
                        settings["ffmpeg_timeout_seconds"],
                    )
                    result = await asyncio.wait_for(
                        transcribe_audio(str(wav_path), requested_language),
                        timeout=settings["transcribe_timeout_seconds"],
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
                audio_buffer.extend(message["bytes"])
                current_size = len(audio_buffer)
                if source_path is None:
                    source_path = Path(settings["upload_dir"]) / f"{uuid.uuid4().hex}{mime_type_to_extension(mime_type)}"

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

                write_bytes(source_path, audio_buffer)
                try:
                    wav_path = await convert_audio_to_wav(
                        str(source_path),
                        settings["output_dir"],
                        settings["ffmpeg_timeout_seconds"],
                    )
                    result = await asyncio.wait_for(
                        transcribe_audio(str(wav_path), requested_language),
                        timeout=settings["transcribe_timeout_seconds"],
                    )
                    emitted = session.apply_transcription_result(result)
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
        remove_file_safely(wav_path)
        remove_file_safely(source_path)
        await websocket.close()


app.include_router(api_router)
