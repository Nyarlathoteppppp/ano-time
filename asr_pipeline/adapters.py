"""Small adapters that assign ordering metadata to ASR callback sources."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class RollingASRSnapshot:
    """Ordering metadata frozen when a rolling audio buffer is submitted.

    MLX inference is serial today, but completion order must not be a hidden
    correctness assumption. A snapshot carries the capture-side sequence so a
    late result cannot rewrite a newer subtitle.
    """

    backend: ASRBackend
    session_generation: int
    stream_id: int
    sequence: int
    audio_anchor: float | None
    source_final: bool
    submission_epoch: int


class RollingASRAdapter:
    """Adapt rolling-buffer ASR snapshots without changing inference itself.

    ``reserve`` runs in the audio-capture thread before a buffer enters the
    single MLX worker. ``complete`` runs after transcription. A VAD-final
    reservation starts a new capture stream immediately, so the following
    utterance never inherits the old buffer state. ``boundary`` invalidates
    queued snapshots from the previous epoch before a pause can resume.
    """

    def __init__(
        self,
        *,
        backend: ASRBackend = ASRBackend.MLX,
        session_generation: int,
        emit: Callable[[ASRHypothesis | ASRStreamBoundary], object],
        clock: Callable[[], float] = time.monotonic,
    ):
        self.backend = ASRBackend(backend)
        self.session_generation = int(session_generation)
        self._emit = emit
        self._clock = clock
        self._lock = threading.RLock()
        self._current_stream_id = 1
        self._next_stream_id = 2
        self._sequence_by_stream: dict[int, int] = {}
        self._audio_anchor_by_stream: dict[int, float | None] = {1: None}
        self._visible_stream_id: int | None = None
        self._submission_epoch = 0

    @property
    def current_stream_id(self) -> int:
        with self._lock:
            return self._current_stream_id

    def note_audio_activity(self, at: float | None = None) -> tuple[int, float] | None:
        """Anchor first speech-like input for the active capture stream."""
        at = self._clock() if at is None else float(at)
        with self._lock:
            stream_id = self._current_stream_id
            if self._audio_anchor_by_stream.get(stream_id) is not None:
                return None
            self._audio_anchor_by_stream[stream_id] = at
            return stream_id, at

    def reserve(self, *, source_final: bool) -> RollingASRSnapshot:
        """Freeze metadata before submitting one buffer to the ASR worker."""
        with self._lock:
            stream_id = self._current_stream_id
            sequence = self._sequence_by_stream.get(stream_id, 0) + 1
            self._sequence_by_stream[stream_id] = sequence
            snapshot = RollingASRSnapshot(
                backend=self.backend,
                session_generation=self.session_generation,
                stream_id=stream_id,
                sequence=sequence,
                audio_anchor=self._audio_anchor_by_stream.get(stream_id),
                source_final=bool(source_final),
                submission_epoch=self._submission_epoch,
            )
            if source_final:
                self._start_new_capture_stream_locked()
            return snapshot

    def complete(
        self,
        snapshot: RollingASRSnapshot,
        text: str,
        *,
        emitted_at: float | None = None,
    ):
        """Publish a completed ASR result unless pause/reset made it stale."""
        emitted_at = self._clock() if emitted_at is None else float(emitted_at)
        text = " ".join((text or "").split())
        with self._lock:
            if snapshot.submission_epoch != self._submission_epoch:
                return None
            if text:
                event: ASRHypothesis | ASRStreamBoundary = ASRHypothesis(
                    text=text,
                    source_final=snapshot.source_final,
                    backend=snapshot.backend,
                    session_generation=snapshot.session_generation,
                    stream_id=snapshot.stream_id,
                    sequence=snapshot.sequence,
                    audio_anchor=snapshot.audio_anchor,
                    emitted_at=emitted_at,
                )
            elif snapshot.source_final:
                # An empty VAD final must still reset the coordinator. It is
                # an audio boundary, not an invented empty subtitle final.
                event = ASRStreamBoundary(
                    backend=snapshot.backend,
                    session_generation=snapshot.session_generation,
                    stream_id=snapshot.stream_id,
                    sequence=snapshot.sequence,
                    reason=BoundaryReason.VAD_SILENCE,
                    audio_anchor=snapshot.audio_anchor,
                    emitted_at=emitted_at,
                )
            else:
                return None
            decision = self._emit(event)
            if getattr(decision, "accepted", True):
                # A source-final (including an empty VAD boundary) leaves no
                # open source remainder to seal again on a later pause.
                self._visible_stream_id = (
                    None if snapshot.source_final else snapshot.stream_id
                )
            return decision

    def boundary(
        self,
        reason: BoundaryReason,
        *,
        emitted_at: float | None = None,
    ):
        """Seal the visible stream and discard every queued old snapshot."""
        emitted_at = self._clock() if emitted_at is None else float(emitted_at)
        with self._lock:
            visible_stream_id = self._visible_stream_id
            self._submission_epoch += 1
            self._start_new_capture_stream_locked()
            if visible_stream_id is None:
                return None
            sequence = self._sequence_by_stream.get(visible_stream_id, 0) + 1
            self._sequence_by_stream[visible_stream_id] = sequence
            event = ASRStreamBoundary(
                backend=self.backend,
                session_generation=self.session_generation,
                stream_id=visible_stream_id,
                sequence=sequence,
                reason=reason,
                audio_anchor=self._audio_anchor_by_stream.get(visible_stream_id),
                emitted_at=emitted_at,
            )
            decision = self._emit(event)
            self._visible_stream_id = None
            return decision

    def _start_new_capture_stream_locked(self) -> None:
        stream_id = self._next_stream_id
        self._next_stream_id += 1
        self._current_stream_id = stream_id
        self._sequence_by_stream.setdefault(stream_id, 0)
        self._audio_anchor_by_stream[stream_id] = None
