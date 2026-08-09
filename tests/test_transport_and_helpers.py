import subprocess
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
