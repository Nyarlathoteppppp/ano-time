import json
import os
import subprocess
import threading


class AppleTranslator:
    """Thread-safe persistent bridge to Apple's on-device Translation framework."""

    LANGUAGE_CODES = {
        "Chinese": "zh-Hans",
        "English": "en",
        "Japanese": "ja",
        "French": "fr",
        "Spanish": "es",
        "German": "de",
        "Korean": "ko",
    }

    def __init__(self, source="en", target="Chinese", timeout=20):
        self.source = source or "en"
        self.target = self.LANGUAGE_CODES.get(target, target)
        self.timeout = timeout
        self.process = None
        self.ready = threading.Event()
        self.error = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._pending = {}

        root = os.path.dirname(os.path.abspath(__file__))
        self.source_path = os.path.join(root, "apple_translation_helper.swift")
        self.binary_path = os.path.join(root, ".build", "apple_translation_helper")
        self.build_script = os.path.join(root, "build_apple_speech.sh")
        self._ensure_built()
        self._start()

    def _ensure_built(self):
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            needs_build = os.path.getmtime(self.binary_path) < os.path.getmtime(self.source_path)
        if needs_build:
            subprocess.run([self.build_script], check=True, cwd=os.path.dirname(self.source_path))

    def _start(self):
        self.process = subprocess.Popen(
            [self.binary_path, self.source, self.target],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        if not self.ready.wait(self.timeout):
            self.stop()
            raise RuntimeError("Apple Translation helper did not become ready")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _read_stdout(self):
        assert self.process and self.process.stdout
        for raw_line in iter(self.process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception as exc:
                print(f"[Apple Translation] Invalid output: {exc}")
                continue
            if event.get("type") == "status" and event.get("status") == "ready":
                print("[Apple Translation] Ready")
                self.ready.set()
            elif event.get("type") == "result":
                with self._lock:
                    pending = self._pending.get(event.get("id"))
                if pending:
                    pending["result"] = event.get("text", "")
                    pending["event"].set()
            elif event.get("type") == "error":
                message = event.get("message", "Unknown Apple Translation error")
                print(f"[Apple Translation] Error: {message}")
                self.error = message
                self.ready.set()
                with self._lock:
                    pending_items = list(self._pending.values())
                for pending in pending_items:
                    pending["error"] = message
                    pending["event"].set()

    def _read_stderr(self):
        assert self.process and self.process.stderr
        for raw_line in iter(self.process.stderr.readline, b""):
            print(f"[Apple Translation helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def translate(self, text, timeout=3):
        if not text or not text.strip():
            return ""
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(self.error or "Apple Translation helper is not running")

        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            pending = {"event": threading.Event(), "result": None, "error": None}
            self._pending[request_id] = pending

        payload = json.dumps({"id": request_id, "text": text}, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                self.process.stdin.write(payload.encode("utf-8"))
            if not pending["event"].wait(timeout):
                raise TimeoutError("Apple Translation timed out")
            if pending["error"]:
                raise RuntimeError(pending["error"])
            return pending["result"] or ""
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def stop(self):
        process = self.process
        if not process:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        finally:
            self.process = None
