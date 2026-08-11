import unittest

from dashboard_support.provider_catalog import default_model_price


class ProviderCatalogTests(unittest.TestCase):
    def test_known_models_have_builtin_prices(self):
        self.assertEqual(
            default_model_price("Google Gemini", "gemini-3.5-flash-lite"),
            (0.30, 2.50),
        )
        self.assertEqual(
            default_model_price("Groq", "openai/gpt-oss-20b"),
            (0.075, 0.30),
        )

    def test_unknown_model_is_never_guessed(self):
        self.assertEqual(
            default_model_price("Custom OpenAI-Compatible", "private-model"),
            (0.0, 0.0),
        )


if __name__ == "__main__":
    unittest.main()
