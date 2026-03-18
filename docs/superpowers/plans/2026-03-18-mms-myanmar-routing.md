# MMS Myanmar Routing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route explicit Myanmar transcription requests (`language=my`) to an MMS-1B backend while keeping the existing API payload and transport behavior unchanged.

**Architecture:** Keep `app/main.py` and the upload/streaming pipeline unchanged, and refactor `app/asr.py` into a small routing layer over two transcription engines. `WhisperTranscriber` remains responsible for `auto` and `yue`, while `MmsTranscriber` owns `my` and normalizes MMS output into the existing response schema.

**Tech Stack:** Python 3.9+, FastAPI, faster-whisper, Hugging Face transformers, torch, torchaudio, unittest

---

## File Map

- Modify: `app/asr.py`
  Purpose: split model-specific logic into Whisper and MMS transcribers, add routing and MMS settings, preserve public `transcribe_audio()` entrypoint.
- Modify: `tests/test_asr.py`
  Purpose: add failing tests for routing, MMS normalization, and isolated model caching.
- Modify: `requirements.txt`
  Purpose: add MMS runtime dependencies.
- Modify: `Dockerfile`
  Purpose: ensure container image includes MMS runtime dependencies and environment defaults.
- Modify: `docker-compose.yml`
  Purpose: document MMS environment variables for local deployment.
- Modify: `README.md`
  Purpose: explain routing behavior, MMS configuration, and operational tradeoffs.

## Chunk 1: Routing And Response Normalization

### Task 1: Add a failing route-selection test for explicit Myanmar requests

**Files:**
- Modify: `tests/test_asr.py`
- Modify: `app/asr.py`

- [ ] **Step 1: Write the failing test**

```python
def test_transcribe_audio_routes_explicit_myanmar_to_mms_transcriber(self) -> None:
    from app import asr

    class DummyMms:
        async def transcribe(self, file_path: str, language: str):
            return {
                "requested_language": language,
                "detected_language": "my",
                "language_probability": 1.0,
                "text": "မင်္ဂလာပါ",
                "segments": [{"start": 0.0, "end": 1.0, "text": "မင်္ဂလာပါ"}],
            }

    class DummyWhisper:
        async def transcribe(self, file_path: str, language: str):
            raise AssertionError("Whisper should not handle explicit Myanmar")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_explicit_myanmar_to_mms_transcriber -v`
Expected: FAIL because `app.asr` does not yet expose separate routeable transcribers.

- [ ] **Step 3: Write minimal implementation**

Implement a routing layer in `app/asr.py`:

```python
class TranscriberRouter:
    def __init__(self, whisper_transcriber, mms_transcriber) -> None:
        self.whisper_transcriber = whisper_transcriber
        self.mms_transcriber = mms_transcriber

    async def transcribe(self, file_path: str, language: str) -> Dict[str, Any]:
        if language == "my":
            return await self.mms_transcriber.transcribe(file_path, language)
        return await self.whisper_transcriber.transcribe(file_path, language)
```

Keep `transcribe_audio()` as the stable entry point, but make it call the router instead of directly calling the Whisper implementation.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_explicit_myanmar_to_mms_transcriber -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_asr.py app/asr.py
git commit -m "feat: route explicit myanmar requests to mms"
```

### Task 2: Add failing tests that non-Myanmar requests still use Whisper

**Files:**
- Modify: `tests/test_asr.py`
- Modify: `app/asr.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_transcribe_audio_routes_auto_to_whisper(self) -> None:
    ...

def test_transcribe_audio_routes_yue_to_whisper(self) -> None:
    ...
```

Use stubs that raise if the wrong backend is selected.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_auto_to_whisper tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_yue_to_whisper -v`
Expected: FAIL until the routing and test injection points are complete.

- [ ] **Step 3: Write minimal implementation**

