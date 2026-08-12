"""Display-only ownership rules for competing subtitle translations.

The pipeline keeps every valid Apple and remote-model revision in its semantic
store.  This coordinator sits *after* that store and only decides which
revision is pleasant and useful to render at a given moment.  Keeping this
policy outside the pipeline means transcript persistence and model fallback
continue to receive the complete event stream.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import time

from subtitle_event import SubtitleEvent, SubtitleStage


_PRIMARY_AI_STAGES = frozenset({
    SubtitleStage.AI_PREVIEW,
    SubtitleStage.AI_STREAM,
})
_FAST_PREVIEW_STAGES = frozenset({
    SubtitleStage.BRIDGE_PREVIEW,
    SubtitleStage.GROQ_BRIDGE,
})
_APPLE_STAGES = frozenset({
    SubtitleStage.APPLE_PARTIAL,
    SubtitleStage.APPLE_FINAL,
})


@dataclass(slots=True)
class _PresentedSegment:
    event: SubtitleEvent
    owner: str = "apple"
    owner_updated_at: float = 0.0


class SubtitlePresentationCoordinator:
    """Prevent rapid Apple/AI draft alternation in the visible subtitle.

    Apple remains the immediate first draft.  Once a primary AI preview is on
    screen, newer *append-only* Apple hypotheses are retained as semantic
    fallback data but do not repeatedly replace the visible Chinese.  Apple
    regains the display only when the AI preview is demonstrably stale, or
    when ASR rewrites rather than extends its source text.
    """

    def __init__(
        self,
        *,
        clock=None,
        ai_grace_seconds=0.90,
        max_ai_source_lag_words=8,
    ):
        self._clock = clock or time.monotonic
        self.ai_grace_seconds = max(0.0, float(ai_grace_seconds))
        self.max_ai_source_lag_words = max(1, int(max_ai_source_lag_words))
        self._segments: dict[int, _PresentedSegment] = {}

    def present(self, event: SubtitleEvent) -> SubtitleEvent | None:
        """Return a display event, or ``None`` when the frame is redundant."""
        event = event
        segment_id = int(event.segment_id)
        now = self._clock()
        current = self._segments.get(segment_id)

        if current is None:
            self._segments[segment_id] = _PresentedSegment(
                event=event,
                owner=self._owner_for(event),
                owner_updated_at=now,
            )
            return event

        if event.stage in _PRIMARY_AI_STAGES:
            return self._accept(segment_id, event, "ai", now)

        if event.stage == SubtitleStage.AI_FINAL:
            return self._accept(segment_id, event, "ai_final", now)

        if event.stage in _FAST_PREVIEW_STAGES:
            # A bridge is useful before the primary preview.  Once the latter
            # owns a cue, a late bridge must not revive an older short draft.
            if current.owner in {"ai", "ai_final"}:
                return None
            return self._accept(segment_id, event, "bridge", now)

        if event.stage == SubtitleStage.ASR_PARTIAL:
            return self._present_asr_partial(segment_id, current, event, now)

        if event.stage == SubtitleStage.ASR_FINAL:
            return self._present_asr_final(segment_id, current, event, now)

        if event.stage in _APPLE_STAGES:
            return self._present_apple(segment_id, current, event, now)

        # Errors and future protocol stages retain the existing behaviour:
        # display immediately rather than hiding diagnostics from the user.
        return self._accept(segment_id, event, self._owner_for(event), now)

    def _present_asr_partial(self, segment_id, current, event, now):
        if current.owner != "ai":
            return self._accept(segment_id, event, current.owner, now)

        if self._is_append_only(
            self._source_for_translation(current.event), event.original_text
        ):
            # SegmentStore exposes the latest Apple draft on ASR events after
            # a newer hypothesis arrives.  Preserve the visible AI text while
            # still advancing the English source immediately.
            return self._accept(
                segment_id,
                self._with_display_target(event, current.event),
                "ai",
                current.owner_updated_at,
            )

        # A non-prefix correction can invalidate the visible AI wording.  The
        # raw ASR event already carries the current local draft when available.
        return self._accept(segment_id, event, self._owner_for(event), now)

    def _present_asr_final(self, segment_id, current, event, now):
        if current.owner != "ai":
            return self._accept(segment_id, event, current.owner, now)

        # Mark the source final without replacing a useful AI preview by the
        # lower-quality Apple final.  AI_FINAL remains free to replace it.
        return self._accept(
            segment_id,
            self._with_display_target(event, current.event),
            "ai",
            current.owner_updated_at,
        )

    def _present_apple(self, segment_id, current, event, now):
        if current.owner != "ai":
            return self._accept(segment_id, event, "apple", now)

        if not self._is_append_only(
            self._source_for_translation(current.event),
            self._source_for_translation(event),
        ):
            # Corrected ASR source: correctness wins over continuity.
            return self._accept(segment_id, event, "apple", now)

        if event.stage == SubtitleStage.APPLE_FINAL:
            # A final Apple draft is the local, current-source fallback when a
            # remote final fails or times out.  It may cause one final update,
            # but hiding it could leave an old partial translation on screen.
            return self._accept(segment_id, event, "apple", now)

        source_lag = self._source_lag_words(
            self._source_for_translation(current.event),
            self._source_for_translation(event),
        )
        preview_age = now - current.owner_updated_at
        if (
            source_lag > self.max_ai_source_lag_words
            and preview_age >= self.ai_grace_seconds
        ):
            # AI did not catch up.  Release the newest Apple draft so captions
            # remain useful during a slow/failed preview request.
            return self._accept(segment_id, event, "apple", now)

        return None

    def _accept(self, segment_id, event, owner, updated_at):
        self._segments[segment_id] = _PresentedSegment(
            event=event,
            owner=owner,
            owner_updated_at=updated_at,
        )
        return event

    @staticmethod
    def _with_display_target(event, current):
        translated = current.translated_text
        committed = min(current.committed_prefix_length, len(translated))
        return SubtitleEvent.create(
            event.segment_id,
            event.revision,
            current.stage,
            event.original_text,
            translated,
            finalized=event.finalized,
            committed_prefix_length=committed,
            translation_source_text=current.translation_source_text,
        )

    @staticmethod
    def _source_for_translation(event):
        return event.translation_source_text or event.original_text

    @staticmethod
    def _owner_for(event):
        if event.stage in _PRIMARY_AI_STAGES or event.stage == SubtitleStage.AI_FINAL:
            return "ai_final" if event.stage == SubtitleStage.AI_FINAL else "ai"
        if event.stage in _FAST_PREVIEW_STAGES:
            return "bridge"
        return "apple"

    @staticmethod
    def _normalise_source(value):
        return " ".join(str(value or "").split()).casefold()

    @classmethod
    def _is_append_only(cls, previous, current):
        previous = cls._normalise_source(previous)
        current = cls._normalise_source(current)
        return bool(previous) and current.startswith(previous)

    @classmethod
    def _source_lag_words(cls, previous, current):
        previous_words = re.findall(r"[A-Za-z0-9*+#'-]+", cls._normalise_source(previous))
        current_words = re.findall(r"[A-Za-z0-9*+#'-]+", cls._normalise_source(current))
        return max(0, len(current_words) - len(previous_words))
