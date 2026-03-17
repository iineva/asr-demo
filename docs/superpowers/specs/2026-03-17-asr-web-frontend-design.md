# ASR Web Frontend Design

**Goal:** Build a mobile-first test frontend with Vite, React, and TypeScript that uses a WeChat-like press-to-record interaction, uploads audio automatically on release, supports slide-up cancel, and displays ASR results from the existing backend.

**Architecture**

The frontend is a standalone `web/` application served separately from the FastAPI backend. It uses a single React page with focused UI state for microphone permission, press state, cancel state, recording duration, upload state, and transcription result.

Audio capture is implemented with `navigator.mediaDevices.getUserMedia()` and `MediaRecorder`. Pressing and holding the main input surface starts recording. Pointer movement above a cancel threshold marks the gesture as canceled. Releasing the pointer either discards the recording or finalizes it, packages the audio blob as `multipart/form-data`, and uploads it to `/transcribe`.

**UI**

The interface is mobile-first and intentionally product-like rather than dashboard-like. The top area contains branding and language selection. The center of the page is a large, tactile press-to-talk surface with clear idle, recording, cancel, uploading, and error states. The bottom area displays the latest recognized text, language metadata, and segments.

**Operational Constraints**

- No fallback file upload control.
- Browser support targets modern mobile browsers that expose `MediaRecorder`.
- Frontend and backend run together via `docker-compose`.
- The browser-facing API base URL is configured through `VITE_API_BASE_URL`.

**Error Handling**

- Microphone permission denial shows a direct user-facing error.
- Unsupported recording or upload failure shows inline error state.
- Gesture cancellation discards the audio without network traffic.
- Backend errors are surfaced without clearing the previous successful result.
