# ASR Streaming Transcription Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add streaming transcription to the existing ASR stack so press-to-talk uses `WebSocket` for real-time partial and final text, while file upload uses streamed HTTP output for progressive results.

**Architecture:** Keep the existing FastAPI plus React structure, but add a shared streaming orchestration layer that both transports use. The backend exposes `WS /api/ws/transcribe` and `POST /api/transcribe/stream`, and the frontend consumes a shared event model so UI reconciliation stays consistent across recording and file upload.

**Tech Stack:** Python 3, FastAPI, WebSocket, streamed HTTP responses, faster-whisper, ffmpeg, React, TypeScript, Vitest, unittest

---

## Chunk 1: Backend Event Model and Streaming Orchestration

### File Map

**Files:**
- Create: `app/streaming.py`
- Modify: `app/asr.py`
- Modify: `app/main.py`
- Modify: `tests/test_main.py`
- Create: `tests/test_streaming.py`

### Task 1: Define streaming event and session contracts

**Files:**
- Create: `tests/test_streaming.py`
- Create: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_partial_segment_event():
    event = build_stream_event(
        event_type="partial_segment",
        sequence=2,
        session_id="s1",
        text="ni hao",
        start=0.0,
        end=0.8,
        is_final=False,
    )
    assert event["type"] == "partial_segment"
    assert event["sequence"] == 2
    assert event["is_final"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_streaming.StreamEventTests.test_build_partial_segment_event -v`
Expected: FAIL because `app.streaming` does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
def build_stream_event(...):
    return {
        "type": event_type,
        "sequence": sequence,
        "session_id": session_id,
        "text": text,
        "start": start,
        "end": end,
        "is_final": is_final,
        "language": language,
        "detail": detail,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_streaming.StreamEventTests.test_build_partial_segment_event -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/streaming.py tests/test_streaming.py
git commit -m "feat: add streaming event contracts"
```

### Task 2: Add reconciliation logic for partial and final segments

**Files:**
- Modify: `tests/test_streaming.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
def test_reconcile_segments_promotes_stable_prefix():
    previous_final = [{"text": "hello", "start": 0.0, "end": 0.5}]
    latest_segments = [
        {"text": "hello", "start": 0.0, "end": 0.5},
        {"text": "world maybe", "start": 0.5, "end": 1.2},
    ]
    result = reconcile_segments(previous_final, latest_segments)
    assert result.final_segments == previous_final
    assert result.partial_segment["text"] == "world maybe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_streaming.StreamReconciliationTests.test_reconcile_segments_promotes_stable_prefix -v`
Expected: FAIL because reconciliation logic is missing

- [ ] **Step 3: Write minimal implementation**

```python
def reconcile_segments(previous_final, latest_segments):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_streaming.StreamReconciliationTests.test_reconcile_segments_promotes_stable_prefix -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/streaming.py tests/test_streaming.py
git commit -m "feat: add streaming reconciliation logic"
```

### Task 3: Extend ASR adapter for repeated decode passes

**Files:**
- Modify: `tests/test_streaming.py`
- Modify: `app/asr.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_streaming_session_uses_transcriber_for_incremental_pass():
    transcriber = FakeTranscriber([...])
    session = StreamingTranscriptionSession(transcriber=transcriber)
    await session.process_audio_chunk(b"abc")
    assert transcriber.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_streaming.StreamSessionTests.test_streaming_session_uses_transcriber_for_incremental_pass -v`
Expected: FAIL because the session cannot trigger decode passes yet

- [ ] **Step 3: Write minimal implementation**

```python
class StreamingTranscriptionSession:
    async def process_audio_chunk(self, chunk: bytes) -> list[dict]:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_streaming.StreamSessionTests.test_streaming_session_uses_transcriber_for_incremental_pass -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/asr.py app/streaming.py tests/test_streaming.py
git commit -m "feat: add incremental transcription session core"
```

## Chunk 2: Backend Streaming Transports

### Task 4: Add streamed file-upload endpoint

**Files:**
- Modify: `tests/test_main.py`
- Modify: `app/main.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_transcribe_stream_returns_progressive_events():
    response = await client.post("/api/transcribe/stream", files={...})
    assert response.status_code == 200
    assert b'"type":"queued"' in response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main.ApiValidationTests.test_transcribe_stream_returns_progressive_events -v`
Expected: FAIL because `/api/transcribe/stream` does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
@api_router.post("/transcribe/stream")
async def transcribe_stream(...):
    return StreamingResponse(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main.ApiValidationTests.test_transcribe_stream_returns_progressive_events -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/streaming.py tests/test_main.py
git commit -m "feat: add streamed upload transcription endpoint"
```

### Task 5: Add `WebSocket` press-to-talk endpoint

**Files:**
- Modify: `tests/test_main.py`
- Modify: `app/main.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_websocket_stream_emits_partial_then_completed():
    with client.websocket_connect("/api/ws/transcribe") as ws:
        ws.send_json({"type": "start", "language": "auto"})
        ws.send_bytes(b"chunk")
        event = ws.receive_json()
        assert event["type"] == "partial_segment"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main.ApiValidationTests.test_websocket_stream_emits_partial_then_completed -v`
Expected: FAIL because the websocket endpoint does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
@api_router.websocket("/ws/transcribe")
async def websocket_transcribe(websocket):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main.ApiValidationTests.test_websocket_stream_emits_partial_then_completed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/streaming.py tests/test_main.py
git commit -m "feat: add websocket transcription transport"
```

### Task 6: Add structured streaming error handling

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_streaming.py`
- Modify: `app/main.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_websocket_missing_start_emits_error_event():
    with client.websocket_connect("/api/ws/transcribe") as ws:
        ws.send_bytes(b"chunk")
        event = ws.receive_json()
        assert event["type"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main tests.test_streaming -v`
Expected: FAIL because transport-level validation is incomplete

- [ ] **Step 3: Write minimal implementation**

```python
if session_not_started:
    await websocket.send_json(build_stream_event(..., event_type="error"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main tests.test_streaming -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/streaming.py tests/test_main.py tests/test_streaming.py
git commit -m "feat: add streaming transport error handling"
```

## Chunk 3: Frontend Streaming Integration

### File Map

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/recorder.ts`
- Modify: `web/src/types.ts`
- Create: `web/src/lib/streaming.ts`
- Create: `web/src/lib/api.test.ts`

### Task 7: Add frontend event types and file-upload stream client

**Files:**
- Modify: `web/src/types.ts`
- Create: `web/src/lib/streaming.ts`
- Create: `web/src/lib/api.test.ts`
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("parses streamed upload events in order", async () => {
  const events = await collectUploadStreamEvents(...)
  expect(events.map((e) => e.type)).toEqual(["queued", "partial_segment", "completed"])
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/lib/api.test.ts`
Expected: FAIL because streaming client helpers do not exist yet

- [ ] **Step 3: Write minimal implementation**

```ts
export async function streamUploadedAudio(...) {
  ...
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/lib/api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/lib/streaming.ts web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat: add frontend streaming event client"
```

### Task 8: Add `WebSocket` press-to-talk client and result reconciliation

**Files:**
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/recorder.ts`
- Modify: `web/src/lib/streaming.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("renders partial text during recording and final text after completion", async () => {
  render(<App ... />)
  expect(await screen.findByText("temporary text")).toBeInTheDocument()
  expect(await screen.findByText("confirmed text")).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because the app still assumes upload-on-release only

- [ ] **Step 3: Write minimal implementation**

```ts
function applyStreamingEvent(...) {
  ...
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/lib/recorder.ts web/src/lib/streaming.ts
git commit -m "feat: add realtime websocket recording flow"
```

### Task 9: Update file-upload UI to show progressive events

**Files:**
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("shows progressive upload results while the file stream is active", async () => {
  ...
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because file upload still waits for one final payload

- [ ] **Step 3: Write minimal implementation**

```ts
async function handleFileUpload(file: File) {
  for await (const event of streamUploadedAudio(file, language)) {
    ...
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/lib/api.ts
git commit -m "feat: add progressive file upload results"
```

## Chunk 4: Verification and Runtime Review

### Task 10: Run backend verification

**Files:**
- Modify: `tests/test_main.py`
- Modify: `tests/test_streaming.py`
- Modify: `app/main.py`
- Modify: `app/asr.py`
- Modify: `app/streaming.py`

- [ ] **Step 1: Run focused backend tests**

Run: `python3 -m unittest tests.test_main tests.test_streaming -v`
Expected: PASS

- [ ] **Step 2: Run syntax verification**

Run: `PYTHONPYCACHEPREFIX=$(pwd)/.pycache python3 -m py_compile app/main.py app/asr.py app/streaming.py tests/test_main.py tests/test_streaming.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/main.py app/asr.py app/streaming.py tests/test_main.py tests/test_streaming.py
git commit -m "test: verify backend streaming transcription flow"
```

### Task 11: Run frontend verification

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/streaming.ts`
- Modify: `web/src/types.ts`

- [ ] **Step 1: Run frontend tests**

Run: `npm test`
Expected: PASS

- [ ] **Step 2: Run frontend type and build verification**

Run: `npm run build`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/lib/api.ts web/src/lib/streaming.ts web/src/types.ts
git commit -m "test: verify frontend streaming transcription flow"
```

### Task 12: Manual end-to-end review

**Files:**
- Modify: `docker-compose.yml`
- Modify: `web/nginx.conf`
- Modify: `web/vite.config.ts`

- [ ] **Step 1: Start the stack**

Run: `docker compose up --build`
Expected: services start and web is reachable on the configured port

- [ ] **Step 2: Verify press-to-talk flow manually**

Expected: while holding the talk surface, temporary text appears and later stabilizes into final text

- [ ] **Step 3: Verify file-upload progressive flow manually**

Expected: upload status advances through queued, preprocessing, incremental segments, and completed

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml web/nginx.conf web/vite.config.ts
git commit -m "chore: finalize streaming runtime integration"
```
