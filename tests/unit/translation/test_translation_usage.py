import unittest
from unittest.mock import patch

from translation_usage import MeteredTranslator, TranslationUsageMeter


class _FakeTranslator:
    def translate(self, text, **kwargs):
        kwargs["usage_callback"]({
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
        })
        return text


class TranslationUsageTests(unittest.TestCase):
    def test_exact_cost_and_hourly_projection_use_provider_split(self):
        meter = TranslationUsageMeter()
        with patch("translation_usage.time.monotonic", side_effect=[20.0, 80.0]):
            meter._first_usage_at = None
            meter.record("Gemini", {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 100_000,
                "total_tokens": 1_100_000,
            }, 0.30, 2.50, True)
            snapshot = meter.snapshot()
        self.assertAlmostEqual(snapshot["cost_usd"], 0.55)
        self.assertAlmostEqual(snapshot["hourly_cost_usd"], 33.0)
        self.assertEqual(snapshot["unpriced_requests"], 0)

    def test_total_only_usage_is_visible_but_not_given_an_invented_cost(self):
        meter = TranslationUsageMeter()
        meter.record("Custom", {"total_tokens": 42}, 1.0, 2.0, True)
        snapshot = meter.snapshot()
        self.assertEqual(snapshot["total_tokens"], 42)
        self.assertEqual(snapshot["cost_usd"], 0.0)
        self.assertEqual(snapshot["unpriced_requests"], 1)

    def test_wrapper_preserves_translation_and_records_usage(self):
        from translation_usage import session_usage_meter
        session_usage_meter.reset()
        wrapped = MeteredTranslator(_FakeTranslator(), "Provider", 1.0, 2.0)
        self.assertEqual(wrapped.translate("hello"), "hello")
        snapshot = session_usage_meter.snapshot()
        self.assertEqual(snapshot["requests"], 1)
        self.assertEqual(snapshot["prompt_tokens"], 1000)


if __name__ == "__main__":
    unittest.main()
