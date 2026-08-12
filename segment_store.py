"""Thread-safe source of truth for subtitle segment revisions and stages."""

from dataclasses import dataclass
import threading

from chinese_text import force_simplified_chinese, is_simplified_chinese_target
from subtitle_event import SubtitleEvent, SubtitleStage


TRANSLATION_RANKS = {
    SubtitleStage.APPLE_PARTIAL: 1,
    SubtitleStage.APPLE_FINAL: 1,
    SubtitleStage.BRIDGE_PREVIEW: 2,
    SubtitleStage.GROQ_BRIDGE: 2,
    SubtitleStage.AI_PREVIEW: 3,
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
    translation_stage: SubtitleStage | None = None
    translation_source_text: str = ""
    committed_prefix_length: int = 0
    stage: SubtitleStage = SubtitleStage.ASR_PARTIAL


class SegmentStore:
    """Accept valid updates and reject stale partials or regressive drafts."""

    def __init__(self, target_lang="Chinese"):
        self._lock = threading.RLock()
        self._segments = {}
        self._force_simplified_chinese = is_simplified_chinese_target(target_lang)

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
        translation_source_text=None,
        committed_prefix_length=None,
    ):
        """Return a typed event when an update is current, otherwise ``None``."""
        stage = SubtitleStage(stage)
        original_text = str(original_text)
        # Shared output boundary for Apple drafts, bridge, Preview and Final:
        # force the requested Chinese script without delaying any request.
        translated_text = str(translated_text)
        if self._force_simplified_chinese:
            translated_text = force_simplified_chinese(translated_text)
        with self._lock:
            state = self._state(segment_id)
            preserve_current_source = False
            event_translation_source = str(translation_source_text or "")

            if stage == SubtitleStage.ASR_PARTIAL:
                if state.finalized:
                    return None
                # Apple Speech often repeats an unchanged hypothesis after the
                # local translation arrives. Do not create a new revision or
                # invalidate that useful draft merely because the last stage
                # stored for this segment is APPLE_PARTIAL.
                if state.original_text == original_text and not translated_text:
                    return None
                state.hypothesis_revision += 1
                if (
                    state.translation_stage in (
                        SubtitleStage.APPLE_PARTIAL,
                        SubtitleStage.BRIDGE_PREVIEW,
                        SubtitleStage.AI_PREVIEW,
                    )
                    and state.translation_source_text
                    and not original_text.startswith(state.translation_source_text)
                ):
                    state.translation_rank = 0
                    state.translation_stage = None
                    state.translation_source_text = ""
                    state.translated_text = ""
                    state.committed_prefix_length = 0

            elif stage == SubtitleStage.APPLE_PARTIAL:
                if state.finalized:
                    return None
                if (
                    expected_hypothesis is not None
                    and (
                        int(expected_hypothesis) > state.hypothesis_revision
                        or not state.original_text.startswith(original_text)
                    )
                ):
                    return None
                preserve_current_source = (
                    expected_hypothesis is not None
                    and int(expected_hypothesis) < state.hypothesis_revision
                )
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

            elif stage in (
                SubtitleStage.BRIDGE_PREVIEW,
                SubtitleStage.AI_PREVIEW,
            ):
                source = str(translation_source_text or original_text)
                if (
                    state.finalized
                    or expected_hypothesis is None
                    or state.hypothesis_revision < int(expected_hypothesis)
                    or not state.original_text.startswith(source)
                ):
                    return None
                if (
                    state.stage == stage
                    and state.translated_text == translated_text
                    and state.translation_source_text == source
                ):
                    return None

            rank = (
                TRANSLATION_RANKS.get(stage, 0)
                if translation_rank is None
                else int(translation_rank)
            )
            if rank:
                incoming_translation_source = str(
                    translation_source_text or original_text
                )
                event_translation_source = incoming_translation_source
                current_translation_source = state.translation_source_text
                incoming_is_newer_source = bool(
                    current_translation_source
                    and incoming_translation_source.startswith(
                        current_translation_source
                    )
                    and incoming_translation_source != current_translation_source
                )
                incoming_is_older_source = bool(
                    current_translation_source
                    and current_translation_source.startswith(
                        incoming_translation_source
                    )
                    and incoming_translation_source != current_translation_source
                )
                # Source freshness wins before provider quality. A fast Apple
                # draft for a longer ASR hypothesis must remain visible until
                # Gemini catches up; conversely, an older Gemini request must
                # never replace that newer draft merely because its rank is
                # higher.
                if incoming_is_older_source:
                    return None
                if rank < state.translation_rank and not incoming_is_newer_source:
                    return None
                if (
                    rank == state.translation_rank
                    and state.stage == SubtitleStage.AI_FINAL
                    and stage == SubtitleStage.AI_STREAM
                ):
                    return None
                state.translation_rank = rank
                if translated_text:
                    state.translation_stage = stage
                    state.translation_source_text = incoming_translation_source
                state.finalized = state.finalized or bool(finalized)

            state.revision += 1
            state.stage = stage
            if (
                original_text
                and stage not in (
                    SubtitleStage.BRIDGE_PREVIEW,
                    SubtitleStage.AI_PREVIEW,
                )
                and not preserve_current_source
            ):
                state.original_text = original_text
            if translated_text:
                previous_translation = state.translated_text
                state.translated_text = translated_text
                if committed_prefix_length is not None:
                    state.committed_prefix_length = max(
                        0,
                        min(int(committed_prefix_length), len(translated_text)),
                    )
                elif stage == SubtitleStage.AI_FINAL:
                    state.committed_prefix_length = len(translated_text)
                elif not translated_text.startswith(
                    previous_translation[:state.committed_prefix_length]
                ):
                    state.committed_prefix_length = 0

            return SubtitleEvent.create(
                state.segment_id,
                state.revision,
                stage,
                state.original_text,
                state.translated_text,
                finalized=state.finalized,
                committed_prefix_length=state.committed_prefix_length,
                translation_source_text=(
                    event_translation_source
                    or state.translation_source_text
                ),
            )

    def preview_is_compatible(self, segment_id, hypothesis_revision, stable_text):
        with self._lock:
            state = self._state(segment_id)
            return (
                not state.finalized
                and state.hypothesis_revision >= int(hypothesis_revision)
                and state.original_text.startswith(str(stable_text))
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

    def partial_is_compatible(self, segment_id, hypothesis_revision, source_text):
        """Allow a completed local draft while its source remains a prefix."""
        with self._lock:
            state = self._state(segment_id)
            return (
                not state.finalized
                and state.hypothesis_revision >= int(hypothesis_revision)
                and state.original_text.startswith(str(source_text))
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
                translation_stage=state.translation_stage,
                translation_source_text=state.translation_source_text,
                committed_prefix_length=state.committed_prefix_length,
                stage=state.stage,
            )
