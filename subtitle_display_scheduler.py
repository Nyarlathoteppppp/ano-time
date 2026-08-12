"""Main-thread latest-wins cadence for subtitle rendering only."""

import time

from ui.qt import QObject, QTimer

from subtitle_event import SubtitleStage
from subtitle_presentation_coordinator import SubtitlePresentationCoordinator
from subtitle_presentation_policy import SubtitlePresentationPolicy


PACING_INTERVALS_MS = {
    "fluent": 110,
    "steady": 180,
    "focus": 280,
}


def interval_for_pacing(pacing):
    """Return the visual coalescing cadence for a supported user setting."""
    return PACING_INTERVALS_MS.get(str(pacing or "fluent").lower(), 110)


class SubtitleDisplayScheduler(QObject):
    """Show the leading update immediately, then coalesce same-stage bursts."""

    def __init__(
        self,
        consumer,
        interval_ms=110,
        parent=None,
        presentation_coordinator=None,
        presentation_policy=None,
    ):
        super().__init__(parent)
        self.consumer = consumer
        # This layer only controls the visual projection.  The pipeline signal
        # still goes directly to the transcript recorder and all model logic.
        self.presentation_coordinator = (
            presentation_coordinator or SubtitlePresentationCoordinator()
        )
        self.presentation_policy = (
            presentation_policy
            if isinstance(presentation_policy, SubtitlePresentationPolicy)
            else SubtitlePresentationPolicy(presentation_policy)
        )
        self.interval_seconds = max(0.0, int(interval_ms) / 1000)
        self._last_emitted_at = {}
        self._last_stage = {}
        self._pending = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush_due)

    def submit(self, event):
        event = self.presentation_coordinator.present(event)
        if event is None:
            return
        event = self.presentation_policy.project(event)
        if event is None:
            return
        segment_id = int(event.segment_id)
        now = time.monotonic()
        stage = event.stage
        stage_changed = self._last_stage.get(segment_id) != stage
        authoritative_stage = stage in {
            SubtitleStage.ASR_FINAL,
            SubtitleStage.APPLE_FINAL,
            SubtitleStage.AI_FINAL,
            SubtitleStage.ERROR,
        }
        elapsed = now - self._last_emitted_at.get(segment_id, float("-inf"))
        if (
            authoritative_stage
            or stage_changed
            or not self._is_paced_stage(stage)
            or elapsed >= self.interval_seconds
        ):
            self._pending.pop(segment_id, None)
            self._emit(event, now)
            return
        self._pending[segment_id] = event
        remaining_ms = max(1, round((self.interval_seconds - elapsed) * 1000))
        if not self._timer.isActive() or self._timer.remainingTime() > remaining_ms:
            self._timer.start(remaining_ms)

    @staticmethod
    def _is_paced_stage(stage):
        """Only coalesce a remote model's continuous text stream.

        Apple/ASR results are latency-critical local updates, so a user asking
        for a calmer *AI stream* must never accidentally delay those results.
        """
        return stage in {
            SubtitleStage.AI_PREVIEW,
            SubtitleStage.AI_STREAM,
        }

    def _emit(self, event, now=None):
        now = time.monotonic() if now is None else now
        segment_id = int(event.segment_id)
        self._last_emitted_at[segment_id] = now
        self._last_stage[segment_id] = event.stage
        self.consumer(event)

    def _flush_due(self):
        if not self._pending:
            return
        now = time.monotonic()
        waiting = []
        for segment_id, event in list(self._pending.items()):
            elapsed = now - self._last_emitted_at.get(
                segment_id, float("-inf")
            )
            if elapsed >= self.interval_seconds:
                self._pending.pop(segment_id, None)
                self._emit(event, now)
            else:
                waiting.append(self.interval_seconds - elapsed)
        if waiting:
            self._timer.start(max(1, round(min(waiting) * 1000)))

    def flush(self):
        self._timer.stop()
        now = time.monotonic()
        for event in list(self._pending.values()):
            self._emit(event, now)
        self._pending.clear()
