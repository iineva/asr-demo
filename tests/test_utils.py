import unittest
from pathlib import Path


class UtilsContractTests(unittest.TestCase):
    def test_validate_language_allows_supported_values(self) -> None:
        from app.utils import validate_language

        self.assertEqual(validate_language("auto"), "auto")
        self.assertEqual(validate_language("my"), "my")
        self.assertEqual(validate_language("yue"), "yue")

    def test_validate_language_rejects_unknown(self) -> None:
        from app.utils import validate_language

        with self.assertRaises(ValueError):
            validate_language("zh")

    def test_normalize_text_collapses_whitespace(self) -> None:
        from app.utils import normalize_text

        self.assertEqual(normalize_text("  hello   world \n "), "hello world")

    def test_requirements_include_requests_for_faster_whisper_runtime(self) -> None:
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("requests", requirements)

    def test_requirements_include_mms_runtime_dependencies(self) -> None:
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("transformers", requirements)
        self.assertIn("torchaudio", requirements)

    def test_docker_compose_uses_hf_home_without_deprecated_transformers_cache(self) -> None:
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("HF_HOME:", compose)
        self.assertNotIn("TRANSFORMERS_CACHE:", compose)

    def test_docker_compose_uses_supported_mms_asr_model(self) -> None:
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("MMS_MODEL_ID: facebook/mms-1b-all", compose)


if __name__ == "__main__":
    unittest.main()
