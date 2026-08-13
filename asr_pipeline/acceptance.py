"""Reject stale ASR callbacks before they can mutate subtitle state."""

from __future__ import annotations

from dataclasses import dataclass

from .events import ASRHypothesis, ASRStreamBoundary


ASREvent = ASRHypothesis | ASRStreamBoundary


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    accepted: bool
    reason: str


class ASREventAcceptanceGate:
    """Monotonic gate for one launched Pipeline session.

    This gate runs *before* subtitle-event revisions exist.  It protects the
    ASR boundary itself, while ``SegmentStore`` continues protecting late
    translation results after a subtitle has been published.
    """

    def __init__(self, session_generation: int):
        self._session_generation = int(session_generation)
        if self._session_generation < 0:
            raise ValueError("session_generation must be non-negative")
        self._active_stream_id: int | None = None
        self._latest_sequence_by_stream: dict[int, int] = {}

    @property
    def session_generation(self) -> int:
        return self._session_generation

    @property
    def active_stream_id(self) -> int | None:
        return self._active_stream_id

    def reset(self, session_generation: int) -> None:
        session_generation = int(session_generation)
        if session_generation < 0:
            raise ValueError("session_generation must be non-negative")
        self._session_generation = session_generation
        self._active_stream_id = None
        self._latest_sequence_by_stream.clear()

    def accept(self, event: ASREvent) -> AcceptanceDecision:
        if event.session_generation != self._session_generation:
            return AcceptanceDecision(False, "stale_session")

        active_stream = self._active_stream_id
        if active_stream is not None and event.stream_id < active_stream:
            return AcceptanceDecision(False, "stale_stream")

        latest = self._latest_sequence_by_stream.get(event.stream_id)
        if latest is not None and event.sequence <= latest:
            return AcceptanceDecision(False, "stale_sequence")

        if active_stream is None or event.stream_id > active_stream:
            self._active_stream_id = event.stream_id
        self._latest_sequence_by_stream[event.stream_id] = event.sequence
        return AcceptanceDecision(True, "accepted")
