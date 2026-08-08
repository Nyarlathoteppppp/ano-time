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
        self.process = subprocess.Popen(
            [self.binary_path, self.locale, str(self.sample_rate)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        if not self.ready.wait(timeout):
            self.stop()
            raise RuntimeError(self.error or "Apple Speech helper did not become ready")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _read_stdout(self):
        assert self.process and self.process.stdout
        for raw_line in iter(self.process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception as exc:
                print(f"[Apple Speech] Invalid helper output: {exc}")
                continue

            event_type = event.get("type")
            if event_type == "result":
                if self.on_result:
                    self.on_result(event.get("text", ""), bool(event.get("final")))
            elif event_type == "status":
                status = event.get("status", "unknown")
                print(f"[Apple Speech] Status: {status}")
                if self.on_status:
                    self.on_status(status)
                if status == "ready":
                    self.ready.set()
            elif event_type == "error":
                self.error = event.get("message", "Unknown Apple Speech error")
                print(f"[Apple Speech] Error: {self.error}")
                self.ready.set()

        if self.process and self.process.poll() not in (None, 0) and not self.error:
            self.error = f"Apple Speech helper exited with code {self.process.returncode}"
            self.ready.set()

    def _read_stderr(self):
        assert self.process and self.process.stderr
        for raw_line in iter(self.process.stderr.readline, b""):
            print(f"[Apple Speech helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def feed(self, audio_data):
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(self.error or "Apple Speech helper is not running")
        pcm = np.clip(audio_data, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2", copy=False)
        try:
            with self._write_lock:
                self.process.stdin.write(pcm.tobytes())
        except BrokenPipeError as exc:
            raise RuntimeError(self.error or "Apple Speech helper pipe closed") from exc

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
