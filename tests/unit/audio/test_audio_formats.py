import unittest

from audio_formats import normalize_sample_rate


class AudioFormatTests(unittest.TestCase):
    def test_apple_uses_nearest_supported_sample_rate(self):
        self.assertEqual(normalize_sample_rate(15904, "apple"), 16000)
        self.assertEqual(normalize_sample_rate(9000, "apple"), 8000)

    def test_other_asr_backends_keep_requested_sample_rate(self):
        for backend in ("mlx", "whisper", "funasr"):
            self.assertEqual(normalize_sample_rate(48000, backend), 48000)
