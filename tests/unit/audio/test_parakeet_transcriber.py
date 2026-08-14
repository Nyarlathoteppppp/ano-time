import threading
import unittest
from unittest.mock import Mock

import numpy as np

from parakeet_transcriber import ParakeetAdaptiveGain, ParakeetEOUTranscriber


class ParakeetEOUTranscriberTests(unittest.TestCase):
    def test_only_accepts_english_and_16khz(self):
        with self.assertRaises(ValueError):
            ParakeetEOUTranscriber(language="zh")
        with self.assertRaises(ValueError):
            ParakeetEOUTranscriber(sample_rate=8000)
        with self.assertRaises(ValueError):
            ParakeetEOUTranscriber(eou_debounce_ms=500)

    def test_retains_the_selected_eou_debounce_for_helper_startup(self):
        transcriber = ParakeetEOUTranscriber(eou_debounce_ms=320)

        self.assertEqual(transcriber.eou_debounce_ms, 320)

    def test_adaptive_gain_is_opt_in(self):
        self.assertFalse(ParakeetEOUTranscriber().adaptive_gain_enabled)
        self.assertTrue(
            ParakeetEOUTranscriber(adaptive_gain_enabled=True).adaptive_gain_enabled
        )

    def test_adaptive_gain_raises_quiet_speech_without_raising_silence(self):
        normalizer = ParakeetAdaptiveGain()

        silent = normalizer.process(np.zeros(160, dtype=np.float32))
        self.assertTrue(np.array_equal(silent, np.zeros(160, dtype=np.float32)))
        self.assertEqual(normalizer.last_gain, 1.0)

        quiet = normalizer.process(np.full(160, 0.008, dtype=np.float32))
        self.assertAlmostEqual(normalizer.last_input_rms, 0.008, places=5)
        self.assertGreater(normalizer.last_gain, 4.0 - 0.01)
        self.assertAlmostEqual(float(np.sqrt(np.mean(quiet ** 2))), 0.032, places=3)

    def test_adaptive_gain_leaves_normal_volume_unchanged(self):
        normalizer = ParakeetAdaptiveGain()
        source = np.full(160, 0.025, dtype=np.float32)

        processed = normalizer.process(source)

        self.assertEqual(normalizer.last_gain, 1.0)
        self.assertTrue(np.array_equal(processed, source))

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

    def test_feed_applies_enabled_adaptive_gain_before_pcm_serialization(self):
        transcriber = ParakeetEOUTranscriber(adaptive_gain_enabled=True)
        stdin = Mock()
        transcriber.process = Mock()
        transcriber.process.poll.return_value = None
        transcriber.process.stdin = stdin

        self.assertTrue(transcriber.feed(np.full(160, 0.008, dtype=np.float32)))

        written = np.frombuffer(stdin.write.call_args.args[0], dtype="<i2")
        self.assertGreater(int(np.abs(written).max()), int(0.008 * 32767 * 3.9))
        self.assertGreater(transcriber.last_input_gain, 3.9)


if __name__ == "__main__":
    unittest.main()
