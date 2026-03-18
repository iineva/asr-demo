import io
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


class ApiValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = os.path.join(self.temp_dir.name, "uploads")
        self.output_dir = os.path.join(self.temp_dir.name, "outputs")
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_invalid_language_returns_400(self) -> None:
        from app.main import app
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/transcribe",
                files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                data={"language": "zh"},
            )

        self.assertEqual(response.status_code, 400)

    async def test_legacy_health_endpoint_returns_ok(self) -> None:
        from app.main import app
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "status": "ok"})

    async def test_cors_preflight_allows_any_origin_by_default(self) -> None:
        from app.main import app
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/transcribe",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertIn("POST", response.headers.get("access-control-allow-methods", ""))

    async def test_cors_actual_response_uses_wildcard_origin_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPLOAD_DIR": self.upload_dir,
                "OUTPUT_DIR": self.output_dir,
                "MAX_UPLOAD_SIZE_MB": "5",
            },
            clear=False,
        ):
            from app.main import app
            from httpx import ASGITransport, AsyncClient

            mocked_result = {
                "requested_language": "yue",
                "detected_language": "yue",
                "language_probability": 0.97,
                "text": "hello world",
                "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
            }

            with patch("app.main.convert_audio_to_wav", new=AsyncMock(return_value="/tmp/audio.wav")), patch(
                "app.main.transcribe_audio", new=AsyncMock(return_value=mocked_result)
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/transcribe",
                        files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                        data={"language": "yue"},
                        headers={"Origin": "http://localhost:5173"},
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    async def test_transcribe_returns_expected_payload(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPLOAD_DIR": self.upload_dir,
                "OUTPUT_DIR": self.output_dir,
                "MAX_UPLOAD_SIZE_MB": "5",
            },
            clear=False,
        ):
            from app.main import app
            from httpx import ASGITransport, AsyncClient

            mocked_result = {
                "requested_language": "yue",
                "detected_language": "yue",
                "language_probability": 0.97,
                "text": "hello world",
                "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
            }

            with patch("app.main.convert_audio_to_wav", new=AsyncMock(return_value="/tmp/audio.wav")), patch(
                "app.main.transcribe_audio", new=AsyncMock(return_value=mocked_result)
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/transcribe",
                        files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                        data={"language": "yue"},
                    )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["success"])
            self.assertEqual(payload["result"]["requested_language"], "yue")

    async def test_transcribe_error_returns_detail(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPLOAD_DIR": self.upload_dir,
                "OUTPUT_DIR": self.output_dir,
                "MAX_UPLOAD_SIZE_MB": "5",
            },
            clear=False,
        ):
            from app.main import app
            from httpx import ASGITransport, AsyncClient

            with patch("app.main.convert_audio_to_wav", new=AsyncMock(return_value="/tmp/audio.wav")), patch(
                "app.main.transcribe_audio", new=AsyncMock(side_effect=RuntimeError("model boom"))
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/transcribe",
                        files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                        data={"language": "auto"},
                    )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["detail"], "transcription failed: model boom")

    async def test_transcribe_stream_returns_progressive_events(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPLOAD_DIR": self.upload_dir,
                "OUTPUT_DIR": self.output_dir,
                "MAX_UPLOAD_SIZE_MB": "5",
            },
            clear=False,
        ):
            from app.main import app
            from httpx import ASGITransport, AsyncClient

            mocked_result = {
                "requested_language": "auto",
                "detected_language": "yue",
                "language_probability": 0.97,
                "text": "hello world",
                "segments": [
                    {"start": 0.0, "end": 0.5, "text": "hello"},
                    {"start": 0.5, "end": 1.0, "text": "world"},
                ],
            }

            with patch("app.main.convert_audio_to_wav", new=AsyncMock(return_value="/tmp/audio.wav")), patch(
                "app.main.transcribe_audio", new=AsyncMock(return_value=mocked_result)
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.post(
                        "/api/transcribe/stream",
                        files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                        data={"language": "auto"},
                    )

        self.assertEqual(response.status_code, 200)
        lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        self.assertEqual(lines[0]["type"], "queued")
        self.assertEqual(lines[1]["type"], "preprocessing")
        self.assertIn("completed", [line["type"] for line in lines])

    def test_websocket_stream_emits_partial_then_completed(self) -> None:
        with patch.dict(
            os.environ,
            {
                "UPLOAD_DIR": self.upload_dir,
                "OUTPUT_DIR": self.output_dir,
                "MAX_UPLOAD_SIZE_MB": "5",
            },
            clear=False,
        ):
            from fastapi.testclient import TestClient
            from app.main import app

            mocked_result = {
                "requested_language": "auto",
                "detected_language": "yue",
                "language_probability": 0.97,
                "text": "hello world",
                "segments": [
                    {"start": 0.0, "end": 0.5, "text": "hello"},
                    {"start": 0.5, "end": 1.0, "text": "world"},
                ],
            }

            with patch("app.main.convert_audio_to_wav", new=AsyncMock(return_value="/tmp/audio.wav")), patch(
                "app.main.transcribe_audio", new=AsyncMock(return_value=mocked_result)
            ):
                with TestClient(app) as client:
                    with client.websocket_connect("/api/ws/transcribe") as websocket:
                        websocket.send_json({"type": "start", "language": "auto", "mime_type": "audio/webm"})
                        queued_event = websocket.receive_json()
                        self.assertEqual(queued_event["type"], "queued")

                        websocket.send_bytes(b"chunk")
                        partial_event = websocket.receive_json()
                        self.assertEqual(partial_event["type"], "partial_segment")

                        websocket.send_json({"type": "finish"})
                        final_event = websocket.receive_json()
                        completed_event = websocket.receive_json()

        self.assertEqual(final_event["type"], "final_segment")
        self.assertEqual(completed_event["type"], "completed")


class LoggingTests(unittest.TestCase):
    def test_json_formatter_includes_exception_details(self) -> None:
        from app.main import JsonFormatter

        formatter = JsonFormatter()

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record = logging.getLogger("test").makeRecord(
                "test",
                logging.ERROR,
                __file__,
                1,
                "transcription failed",
                args=(),
                exc_info=sys.exc_info(),
            )

        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["message"], "transcription failed")
        self.assertEqual(payload["exception"]["type"], "RuntimeError")
        self.assertIn("boom", payload["exception"]["message"])
        self.assertIn("RuntimeError: boom", payload["exception"]["traceback"])


if __name__ == "__main__":
    unittest.main()
