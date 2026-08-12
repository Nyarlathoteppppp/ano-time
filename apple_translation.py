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

    def __init__(self, source="en", target="Chinese", timeout=20, status_callback=None):
        self.source = self.normalize_source_language(source)
        self.target = self.LANGUAGE_CODES.get(target, target)
        self.timeout = timeout
        self.status_callback = status_callback
        self.process = None
        self.started = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.status = "initializing"
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

    @staticmethod
    def normalize_source_language(source):
        normalized = str(source or "").strip()
        if not normalized or normalized.lower() == "auto":
            return "en"
        return normalized

    @property
    def is_ready(self):
        return self.ready.is_set() and not self.error

    def _notify_status(self, status, message):
        self.status = status
        callback = self.status_callback
        if callback:
            try:
                callback(status, message)
            except Exception as exc:
                print(f"[Apple Translation] Status callback failed: {exc}")

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
        # The helper can be alive while macOS downloads its language assets.
        # Wait only for process startup; preparation continues in the helper
        # without blocking the Pipeline or remote translation path.
        if not self.started.wait(self.timeout):
            self.stop()
            raise RuntimeError("Apple Translation helper did not start")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _handle_event(self, event):
        if event.get("type") == "status":
            status = event.get("status")
            if status == "preparing_languages":
                print("[Apple Translation] Preparing language resources")
                self._notify_status(
                    "preparing",
                    "Apple · downloading language resources",
                )
                self.started.set()
            elif status == "ready":
                print("[Apple Translation] Ready")
                self.ready.set()
                self.started.set()
                self._notify_status("ready", "Apple · ready")
            return
        if event.get("type") == "result":
            with self._lock:
                pending = self._pending.get(event.get("id"))
            if pending:
                pending["result"] = event.get("text", "")
                pending["event"].set()
            return
        if event.get("type") == "request_error":
            # Translation.framework can reject one particular request while
            # the session and downloaded language pair remain usable.  Keep
            # the helper ready and fail only the matching subtitle request.
            message = event.get("message", "Apple Translation request failed")
            request_id = event.get("id")
            print(
                "[Apple Translation] Request error"
                f" (id={request_id}): {message}"
            )
            with self._lock:
                pending = self._pending.get(request_id)
            if pending:
                pending["error"] = message
                pending["event"].set()
            return
        if event.get("type") == "error":
            message = event.get("message", "Unknown Apple Translation error")
            print(f"[Apple Translation] Error: {message}")
            self.error = message
            self.started.set()
            self._notify_status("error", f"Apple · {message}")
            with self._lock:
                pending_items = list(self._pending.values())
            for pending in pending_items:
                pending["error"] = message
                pending["event"].set()

    def _read_stdout(self):
        assert self.process and self.process.stdout
        for raw_line in iter(self.process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception as exc:
                print(f"[Apple Translation] Invalid output: {exc}")
                continue
            self._handle_event(event)

    def _read_stderr(self):
        assert self.process and self.process.stderr
        for raw_line in iter(self.process.stderr.readline, b""):
            print(f"[Apple Translation helper] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def translate(self, text, timeout=3):
        if not text or not text.strip():
            return ""
        if self.error:
            raise RuntimeError(self.error)
        if not self.is_ready:
            raise RuntimeError("Apple Translation is preparing language resources")
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
