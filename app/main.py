import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.asr import get_transcriber, transcribe_audio
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
        "preload_model": os.getenv("PRELOAD_MODEL_ON_STARTUP", "false").lower() == "true",
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


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"success": True, "status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    try:
        await asyncio.to_thread(get_transcriber)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"success": False, "status": "degraded", "detail": str(exc)})
    return JSONResponse(status_code=200, content={"success": True, "status": "ready"})


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto")) -> Dict[str, Any]:
    settings = get_settings()
    try:
        requested_language = validate_language(language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_path = None  # type: Optional[Path]
    wav_path = None  # type: Optional[Path]

    try:
        source_path = await save_upload_file(file, settings["upload_dir"], settings["max_upload_size_bytes"])
        wav_path = await convert_audio_to_wav(
            str(source_path),
            settings["output_dir"],
            settings["ffmpeg_timeout_seconds"],
        )
        result = await asyncio.wait_for(
            transcribe_audio(str(wav_path), requested_language),
            timeout=settings["transcribe_timeout_seconds"],
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
