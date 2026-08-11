"""Non-blocking, per-session bilingual transcript persistence."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import queue
import threading
import time

from subtitle_record_store import SubtitleRecordStore
from subtitle_event import SubtitleStage


class SessionTranscriptRecorder:
    """Persist semantic subtitle records without blocking the subtitle fast path."""

    RETENTION_SECONDS = 3 * 24 * 60 * 60
    FILE_PREFIX = "AnoTime_"

    def __init__(self, output_dir=None, now=None, flush_delay=0.20):
        self._now = now or time.time
        self._flush_delay = max(0.0, float(flush_delay))
        self._store = SubtitleRecordStore()
        self._pending = queue.SimpleQueue()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._write_lock = threading.Lock()
        self.last_error = None

        self.output_dir = Path(
            output_dir or Path.home() / "Documents" / "Anotime Records"
        ).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_expired_records()

        started_at = datetime.fromtimestamp(self._now()).astimezone()
        self.started_at = started_at
        stem = f"{self.FILE_PREFIX}{started_at:%Y-%m-%d_%H-%M-%S}_双语记录"
        self.path = self._unique_path(stem)
        self._write_snapshot()

        self._thread = threading.Thread(
            target=self._writer_loop,
            name="anotime-transcript-writer",
            daemon=True,
        )
        self._thread.start()

    def _unique_path(self, stem):
        candidate = self.output_dir / f"{stem}.txt"
        suffix = 2
        while candidate.exists():
            candidate = self.output_dir / f"{stem}_{suffix}.txt"
            suffix += 1
        return candidate

    def cleanup_expired_records(self):
        cutoff = self._now() - self.RETENTION_SECONDS
        for path in self.output_dir.glob(f"{self.FILE_PREFIX}*_双语记录.txt"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                # Retention failure must never prevent translation from starting.
                continue

    def update_text(self, chunk_id, original_text, translated_text, state="partial"):
        if self._stopping.is_set():
            return
        # The live subtitle signal only performs an unbounded in-memory put.
        # Semantic merging and every filesystem operation stay on the writer.
        self._pending.put(
            (chunk_id, original_text, translated_text, state)
        )
        self._wake.set()

    def update_event(self, event):
        """Persist semantic finalized state, never provisional display previews."""
        if not event.finalized:
            return
        self.update_text(
            event.segment_id,
            event.original_text,
            "" if event.stage == SubtitleStage.ASR_FINAL else event.translated_text,
            "final",
        )

    def _drain_pending(self):
        while True:
            try:
                update = self._pending.get_nowait()
            except queue.Empty:
                return
            self._store.update(*update)

    def _render(self):
        updated_at = datetime.fromtimestamp(self._now()).astimezone()
        lines = [
            "AnoTime 双语课堂记录",
            f"日期：{self.started_at:%Y-%m-%d}",
            f"开始时间：{self.started_at:%H:%M:%S %Z}",
            f"最后更新：{updated_at:%Y-%m-%d %H:%M:%S %Z}",
            "",
        ]
        for _segment_id, item in self._store.sorted_items():
            original = item["original"].strip()
            translated = item["translated"].strip()
            if not original and not translated:
                continue
            lines.extend(
                [
                    f"[{item['timestamp']}]",
                    f"原文：{original or '—'}",
                    f"译文：{translated or '—'}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _write_snapshot(self):
        with self._write_lock:
            temporary = self.path.with_suffix(".txt.tmp")
            try:
                temporary.write_text(self._render(), encoding="utf-8")
                os.replace(temporary, self.path)
                self.last_error = None
            except OSError as exc:
                self.last_error = str(exc)
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _writer_loop(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            if not self._stopping.is_set() and self._flush_delay:
                self._stopping.wait(self._flush_delay)
            self._drain_pending()
            self._write_snapshot()
            if self._stopping.is_set():
                return

    def stop(self):
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._wake.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            self._write_snapshot()
