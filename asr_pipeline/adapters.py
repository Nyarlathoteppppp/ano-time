"""Small adapters that assign ordering metadata to native ASR callbacks."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .events import ASRBackend, ASRHypothesis, ASRStreamBoundary, BoundaryReason


class StreamingASRAdapter:
    """Convert one streaming ASR callback source into ordered protocol events.

    The adapter deliberately does not know how the recognizer works.  It owns
    only the monotonically increasing stream/sequence metadata required at the
    shared subtitle boundary.  Callers must allocate one adapter per launched
    Pipeline session.
    """

    def __init__(
        self,
        *,
        backend: ASRBackend,
        session_generation: int,
        emit: Callable[[ASRHypothesis | ASRStreamBoundary], object],
        clock: Callable[[], float] = time.monotonic,
    ):
        self.backend = ASRBackend(backend)
        self.session_generation = int(session_generation)
        self._emit = emit
        self._clock = clock
        self._lock = threading.RLock()
        self._stream_id = 1
        self._sequence = 0
        self._audio_anchor: float | None = None

    @property
    def current_stream_id(self) -> int:
        with self._lock:
            return self._stream_id

    def note_audio_activity(self, at: float | None = None) -> tuple[int, float] | None:
        """Remember the first speech-like audio time for the current stream."""
        at = self._clock() if at is None else float(at)
        with self._lock:
            if self._audio_anchor is not None:
                return None
            self._audio_anchor = at
            return self._stream_id, at

    def result(
        self,
        text: str,
        source_final: bool,
        *,
        emitted_at: float | None = None,
    ):
        """Publish one callback result and advance after a source final."""
        emitted_at = self._clock() if emitted_at is None else float(emitted_at)
        with self._lock:
            self._sequence += 1
            event = ASRHypothesis(
                text=text,
                source_final=source_final,
                backend=self.backend,
                session_generation=self.session_generation,
                stream_id=self._stream_id,
                sequence=self._sequence,
                audio_anchor=self._audio_anchor,
                emitted_at=emitted_at,
            )
            decision = self._emit(event)
            if source_final:
                self._advance_stream_locked()
            return decision

    def boundary(
        self,
        reason: BoundaryReason,
        *,
        emitted_at: float | None = None,
    ):
        """Publish an explicit source reset and start a fresh stream."""
        emitted_at = self._clock() if emitted_at is None else float(emitted_at)
        with self._lock:
            self._sequence += 1
            event = ASRStreamBoundary(
                backend=self.backend,
                session_generation=self.session_generation,
                stream_id=self._stream_id,
                sequence=self._sequence,
                reason=reason,
                audio_anchor=self._audio_anchor,
                emitted_at=emitted_at,
            )
            decision = self._emit(event)
            self._advance_stream_locked()
            return decision

    def _advance_stream_locked(self) -> None:
        self._stream_id += 1
        self._sequence = 0
        self._audio_anchor = None
