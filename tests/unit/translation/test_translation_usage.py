import unittest
import os
import tempfile
import threading
from unittest.mock import patch

from translation_usage import DailyUsageLedger, MeteredTranslator, TranslationUsageMeter


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

    def test_estimated_usage_is_kept_separate_from_exact_tokens(self):
        meter = TranslationUsageMeter()
        meter.record("Provider", {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "estimated": True,
        }, 1.0, 2.0, True)
        meter.record("Provider", {
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
            "estimated": False,
        }, 1.0, 2.0, True)

        snapshot = meter.snapshot()

        self.assertEqual(snapshot["prompt_tokens"], 200)
        self.assertEqual(snapshot["estimated_prompt_tokens"], 120)
        self.assertEqual(snapshot["estimated_completion_tokens"], 30)
        self.assertEqual(snapshot["estimated_requests"], 1)
        self.assertGreater(snapshot["estimated_cost_usd"], 0)

    def test_wrapper_preserves_translation_and_records_usage(self):
        meter = TranslationUsageMeter()
        wrapped = MeteredTranslator(_FakeTranslator(), "Provider", 1.0, 2.0)
        with patch("translation_usage.session_usage_meter", meter):
            self.assertEqual(wrapped.translate("hello"), "hello")
        snapshot = meter.snapshot()
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

    def test_daily_cost_survives_session_reset_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "daily.json")
            ledger = DailyUsageLedger(path)
            meter = TranslationUsageMeter(ledger)
            meter.record("Gemini", {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 100_000,
                "total_tokens": 1_100_000,
            }, 0.30, 2.50, True)
            meter.reset()
            self.assertEqual(meter.snapshot()["requests"], 0)
            self.assertAlmostEqual(meter.snapshot()["today"]["cost_usd"], 0.55)
            ledger.flush()

            restored = DailyUsageLedger(path)
            self.assertAlmostEqual(restored.snapshot()["cost_usd"], 0.55)
            self.assertEqual(restored.snapshot()["requests"], 1)

    def test_concurrent_daily_records_use_one_writer_and_lose_no_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = DailyUsageLedger(os.path.join(directory, "daily.json"))
            threads = [
                threading.Thread(target=ledger.record, args=({
                    "requests": 1,
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },))
                for _ in range(40)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            ledger.flush()

            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["requests"], 40)
            self.assertEqual(snapshot["total_tokens"], 120)
            self.assertIsNotNone(ledger._writer)

    def test_daily_ledger_rolls_over_on_local_date(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = DailyUsageLedger(os.path.join(directory, "daily.json"))
            ledger.record({"requests": 1, "cost_usd": 0.25})
            with patch.object(ledger, "_today", return_value="2099-01-01"):
                snapshot = ledger.snapshot()
            self.assertEqual(snapshot["requests"], 0)
            self.assertEqual(snapshot["cost_usd"], 0.0)
            ledger.flush()


if __name__ == "__main__":
    unittest.main()
