import os
import subprocess
import threading

import numpy as np


class SystemAudioCapture:
    """Raw macOS system-audio input backed by ScreenCaptureKit."""

    def __init__(self, device_index=None, sample_rate=16000, chunk_duration=0.1,
                 silence_threshold=0.01, silence_duration=1.0,
                 max_phrase_duration=5.0, streaming_mode=False,
                 streaming_interval=1.5, streaming_step_size=0.2,
                 streaming_overlap=0.3):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.block_size = int(sample_rate * chunk_duration)
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.max_phrase_duration = max_phrase_duration
        self.streaming_mode = streaming_mode
        self.streaming_interval = streaming_interval
        self.streaming_step_size = streaming_step_size
        self.streaming_overlap = streaming_overlap
        self.running = False
        self.process = None
        self._stderr_thread = None

        root = os.path.dirname(os.path.abspath(__file__))
        self.source_path = os.path.join(root, "apple_system_audio_helper.swift")
        self.binary_path = os.path.join(root, ".build", "apple_system_audio_helper")
        self.build_script = os.path.join(root, "build_apple_speech.sh")

    def _ensure_built(self):
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            needs_build = os.path.getmtime(self.source_path) > os.path.getmtime(self.binary_path)
        if needs_build:
            subprocess.run([self.build_script], check=True, cwd=os.path.dirname(self.build_script))

    def _read_stderr(self, process):
        if not process.stderr:
            return
        for raw_line in iter(process.stderr.readline, b""):
            message = raw_line.decode("utf-8", errors="replace").rstrip()
            if message:
                print(f"[System Audio] {message}")

    def generator(self):
        self._ensure_built()
        block_samples = max(1, int(self.sample_rate * self.streaming_step_size))
        block_bytes = block_samples * np.dtype(np.float32).itemsize
        print(
            f"[System Audio] Starting ScreenCaptureKit stream "
            f"({self.sample_rate} Hz, step={self.streaming_step_size}s)"
        )
        self.process = subprocess.Popen(
            [self.binary_path, str(self.sample_rate)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        process = self.process
        self.running = True
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, args=(process,), daemon=True
        )
        self._stderr_thread.start()

        pending = bytearray()
        try:
            while self.running and process.poll() is None and process.stdout:
                chunk = process.stdout.read(block_bytes - len(pending))
                if not chunk:
                    break
                pending.extend(chunk)
                if len(pending) == block_bytes:
                    yield np.frombuffer(bytes(pending), dtype=np.float32)
                    pending.clear()
        finally:
            self.running = False
            if process.poll() is None:
                process.terminate()
            print("[System Audio] Generator stopped")

        if process.returncode not in (None, 0, -15):
            raise RuntimeError(
                "System audio capture stopped. Grant Screen & System Audio Recording "
                "permission in System Settings, then restart the app."
            )

    def stop(self):
        self.running = False
        process = self.process
        if not process:
            return
        if process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(b"quit\n")
                    process.stdin.flush()
                    process.stdin.close()
                process.wait(timeout=2)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.terminate()
        self.process = None
        print("[System Audio] Capture stopped")