Complete any missing router plumbing so `auto` and `yue` are sent to Whisper without affecting `my`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_auto_to_whisper tests.test_asr.AsrTranscriberTests.test_transcribe_audio_routes_yue_to_whisper -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_asr.py app/asr.py
git commit -m "test: lock whisper routing for auto and yue"
```

### Task 3: Add a failing MMS normalization test

**Files:**
- Modify: `tests/test_asr.py`
- Modify: `app/asr.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mms_transcriber_normalizes_result_payload_without_timestamps(self) -> None:
    model_output = {"text": " မင်္ဂလာပါ "}
    duration_seconds = 1.75
    result = transcriber._normalize_mms_result(model_output, duration_seconds, "my")
    self.assertEqual(result["requested_language"], "my")
    self.assertEqual(result["detected_language"], "my")
    self.assertEqual(result["language_probability"], 1.0)
    self.assertEqual(result["segments"], [{"start": 0.0, "end": 1.75, "text": "မင်္ဂလာပါ"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_mms_transcriber_normalizes_result_payload_without_timestamps -v`
Expected: FAIL because `MmsTranscriber` and normalization helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add an `MmsTranscriber` class with a dedicated normalization helper that:

```python
return {
    "requested_language": language,
    "detected_language": "my",
    "language_probability": 1.0,
    "text": normalized_text,
    "segments": [{"start": 0.0, "end": round(duration_seconds, 3), "text": normalized_text}] if normalized_text else [],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_mms_transcriber_normalizes_result_payload_without_timestamps -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_asr.py app/asr.py
git commit -m "feat: normalize mms myanmar transcripts to api schema"
```

## Chunk 2: MMS Runtime And Model Settings

### Task 4: Add failing tests for separate Whisper and MMS settings caches

**Files:**
- Modify: `tests/test_asr.py`
- Modify: `app/asr.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_get_mms_settings_reads_runtime_env(self) -> None:
    ...

def test_whisper_and_mms_singletons_are_cached_independently(self) -> None:
    ...
```

Use `patch.dict("os.environ", ...)` and assert MMS settings do not overwrite Whisper settings.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_get_mms_settings_reads_runtime_env tests.test_asr.AsrTranscriberTests.test_whisper_and_mms_singletons_are_cached_independently -v`
Expected: FAIL because MMS settings and singleton accessors are not implemented.

- [ ] **Step 3: Write minimal implementation**

Add:

```python
@dataclass(frozen=True)
class MmsSettings:
    model_id: str
    device: str
    torch_dtype: str
```

And create dedicated cached accessors such as:

```python
@lru_cache(maxsize=1)
def get_mms_settings() -> MmsSettings: ...

def get_mms_transcriber() -> MmsTranscriber: ...
def get_whisper_transcriber() -> WhisperTranscriber: ...
def get_transcriber_router() -> TranscriberRouter: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_get_mms_settings_reads_runtime_env tests.test_asr.AsrTranscriberTests.test_whisper_and_mms_singletons_are_cached_independently -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_asr.py app/asr.py
git commit -m "feat: add isolated mms settings and singleton cache"
```

### Task 5: Add failing tests for MMS model invocation boundaries

**Files:**
- Modify: `tests/test_asr.py`
- Modify: `app/asr.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mms_transcriber_invokes_processor_model_and_decoder(self) -> None:
    ...
```

Use lightweight stubs for processor/model/decoder and assert the transcriber reads a wav file path, performs one MMS inference pass, and returns normalized output.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_mms_transcriber_invokes_processor_model_and_decoder -v`
Expected: FAIL until the MMS transcriber is wired.

- [ ] **Step 3: Write minimal implementation**

Implement `MmsTranscriber.transcribe()` with explicit dependency seams so tests can inject stubs. Keep the real runtime path focused:

```python
waveform, sample_rate = torchaudio.load(file_path)
inputs = processor(waveform.squeeze(0), sampling_rate=sample_rate, return_tensors="pt")
generated = model.generate(**inputs)
text = processor.batch_decode(generated, skip_special_tokens=True)[0]
```

Normalize the result through the helper from Task 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_asr.AsrTranscriberTests.test_mms_transcriber_invokes_processor_model_and_decoder -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_asr.py app/asr.py
git commit -m "feat: add mms transcription runtime path"
```

## Chunk 3: Dependency And Runtime Configuration

### Task 6: Add MMS runtime dependencies and container defaults

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write the failing contract test**

Add or extend a lightweight requirements/config contract test in `tests/test_utils.py` or `tests/test_asr.py`:

```python
def test_requirements_include_mms_runtime_dependencies(self) -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    self.assertIn("transformers", requirements)
    self.assertIn("torchaudio", requirements)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_utils.UtilsContractTests.test_requirements_include_mms_runtime_dependencies -v`
Expected: FAIL until dependencies are added.

- [ ] **Step 3: Write minimal implementation**

Update:
- `requirements.txt` with MMS runtime packages
- `Dockerfile` with `MMS_MODEL_ID`, `MMS_DEVICE`, and `MMS_TORCH_DTYPE` defaults
- `docker-compose.yml` with matching environment variables for local runs

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_utils.UtilsContractTests.test_requirements_include_mms_runtime_dependencies -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_utils.py requirements.txt Dockerfile docker-compose.yml
git commit -m "chore: add mms runtime dependencies and env defaults"
```

### Task 7: Document the new routing and MMS configuration

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the failing documentation expectation**

If the repo already uses doc contract tests, add one. Otherwise, treat this as a documentation-only step and skip the failing test.

- [ ] **Step 2: Update the documentation**

Document:
- explicit `my` routing to MMS-1B
- `auto` and `yue` staying on Whisper
- MMS first-load/download behavior
- new MMS environment variables
- the fact that Myanmar segments may be synthetic single-span segments

- [ ] **Step 3: Verify the docs**

Run: `rg -n "MMS_MODEL_ID|language=my|single segment|Whisper" README.md`
Expected: matching lines describing the new behavior.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: explain mms routing for myanmar transcription"
```

## Chunk 4: Final Verification

### Task 8: Run focused backend verification

**Files:**
- Modify: `app/asr.py`
- Modify: `tests/test_asr.py`
- Modify: `tests/test_utils.py`

- [ ] **Step 1: Run the ASR unit suite**

Run: `python3 -m unittest tests.test_asr tests.test_utils -v`
Expected: PASS

- [ ] **Step 2: Run syntax verification**

Run: `PYTHONPYCACHEPREFIX=$(pwd)/.pycache python3 -m py_compile app/asr.py tests/test_asr.py tests/test_utils.py`
Expected: PASS

- [ ] **Step 3: Run API-level verification if dependencies are installed**

Run: `python3 -m unittest tests.test_main tests.test_streaming -v`
Expected: PASS if FastAPI and related runtime deps are installed in the environment. If unavailable, record the exact missing module error in the handoff.

- [ ] **Step 4: Commit the final integrated change**

```bash
git add app/asr.py tests/test_asr.py tests/test_utils.py requirements.txt Dockerfile docker-compose.yml README.md
git commit -m "feat: route explicit myanmar transcription to mms"
```
