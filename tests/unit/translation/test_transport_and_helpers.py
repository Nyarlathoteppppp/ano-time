import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

from apple_translation import AppleTranslator
from native_notch_overlay import NativeNotchOverlay
from translator import Translator


class _StubbornProcess:
    def __init__(self):
        self.stdin = MagicMock()
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_calls <= 2:
            raise subprocess.TimeoutExpired("helper", timeout)
        return -9

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1


class TransportAndHelperTests(unittest.TestCase):
    def test_apple_translation_normalizes_auto_source_to_english(self):
        self.assertEqual(AppleTranslator.normalize_source_language("auto"), "en")
        self.assertEqual(AppleTranslator.normalize_source_language(""), "en")
        self.assertEqual(AppleTranslator.normalize_source_language("ja"), "ja")

    def test_apple_language_preparation_starts_without_claiming_ready(self):
        statuses = []
        translator = AppleTranslator.__new__(AppleTranslator)
        translator.started = threading.Event()
        translator.ready = threading.Event()
        translator.error = None
        translator.status = "initializing"
        translator.status_callback = lambda *args: statuses.append(args)
        translator._lock = threading.Lock()
        translator._pending = {}

        translator._handle_event({"type": "status", "status": "preparing_languages"})

        self.assertTrue(translator.started.is_set())
        self.assertFalse(translator.is_ready)
        self.assertEqual(statuses[-1][0], "preparing")

        translator._handle_event({"type": "status", "status": "ready"})
        self.assertTrue(translator.is_ready)
        self.assertEqual(statuses[-1][0], "ready")

    def test_remote_translation_verifies_tls_certificates(self):
        http_client = object()
        with (
            patch("translator.httpx.Client", return_value=http_client) as client_factory,
            patch("translator.OpenAI") as openai,
        ):
            Translator(
                api_key="test-key",
                base_url="https://api.groq.com/openai/v1",
                model="test-model",
            )

        self.assertTrue(client_factory.call_args.kwargs["verify"])
        self.assertFalse(client_factory.call_args.kwargs["trust_env"])
        self.assertIs(openai.call_args.kwargs["http_client"], http_client)

    def test_apple_helper_is_killed_and_reaped_after_shutdown_timeouts(self):
        process = _StubbornProcess()
        translator = AppleTranslator.__new__(AppleTranslator)
        translator.process = process

        translator.stop()

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, 3)
        self.assertIsNone(translator.process)

    def test_notch_helper_is_killed_and_reaped_after_shutdown_timeouts(self):
        process = _StubbornProcess()
        overlay = NativeNotchOverlay.__new__(NativeNotchOverlay)
        overlay.delegate = None
        overlay.process = process
        overlay._send = lambda _payload: None
        overlay._writer_stop = MagicMock()
        overlay._writer_thread = None

        overlay.close()

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, 3)
        self.assertIsNone(overlay.process)


if __name__ == "__main__":
    unittest.main()
