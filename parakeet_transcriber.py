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


class ParakeetAdaptiveGain:
    """Raise only weak, non-silent PCM before it reaches Parakeet.

    This is deliberately an input preconditioner, not an audio/VAD change. It
    leaves silence and ordinary speech untouched, so enabling it cannot make
    the shared capture path diverge from Apple ASR.  The values are
    conservative and exposed for unit tests and runtime diagnostics.
    """

    silence_rms = 0.0015
    activation_rms = 0.0200
    target_rms = 0.0350
    maximum_gain = 4.0

    def __init__(self):
        self.last_input_rms = 0.0
        self.last_gain = 1.0

    def process(self, audio_data):
        samples = np.asarray(audio_data, dtype=np.float32)
        if samples.size == 0:
            self.last_input_rms = 0.0
            self.last_gain = 1.0
            return samples
        finite_samples = np.nan_to_num(
            samples, nan=0.0, posinf=1.0, neginf=-1.0
        )
        rms = float(np.sqrt(np.mean(np.square(finite_samples, dtype=np.float64))))
        self.last_input_rms = rms
        if rms <= self.silence_rms or rms >= self.activation_rms:
            self.last_gain = 1.0
            return finite_samples
        self.last_gain = min(self.maximum_gain, self.target_rms / rms)
        return np.clip(finite_samples * self.last_gain, -1.0, 1.0)


class ParakeetEOUTranscriber:
    """Persistent CoreML Parakeet EOU helper emitting partial and EOU results."""

    def __init__(
        self,
        language="en",
        sample_rate=16_000,
        eou_debounce_ms=640,
        adaptive_gain_enabled=False,
        on_result=None,
        on_status=None,
    ):
        if language not in (None, "", "auto", "en"):
            raise ValueError("Parakeet EOU experimental backend currently supports English only")
        if int(sample_rate) != 16_000:
            raise ValueError("Parakeet EOU experimental backend requires 16000 Hz mono PCM")
        eou_debounce_ms = int(eou_debounce_ms)
        if eou_debounce_ms not in (320, 480, 640, 800):
            raise ValueError("Parakeet EOU debounce must be 320, 480, 640, or 800 ms")
        self.sample_rate = 16_000
        self.eou_debounce_ms = eou_debounce_ms
        self.adaptive_gain_enabled = bool(adaptive_gain_enabled)
        self._adaptive_gain = (
            ParakeetAdaptiveGain() if self.adaptive_gain_enabled else None
        )
        self.last_input_rms = 0.0
        self.last_input_gain = 1.0
        self.on_result = on_result
        self.on_status = on_status
        self.process = None
        self.ready = threading.Event()
        self.error = None
        self._write_lock = threading.Lock()
        self._reset_lock = threading.Lock()
        self._resetting = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self._process_generation = 0

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
        process = subprocess.Popen(
            [
                self.binary_path,
                "--eou-debounce-ms",
                str(self.eou_debounce_ms),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        with self._lifecycle_lock:
            self._process_generation += 1
            generation = self._process_generation
            self.process = process
        threading.Thread(
            target=self._read_stdout, args=(process, generation), daemon=True
        ).start()
        threading.Thread(
            target=self._read_stderr, args=(process,), daemon=True
        ).start()
        if not self.ready.wait(timeout):
            self.stop()
            raise RuntimeError(self.error or "Parakeet EOU helper did not become ready")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _read_stdout(self, process, generation):
        """Read one helper process without letting an old session leak events."""
        assert process.stdout
        for raw_line in iter(process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                print(f"[Parakeet EOU] Invalid helper output: {exc}")
                continue
            event_type = event.get("type")
            if event_type == "result" and self.on_result and self._accepts_event_from(process, generation):
                self.on_result(event.get("text", ""), bool(event.get("final")))
            elif event_type == "status":
                status = event.get("status", "unknown")
                print(f"[Parakeet EOU] Status: {status}")
                if self.on_status and self._accepts_event_from(
                    process, generation, allow_reset=True
                ):
                    self.on_status(status)
                if status == "ready" and self._accepts_event_from(
                    process, generation, allow_reset=True
                ):
                    self.ready.set()
            elif event_type == "error":
                if self._accepts_event_from(process, generation, allow_reset=True):
                    self.error = event.get("message", "Unknown Parakeet EOU error")
                    print(f"[Parakeet EOU] Error: {self.error}")
                    self.ready.set()
        if (
            self._accepts_event_from(process, generation, allow_reset=True)
            and process.poll() not in (None, 0)
            and not self.error
        ):
            self.error = f"Parakeet EOU helper exited with code {self.process.returncode}"
            self.ready.set()

    def _accepts_event_from(self, process, generation, *, allow_reset=False):
        with self._lifecycle_lock:
            return (
                (allow_reset or not self._resetting.is_set())
                and self.process is process
                and self._process_generation == generation
            )

    def _read_stderr(self, process):
        assert process.stderr
        for raw_line in iter(process.stderr.readline, b""):
            print(f"[Parakeet EOU helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def feed(self, audio_data):
        if self._resetting.is_set():
            return False
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(self.error or "Parakeet EOU helper is not running")
        if self._adaptive_gain:
            pcm = self._adaptive_gain.process(audio_data)
            self.last_input_rms = self._adaptive_gain.last_input_rms
            self.last_input_gain = self._adaptive_gain.last_gain
        else:
            pcm = np.asarray(audio_data, dtype=np.float32)
            self.last_input_rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
            self.last_input_gain = 1.0
        pcm = np.clip(pcm, -1.0, 1.0)
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
            with self._lifecycle_lock:
                if self.process is process:
                    self.process = None
