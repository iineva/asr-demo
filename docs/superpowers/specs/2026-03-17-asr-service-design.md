# ASR Service Design

**Goal:** Build a production-deployable ASR HTTP service with FastAPI, `faster-whisper` (`large-v3`), `ffmpeg` preprocessing, Docker deployment, and language control for `my`, `yue`, and `auto`.

**Architecture**

The service is a single FastAPI application with a thin API layer and two focused modules. `app/main.py` owns request handling, validation, lifecycle hooks, health endpoints, and exception mapping. `app/asr.py` owns model lifecycle and transcription. `app/utils.py` owns file validation, streaming upload persistence, ffmpeg transcoding, and cleanup helpers.

The runtime flow is: validate request -> stream upload to `uploads/` -> transcode to normalized wav in `outputs/` -> run `faster-whisper` with requested or auto language -> normalize output text and segments -> return structured JSON. The model is loaded once per process, preferring CUDA and falling back to CPU if initialization fails.

**Operational Constraints**

- Single-process `uvicorn` in-container to avoid loading `large-v3` multiple times.
- Horizontal scaling should happen via multiple containers rather than multiple workers in one container.
- Upload size, allowed extension, paths, timeouts, and model device behavior are configured via environment variables.
- The container runs as a non-root user and exposes health endpoints for orchestration.

**Error Handling**

- Invalid `language` or unsupported file extension returns HTTP 400.
- Empty files return HTTP 400.
- ffmpeg failures return HTTP 500 with stable error messaging.
- Model loading or transcription failures return HTTP 500.
- Health endpoints distinguish liveness from readiness by checking whether the app is up and whether the model can be acquired.

**Testing Strategy**

- Unit tests verify language validation, filename/extension checks, text normalization, and API validation behavior.
- The API test uses dependency-free monkeypatching to avoid requiring the actual model or ffmpeg binary during test execution.
