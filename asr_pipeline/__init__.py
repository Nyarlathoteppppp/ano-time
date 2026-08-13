"""Backend-neutral ASR event protocol.

This package deliberately has no Qt, audio-capture, model, provider, or UI
dependencies.  ASR adapters publish hypotheses here before a later migration
hands them to the shared subtitle coordinator.
"""

from .acceptance import ASREventAcceptanceGate, AcceptanceDecision
from .adapters import StreamingASRAdapter
from .coordinator import (
    ASRBoundaryUpdate,
    ASRFirstPartial,
    ASRPartialUpdate,
    ASRSemanticFinal,
    ASRStablePrefix,
    ASRSubtitleCoordinator,
)
from .events import ASRBackend, ASRHypothesis, ASRStreamBoundary, BoundaryReason

__all__ = [
    "ASRBackend",
    "ASRBoundaryUpdate",
    "ASREventAcceptanceGate",
    "ASRFirstPartial",
    "ASRHypothesis",
    "ASRPartialUpdate",
    "ASRSemanticFinal",
    "ASRStablePrefix",
    "ASRSubtitleCoordinator",
    "ASRStreamBoundary",
    "AcceptanceDecision",
    "BoundaryReason",
    "StreamingASRAdapter",
]
