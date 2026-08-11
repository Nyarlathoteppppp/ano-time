"""Typed subtitle protocol shared by the pipeline and display adapters."""

from dataclasses import dataclass
from enum import Enum
import time


class SubtitleStage(str, Enum):
    ASR_PARTIAL = "asr_partial"
    ASR_FINAL = "asr_final"
    APPLE_PARTIAL = "apple_partial"
    APPLE_FINAL = "apple_final"
    BRIDGE_PREVIEW = "bridge_preview"
    AI_PREVIEW = "ai_preview"
    GROQ_BRIDGE = "groq_bridge"
    AI_STREAM = "ai_stream"
    AI_FINAL = "ai_final"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SubtitleEvent:
    segment_id: int
    revision: int
    stage: SubtitleStage
    original_text: str
    translated_text: str
    finalized: bool
    committed_prefix_length: int
    timestamp: float

    @classmethod
    def create(
        cls,
        segment_id,
        revision,
        stage,
        original_text,
        translated_text="",
        finalized=False,
        committed_prefix_length=0,
    ):
        return cls(
            segment_id=int(segment_id),
            revision=int(revision),
            stage=SubtitleStage(stage),
            original_text=str(original_text),
            translated_text=str(translated_text),
            finalized=bool(finalized),
            committed_prefix_length=max(
                0,
                min(int(committed_prefix_length), len(str(translated_text))),
            ),
            timestamp=time.time(),
        )

    @property
    def legacy_state(self):
        return "final" if self.finalized else "partial"
