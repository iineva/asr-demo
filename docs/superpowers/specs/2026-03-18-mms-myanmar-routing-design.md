# MMS Myanmar Routing Design

**Goal:** Keep the existing ASR HTTP and streaming APIs unchanged while routing explicit Myanmar requests (`language=my`) to an MMS-1B transcription path. Requests for `language=auto` and `language=yue` continue using the current Whisper-based path.

## Architecture

The API layer in `app/main.py` remains unchanged. Request validation, upload handling, ffmpeg conversion, streamed responses, and WebSocket orchestration keep calling the same `transcribe_audio(file_path, language)` entry point.

The transcription layer in `app/asr.py` becomes a small router over two engines:

- `WhisperTranscriber` handles `auto` and `yue`
- `MmsTranscriber` handles `my`
- `TranscriberRouter` selects the engine based on the validated `language`

This keeps the transport and response contracts stable while isolating model-specific logic behind one internal interface.

## Routing Rules

- `language=my`: always use `MmsTranscriber`
- `language=yue`: always use `WhisperTranscriber`
- `language=auto`: always use `WhisperTranscriber`

There is no automatic fallback from Whisper auto-detection into MMS. The switch is user-driven only, matching the product requirement.

## Model Lifecycle

Whisper and MMS use separate singletons and separate configuration, both initialized lazily on first use.

- Whisper keeps the current model/cache behavior
- MMS loads its own Hugging Face model, processor/tokenizer, and any required audio helpers
- Each engine exposes the same `transcribe(file_path, language)` contract

This avoids mixing model configuration and lets explicit Myanmar traffic pay the MMS cost without affecting other languages.

## Result Contract

Both engines must return the current payload shape:

- `requested_language`
- `detected_language`
- `language_probability`
- `text`
- `segments`

For MMS Myanmar results:

- `requested_language` remains `my`
- `detected_language` is normalized to `my`
- `language_probability` is set to `1.0`
- `text` is normalized with the existing text cleanup path
- `segments` returns at least one segment

If MMS does not provide word or segment timestamps, the adapter returns a single synthetic segment covering the whole clip:

- `start=0.0`
- `end=<audio duration seconds>`
- `text=<normalized transcript>`

This preserves frontend compatibility and keeps streaming completion events unchanged, even if Myanmar segmentation is less precise than Whisper.

## Dependencies And Configuration

The project adds a Hugging Face inference stack for MMS while retaining the existing Whisper runtime.

Expected additions:

- `transformers`
- `torchaudio`
- any MMS-required support packages such as `sentencepiece` or `accelerate` if the selected model requires them

Expected configuration:

- `MMS_MODEL_ID`
- `MMS_DEVICE`
- `MMS_TORCH_DTYPE`
- optional cache/config overrides if needed for deployment

The compose and Docker configuration should document these variables explicitly. Model downloads are accepted as part of deployment and first-start behavior.

## Error Handling

The API should keep existing exception behavior. MMS-specific load or inference failures should surface through the same HTTP 500 and streamed error paths already used for Whisper failures.

The routing layer should not silently fall back from `my` to Whisper. If MMS fails, the request fails. This makes operational issues visible instead of masking them with a lower-quality engine.

## Testing Strategy

Implementation should be test-first and cover the routing boundary, not just raw model calls.

Required tests:

- `language=my` routes to `MmsTranscriber`
- `language=auto` routes to `WhisperTranscriber`
- `language=yue` routes to `WhisperTranscriber`
- MMS output is normalized into the current response schema
- synthetic single-segment behavior is correct when MMS lacks timestamps
- MMS and Whisper singleton/model settings are cached independently
- existing API-level tests still pass without payload changes

## Files Expected To Change

- `app/asr.py`
- `tests/test_asr.py`
- `requirements.txt`
- `Dockerfile`
- `docker-compose.yml`
- `README.md`

If MMS setup requires container/runtime tuning, `docker-compose.gpu.yml` may also need updates.
