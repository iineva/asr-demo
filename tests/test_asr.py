import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.asr import ASRTranscriber


class DummyModel:
    def __init__(self) -> None:
        self.last_kwargs = None

    def transcribe(self, file_path, **kwargs):
        self.last_kwargs = kwargs
        segments = [SimpleNamespace(start=0.0, end=1.0, text=" မင်္ဂလာပါ ")]
        info = SimpleNamespace(language="my", language_probability=0.99)
        return segments, info


class AsrTranscriberTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
