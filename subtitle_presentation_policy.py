"""User-selected visibility rules for subtitle revisions.

This module deliberately operates after the semantic subtitle store and the
presentation coordinator.  It can hide an intermediate *rendering* update,
but never cancels ASR, Apple translation, model requests, or transcript
persistence.
"""

from __future__ import annotations

from subtitle_event import SubtitleEvent, SubtitleStage


PRESENTATION_POLICIES = {
    "realtime": "实时优先",
    "balanced": "平衡",
    "stable": "稳定优先",
}


class SubtitlePresentationPolicy:
    """Decide whether one already-valid subtitle event should be rendered."""

    _BALANCED_HIDDEN = frozenset({
        SubtitleStage.APPLE_PARTIAL,
        SubtitleStage.BRIDGE_PREVIEW,
        SubtitleStage.GROQ_BRIDGE,
        SubtitleStage.AI_STREAM,
    })
    _STABLE_HIDDEN = _BALANCED_HIDDEN | frozenset({
        SubtitleStage.AI_PREVIEW,
    })

    def __init__(self, mode="realtime"):
        self.mode = str(mode or "realtime").strip().lower()
        if self.mode not in PRESENTATION_POLICIES:
            self.mode = "realtime"

    def project(self, event: SubtitleEvent) -> SubtitleEvent | None:
        """Return a visible projection without mutating semantic subtitle data.

        ASR events can intentionally carry the last known translation while a
        newer source hypothesis is being assembled.  In a calmer display mode
        that retained text must not leak an old Apple draft back onto screen,
        so we keep its English source but remove only the transient target.
        """
        if self.mode == "realtime":
            return event
        hidden = (
            self._BALANCED_HIDDEN
            if self.mode == "balanced"
            else self._STABLE_HIDDEN
        )
        if event.stage in hidden:
            return None
        if (
            event.stage in {
                SubtitleStage.ASR_PARTIAL,
                SubtitleStage.ASR_FINAL,
            }
            and event.translated_text
        ):
            return SubtitleEvent.create(
                event.segment_id,
                event.revision,
                event.stage,
                event.original_text,
                "",
                finalized=event.finalized,
                translation_source_text=event.translation_source_text,
            )
        return event
