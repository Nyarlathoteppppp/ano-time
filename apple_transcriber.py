import json
import os
import subprocess
import threading

import numpy as np


class AppleSpeechTranscriber:
    """Persistent bridge to macOS 26 SpeechAnalyzer/SpeechTranscriber."""

    LANGUAGE_LOCALES = {
        "en": "en-US",
        "zh": "zh-CN",
        "ja": "ja-JP",
        "ko": "ko-KR",
        "es": "es-ES",
        "fr": "fr-FR",
        "de": "de-DE",
        "ru": "ru-RU",
        "pt": "pt-BR",
        "it": "it-IT",
    }

    def __init__(self, language="en", sample_rate=16000, on_result=None, on_status=None):
        self.language = language or "en"
        self.locale = self.LANGUAGE_LOCALES.get(self.language, self.language)
        self.sample_rate = sample_rate
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
        self.source_path = os.path.join(root, "apple_speech_helper.swift")
        self.binary_path = os.path.join(root, ".build", "apple_speech_helper")
        self.build_script = os.path.join(root, "build_apple_speech.sh")

    def _ensure_built(self):
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            needs_build = os.path.getmtime(self.binary_path) < os.path.getmtime(self.source_path)
        if needs_build:
            print("[Apple Speech] Building native helper...")
            subprocess.run([self.build_script], check=True, cwd=os.path.dirname(self.source_path))

    def start(self, timeout=60):
        self._ensure_built()
        process = subprocess.Popen(
            [self.binary_path, self.locale, str(self.sample_rate)],
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
            raise RuntimeError(self.error or "Apple Speech helper did not become ready")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _read_stdout(self, process, generation):
        """Read one helper process without letting an old session leak events."""
        assert process.stdout
        for raw_line in iter(process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception as exc:
                print(f"[Apple Speech] Invalid helper output: {exc}")
                continue

            event_type = event.get("type")
            if event_type == "result":
                if self.on_result and self._accepts_event_from(process, generation):
                    self.on_result(event.get("text", ""), bool(event.get("final")))
            elif event_type == "status":
                status = event.get("status", "unknown")
                print(f"[Apple Speech] Status: {status}")
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
                    self.error = event.get("message", "Unknown Apple Speech error")
                    print(f"[Apple Speech] Error: {self.error}")
                    self.ready.set()

        if (
            self._accepts_event_from(process, generation, allow_reset=True)
            and process.poll() not in (None, 0)
            and not self.error
        ):
            self.error = f"Apple Speech helper exited with code {self.process.returncode}"
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
            print(f"[Apple Speech helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def feed(self, audio_data):
        if self._resetting.is_set():
            # A very fast resume can race the background reset. Dropping this
            # tiny boundary slice is safer than joining two utterances.
            return False
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(self.error or "Apple Speech helper is not running")
        pcm = np.clip(audio_data, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2", copy=False)
        try:
            with self._write_lock:
                self.process.stdin.write(pcm.tobytes())
            return True
        except BrokenPipeError as exc:
            if self._resetting.is_set():
                return False
            raise RuntimeError(self.error or "Apple Speech helper pipe closed") from exc

    def reset(self):
        """Start a fresh native recognition session at a pause boundary."""
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
