"""Immutable request types for the progressive preview lane."""

from dataclasses import dataclass

from translation_context import TranslationContext


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    segment_id: int
    hypothesis_revision: int
    source_text: str
    generation: int
    submitted_at: float
    deadline: float
    context: TranslationContext | None = None
