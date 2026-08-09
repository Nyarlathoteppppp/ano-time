import json
import os
import queue
import re
import subprocess
import threading
import time
import unicodedata

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class NativeNotchOverlay(QObject):
    """Qt-compatible bridge to the native SwiftUI DynamicNotchKit helper."""

    stop_requested = pyqtSignal()
    pause_requested = pyqtSignal(bool)
    _event_received = pyqtSignal(str)

    def __init__(self, display_duration=None, window_width=800, window_height=120,
                 display_mode="notch"):
        super().__init__()
        self.window_width = window_width
        self.window_height = window_height
        self.process = None
        self.delegate = None
        self.transcript_data = {}
        self._last_native_items = None
        self._paused = False
        self._write_lock = threading.Lock()
        self._write_queue = queue.Queue(maxsize=1)
        self._writer_stop = threading.Event()
        self._writer_thread = None
        self._event_received.connect(self._handle_event)

        root = os.path.dirname(os.path.abspath(__file__))
        self.package_dir = os.path.join(root, "native_notch")
        self.binary_path = os.path.join(
            self.package_dir, ".build", "release", "RealtimeNotchHelper"
        )
        self.build_script = os.path.join(root, "build_native_notch.sh")

    def _ensure_built(self):
        source_files = [
            os.path.join(self.package_dir, "Package.swift"),
            os.path.join(self.package_dir, "Sources", "RealtimeNotchHelper", "main.swift"),
        ]
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            binary_mtime = os.path.getmtime(self.binary_path)
            needs_build = any(os.path.getmtime(path) > binary_mtime for path in source_files)
        if needs_build:
            subprocess.run([self.build_script], check=True, cwd=os.path.dirname(self.build_script))

    def show(self):
        self._ensure_built()
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [self.binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._start_writer()
        print("[Native Notch] DynamicNotchKit helper started")

    def _start_writer(self):
        if self._writer_thread and self._writer_thread.is_alive():
            return
        self._writer_stop.clear()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="notch-latest-writer",
            daemon=True,
        )
        self._writer_thread.start()

    def _writer_loop(self):
        while not self._writer_stop.is_set():
            try:
                line = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            process = self.process
            if not process or process.poll() is not None or not process.stdin:
                continue
            try:
                with self._write_lock:
                    process.stdin.write(line)
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def _read_stdout(self):
        process = self.process
        if not process or not process.stdout:
            return
        for raw_line in iter(process.stdout.readline, b""):
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception:
                continue
            if event.get("event"):
                self._event_received.emit(event["event"])

    def _read_stderr(self):
        process = self.process
        if not process or not process.stderr:
            return
        for raw_line in iter(process.stderr.readline, b""):
            print(f"[Native Notch] {raw_line.decode('utf-8', errors='replace').rstrip()}")

    def _handle_event(self, event):
        if event == "exit":
            QTimer.singleShot(0, self.stop_requested.emit)
        elif event == "pause":
            self._paused = True
            QTimer.singleShot(0, lambda: self.pause_requested.emit(True))
        elif event == "resume":
            self._paused = False
            QTimer.singleShot(0, lambda: self.pause_requested.emit(False))
        elif event == "glass":
            QTimer.singleShot(0, self._show_glass_overlay)

    def _show_glass_overlay(self):
        if self.delegate:
            return
        from overlay_window import OverlayWindow

        self.delegate = OverlayWindow(
            window_width=self.window_width,
            window_height=self.window_height,
            display_mode="glass",
            allow_notch_switch=True,
        )
        self.delegate.stop_requested.connect(
            lambda: QTimer.singleShot(0, self.stop_requested.emit)
        )
        self.delegate.notch_requested.connect(
            lambda: QTimer.singleShot(0, self._show_native_overlay)
        )
        for chunk_id in sorted(self.transcript_data):
            item = self.transcript_data[chunk_id]
            self.delegate.update_text(
                chunk_id,
                item["original"],
                item["translated"],
                "final" if item["finalized"] else "partial",
            )
        self.delegate.show()

    def _show_native_overlay(self):
        if self.delegate:
            self.delegate.close()
            self.delegate = None
        self.show()
        if self.transcript_data:
            self._send({"items": self._latest_items()})

    def update_text(self, chunk_id, original_text, translated_text, state="partial"):
        current = self.transcript_data.get(chunk_id)
        if current and current["finalized"] and state != "final":
            return
        existing = self.transcript_data.setdefault(
            chunk_id,
            {
                "timestamp": time.strftime("%H:%M:%S"),
                "original": "",
                "translated": "",
                "finalized": False,
            },
        )
        existing["finalized"] = existing["finalized"] or state == "final"
        if original_text:
            existing["original"] = original_text
        if translated_text:
            existing["translated"] = translated_text

        if self.delegate:
            self.delegate.update_text(
                chunk_id,
                original_text,
                translated_text,
                "final" if existing["finalized"] else "partial",
            )
            return

        latest_items = self._latest_items()
        # A late translation for a subtitle that has already scrolled out is
        # still retained in transcript_data, but must not perturb the notch.
        if latest_items != self._last_native_items:
            self._last_native_items = latest_items
            self._send({"items": latest_items})

    def _latest_items(self):
        rendered = []
        for chunk_id in sorted(self.transcript_data):
            item = self.transcript_data[chunk_id]
            translated_parts = self._split_display_text(item["translated"], 58)
            if not item["finalized"] or len(translated_parts) <= 1:
                rendered.append({
                    "id": chunk_id,
                    "original": item["original"],
                    "translated": item["translated"],
                    "finalized": item["finalized"],
                })
                continue

            original_parts = self._balanced_parts(
                item["original"], len(translated_parts)
            )
            for index, translated in enumerate(translated_parts):
                rendered.append({
                    "id": chunk_id * 1000 + index,
                    "original": original_parts[index],
                    "translated": translated,
                    "finalized": True,
                })
        return rendered[-3:]

    @staticmethod
    def _split_display_text(text, max_chars):
        text = " ".join((text or "").split())
        # The native Chinese label is 16 pt and can show two lines within a
        # 560 pt notch. Split only when the rendered text would exceed that
        # capacity; raw character count is inaccurate for mixed CJK/ASCII.
        if not text or NativeNotchOverlay._visual_width(text) <= 1104:
            return [text]
        clauses = [part for part in re.split(r"(?<=[。！？!?；;，,])", text) if part]
        parts = []
        current = ""
        for clause in clauses:
            if current and len(current) + len(clause) > max_chars:
                parts.append(current.strip())
                current = ""
            while len(clause) > max_chars:
                split_at = clause.rfind(" ", 0, max_chars + 1)
                split_at = split_at if split_at > 0 else max_chars
                if current:
                    parts.append(current.strip())
                    current = ""
                parts.append(clause[:split_at].strip())
                clause = clause[split_at:].strip()
            current += clause
        if current.strip():
            parts.append(current.strip())
        return parts or [text]

    @staticmethod
    def _visual_width(text):
        return sum(
            16 if unicodedata.east_asian_width(char) in ("W", "F", "A") else 8
            for char in text
        )

    @staticmethod
    def _balanced_parts(text, count):
        text = " ".join((text or "").split())
        if count <= 1:
            return [text]
        words = text.split()
        if len(words) >= count:
            return [
                " ".join(words[len(words) * i // count:len(words) * (i + 1) // count])
                for i in range(count)
            ]
        return [
            text[len(text) * i // count:len(text) * (i + 1) // count].strip()
            for i in range(count)
        ]

    def _send(self, payload):
        process = self.process
        if not process or process.poll() is not None or not process.stdin:
            return
        payload = dict(payload)
        payload.setdefault("paused", self._paused)
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        # The UI thread never writes to the subprocess. Keep only the newest
        # complete frame so a slow SwiftUI helper cannot create visual backlog.
        try:
            self._write_queue.put_nowait(line)
        except queue.Full:
            try:
                self._write_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._write_queue.put_nowait(line)
            except queue.Full:
                pass

    def set_paused(self, paused):
        self._paused = bool(paused)
        payload = {"paused": self._paused}
        if self.transcript_data:
            payload["items"] = self._latest_items()
        self._send(payload)

    def close(self):
        if self.delegate:
            self.delegate.close()
            self.delegate = None
        process = self.process
        if not process:
            return
        self._send({"command": "quit"})
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
        self._writer_stop.set()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=0.2)
        self.process = None
