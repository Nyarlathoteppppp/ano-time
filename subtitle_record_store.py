"""Complete semantic subtitle records, independent from any display layout."""

import bisect
import threading
import time


class SubtitleRecordStore:
    """Keep one complete record per segment; never store UI display fragments."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records = {}
        # Segment identifiers are normally monotonic.  Keeping their order once
        # lets display projections read the newest few records in O(limit),
        # instead of sorting a whole multi-hour lecture for every refresh.
        self._ordered_segment_ids = []

    def update(
        self,
        segment_id,
        original_text,
        translated_text,
        state="partial",
        committed_prefix_length=0,
    ):
        segment_id = int(segment_id)
        with self._lock:
            current = self._records.get(segment_id)
            if current and current["finalized"] and state != "final":
                return None
            if current is None:
                if (
                    not self._ordered_segment_ids
                    or segment_id > self._ordered_segment_ids[-1]
                ):
                    self._ordered_segment_ids.append(segment_id)
                else:
                    # Keep the record contract deterministic for out-of-order
                    # replay/tests without slowing down the normal append path.
                    bisect.insort(self._ordered_segment_ids, segment_id)
            record = self._records.setdefault(
                segment_id,
                {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "original": "",
                    "translated": "",
                    "finalized": False,
                    "committed_prefix_length": 0,
                },
            )
            record["finalized"] = record["finalized"] or state == "final"
            if original_text:
                record["original"] = str(original_text)
            if translated_text:
                record["translated"] = str(translated_text)
                record["committed_prefix_length"] = max(
                    0,
                    min(int(committed_prefix_length), len(str(translated_text))),
                )
            return dict(record)

    def get(self, segment_id):
        with self._lock:
            record = self._records.get(int(segment_id))
            return dict(record) if record is not None else None

    def sorted_items(self):
        with self._lock:
            return [
                (segment_id, dict(self._records[segment_id]))
                for segment_id in self._ordered_segment_ids
            ]

    def latest_items(self, limit):
        limit = max(0, int(limit))
        if not limit:
            return []
        with self._lock:
            segment_ids = self._ordered_segment_ids[-limit:]
            return [
                (segment_id, dict(self._records[segment_id]))
                for segment_id in segment_ids
            ]

    def latest_items_excluding(self, limit, excluded_segment_ids=()):
        """Return the newest records not hidden by a display-only projection."""
        limit = max(0, int(limit))
        if not limit:
            return []
        excluded = {int(segment_id) for segment_id in excluded_segment_ids}
        with self._lock:
            newest = []
            for segment_id in reversed(self._ordered_segment_ids):
                if segment_id in excluded:
                    continue
                newest.append(segment_id)
                if len(newest) == limit:
                    break
            newest.reverse()
            return [
                (segment_id, dict(self._records[segment_id]))
                for segment_id in newest
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
