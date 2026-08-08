import json
import os
import subprocess
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal


class NativeNotchOverlay(QObject):
    """Qt-compatible bridge to the native SwiftUI DynamicNotchKit helper."""

    stop_requested = pyqtSignal()
    _event_received = pyqtSignal(str)

    def __init__(self, display_duration=None, window_width=800, window_height=120,
                 display_mode="notch"):
        super().__init__()
        self.window_width = window_width
        self.window_height = window_height
        self.process = None
        self.delegate = None
        self.transcript_data = {}
        self._write_lock = threading.Lock()
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
        print("[Native Notch] DynamicNotchKit helper started")

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
            self.stop_requested.emit()
        elif event == "glass":
            self._show_glass_overlay()

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
        self.delegate.stop_requested.connect(self.stop_requested.emit)
        self.delegate.notch_requested.connect(self._show_native_overlay)
        for chunk_id in sorted(self.transcript_data):
            item = self.transcript_data[chunk_id]
            self.delegate.update_text(chunk_id, item["original"], item["translated"])
        self.delegate.show()

    def _show_native_overlay(self):
        if self.delegate:
            self.delegate.close()
            self.delegate = None
        self.show()
        if self.transcript_data:
            latest_id = max(self.transcript_data)
            item = self.transcript_data[latest_id]
            self._send({"original": item["original"], "translated": item["translated"]})

    def update_text(self, chunk_id, original_text, translated_text):
        existing = self.transcript_data.setdefault(
            chunk_id,
            {"timestamp": time.strftime("%H:%M:%S"), "original": "", "translated": ""},
        )
        if original_text:
            existing["original"] = original_text
        if translated_text:
            existing["translated"] = translated_text

        if self.delegate:
            self.delegate.update_text(chunk_id, original_text, translated_text)
            return

        self._send({
            "original": existing["original"],
            "translated": existing["translated"],
        })

    def _send(self, payload):
        process = self.process
        if not process or process.poll() is not None or not process.stdin:
            return
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            with self._write_lock:
                process.stdin.write(line.encode("utf-8"))
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

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
        self.process = None
