import asyncio
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional, Union

LOGGER = logging.getLogger("asr.utils")
SUPPORTED_LANGUAGES = {"auto", "my", "yue"}
ALLOWED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".webm"}


class FFmpegError(RuntimeError):
    """Raised when ffmpeg preprocessing fails."""


def validate_language(language: Optional[str]) -> str:
    normalized = (language or "auto").strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    return normalized


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def validate_extension(filename: Optional[str]) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension or 'unknown'}")
    return extension


def ensure_directory(path: Union[str, os.PathLike[str]]) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def save_upload_file(upload_file: Any, destination_dir: str, max_size_bytes: int) -> Path:
    ensure_directory(destination_dir)
    extension = validate_extension(upload_file.filename)
    destination = Path(destination_dir) / f"{uuid.uuid4().hex}{extension}"
    total_bytes = 0

    try:
        with destination.open("wb") as handle:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_size_bytes:
                    raise ValueError("Uploaded file exceeds size limit")
                handle.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    finally:
        await upload_file.close()

    if total_bytes == 0:
        if destination.exists():
            destination.unlink()
        raise ValueError("Uploaded file is empty")

    return destination


def _run_ffmpeg(input_path: str, output_path: str, timeout_seconds: int) -> None:
    import ffmpeg

    try:
        (
            ffmpeg.input(input_path)
            .output(output_path, ar=16000, ac=1, format="wav")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True, quiet=True, cmd=["ffmpeg"])
        )
    except ffmpeg.Error as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
        LOGGER.exception("ffmpeg preprocessing failed", extra={"input_path": input_path, "output_path": output_path})
        raise FFmpegError(stderr or "ffmpeg preprocessing failed") from exc


async def convert_audio_to_wav(input_path: str, output_dir: str, timeout_seconds: int) -> Path:
    ensure_directory(output_dir)
    output_path = Path(output_dir) / f"{Path(input_path).stem}.wav"
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_run_ffmpeg, input_path, str(output_path), timeout_seconds),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        if output_path.exists():
            output_path.unlink()
        raise FFmpegError("ffmpeg preprocessing timed out") from exc
    return output_path


def remove_file_safely(path: Optional[Union[str, os.PathLike[str]]]) -> None:
    if not path:
        return
    candidate = Path(path)
    if candidate.exists():
        candidate.unlink()
