import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from system_audio_capture import SystemAudioCapture


class FakeProcess:
    def __init__(self, returncode=None, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.stdin = io.BytesIO()
        self.terminated = False
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class SystemAudioCaptureTests(unittest.TestCase):
    def test_missing_or_stale_helper_runs_build_script(self):
        capture = SystemAudioCapture()
        with tempfile.TemporaryDirectory() as directory:
            capture.binary_path = os.path.join(directory, "missing-helper")
            capture.source_path = os.path.join(directory, "source.swift")
            capture.build_script = os.path.join(directory, "build.sh")
            with patch("system_audio_capture.subprocess.run") as run:
                capture._ensure_built()
            run.assert_called_once_with(
                [capture.build_script],
                check=True,
                cwd=os.path.dirname(capture.build_script),
            )

    def test_stderr_parser_preserves_recent_permission_error(self):
        capture = SystemAudioCapture()
        process = FakeProcess(stderr="permission denied\nScreenCaptureKit failed\n".encode())
        capture._read_stderr(process)
        self.assertIn("permission denied", capture._failure_detail())
        self.assertIn("ScreenCaptureKit failed", capture._failure_detail())

    def test_nonzero_helper_exit_includes_exit_code_and_stderr(self):
        capture = SystemAudioCapture(streaming_step_size=0.01)
        process = FakeProcess(returncode=2, stderr=b"user denied screen recording\n")
        capture._ensure_built = lambda: None
        capture._stderr_messages = ["user denied screen recording"]
        with patch("system_audio_capture.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(
                RuntimeError,
                "code 2: user denied screen recording",
            ):
                list(capture.generator())

    def test_stop_requests_clean_helper_shutdown(self):
        capture = SystemAudioCapture()
        process = FakeProcess(returncode=None)
        capture.process = process

        capture.stop()

        self.assertTrue(process.waited)
        self.assertIsNone(capture.process)


if __name__ == "__main__":
    unittest.main()
