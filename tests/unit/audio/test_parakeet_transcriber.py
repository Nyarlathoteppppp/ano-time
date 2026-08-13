import threading
import unittest
from unittest.mock import Mock

import numpy as np

from parakeet_transcriber import ParakeetEOUTranscriber


class ParakeetEOUTranscriberTests(unittest.TestCase):
    def test_only_accepts_english_and_16khz(self):
        with self.assertRaises(ValueError):
            ParakeetEOUTranscriber(language="zh")
        with self.assertRaises(ValueError):
            ParakeetEOUTranscriber(sample_rate=8000)

    def test_reset_suppresses_boundary_audio_and_restarts_helper(self):
        transcriber = ParakeetEOUTranscriber()
        calls = []
        transcriber.stop = Mock(side_effect=lambda: calls.append("stop"))
        transcriber.start = Mock(side_effect=lambda: calls.append("start"))

        transcriber.reset()

        self.assertEqual(calls, ["stop", "start"])
        self.assertFalse(transcriber._resetting.is_set())

    def test_feed_drops_boundary_audio_while_resetting(self):
        transcriber = ParakeetEOUTranscriber()
        transcriber._resetting.set()
        self.assertFalse(transcriber.feed([0.1, 0.2]))

    def test_feed_writes_16_bit_pcm_to_the_native_helper(self):
        transcriber = ParakeetEOUTranscriber()
        stdin = Mock()
        transcriber.process = Mock()
        transcriber.process.poll.return_value = None
        transcriber.process.stdin = stdin

        self.assertTrue(transcriber.feed(np.array([-1.0, 0.0, 1.0])))

        written = stdin.write.call_args.args[0]
        self.assertEqual(np.frombuffer(written, dtype="<i2").tolist(), [-32767, 0, 32767])


if __name__ == "__main__":
    unittest.main()
