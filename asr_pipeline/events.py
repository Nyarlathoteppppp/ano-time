"""Immutable ASR events shared by every local recognition backend.

The protocol intentionally describes only what happened at the ASR boundary.
It does not decide semantic sentence boundaries, create subtitle IDs, or know
anything about translation and presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ASRBackend(str, Enum):
    APPLE = "apple"
    PARAKEET_EOU = "parakeet_eou"
    MLX = "mlx"


class BoundaryReason(str, Enum):
    PAUSE = "pause"
    STOP = "stop"
    VAD_SILENCE = "vad_silence"
    SOURCE_RESET = "source_reset"
    SESSION_RESET = "session_reset"


def _normalise_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _require_nonnegative(name: str, value: int) -> int:
    value = int(value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class ASRHypothesis:
    """One cumulative English hypothesis for a single audio stream.

    ``sequence`` is assigned when the associated audio snapshot is submitted
    to ASR, never when inference completes.  This lets a coordinator reject a
    slow MLX result that arrives after a newer buffer has already published.
    ``source_final`` means the source ASR considers input complete; it is not a
    semantic subtitle or translation-final decision.
    """

    text: str
    source_final: bool
    backend: ASRBackend
    session_generation: int
    stream_id: int
    sequence: int
    audio_anchor: float | None
    emitted_at: float

    def __post_init__(self):
        text = _normalise_text(self.text)
        if not text:
            raise ValueError("ASRHypothesis.text must not be empty")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "backend", ASRBackend(self.backend))
        object.__setattr__(
            self,
            "session_generation",
            _require_nonnegative("session_generation", self.session_generation),
        )
        object.__setattr__(self, "stream_id", _require_nonnegative("stream_id", self.stream_id))
        object.__setattr__(self, "sequence", _require_nonnegative("sequence", self.sequence))
        if self.audio_anchor is not None:
            object.__setattr__(self, "audio_anchor", float(self.audio_anchor))
        object.__setattr__(self, "emitted_at", float(self.emitted_at))


@dataclass(frozen=True, slots=True)
class ASRStreamBoundary:
    """An explicit audio-stream reset without inventing an empty final text."""

    backend: ASRBackend
    session_generation: int
    stream_id: int
    sequence: int
    reason: BoundaryReason
    audio_anchor: float | None
    emitted_at: float

    def __post_init__(self):
        object.__setattr__(self, "backend", ASRBackend(self.backend))
        object.__setattr__(
            self,
            "session_generation",
            _require_nonnegative("session_generation", self.session_generation),
        )
        object.__setattr__(self, "stream_id", _require_nonnegative("stream_id", self.stream_id))
        object.__setattr__(self, "sequence", _require_nonnegative("sequence", self.sequence))
        object.__setattr__(self, "reason", BoundaryReason(self.reason))
        if self.audio_anchor is not None:
            object.__setattr__(self, "audio_anchor", float(self.audio_anchor))
        object.__setattr__(self, "emitted_at", float(self.emitted_at))
