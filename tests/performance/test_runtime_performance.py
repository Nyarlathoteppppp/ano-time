import time
import unittest
from unittest.mock import patch

from runtime_performance import RuntimePerformanceSampler
from runtime_log import configure_diagnostics


class RuntimePerformanceTests(unittest.TestCase):
    def tearDown(self):
        configure_diagnostics(False)

    def test_sampler_does_not_start_when_diagnostics_are_off(self):
        configure_diagnostics(False)
        sampler = RuntimePerformanceSampler(interval_seconds=0.01)
        self.assertFalse(sampler.start())
        self.assertIsNone(sampler._thread)

    def test_sampler_records_resource_and_subtitle_rate_then_stops(self):
        configure_diagnostics(True)
        samples = []
        sampler = RuntimePerformanceSampler(
            event_count_provider=lambda: 3,
            interval_seconds=0.01,
        )
        with patch(
            "runtime_performance.log_stage",
            side_effect=lambda stage, **metrics: samples.append((stage, metrics)),
        ):
            sampler.start()
            time.sleep(0.035)
            sampler.stop()

        self.assertGreaterEqual(len(samples), 1)
        stage, metrics = samples[0]
        self.assertEqual(stage, "runtime_performance")
        self.assertEqual(metrics["subtitle_events"], 3)
        self.assertGreaterEqual(float(metrics["cpu_percent"]), 0)
        self.assertGreater(float(metrics["rss_mb"]), 0)
        self.assertIsNone(sampler._thread)
