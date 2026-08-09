"""Thread-safe source of truth for subtitle segment revisions and stages."""

from dataclasses import dataclass
import threading

from subtitle_event import SubtitleEvent, SubtitleStage


TRANSLATION_RANKS = {
    SubtitleStage.APPLE_FINAL: 1,
    SubtitleStage.GROQ_BRIDGE: 2,
    SubtitleStage.AI_STREAM: 3,
    SubtitleStage.AI_FINAL: 3,
}


@dataclass(slots=True)
class SegmentState:
    segment_id: int
    revision: int = 0
    hypothesis_revision: int = 0
    original_text: str = ""
    translated_text: str = ""
    finalized: bool = False
    translation_rank: int = 0
    stage: SubtitleStage = SubtitleStage.ASR_PARTIAL


class SegmentStore:
    """Accept valid updates and reject stale partials or regressive drafts."""

    def __init__(self):
        self._lock = threading.RLock()
        self._segments = {}

    def _state(self, segment_id):
        segment_id = int(segment_id)
        return self._segments.setdefault(segment_id, SegmentState(segment_id))

    def publish(
        self,
        segment_id,
        stage,
        original_text,
        translated_text="",
        finalized=False,
        expected_hypothesis=None,
        translation_rank=None,
    ):
        """Return a typed event when an update is current, otherwise ``None``."""
        stage = SubtitleStage(stage)
        original_text = str(original_text)
        translated_text = str(translated_text)
        with self._lock:
            state = self._state(segment_id)

            if stage == SubtitleStage.ASR_PARTIAL:
                if state.finalized:
                    return None
                if (
                    state.stage == stage
                    and state.original_text == original_text
                    and not translated_text
                ):
                    return None
                state.hypothesis_revision += 1

            elif stage == SubtitleStage.APPLE_PARTIAL:
                if state.finalized:
                    return None
                if (
                    expected_hypothesis is not None
                    and int(expected_hypothesis) != state.hypothesis_revision
                ):
                    return None
                if (
                    state.stage == stage
                    and state.original_text == original_text
                    and state.translated_text == translated_text
                ):
                    return None

            elif stage == SubtitleStage.ASR_FINAL:
                if state.finalized and state.original_text == original_text:
                    return None
                state.hypothesis_revision += 1
                state.finalized = True

            rank = (
                TRANSLATION_RANKS.get(stage, 0)
                if translation_rank is None
                else int(translation_rank)
            )
            if rank:
                if rank < state.translation_rank:
                    return None
                if (
                    rank == state.translation_rank
                    and state.stage == SubtitleStage.AI_FINAL
                    and stage == SubtitleStage.AI_STREAM
                ):
                    return None
                state.translation_rank = rank
                state.finalized = state.finalized or bool(finalized)

            state.revision += 1
            state.stage = stage
            if original_text:
                state.original_text = original_text
            if translated_text:
                state.translated_text = translated_text

            return SubtitleEvent.create(
                state.segment_id,
                state.revision,
                stage,
                original_text,
                translated_text,
                finalized=bool(finalized),
            )

    def hypothesis_revision(self, segment_id):
        with self._lock:
            return self._state(segment_id).hypothesis_revision

    def is_current_partial(self, segment_id, hypothesis_revision):
        with self._lock:
            state = self._state(segment_id)
            return (
                not state.finalized
                and state.hypothesis_revision == int(hypothesis_revision)
            )

    def invalidate_partial(self, segment_id):
        """Invalidate in-flight Apple work without publishing a UI event."""
        with self._lock:
            state = self._state(segment_id)
            state.hypothesis_revision += 1

    def invalidate_all_partials(self):
        with self._lock:
            for state in self._segments.values():
                if not state.finalized:
                    state.hypothesis_revision += 1

    def snapshot(self, segment_id):
        """Return a detached state snapshot for tests and adapters."""
        with self._lock:
            state = self._state(segment_id)
            return SegmentState(
                segment_id=state.segment_id,
                revision=state.revision,
                hypothesis_revision=state.hypothesis_revision,
                original_text=state.original_text,
                translated_text=state.translated_text,
                finalized=state.finalized,
                translation_rank=state.translation_rank,
                stage=state.stage,
            )
