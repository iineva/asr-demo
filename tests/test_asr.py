import asyncio
import os
import tempfile
import unittest
import wave
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

from app.asr import ASRTranscriber, MmsTranscriber, TranscriberRouter


class DummyModel:
    def __init__(self) -> None:
        self.last_kwargs = None

    def transcribe(self, file_path, **kwargs):
        self.last_kwargs = kwargs
        segments = [SimpleNamespace(start=0.0, end=1.0, text=" မင်္ဂလာပါ ")]
        info = SimpleNamespace(language="my", language_probability=0.99)
        return segments, info


class DetectLanguageRecordingModel:
    def __init__(self) -> None:
        self.audio_inputs = []
        self.last_kwargs = None

    def transcribe(self, audio_input, **kwargs):
        self.audio_inputs.append(audio_input)
        self.last_kwargs = kwargs
        return [], SimpleNamespace(language="yue", language_probability=0.88)


class MyanmarAutoRetryModel:
    def __init__(self) -> None:
        self.calls = []

    def transcribe(self, file_path, **kwargs):
        self.calls.append(kwargs.copy())
        if len(self.calls) == 1:
            segments = [SimpleNamespace(start=0.0, end=1.0, text="")]
            info = SimpleNamespace(language="my", language_probability=0.99)
            return segments, info

        segments = [SimpleNamespace(start=0.0, end=1.0, text=" မင်္ဂလာပါ ")]
        info = SimpleNamespace(language="my", language_probability=0.99)
        return segments, info


class RecordingAsyncTranscriber:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def transcribe(self, file_path: str, language: str):
        self.calls.append((file_path, language))
        return self.payload


class RecordingWhisperRouterTranscriber(RecordingAsyncTranscriber):
    def __init__(self, payload, *, detected_language: Optional[str], language_probability: float) -> None:
        super().__init__(payload)
        self.detected_language = detected_language
        self.language_probability = language_probability
        self.detect_calls = []

    async def detect_language(self, file_path: str):
        self.detect_calls.append(file_path)
        return {"language": self.detected_language, "language_probability": self.language_probability}


class FakeProcessor:
    def __init__(self) -> None:
        self.inputs = []
        self.decode_calls = []

    def __call__(self, waveform, sampling_rate: int, return_tensors: str):
        self.inputs.append((waveform, sampling_rate, return_tensors))
        return {"input_values": "encoded-audio"}

    def batch_decode(self, generated_ids, skip_special_tokens: bool):
        self.decode_calls.append((generated_ids, skip_special_tokens))
        return [" မင်္ဂလာပါ "]


class FakeTensor:
    def squeeze(self, dim: int):
        return f"squeezed-{dim}"


class FakeArgmaxTensor:
    def __init__(self) -> None:
        self.argmax_calls = []

    def argmax(self, dim: int):
        self.argmax_calls.append(dim)
        return [["token-1", "token-2"]]


class FakeMmsOutputs:
    def __init__(self) -> None:
        self.logits = FakeArgmaxTensor()


class FakeMmsModel:
    def __init__(self) -> None:
        self.forward_calls = []
        self.outputs = FakeMmsOutputs()
        self.loaded_adapters = []

    def __call__(self, **kwargs):
        self.forward_calls.append(kwargs)
        return self.outputs

    def load_adapter(self, target_lang: str) -> None:
        self.loaded_adapters.append(target_lang)


