import json
import os
import queue
import re
import subprocess
import threading
import unicodedata

from ui.qt import QObject, QTimer, Signal
from display_fragment_plan import DisplayFragmentPlan
from subtitle_record_store import SubtitleRecordStore


class NativeNotchOverlay(QObject):
    """Qt-compatible bridge to the native SwiftUI DynamicNotchKit helper."""

    stop_requested = Signal()
    pause_requested = Signal(bool)
    _event_received = Signal(str)
    _native_build_completed = Signal()
    _native_build_failed = Signal(str)

    def __init__(self, display_duration=None, window_width=800, window_height=120,
                 display_mode="notch"):
        super().__init__()
        self.window_width = window_width
        self.window_height = window_height
        self.process = None
        self.delegate = None
        self.record_store = SubtitleRecordStore()
        # Only the notch owns this projection cache. Glass and transcript
        # records must always retain their complete semantic sentences.
        self._display_fragment_plan = DisplayFragmentPlan()
        self._last_native_items = None
        self._paused = False
        self._busy_stages = set()
        self._hidden_short_segments = set()
        self._short_segment_versions = {}
        self._short_source_signatures = {}
        self._write_lock = threading.Lock()
        self._write_queue = queue.Queue(maxsize=1)
        self._writer_stop = threading.Event()
        self._writer_thread = None
        self._native_build_lock = threading.Lock()
        self._native_build_in_progress = False
        self._visible_requested = False
        self._display_mode = "notch"
        self._event_received.connect(self._handle_event)
        self._native_build_completed.connect(self._on_native_build_completed)
        self._native_build_failed.connect(self._on_native_build_failed)

        root = os.path.dirname(os.path.abspath(__file__))
        self.package_dir = os.path.join(root, "native_notch")
        self.binary_path = os.path.join(
            self.package_dir, ".build", "release", "RealtimeNotchHelper"
        )
        self.build_script = os.path.join(root, "build_native_notch.sh")

    @property
    def transcript_data(self):
        """Read-only compatibility snapshot of complete semantic records."""
        return self.record_store.snapshot()

    def _needs_native_build(self):
        source_root = os.path.join(self.package_dir, "Sources")
        source_files = [os.path.join(self.package_dir, "Package.swift")]
        for directory, _subdirs, filenames in os.walk(source_root):
            source_files.extend(
                os.path.join(directory, filename)
                for filename in filenames
                if filename.endswith(".swift")
            )
        needs_build = not os.path.exists(self.binary_path)
        if not needs_build:
            binary_mtime = os.path.getmtime(self.binary_path)
            needs_build = any(os.path.getmtime(path) > binary_mtime for path in source_files)
        return needs_build

    def _ensure_built(self):
        """Synchronously build the helper for installer/worker use only."""
        if self._needs_native_build():
            subprocess.run([self.build_script], check=True, cwd=os.path.dirname(self.build_script))

    def show(self):
        self._visible_requested = True
        if self.process and self.process.poll() is None:
            return
        if self._needs_native_build():
            self._start_native_build_async()
            return
        self._start_native_helper()

    def _start_native_build_async(self):
        """Build DynamicNotchKit away from the Qt GUI thread."""
        with self._native_build_lock:
            if self._native_build_in_progress:
                return
            self._native_build_in_progress = True

        print("[Native Notch] Preparing native helper in background...")

        def build():
            try:
                self._ensure_built()
            except Exception as exc:
                self._native_build_failed.emit(str(exc))
            else:
                self._native_build_completed.emit()

        threading.Thread(
            target=build,
            name="notch-native-builder",
            daemon=True,
        ).start()

    def _on_native_build_completed(self):
        with self._native_build_lock:
            self._native_build_in_progress = False
        if self._visible_requested and self._display_mode == "notch":
            self._start_native_helper()

    def _on_native_build_failed(self, detail):
        with self._native_build_lock:
            self._native_build_in_progress = False
        print(f"[Native Notch] Helper build failed: {detail}")

    def _start_native_helper(self):
        """Start an already-built helper without compile work."""
        if self.process and self.process.poll() is None:
            return
        if not os.path.exists(self.binary_path):
            self._start_native_build_async()
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
        self._last_native_items = self._latest_items()
        self._send({"items": self._last_native_items})

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
        # The Swift helper emits `glass` before its closing animation exits.
        # Detach it immediately so a quick switch back cannot mistake that
        # terminating process for a live notch renderer.
        self._display_mode = "glass"
        self._visible_requested = False
        self._retire_native_process()
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
        # Glass is a bounded live projection.  Replaying a full lecture here
        # builds then immediately deletes thousands of Qt widgets and causes a
        # visible pause when switching display modes.
        for chunk_id, item in self.record_store.latest_items(40):
            self.delegate.update_text(
                chunk_id,
                item["original"],
                item["translated"],
                "final" if item["finalized"] else "partial",
                item.get("committed_prefix_length", 0),
            )
        self.delegate.show()

    def _show_native_overlay(self):
        self._display_mode = "notch"
        if self.delegate:
            self.delegate.close()
            self.delegate = None
        self._discard_pending_frames()
        self.show()
        # A newly started helper has no knowledge of the previous frame even
        # when the semantic subtitle projection itself is unchanged.
        self._last_native_items = None
        if self.record_store:
            self._send({"items": self._latest_items()})

    def _discard_pending_frames(self):
        while True:
            try:
                self._write_queue.get_nowait()
            except queue.Empty:
                return

    def _retire_native_process(self):
        """Detach and asynchronously reap a helper that is already exiting."""
        process = self.process
        if process is None:
            return
        self.process = None
        self._discard_pending_frames()

        def reap():
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)

        threading.Thread(
            target=reap,
            name="notch-retired-process-reaper",
            daemon=True,
        ).start()

    def update_text(self, chunk_id, original_text, translated_text, state="partial"):
        record = self.record_store.update(
            chunk_id, original_text, translated_text, state
        )
        if record is None:
            return
        self._track_short_segment(chunk_id, record)

        if self.delegate:
            self._forward_current_glass_record(chunk_id, record)
            return

        latest_items = self._latest_items()
        # A late translation for a subtitle that has already scrolled out is
        # still retained in record_store, but must not perturb the notch.
        if latest_items != self._last_native_items:
            self._last_native_items = latest_items
            self._send({"items": latest_items})

    def update_event(self, event):
        record = self.record_store.update(
            event.segment_id,
            event.original_text,
            event.translated_text,
            event.legacy_state,
            event.committed_prefix_length,
        )
        if record is None:
            return
        self._track_short_segment(event.segment_id, record)
        if self.delegate:
            self._forward_current_glass_record(event.segment_id, record)
            return
        latest_items = self._latest_items()
        if latest_items != self._last_native_items:
            self._last_native_items = latest_items
            self._send({"items": latest_items})

    def update_runtime_status(self, stage, status, detail):
        """Forward coarse activity state without sending diagnostic details."""
        if self.delegate:
            return
        stage = str(stage)
        if stage not in {"ASR", "Draft", "Remote"}:
            return
        activity_stage = stage
        if stage == "Remote":
            provider = str(detail or "").split(" · ", 1)[0].strip()
            if provider:
                activity_stage = f"Remote:{provider}"
        if str(status) == "active":
            self._busy_stages.add(activity_stage)
        else:
            self._busy_stages.discard(activity_stage)
        # Runtime activity is independent from subtitles. Sending the current
        # items again makes SwiftUI re-run presentation reconciliation and can
        # repeatedly cancel the notch's deliberate shrink cooldown.
        self._send({})

    def _latest_items(self):
        # Display fragments are an ephemeral projection. They never enter the
        # complete semantic record store or classroom export data.
        visible_records = self.record_store.latest_items_excluding(
            3,
            self._hidden_short_segments,
        )
        self._display_fragment_plan.retain(
            chunk_id for chunk_id, _item in visible_records
        )
        cues = []
        for chunk_id, item in visible_records:
            translated_parts = self._display_fragment_plan.project(
                chunk_id,
                item["translated"],
                lambda value: self._split_display_text(value, 58),
            )
            original_parts = (
                self._split_finalized_source(item["original"], 34)
                if item["finalized"] else [item["original"]]
            )
            part_count = max(len(original_parts), len(translated_parts))
            if len(original_parts) != part_count:
                original_parts = self._semantic_parts_for_count(
                    item["original"], part_count
                )
            if len(translated_parts) != part_count:
                translated_parts = self._semantic_parts_for_count(
                    item["translated"], part_count
                )
            remaining_committed = item.get("committed_prefix_length", 0)
            fragments = []
            for index, (original, translated) in enumerate(zip(
                original_parts, translated_parts
            )):
                part_committed = min(len(translated), remaining_committed)
                fragments.append({
                    "id": chunk_id * 1000 + index,
                    "original": original,
                    "translated": translated,
                    "finalized": item["finalized"],
                    "committedPrefixLength": part_committed,
                })
                remaining_committed = max(
                    0, remaining_committed - len(translated)
                )
            cues.append({
                "id": chunk_id,
                "segmentID": chunk_id,
                "original": item["original"],
                "translated": item["translated"],
                "finalized": item["finalized"],
                "committedPrefixLength": item.get(
                    "committed_prefix_length", 0
                ),
                "fragments": fragments,
            })
        return cues

    def _forward_current_glass_record(self, segment_id, record):
        """Update glass only when this semantic record is still visible.

        The complete record is already retained in ``record_store``.  A late
        remote final for a scrolled-out segment must not recreate a Qt widget
        just to have it trimmed again.
        """
        if not self.delegate:
            return
        visible_ids = {
            chunk_id for chunk_id, _item in self.record_store.latest_items(40)
        }
        if int(segment_id) not in visible_ids:
            return
        self.delegate.update_text(
            segment_id,
            record["original"],
            record["translated"],
            "final" if record["finalized"] else "partial",
            record.get("committed_prefix_length", 0),
        )

    @staticmethod
    def _is_ephemeral_short_segment(record):
        """Return true for isolated 1–3 word fragments, not wrapped rows."""
        original = " ".join(str(record.get("original") or "").split())
        if not original:
            return False
        words = re.findall(r"[A-Za-z0-9*+.#'-]+", original)
        return 0 < len(words) <= 3

    def _track_short_segment(self, segment_id, record):
        """Hide an unchanged short semantic segment after 1.5 seconds."""
        segment_id = int(segment_id)
        signature = " ".join(str(record.get("original") or "").split())
        previous_signature = self._short_source_signatures.get(segment_id)
        if not self._is_ephemeral_short_segment(record):
            self._short_source_signatures[segment_id] = signature
            self._short_segment_versions[segment_id] = (
                self._short_segment_versions.get(segment_id, 0) + 1
            )
            self._hidden_short_segments.discard(segment_id)
            return
        # Translation refinements for the same source do not extend its screen
        # lifetime or resurrect a fragment that already expired.
        if signature == previous_signature:
            return
        self._short_source_signatures[segment_id] = signature
        self._hidden_short_segments.discard(segment_id)
        version = self._short_segment_versions.get(segment_id, 0) + 1
        self._short_segment_versions[segment_id] = version
        QTimer.singleShot(
            1500,
            lambda sid=segment_id, expected=version, source=signature:
                self._expire_short_segment(sid, expected, source),
        )

    def _expire_short_segment(self, segment_id, expected_version, source_signature):
        if self._short_segment_versions.get(segment_id) != expected_version:
            return
        record = self.record_store.get(segment_id)
        if (
            record is None
            or " ".join(str(record.get("original") or "").split())
                != source_signature
            or not self._is_ephemeral_short_segment(record)
        ):
            return
        self._hidden_short_segments.add(segment_id)
        latest_items = self._latest_items()
        if latest_items != self._last_native_items:
            self._last_native_items = latest_items
            self._send({"items": latest_items})

    @staticmethod
    def _split_finalized_source(text, max_words):
        """Split long finalized text only at explicit clause boundaries."""
        text = " ".join((text or "").split())
        if len(text.split()) <= max_words:
            return [text]
        clauses = [
            part.strip()
            for part in re.split(r"(?<=[.!?;,:])\s+", text)
            if part.strip()
        ]
        if len(clauses) <= 1:
            # No safe semantic boundary: preserve the sentence intact.
            return [text]
        parts = []
        current = []
        current_words = 0
        for clause in clauses:
            clause_words = len(clause.split())
            if current and current_words + clause_words > max_words:
                parts.append(" ".join(current))
                current = []
                current_words = 0
            current.append(clause)
            current_words += clause_words
        if current:
            parts.append(" ".join(current))
        return parts if len(parts) > 1 else [text]

    @staticmethod
    def _semantic_parts_for_count(text, count):
        """Align display fragments while preferring punctuation boundaries."""
        text = " ".join((text or "").split())
        if count <= 1:
            return [text]
        clauses = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?；;，,])", text)
            if part.strip()
        ]
        if len(clauses) < count:
            return NativeNotchOverlay._balanced_parts(text, count)
        parts = []
        start = 0
        total_width = max(1, NativeNotchOverlay._visual_width(text))
        for index in range(count):
            remaining_parts = count - index
            remaining_clauses = len(clauses) - start
            if remaining_parts == 1:
                parts.append("".join(clauses[start:]).strip())
                break
            target = total_width / count
            end = start
            width = 0
            while end < len(clauses) - (remaining_parts - 1):
                next_width = NativeNotchOverlay._visual_width(clauses[end])
                if end > start and width + next_width > target:
                    break
                width += next_width
                end += 1
            end = max(start + 1, end)
            parts.append("".join(clauses[start:end]).strip())
            start = end
        return parts

    @staticmethod
    def _split_display_text(text, max_chars):
        text = " ".join((text or "").split())
        # The native label has 480 pt of usable width after horizontal padding
        # and two visible lines. A wide/CJK character is approximately 16 pt,
        # so 58 CJK characters (928 visual units) is the safe rendered limit.
        # Apply this to provisional drafts too: small-notch mode then keeps the
        # newest fitting fragment visible as a long partial continues growing.
        max_visual_width = max(16, int(max_chars) * 16)
        if not text or NativeNotchOverlay._visual_width(text) <= max_visual_width:
            return [text]
        clauses = [part for part in re.split(r"(?<=[。！？!?；;，,])", text) if part]
        parts = []
        current = ""
        for clause in clauses:
            if (
                current
                and NativeNotchOverlay._visual_width(current + clause)
                > max_visual_width
            ):
                parts.append(current.strip())
                current = ""
            while NativeNotchOverlay._visual_width(clause) > max_visual_width:
                split_at = NativeNotchOverlay._visual_prefix_length(
                    clause, max_visual_width
                )
                word_boundary = clause.rfind(" ", 0, split_at + 1)
                if word_boundary > max(0, split_at // 2):
                    split_at = word_boundary
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
    def _visual_prefix_length(text, max_visual_width):
        width = 0
        for index, char in enumerate(text):
            char_width = (
                16 if unicodedata.east_asian_width(char) in ("W", "F", "A") else 8
            )
            if width + char_width > max_visual_width:
                return max(1, index)
            width += char_width
        return len(text)

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
        payload.setdefault("busyStages", sorted(self._busy_stages))
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
        if self._paused:
            self._busy_stages.clear()
        payload = {"paused": self._paused}
        if self.record_store:
            payload["items"] = self._latest_items()
        self._send(payload)

    def close(self):
        self._visible_requested = False
        if self.delegate:
            self.delegate.close()
            self.delegate = None
        process = self.process
        if process:
            self._send({"command": "quit"})
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        self._writer_stop.set()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=0.2)
        self.process = None
