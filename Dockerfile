FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SERVICE_NAME=asr-service \
    UPLOAD_DIR=/app/uploads \
    OUTPUT_DIR=/app/outputs \
    MAX_UPLOAD_SIZE_MB=100 \
    FFMPEG_TIMEOUT_SECONDS=300 \
    TRANSCRIBE_TIMEOUT_SECONDS=300 \
    PRELOAD_MODEL_ON_STARTUP=false \
    WHISPER_MODEL_SIZE=medium \
    WHISPER_DEVICE=auto \
    WHISPER_COMPUTE_TYPE_CUDA=float16 \
    WHISPER_COMPUTE_TYPE_CPU=int8 \
    WHISPER_BEAM_SIZE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system appgroup && useradd --system --gid appgroup --create-home appuser

COPY requirements.txt /app/requirements.txt

RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r /app/requirements.txt

COPY app /app/app
COPY uploads /app/uploads
COPY outputs /app/outputs

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