class AsrTranscriberTests(unittest.TestCase):
    def tearDown(self) -> None:
        from app import asr

        asr.get_model_settings.cache_clear()
        if hasattr(asr, "get_mms_settings"):
            asr.get_mms_settings.cache_clear()
        asr._WHISPER_MODEL_INSTANCE = None
        asr._MMS_MODEL_INSTANCE = None
        asr._ROUTER_INSTANCE = None

    def test_transcribe_enforces_transcribe_task(self) -> None:
        model = DummyModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        result = transcriber._transcribe_sync("sample.wav", "auto")

        self.assertEqual(model.last_kwargs["task"], "transcribe")
        self.assertNotIn("language", model.last_kwargs)
        self.assertEqual(result["text"], "မင်္ဂလာပါ")

    def test_transcribe_uses_myanmar_script_prompt_for_my_language(self) -> None:
        model = DummyModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        transcriber._transcribe_sync("sample.wav", "my")

        self.assertEqual(model.last_kwargs["task"], "transcribe")
        self.assertEqual(model.last_kwargs["language"], "my")
        self.assertIn("မြန်မာ", model.last_kwargs["initial_prompt"])

    def test_transcribe_uses_overridden_myanmar_prompt_from_env(self) -> None:
        model = DummyModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        with patch.dict("os.environ", {"WHISPER_INITIAL_PROMPT_MY": "USE_CUSTOM_PROMPT"}, clear=False):
            transcriber._transcribe_sync("sample.wav", "my")

        self.assertEqual(model.last_kwargs["initial_prompt"], "USE_CUSTOM_PROMPT")

    def test_transcribe_retries_auto_myanmar_with_script_prompt_when_first_pass_is_empty(self) -> None:
        model = MyanmarAutoRetryModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        result = transcriber._transcribe_sync("sample.wav", "auto")

        self.assertEqual(len(model.calls), 2)
        self.assertNotIn("language", model.calls[0])
        self.assertEqual(model.calls[1]["language"], "my")
        self.assertIn("မြန်မာ", model.calls[1]["initial_prompt"])
        self.assertEqual(result["text"], "မင်္ဂလာပါ")
        self.assertEqual(result["detected_language"], "my")

    def test_transcribe_uses_runtime_beam_and_vad_settings(self) -> None:
        model = DummyModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        with patch.dict(
            "os.environ",
            {"WHISPER_BEAM_SIZE": "3", "WHISPER_VAD_FILTER": "false"},
            clear=False,
        ):
            from app import asr

            asr.get_model_settings.cache_clear()
            transcriber._transcribe_sync("sample.wav", "auto")

        self.assertEqual(model.last_kwargs["beam_size"], 3)
        self.assertFalse(model.last_kwargs["vad_filter"])

    def test_transcribe_disables_vad_by_default(self) -> None:
        model = DummyModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        transcriber._transcribe_sync("sample.wav", "auto")

        self.assertTrue(model.last_kwargs["vad_filter"])

    def test_builds_vad_metrics_from_transcription_info(self) -> None:
        info = SimpleNamespace(duration=10.0, duration_after_vad=6.5)

        metrics = ASRTranscriber.build_vad_metrics(info=info, vad_elapsed_ms=240)

        self.assertEqual(
            metrics,
            {
                "vad_elapsed_ms": 240,
                "input_duration_ms": 10000,
                "speech_duration_ms": 6500,
                "removed_silence_ms": 3500,
            },
        )

    def test_detect_language_uses_in_memory_preview_audio_for_wav(self) -> None:
        model = DetectLanguageRecordingModel()
        transcriber = ASRTranscriber(model=model, device="cpu")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
            file_path = audio_file.name

        try:
            with wave.open(file_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\x00\x00" * 16000 * 2)

            with patch.dict("os.environ", {"WHISPER_LANGUAGE_DETECT_SECONDS": "1.0"}, clear=False):
                result = transcriber._detect_language_sync(file_path)

            self.assertEqual(result["language"], "yue")
            self.assertEqual(result["language_probability"], 0.88)
            self.assertEqual(model.last_kwargs["task"], "transcribe")
            self.assertNotIsInstance(model.audio_inputs[0], str)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    def test_transcriber_router_routes_explicit_myanmar_to_mms(self) -> None:
        whisper = RecordingAsyncTranscriber({"engine": "whisper"})
        mms = RecordingAsyncTranscriber({"engine": "mms"})
        router = TranscriberRouter(whisper_getter=lambda: whisper, mms_getter=lambda: mms)

        result = asyncio.run(router.transcribe("sample.wav", "my"))

        self.assertEqual(result, {"engine": "mms"})
        self.assertEqual(mms.calls, [("sample.wav", "my")])
        self.assertEqual(whisper.calls, [])

    def test_transcriber_router_routes_auto_to_whisper(self) -> None:
        whisper = RecordingWhisperRouterTranscriber(
            {"requested_language": "yue", "detected_language": "yue", "language_probability": 0.99, "text": "你好", "segments": []},
            detected_language="yue",
            language_probability=0.99,
        )
        mms = RecordingAsyncTranscriber({"engine": "mms"})
        router = TranscriberRouter(whisper_getter=lambda: whisper, mms_getter=lambda: mms)

        result = asyncio.run(router.transcribe("sample.wav", "auto"))

        self.assertEqual(whisper.detect_calls, ["sample.wav"])
        self.assertEqual(whisper.calls, [("sample.wav", "yue")])
        self.assertEqual(result["requested_language"], "auto")
        self.assertEqual(result["detected_language"], "yue")
        self.assertEqual(result["language_probability"], 0.99)
        self.assertEqual(mms.calls, [])

    def test_transcriber_router_reroutes_auto_myanmar_detection_to_mms(self) -> None:
        whisper = RecordingWhisperRouterTranscriber(
            {"requested_language": "auto", "detected_language": "my", "language_probability": 0.91, "text": "latin fallback", "segments": []},
            detected_language="my",
            language_probability=0.91,
        )
        mms = RecordingAsyncTranscriber(
            {
                "requested_language": "my",
                "detected_language": "my",
                "language_probability": 1.0,
                "text": "မင်္ဂလာပါ",
                "segments": [{"start": 0.0, "end": 1.0, "text": "မင်္ဂလာပါ"}],
                "timing": {"vad_ms": 0},
            }
        )
        router = TranscriberRouter(whisper_getter=lambda: whisper, mms_getter=lambda: mms)

        result = asyncio.run(router.transcribe("sample.wav", "auto"))

        self.assertEqual(whisper.detect_calls, ["sample.wav"])
        self.assertEqual(whisper.calls, [])
        self.assertEqual(mms.calls, [("sample.wav", "my")])
        self.assertEqual(result["requested_language"], "auto")
        self.assertEqual(result["detected_language"], "my")
        self.assertEqual(result["language_probability"], 0.91)
        self.assertEqual(result["text"], "မင်္ဂလာပါ")
        self.assertEqual(result["segments"], [{"start": 0.0, "end": 1.0, "text": "မင်္ဂလာပါ"}])

    def test_transcriber_router_falls_back_to_whisper_auto_when_detection_unknown(self) -> None:
        whisper = RecordingWhisperRouterTranscriber(
            {"requested_language": "auto", "detected_language": "auto", "language_probability": 0.4, "text": "fallback", "segments": []},
            detected_language=None,
            language_probability=0.0,
        )
        mms = RecordingAsyncTranscriber({"engine": "mms"})
        router = TranscriberRouter(whisper_getter=lambda: whisper, mms_getter=lambda: mms)

        result = asyncio.run(router.transcribe("sample.wav", "auto"))

        self.assertEqual(whisper.detect_calls, ["sample.wav"])
        self.assertEqual(whisper.calls, [("sample.wav", "auto")])
        self.assertEqual(result["text"], "fallback")
        self.assertEqual(mms.calls, [])

    def test_transcriber_router_routes_yue_to_whisper(self) -> None:
        whisper = RecordingAsyncTranscriber({"engine": "whisper"})
        mms = RecordingAsyncTranscriber({"engine": "mms"})
        router = TranscriberRouter(whisper_getter=lambda: whisper, mms_getter=lambda: mms)

        result = asyncio.run(router.transcribe("sample.wav", "yue"))

        self.assertEqual(result, {"engine": "whisper"})
        self.assertEqual(whisper.calls, [("sample.wav", "yue")])
        self.assertEqual(mms.calls, [])

    def test_mms_transcriber_normalizes_result_payload_without_timestamps(self) -> None:
        transcriber = MmsTranscriber(
            processor=FakeProcessor(),
            model=FakeMmsModel(),
            device="cpu",
            audio_loader=lambda _path: (FakeTensor(), 16000),
            duration_getter=lambda _path: 1.75,
        )

        result = transcriber._normalize_result(" မင်္ဂလာပါ ", 1.75, "my")

        self.assertEqual(result["requested_language"], "my")
        self.assertEqual(result["detected_language"], "my")
        self.assertEqual(result["language_probability"], 1.0)
        self.assertEqual(result["text"], "မင်္ဂလာပါ")
        self.assertEqual(result["segments"], [{"start": 0.0, "end": 1.75, "text": "မင်္ဂလာပါ"}])

    def test_mms_transcriber_invokes_processor_model_and_decoder(self) -> None:
        processor = FakeProcessor()
        model = FakeMmsModel()
        transcriber = MmsTranscriber(
            processor=processor,
            model=model,
            device="cpu",
            audio_loader=lambda _path: (FakeTensor(), 16000),
            duration_getter=lambda _path: 2.25,
        )

        result = asyncio.run(transcriber.transcribe("sample.wav", "my"))

        self.assertEqual(processor.inputs, [("squeezed-0", 16000, "pt")])
        self.assertEqual(model.forward_calls, [{"input_values": "encoded-audio"}])
        self.assertEqual(model.outputs.logits.argmax_calls, [-1])
        self.assertEqual(processor.decode_calls, [([["token-1", "token-2"]], True)])
        self.assertEqual(result["detected_language"], "my")
        self.assertEqual(result["segments"], [{"start": 0.0, "end": 2.25, "text": "မင်္ဂလာပါ"}])

    def test_mms_transcriber_logs_inference_start_and_end(self) -> None:
        from app import asr

        processor = FakeProcessor()
        model = FakeMmsModel()
        transcriber = MmsTranscriber(
            processor=processor,
            model=model,
            device="mps",
            audio_loader=lambda _path: (FakeTensor(), 16000),
            duration_getter=lambda _path: 2.25,
        )

        with patch.object(asr.LOGGER, "info") as logger_info:
            result = transcriber._transcribe_sync("sample.wav", "my")

        self.assertEqual(result["text"], "မင်္ဂလာပါ")
        logger_info.assert_any_call(
            "mms decode step=start file=%s language=%s device=%s",
            "sample.wav",
            "my",
            "mps",
        )
        end_calls = [
            call.args
            for call in logger_info.call_args_list
            if call.args and call.args[0] == "mms decode step=done elapsed_ms=%s text_len=%s"
        ]
        self.assertEqual(len(end_calls), 1)
        self.assertEqual(end_calls[0][2], len("မင်္ဂလာပါ"))

    def test_mms_transcriber_applies_vad_when_enabled(self) -> None:
        processor = FakeProcessor()
        model = FakeMmsModel()
        vad_calls = []

        transcriber = MmsTranscriber(
            processor=processor,
            model=model,
            device="cpu",
            audio_loader=lambda _path: (FakeTensor(), 16000),
            duration_getter=lambda _path: 2.25,
            vad_filter=True,
            vad_processor=lambda waveform, sample_rate: (vad_calls.append((waveform, sample_rate)) or waveform, 37),
        )

        result = asyncio.run(transcriber.transcribe("sample.wav", "my"))

        self.assertEqual(len(vad_calls), 1)
        self.assertEqual(vad_calls[0][1], 16000)
        self.assertEqual(result["timing"]["vad_ms"], 37)

    def test_get_mms_settings_reads_runtime_env(self) -> None:
        from app import asr

        with patch.dict(
            "os.environ",
            {
                "MMS_MODEL_ID": "facebook/mms-1b-all",
                "MMS_DEVICE": "cuda",
                "MMS_TORCH_DTYPE": "float16",
            },
            clear=False,
        ):
            settings = asr.get_mms_settings()

        self.assertEqual(settings.model_id, "facebook/mms-1b-all")
        self.assertEqual(settings.device, "cuda")
        self.assertEqual(settings.torch_dtype, "float16")

    def test_get_mms_settings_prefers_mps_when_auto_on_apple_silicon(self) -> None:
        from app import asr

        with patch("app.asr._is_cuda_available", return_value=False), patch(
            "app.asr._is_mps_available", return_value=True
        ), patch.dict("os.environ", {"MMS_DEVICE": "auto"}, clear=False):
            settings = asr.get_mms_settings()

        self.assertEqual(settings.device, "mps")

    def test_create_mms_transcriber_logs_selected_runtime(self) -> None:
        from app import asr

        fake_processor = object()
        fake_model = FakeMmsModel()
        fake_model.to = lambda device: fake_model
        fake_settings = asr.MmsSettings(
            model_id="facebook/mms-1b-all",
            device="mps",
            torch_dtype="float16",
            vad_filter=True,
        )

        with patch("app.asr.get_mms_settings", return_value=fake_settings), patch(
            "app.asr._load_mms_processor", return_value=fake_processor
        ), patch.object(asr.LOGGER, "info") as logger_info:
            with patch("app.asr._load_mms_model", return_value=fake_model) as load_model:
                with patch("app.asr._load_mms_processor", return_value=fake_processor) as load_processor:
                    transcriber = asr._create_mms_transcriber()

        self.assertEqual(transcriber.device, "mps")
        self.assertEqual(fake_model.loaded_adapters, ["mya"])
        load_processor.assert_called_once_with("facebook/mms-1b-all", "mya")
        load_model.assert_called_once_with("facebook/mms-1b-all", "mya")
        logger_info.assert_any_call(
            "mms runtime init step=start model_id=%s device=%s target_lang=%s",
            "facebook/mms-1b-all",
            "mps",
            "mya",
        )
        done_calls = [
            call.args
            for call in logger_info.call_args_list
            if call.args
            and call.args[0]
            == "mms runtime init step=done elapsed_ms=%s model_id=%s device=%s torch_dtype=%s target_lang=%s"
        ]
        self.assertEqual(len(done_calls), 1)
        self.assertEqual(done_calls[0][2], "facebook/mms-1b-all")
        self.assertEqual(done_calls[0][3], "mps")
        self.assertEqual(done_calls[0][4], "float16")
        self.assertEqual(done_calls[0][5], "mya")

    def test_whisper_and_mms_singletons_are_cached_independently(self) -> None:
        from app import asr

        whisper_one = object()
        whisper_two = object()
        mms_one = object()
        mms_two = object()

        with patch("app.asr._create_whisper_transcriber", side_effect=[whisper_one, whisper_two]), patch(
            "app.asr._create_mms_transcriber", side_effect=[mms_one, mms_two]
        ):
            self.assertIs(asr.get_whisper_transcriber(), whisper_one)
            self.assertIs(asr.get_whisper_transcriber(), whisper_one)
            self.assertIs(asr.get_mms_transcriber(), mms_one)
            self.assertIs(asr.get_mms_transcriber(), mms_one)

        self.assertIsNot(asr.get_whisper_transcriber(), asr.get_mms_transcriber())

    def test_transcribe_audio_auto_does_not_initialize_mms(self) -> None:
        from app import asr

        whisper = RecordingWhisperRouterTranscriber(
            {
                "requested_language": "yue",
                "detected_language": "yue",
                "language_probability": 0.99,
                "text": "test",
                "segments": [],
            },
            detected_language="yue",
            language_probability=0.99,
        )

        with patch("app.asr.get_whisper_transcriber", return_value=whisper), patch(
            "app.asr.get_mms_transcriber", side_effect=AssertionError("MMS should not be initialized for auto")
        ):
            result = asyncio.run(asr.transcribe_audio("sample.wav", "auto"))

        self.assertEqual(result["text"], "test")
        self.assertEqual(whisper.detect_calls, ["sample.wav"])
        self.assertEqual(whisper.calls, [("sample.wav", "yue")])


if __name__ == "__main__":
    unittest.main()
