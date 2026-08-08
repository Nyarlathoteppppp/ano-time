import os
import tempfile
import time
import unittest

from hybrid_translator import HybridTranslator


class _FakeTranslator:
    def __init__(self, name, error=None):
        self.name = name
        self.error = error
        self.calls = 0

    def translate(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
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


if __name__ == "__main__":
    unittest.main()
