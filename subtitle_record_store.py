"""Complete semantic subtitle records, independent from any display layout."""

import threading
import time


class SubtitleRecordStore:
    """Keep one complete record per segment; never store UI display fragments."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records = {}

    def update(self, segment_id, original_text, translated_text, state="partial"):
        segment_id = int(segment_id)
        with self._lock:
            current = self._records.get(segment_id)
            if current and current["finalized"] and state != "final":
                return None
            record = self._records.setdefault(
                segment_id,
                {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "original": "",
                    "translated": "",
                    "finalized": False,
                },
            )
            record["finalized"] = record["finalized"] or state == "final"
            if original_text:
                record["original"] = str(original_text)
            if translated_text:
                record["translated"] = str(translated_text)
            return dict(record)

    def get(self, segment_id):
        with self._lock:
            record = self._records.get(int(segment_id))
            return dict(record) if record is not None else None

    def sorted_items(self):
        with self._lock:
            return [
                (segment_id, dict(self._records[segment_id]))
                for segment_id in sorted(self._records)
            ]

    def latest_items(self, limit):
        limit = max(0, int(limit))
        if not limit:
            return []
        with self._lock:
            segment_ids = sorted(self._records)[-limit:]
            return [
                (segment_id, dict(self._records[segment_id]))
                for segment_id in segment_ids
            ]

    def snapshot(self):
        with self._lock:
            return {
                segment_id: dict(record)
                for segment_id, record in self._records.items()
            }

    def __bool__(self):
        with self._lock:
            return bool(self._records)
