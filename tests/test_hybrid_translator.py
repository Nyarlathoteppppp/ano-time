import os
import tempfile
import time
import unittest

from hybrid_translator import HybridTranslator


class _FakeTranslator:
    def __init__(self, name, error=None, usage=None):
        self.name = name
        self.error = error
        self.usage = usage
        self.calls = 0

    def translate(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        if self.usage is not None and _kwargs.get("usage_callback"):
            _kwargs["usage_callback"](self.usage)
        return self.name


class _StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class HybridTranslatorTests(unittest.TestCase):
    def _router(self, providers, directory):
        return HybridTranslator(
            providers,
            usage_path=os.path.join(directory, "usage.json"),
        )

    def test_round_robins_without_double_sending(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq")
            gemini = _FakeTranslator("gemini")
            router = self._router(
                [
                    {"name": "groq", "translator": groq, "daily_limit": 1000},
                    {"name": "gemini", "translator": gemini},
                ],
                directory,
            )
            self.assertEqual(router.translate("one"), "groq")
            self.assertEqual(router.translate("two"), "gemini")
            self.assertEqual((groq.calls, gemini.calls), (1, 1))

    def test_reports_active_provider_and_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            router = self._router(
                [{"name": "gemini", "translator": _FakeTranslator("translated")}],
                directory,
            )
            events = []
            router.status_callback = lambda *event: events.append(event)
            self.assertEqual(router.translate("sentence"), "translated")
            self.assertEqual(events[0][:2], ("active", "gemini"))
            self.assertEqual(events[-1][:2], ("ok", "gemini"))
            self.assertIsNotNone(events[-1][2])

    def test_rate_limit_immediately_fails_over(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq", _StatusError(429))
            gemini = _FakeTranslator("gemini")
            router = self._router(
                [
                    {"name": "groq", "translator": groq},
                    {"name": "gemini", "translator": gemini},
                ],
                directory,
            )
            self.assertEqual(router.translate("sentence"), "gemini")
            self.assertEqual((groq.calls, gemini.calls), (1, 1))
            self.assertEqual(router.translate("next"), "gemini")
            self.assertEqual(groq.calls, 1)

    def test_provider_timeout_fails_over_when_deadline_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq", TimeoutError("provider timeout"))
            gemini = _FakeTranslator("gemini")
            router = self._router(
                [
                    {"name": "groq", "translator": groq},
                    {"name": "gemini", "translator": gemini},
                ],
                directory,
            )
            self.assertEqual(
                router.translate("sentence", deadline=time.monotonic() + 3),
                "gemini",
            )
            self.assertEqual((groq.calls, gemini.calls), (1, 1))

    def test_persisted_daily_limit_skips_exhausted_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq")
            gemini = _FakeTranslator("gemini")
            router = self._router(
                [
                    {"name": "groq", "translator": groq, "daily_limit": 1},
                    {"name": "gemini", "translator": gemini},
                ],
                directory,
            )
            self.assertEqual(router.translate("one"), "groq")
            self.assertEqual(router.translate("two"), "gemini")
            self.assertEqual(router.translate("three"), "gemini")
            self.assertEqual(groq.calls, 1)

    def test_fallback_priority_waits_until_free_quotas_are_exhausted(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq")
            gemini = _FakeTranslator("gemini")
            qwen = _FakeTranslator("qwen")
            router = self._router(
                [
                    {"name": "groq", "translator": groq, "daily_limit": 1, "priority": 0},
                    {"name": "gemini", "translator": gemini, "daily_limit": 1, "priority": 0},
                    {"name": "qwen", "translator": qwen, "priority": 1},
                ],
                directory,
            )
            self.assertEqual(router.translate("one"), "groq")
            self.assertEqual(router.translate("two"), "gemini")
            self.assertEqual(router.translate("three"), "qwen")
            self.assertEqual((groq.calls, gemini.calls, qwen.calls), (1, 1, 1))

    def test_expired_minute_cooldown_returns_provider_to_free_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            groq = _FakeTranslator("groq")
            qwen = _FakeTranslator("qwen")
            router = self._router(
                [
                    {"name": "groq", "translator": groq, "priority": 0},
                    {"name": "qwen", "translator": qwen, "priority": 1},
                ],
                directory,
            )
            router.providers[0]["cooldown_until"] = time.monotonic() + 60
            self.assertEqual(router.translate("during cooldown"), "qwen")
            router.providers[0]["cooldown_until"] = time.monotonic() - 1
            self.assertEqual(router.translate("after reset"), "groq")

    def test_actual_usage_replaces_reservation_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            usage_path = os.path.join(directory, "usage.json")
            first_groq = _FakeTranslator("groq", usage=900)
            first_router = HybridTranslator(
                [
                    {
                        "name": "groq",
                        "translator": first_groq,
                        "tpm_limit": 1000,
                        "priority": 0,
                    }
                ],
                usage_path=usage_path,
            )
            self.assertEqual(first_router.translate("first"), "groq")
            self.assertEqual(first_router.providers[0]["last_minute_tokens"], 900)

            restarted_groq = _FakeTranslator("groq")
            qwen = _FakeTranslator("qwen")
            restarted = HybridTranslator(
                [
                    {
                        "name": "groq",
                        "translator": restarted_groq,
                        "tpm_limit": 1000,
                        "priority": 0,
                    },
                    {"name": "qwen", "translator": qwen, "priority": 1},
                ],
                usage_path=usage_path,
            )
            self.assertEqual(restarted.translate("second"), "qwen")
            self.assertEqual(restarted_groq.calls, 0)

    def test_cloudflare_neurons_use_actual_daily_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            glm = _FakeTranslator(
                "glm", usage={"total_tokens": 71, "neurons": 0.98}
            )
            qwen = _FakeTranslator("qwen")
            router = self._router(
                [
                    {
                        "name": "glm",
                        "translator": glm,
                        "daily_neuron_limit": 4,
                        "neuron_input_per_million": 5500,
                        "neuron_output_per_million": 36400,
                        "priority": 0,
                    },
                    {"name": "qwen", "translator": qwen, "priority": 1},
                ],
                directory,
            )
            self.assertEqual(router.translate("one"), "glm")
            self.assertAlmostEqual(router.providers[0]["last_daily_neurons"], 0.98)
            self.assertEqual(router.translate("two"), "glm")
            self.assertAlmostEqual(router.providers[0]["last_daily_neurons"], 1.96)
            self.assertEqual(router.translate("three"), "qwen")

    def test_configured_quality_speed_priority_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            gemini = _FakeTranslator("gemini")
            glm = _FakeTranslator("glm")
            groq = _FakeTranslator("groq")
            router = self._router(
                [
                    {"name": "gemini", "translator": gemini, "daily_limit": 1, "priority": 0},
                    {"name": "glm", "translator": glm, "daily_limit": 1, "priority": 1},
                    {"name": "groq", "translator": groq, "priority": 2},
                ],
                directory,
            )
            self.assertEqual(router.translate("one"), "gemini")
            self.assertEqual(router.translate("two"), "glm")
            self.assertEqual(router.translate("three"), "groq")

    def test_provider_filtering_shares_quota_and_separates_bridge_from_final(self):
        with tempfile.TemporaryDirectory() as directory:
            gemini = _FakeTranslator("gemini")
            groq = _FakeTranslator("groq")
            qwen = _FakeTranslator("qwen")
            router = self._router(
                [
                    {"name": "gemini", "translator": gemini, "priority": 0},
                    {
                        "name": "groq",
                        "translator": groq,
                        "daily_limit": 1,
                        "priority": 1,
                    },
                    {"name": "qwen", "translator": qwen, "priority": 2},
                ],
                directory,
            )
            self.assertEqual(router.translate_only({"groq"}, "bridge"), "groq")
            self.assertEqual(
                router.translate_excluding({"groq"}, "final"), "gemini"
            )
            with self.assertRaises(RuntimeError):
                router.translate_only({"groq"}, "bridge quota exhausted")
            self.assertEqual((groq.calls, gemini.calls, qwen.calls), (1, 1, 0))


if __name__ == "__main__":
    unittest.main()
