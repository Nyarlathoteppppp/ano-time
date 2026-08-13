"""Optional FluidAudio Parakeet EOU streaming bridge for Apple Silicon Macs.

This is deliberately parallel to ``apple_transcriber.py``.  It exposes the
same narrow lifecycle contract to ``Pipeline`` but keeps FluidAudio/SwiftPM out
of the default Apple ASR process and dependency graph.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading

import numpy as np


class ParakeetEOUTranscriber:
    """Persistent CoreML Parakeet EOU helper emitting partial and EOU results."""

    def __init__(self, language="en", sample_rate=16_000, on_result=None, on_status=None):
        if language not in (None, "", "auto", "en"):
            raise ValueError("Parakeet EOU experimental backend currently supports English only")
        if int(sample_rate) != 16_000:
            raise ValueError("Parakeet EOU experimental backend requires 16000 Hz mono PCM")
        self.sample_rate = 16_000
        self.on_result = on_result
        self.on_status = on_status
        self.process = None
        self.ready = threading.Event()
        self.error = None
        self._write_lock = threading.Lock()
        self._reset_lock = threading.Lock()
        self._resetting = threading.Event()

        root = os.path.dirname(os.path.abspath(__file__))
        self.package_path = os.path.join(root, "native", "parakeet_eou")
        self.source_path = os.path.join(
            self.package_path, "Sources", "ParakeetEOUHelper", "main.swift"
        )
        self.binary_path = os.path.join(
            self.package_path, ".build", "release", "ParakeetEOUHelper"
        )

    def _ensure_built(self):
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            needs_build = os.path.getmtime(self.binary_path) < os.path.getmtime(self.source_path)
        if needs_build:
            print("[Parakeet EOU] Building optional native helper…")
            subprocess.run(
                ["swift", "build", "-c", "release"],
                check=True,
                cwd=self.package_path,
            )

    def start(self, timeout=180):
        self._ensure_built()
        self.process = subprocess.Popen(
            [self.binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        if not self.ready.wait(timeout):
            self.stop()
            raise RuntimeError(self.error or "Parakeet EOU helper did not become ready")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _read_stdout(self):
        assert self.process and self.process.stdout
        for raw_line in iter(self.process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"[Parakeet EOU] Invalid helper output: {exc}")
                continue
            event_type = event.get("type")
            if event_type == "result" and self.on_result and not self._resetting.is_set():
                self.on_result(event.get("text", ""), bool(event.get("final")))
            elif event_type == "status":
                status = event.get("status", "unknown")
                print(f"[Parakeet EOU] Status: {status}")
                if self.on_status:
                    self.on_status(status)
                if status == "ready":
                    self.ready.set()
            elif event_type == "error":
                self.error = event.get("message", "Unknown Parakeet EOU error")
                print(f"[Parakeet EOU] Error: {self.error}")
                self.ready.set()
        if self.process and self.process.poll() not in (None, 0) and not self.error:
            self.error = f"Parakeet EOU helper exited with code {self.process.returncode}"
            self.ready.set()

    def _read_stderr(self):
        assert self.process and self.process.stderr
        for raw_line in iter(self.process.stderr.readline, b""):
            print(f"[Parakeet EOU helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def feed(self, audio_data):
        if self._resetting.is_set():
            return False
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(self.error or "Parakeet EOU helper is not running")
        pcm = np.clip(audio_data, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2", copy=False)
        try:
            with self._write_lock:
                self.process.stdin.write(pcm.tobytes())
            return True
        except BrokenPipeError as exc:
            if self._resetting.is_set():
                return False
            raise RuntimeError(self.error or "Parakeet EOU helper pipe closed") from exc

    def reset(self):
        """Use a fresh EOU decoding session after an explicit user pause."""
        if not self._reset_lock.acquire(blocking=False):
            return
        self._resetting.set()
        try:
            self.stop()
            self.ready.clear()
            self.error = None
            self.start()
        finally:
            self._resetting.clear()
            self._reset_lock.release()

    def stop(self):
        process = self.process
        if not process:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        finally:
            self.process = None
