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
                "/transcribe",
                files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                data={"language": "zh"},
            )

        self.assertEqual(response.status_code, 400)

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
                        "/transcribe",
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
                        "/transcribe",
                        files={"file": ("sample.wav", io.BytesIO(b"fake"), "audio/wav")},
                        data={"language": "auto"},
                    )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["detail"], "transcription failed: model boom")


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
