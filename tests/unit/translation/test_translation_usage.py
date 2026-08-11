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
        with patch(
            "translation_usage.time.monotonic", side_effect=[20.0, 20.0, 80.0]
        ):
            meter._first_usage_at = None
            meter.set_active(True)
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

    def test_hourly_projection_clock_freezes_while_paused(self):
        meter = TranslationUsageMeter()
        with patch(
            "translation_usage.time.monotonic",
            side_effect=[0.0, 0.0, 10.0, 10.0, 70.0],
        ):
            meter.set_active(True)
            meter.record("Gemini", {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "total_tokens": 1_000_000,
            }, 1.0, 1.0, True)
            meter.set_active(False)
            paused = meter.snapshot()
            later = meter.snapshot()
        self.assertEqual(paused["elapsed_seconds"], 10.0)
        self.assertEqual(later["elapsed_seconds"], 10.0)
        self.assertEqual(paused["hourly_cost_usd"], later["hourly_cost_usd"])

    def test_warmup_cost_is_totaled_but_excluded_from_hourly_projection(self):
        meter = TranslationUsageMeter()
        with patch(
            "translation_usage.time.monotonic",
            side_effect=[0.0, 10.0, 10.0, 70.0],
        ):
            meter.record("Gemini", {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "total_tokens": 1_000_000,
            }, 1.0, 1.0, True)
            meter.set_active(True)
            meter.record("Gemini", {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 0,
                "total_tokens": 1_000_000,
            }, 1.0, 1.0, True)
            snapshot = meter.snapshot()
        self.assertEqual(snapshot["cost_usd"], 2.0)
        self.assertEqual(snapshot["elapsed_seconds"], 60.0)
        self.assertEqual(snapshot["hourly_cost_usd"], 60.0)

    def test_disabled_meter_ignores_usage_without_affecting_callers(self):
        meter = TranslationUsageMeter()
        meter.set_enabled(False)
        meter.record("Gemini", {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }, 0.3, 2.5, True)
        snapshot = meter.snapshot()
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["requests"], 0)


if __name__ == "__main__":
    unittest.main()
