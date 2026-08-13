import threading
import unittest
from unittest.mock import Mock

from apple_transcriber import AppleSpeechTranscriber


class AppleSpeechTranscriberTests(unittest.TestCase):
    def test_reset_suppresses_feed_and_restarts_native_session(self):
        transcriber = AppleSpeechTranscriber()
        calls = []
        transcriber.stop = Mock(side_effect=lambda: calls.append("stop"))
        transcriber.start = Mock(side_effect=lambda: calls.append("start"))

        transcriber.reset()

        self.assertEqual(calls, ["stop", "start"])
        self.assertFalse(transcriber._resetting.is_set())

    def test_feed_drops_boundary_audio_while_resetting(self):
        transcriber = AppleSpeechTranscriber()
        transcriber._resetting.set()
        self.assertFalse(transcriber.feed([0.1, 0.2]))

    def test_old_native_process_generation_is_rejected_after_restart(self):
        transcriber = AppleSpeechTranscriber()
        old_process = object()
        current_process = object()
        transcriber.process = current_process
        transcriber._process_generation = 2

        self.assertFalse(transcriber._accepts_event_from(old_process, 1))
        self.assertTrue(transcriber._accepts_event_from(current_process, 2))


if __name__ == "__main__":
    unittest.main()
