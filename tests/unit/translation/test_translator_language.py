import unittest
from types import SimpleNamespace

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

    def test_gemini_warmup_uses_tiny_stream_and_closes_it(self):
        class Stream(list):
            closed = False

            def close(self):
                self.closed = True

        stream = Stream([
            SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="准备好了")
                )]
            )
        ])
        completions = SimpleNamespace(
            create=lambda **options: (
                setattr(completions, "options", options) or stream
            )
        )
        translator = Translator.__new__(Translator)
        translator.base_url = (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        translator.model = "gemini-3.5-flash-lite"
        translator.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        self.assertTrue(translator.warmup())
        self.assertEqual(completions.options["max_tokens"], 4)
        self.assertTrue(completions.options["stream"])
        self.assertEqual(completions.options["reasoning_effort"], "minimal")
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
