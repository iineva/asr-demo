import asyncio
import unittest
from pathlib import Path
import tempfile
import wave
from unittest.mock import AsyncMock, patch


class MainHelpersTests(unittest.TestCase):
    def test_is_pcm_stream_detects_pcm_mime(self) -> None:
        from app import main

        self.assertTrue(main.is_pcm_stream("audio/pcm"))
        self.assertTrue(main.is_pcm_stream("audio/L16"))
        self.assertFalse(main.is_pcm_stream("audio/webm"))

    def test_is_opus_stream_detects_opus_container_mime(self) -> None:
        from app import main

        self.assertTrue(main.is_opus_stream("audio/webm;codecs=opus"))
        self.assertTrue(main.is_opus_stream("audio/ogg;codecs=opus"))
        self.assertFalse(main.is_opus_stream("audio/wav"))

    def test_write_pcm16le_wav_creates_valid_wave_file(self) -> None:
        from app import main

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            pcm_payload = b"\x00\x00" * 320
            main.write_pcm16le_wav(
                target_path=wav_path,
                pcm_payload=pcm_payload,
                sample_rate=16000,
                channels=1,
                bytes_per_sample=2,
            )

            with wave.open(str(wav_path), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), 16000)
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm_payload)
        finally:
            wav_path.unlink(missing_ok=True)

    def test_get_settings_uses_20ms_chunk_defaults_for_low_latency_partial_decode(self) -> None:
        from app import main

        with patch.dict("os.environ", {}, clear=True):
            settings = main.get_settings()

        self.assertEqual(settings["ws_chunk_ms"], 20)
        self.assertEqual(settings["ws_chunk_bytes"], 640)
        self.assertEqual(settings["ws_partial_min_bytes"], 640)
        self.assertEqual(settings["ws_partial_min_interval_ms"], 20)

    def test_get_settings_supports_custom_chunk_parameters(self) -> None:
        from app import main

        with patch.dict(
            "os.environ",
            {
                "WS_CHUNK_MS": "40",
                "WS_AUDIO_SAMPLE_RATE": "16000",
                "WS_AUDIO_CHANNELS": "1",
                "WS_AUDIO_BYTES_PER_SAMPLE": "2",
            },
            clear=True,
        ):
            settings = main.get_settings()

        self.assertEqual(settings["ws_chunk_bytes"], 1280)
        self.assertEqual(settings["ws_partial_min_bytes"], 1280)
        self.assertEqual(settings["ws_partial_min_interval_ms"], 40)

    def test_run_transcription_with_lazy_conversion_skips_wav_for_explicit_whisper_language(self) -> None:
        from app import main

        settings = {
            "output_dir": "outputs",
            "ffmpeg_timeout_seconds": 300,
            "transcribe_timeout_seconds": 300,
        }

        async def run_test() -> None:
            with patch("app.main.convert_audio_to_wav", new_callable=AsyncMock) as convert_mock, patch(
                "app.main.transcribe_audio",
                new=AsyncMock(return_value={"text": "hello", "segments": [], "timing": {"vad_ms": 0}}),
            ) as transcribe_mock:
                result, convert_ms, wav_path = await main.run_transcription_with_lazy_conversion(
                    Path("uploads/sample.mp3"),
                    "yue",
                    settings,
                )

            self.assertEqual(result["text"], "hello")
            self.assertEqual(convert_ms, 0)
            self.assertIsNone(wav_path)
            convert_mock.assert_not_called()
            transcribe_mock.assert_awaited_once_with("uploads/sample.mp3", "yue")

        asyncio.run(run_test())

    def test_run_transcription_with_lazy_conversion_skips_wav_for_auto_whisper_route(self) -> None:
        from app import main

        settings = {
            "output_dir": "outputs",
            "ffmpeg_timeout_seconds": 300,
            "transcribe_timeout_seconds": 300,
        }

        whisper = AsyncMock()
        whisper.detect_language = AsyncMock(return_value={"language": "yue", "language_probability": 0.91})
        whisper.transcribe = AsyncMock(
            return_value={"text": "你好", "segments": [], "timing": {"vad_ms": 0}, "requested_language": "yue"}
        )

        async def run_test() -> None:
            with patch("app.main.get_whisper_transcriber", return_value=whisper), patch(
                "app.main.convert_audio_to_wav",
                new_callable=AsyncMock,
            ) as convert_mock:
                result, convert_ms, wav_path = await main.run_transcription_with_lazy_conversion(
                    Path("uploads/sample.webm"),
                    "auto",
                    settings,
                )

            self.assertEqual(result["text"], "你好")
            self.assertEqual(result["requested_language"], "auto")
            self.assertEqual(result["detected_language"], "yue")
            self.assertEqual(result["language_probability"], 0.91)
            self.assertEqual(convert_ms, 0)
            self.assertIsNone(wav_path)
            convert_mock.assert_not_called()
            whisper.detect_language.assert_awaited_once_with("uploads/sample.webm")
            whisper.transcribe.assert_awaited_once_with("uploads/sample.webm", "yue")

        asyncio.run(run_test())

    def test_run_transcription_with_lazy_conversion_converts_when_auto_reroutes_to_mms(self) -> None:
        from app import main

        settings = {
            "output_dir": "outputs",
            "ffmpeg_timeout_seconds": 300,
            "transcribe_timeout_seconds": 300,
        }

        whisper = AsyncMock()
        whisper.detect_language = AsyncMock(return_value={"language": "my", "language_probability": 0.97})

        async def run_test() -> None:
            with patch("app.main.get_whisper_transcriber", return_value=whisper), patch(
                "app.main.convert_audio_to_wav",
                new=AsyncMock(return_value=Path("outputs/sample.wav")),
            ) as convert_mock, patch(
                "app.main.transcribe_audio",
                new=AsyncMock(
                    return_value={
                        "text": "မင်္ဂလာပါ",
                        "segments": [{"start": 0.0, "end": 1.0, "text": "မင်္ဂလာပါ"}],
                        "timing": {"vad_ms": 0},
                        "requested_language": "my",
                        "detected_language": "my",
                        "language_probability": 1.0,
                    }
                ),
            ) as transcribe_mock:
                result, convert_ms, wav_path = await main.run_transcription_with_lazy_conversion(
                    Path("uploads/sample.m4a"),
                    "auto",
                    settings,
                )

            self.assertGreaterEqual(convert_ms, 0)
            self.assertEqual(wav_path, Path("outputs/sample.wav"))
            self.assertEqual(result["requested_language"], "auto")
            self.assertEqual(result["detected_language"], "my")
            self.assertEqual(result["language_probability"], 0.97)
            convert_mock.assert_awaited_once_with("uploads/sample.m4a", "outputs", 300)
            transcribe_mock.assert_awaited_once_with("outputs/sample.wav", "my")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
