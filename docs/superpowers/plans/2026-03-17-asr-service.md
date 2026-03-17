# ASR Service Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready FastAPI ASR service that accepts audio uploads, normalizes them with ffmpeg, transcribes with `faster-whisper large-v3`, and runs in Docker with GPU support and CPU fallback.

**Architecture:** Keep a lightweight three-file application layout. `main.py` handles HTTP and lifecycle, `asr.py` encapsulates model loading/transcription with singleton behavior, and `utils.py` handles upload persistence plus ffmpeg preprocessing. Use environment-driven runtime configuration and health endpoints for production deployment.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, faster-whisper, torch, ffmpeg-python, python-multipart, Docker, docker compose

---

### File Map

**Files:**
- Create: `app/main.py`
- Create: `app/asr.py`
- Create: `app/utils.py`
- Create: `tests/test_utils.py`
- Create: `tests/test_main.py`
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `uploads/.gitkeep`
- Create: `outputs/.gitkeep`

### Task 1: Utility Contracts

**Files:**
- Create: `tests/test_utils.py`
- Create: `app/utils.py`

- [ ] **Step 1: Write the failing test**

```python
def test_validate_language_rejects_unknown():
    with self.assertRaises(ValueError):
        validate_language("zh")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_utils -v`
Expected: FAIL or import error because utility code does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
def validate_language(language: str) -> str:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_utils -v`
Expected: PASS

### Task 2: API Validation and Response Flow

**Files:**
- Create: `tests/test_main.py`
- Create: `app/main.py`

- [ ] **Step 1: Write the failing test**

```python
def test_transcribe_rejects_invalid_language():
    response = client.post("/transcribe", data={"language": "zh"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL because endpoint does not exist yet

- [ ] **Step 3: Write minimal implementation**

```python
@app.post("/transcribe")
async def transcribe(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main -v`
Expected: PASS

### Task 3: ASR Integration

**Files:**
- Create: `app/asr.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write the failing test**

Add a test that monkeypatches `transcribe_audio` and verifies the API returns normalized result payload.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL until integration is wired

- [ ] **Step 3: Write minimal implementation**

Implement singleton model loading, device fallback, and API integration.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main -v`
Expected: PASS

### Task 4: Container Runtime

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Write configuration and container files**
- [ ] **Step 2: Verify file presence and command syntax**

Run: `python3 -m py_compile app/main.py app/asr.py app/utils.py`
Expected: PASS

### Task 5: End-to-End Verification

**Files:**
- Modify: `app/main.py`
- Modify: `app/asr.py`
- Modify: `app/utils.py`
- Modify: `tests/test_utils.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Run focused tests**

Run: `python3 -m unittest tests.test_utils tests.test_main -v`
Expected: PASS

- [ ] **Step 2: Run syntax verification**

Run: `python3 -m py_compile app/main.py app/asr.py app/utils.py`
Expected: PASS

- [ ] **Step 3: Check requirement coverage**

Verify the implementation includes the required dependencies, Docker files, mounted directories, GPU-capable image, health endpoints, upload limits, timeouts, and singleton model behavior.
