import threading
import unittest

from types import SimpleNamespace

from smart_hint import SmartHint, SmartHintScheduler, build_smart_hint_scheduler


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result or SmartHint("Statistical machine learning", ("regularisation",))
        self.error = error
        self.sources = []
        self.closed = False

    def summarize(self, source):
        self.sources.append(tuple(source))
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True


class SmartHintSchedulerTests(unittest.TestCase):
    def test_runs_only_after_interval_and_keeps_latest_forty_final_sources(self):
        now = [0.0]
        statuses = []
        client = FakeClient()
        scheduler = SmartHintScheduler(
            client,
            interval_seconds=30,
            status_callback=lambda *args: statuses.append(args),
            clock=lambda: now[0],
        )
        try:
            for index in range(45):
                scheduler.observe_finalized(f"final source {index}")
            self.assertEqual(client.sources, [])
            self.assertEqual(len(scheduler.source_snapshot()), 40)
            self.assertEqual(scheduler.source_snapshot()[0], "final source 5")

            now[0] = 31.0
            self.assertTrue(scheduler.observe_finalized("new finalized source"))
            future = scheduler._future
            future.result(timeout=1)

            self.assertEqual(len(client.sources), 1)
            self.assertEqual(len(client.sources[0]), 40)
            self.assertIn("Inferred lecture topic", scheduler.snapshot())
            self.assertTrue(any(status == "ok" for status, _ in statuses))
        finally:
            scheduler.shutdown()
        self.assertTrue(client.closed)

    def test_failure_is_reported_without_retaining_a_failed_hint(self):
        now = [0.0]
        statuses = []
        client = FakeClient(error=RuntimeError("service unavailable"))
        scheduler = SmartHintScheduler(
            client,
            interval_seconds=30,
            status_callback=lambda *args: statuses.append(args),
            clock=lambda: now[0],
        )
        try:
            for index in range(4):
                scheduler.observe_finalized(f"source {index}")
            now[0] = 31.0
            self.assertTrue(scheduler.observe_finalized("source 4"))
            # Scheduler starts at t=30. It must fail privately rather than
            # leaking an exception to the caller or altering translation state.
            # The task can finish before _future is inspected.
            for _ in range(50):
                if any(status == "warning" for status, _ in statuses):
                    break
                threading.Event().wait(0.01)
            self.assertEqual(scheduler.snapshot(), "")
            self.assertTrue(any(status == "warning" for status, _ in statuses))
        finally:
            scheduler.shutdown()

    def test_hint_prompt_is_compact_and_combines_topic_and_keywords(self):
        hint = SmartHint("Bayesian inference", ("prior", "posterior", "MCMC"))
        self.assertEqual(
            hint.prompt_text(),
            "Inferred lecture topic: Bayesian inference. Relevant terms: prior, posterior, MCMC.",
        )

    def test_siliconflow_can_reuse_the_existing_provider_key(self):
        settings = SimpleNamespace(
            smart_hint_enabled=True,
            smart_hint_provider="siliconflow",
            smart_hint_api_key="",
            siliconflow_api_key="saved-provider-key",
            smart_hint_base_url="https://api.siliconflow.cn/v1",
            smart_hint_model="deepseek-ai/DeepSeek-V4-Flash",
            smart_hint_interval_seconds=240,
        )
        scheduler = build_smart_hint_scheduler(settings)
        try:
            self.assertIsNotNone(scheduler)
        finally:
            scheduler.shutdown()
