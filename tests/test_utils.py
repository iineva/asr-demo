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


if __name__ == "__main__":
    unittest.main()
