import unittest
from unittest.mock import patch

from audio_capture import AudioCapture


class AudioCaptureTests(unittest.TestCase):
    def test_device_initialization_failure_is_reported_to_pipeline(self):
        capture = AudioCapture(device_index=None, streaming_step_size=0.01)
        with patch("audio_capture.sd.InputStream", side_effect=OSError("permission denied")):
            with self.assertRaisesRegex(
                RuntimeError,
                "Audio device initialization failed: permission denied",
            ):
                list(capture.generator())

        self.assertFalse(capture.running)


if __name__ == "__main__":
    unittest.main()
