import unittest

from translator import Translator


class TranslatorLanguageTest(unittest.TestCase):
    def test_chinese_aliases_are_simplified_for_generic_prompts(self):
        aliases = ("Chinese", "zh", "zh-CN", "zh_Hans", "Simplified Chinese")
        for language in aliases:
            with self.subTest(language=language):
                self.assertEqual(
                    Translator._prompt_target_language(language),
                    "Simplified Chinese",
                )

    def test_other_languages_are_unchanged(self):
        self.assertEqual(Translator._prompt_target_language("Japanese"), "Japanese")
        self.assertEqual(
            Translator._prompt_target_language("Traditional Chinese"),
            "Traditional Chinese",
        )


if __name__ == "__main__":
    unittest.main()
