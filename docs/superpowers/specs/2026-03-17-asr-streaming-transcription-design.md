# ASR Streaming Transcription Design

**Goal:** Extend the existing ASR system to support streaming-style interactions for both primary input modes: real-time press-to-talk transcription over `WebSocket`, and progressive file-upload transcription over streamed HTTP responses. The design must preserve the existing batch transcription core while adding a shared event model, clear session state, and a same-origin frontend integration under `/api`.

**Architecture**

The streaming design adds a transport layer, a shared orchestration layer, and a model-adaptation layer on top of the current FastAPI service.

- The transport layer exposes two new endpoints:
  - `WS /api/ws/transcribe` for press-to-talk sessions
  - `POST /api/transcribe/stream` for progressive file-upload transcription
- The orchestration layer owns session state, buffered audio, decode scheduling, result reconciliation, and event emission. Both transports use this same layer so the frontend receives a consistent event shape regardless of input source.
- The model-adaptation layer continues to use `faster-whisper`, but it now supports repeated decoding over a growing audio buffer so the backend can emit unstable partial text first and later promote stable text to final segments.

The existing non-streaming `POST /api/transcribe` endpoint remains available as a compatibility path until the frontend fully switches to streaming behavior for both entry points.

**Protocols**

The press-to-talk flow uses `WebSocket` because it needs low-latency bidirectional messaging and a long-lived session:

1. The frontend opens `WS /api/ws/transcribe`.
2. The first message is a `start` event describing `language`, MIME type, sample rate, and optional client metadata.
3. The frontend sends binary audio chunks at a fixed cadence while the user is holding the recording surface.
4. The frontend sends a `finish` control event when the user releases.
5. The backend emits `partial_segment`, `final_segment`, `completed`, or `error` events throughout the session.

The file-upload flow uses a streamed HTTP response because the input is still a single uploaded file, but the user should receive incremental output:

1. The frontend uploads the file to `POST /api/transcribe/stream`.
2. The response is a streamed event feed using NDJSON or SSE-compatible event framing.
3. The backend emits `queued`, `preprocessing`, `partial_segment`, `final_segment`, `completed`, or `error` events in order.

`WebSocket` and streamed HTTP deliberately remain separate protocols. The press-to-talk path is stateful and latency-sensitive. The file-upload path is task-oriented and request-scoped. Sharing only the event model keeps the design simpler than forcing one protocol onto both behaviors.

**Event Model**

Every emitted event uses the same top-level structure so the frontend can reuse rendering and reconciliation logic:

- `type`: event name such as `queued`, `preprocessing`, `partial_segment`, `final_segment`, `completed`, `error`
- `sequence`: strictly increasing integer per session or request
- `session_id`: stable identifier for the stream
- `text`: recognized text for partial or final output when applicable
- `start` and `end`: segment timing when available
- `is_final`: explicit stability marker for text-bearing events
- `language`: requested or detected language metadata when available
- `detail`: machine-readable or user-facing error/progress detail

The frontend treats `partial_segment` as replaceable tail output and `final_segment` as append-only confirmed output. `completed` includes the final aggregated text and segment list so the caller does not need to reconstruct the final payload from local state alone.

**State Model**

The orchestration layer tracks a focused state machine:

- `idle`: no stream has started
- `streaming`: receiving audio or processing file input and eligible for partial output
- `finishing`: input has ended and the backend is doing final reconciliation
- `completed`: terminal success state
- `error`: terminal failure state

Each active stream also tracks:

- `final_segments`: confirmed segments that will never change
- `partial_segment`: the current unstable tail segment, if any
- `audio_buffer`: accumulated PCM or normalized wav content used for re-decode windows
- `last_emitted_sequence`: monotonic event counter
- `requested_language` and latest detected language metadata

The core reconciliation rule is simple: on each decode pass, compare the stable prefix against the previously emitted text. Promote newly stable text to `final_segment`, replace the unstable suffix as `partial_segment`, and only emit `completed` after the final pass finishes.

**Error Handling**

The backend must surface structured failures rather than silently dropping streams.

For `WebSocket` sessions:

- missing `start` before audio data
- unsupported MIME type or audio format
- oversized chunks
- session inactivity timeout
- disconnect during `streaming` or `finishing`
- decode or model failure during incremental passes

For streamed file uploads:

- empty upload
- unsupported extension
- ffmpeg preprocessing failure
- streaming response interruption
- decode timeout
- finalization failure after partial output has already been sent

All failures emit an `error` event with `detail`, then close the stream or request cleanly.

**Frontend Behavior**

The frontend remains same-origin and uses `/api` paths exclusively.

For press-to-talk:

- open the `WebSocket` on press
- stream chunks while recording
- render final segments in the stable results area
- render the current partial segment in a visually distinct temporary area
- on release, send `finish` and wait for `completed`

For file upload:

- submit the selected file to `POST /api/transcribe/stream`
- consume the streamed event feed incrementally
- reuse the same result store used by press-to-talk, including partial and final display handling

This keeps the UI model consistent even though the transport protocols differ.

**Testing Strategy**

Backend tests should cover three layers:

- protocol tests for `WebSocket` and streamed HTTP endpoint event ordering
- orchestration tests for state transitions, sequence assignment, and partial/final reconciliation
- adapter tests for how repeated decode results are converted into partial and final segments

Frontend tests should cover:

- press-to-talk `WebSocket` lifecycle, including partial replacement and final append behavior
- file-upload stream consumption and progressive rendering
- terminal error behavior that preserves the last successful finalized text when possible

Test fixtures should mock decode outputs directly so the event model can be validated without requiring live model inference in unit tests.

**Implementation Order**

1. Define shared streaming event types and session state objects.
2. Extract orchestration logic from the current one-shot transcription path into a reusable service.
3. Add `POST /api/transcribe/stream` with progressive event emission for file uploads.
4. Add `WS /api/ws/transcribe` for press-to-talk sessions.
5. Update the frontend upload flow to consume streamed events.
6. Update the press-to-talk frontend to use `WebSocket` and render partial plus final text distinctly.
7. Keep the existing batch endpoint during rollout, then decide later whether to retire it.
