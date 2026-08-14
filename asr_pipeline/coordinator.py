"""The backend-neutral ASR-to-subtitle state machine.

This module intentionally stops before translation and rendering.  It accepts
cumulative ASR hypotheses, determines stable semantic subtitle boundaries, and
calls the supplied domain callbacks.  ``Pipeline`` remains the owner of audio,
executors, translators, Qt signals, and overlay windows.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
import re

from finalized_text import is_meaningful_final
from live_segmenter import IncrementalSegmenter
from stable_prefix import StablePrefixTracker

from .acceptance import ASREventAcceptanceGate, AcceptanceDecision
from .events import ASRHypothesis, ASRStreamBoundary


@dataclass(frozen=True, slots=True)
class ASRPartialUpdate:
    segment_id: int
    text: str
    stable_source_text: str
    segment_started_at: float
    first_partial_at: float
    observed_at: float


@dataclass(frozen=True, slots=True)
class ASRSemanticFinal:
    segment_id: int
    text: str
    segment_started_at: float
    first_partial_at: float | None
    cut_reason: str
    source_correction: bool = False


@dataclass(slots=True)
class _HostCandidate:
    """One Parakeet-only semantic cut awaiting native confirmation."""

    segment_id: int
    text: str
    start_word: int
    end_word: int
    segment_started_at: float
    first_partial_at: float | None
    cut_reason: str
    created_at: float
    stable_observations: int = 1
    last_observation_sequence: int = 0
    sealed: bool = False


@dataclass(frozen=True, slots=True)
class ASRFirstPartial:
    segment_id: int
    text: str
    segment_started_at: float
    first_partial_at: float
    anchored: bool


@dataclass(frozen=True, slots=True)
class ASRStablePrefix:
    segment_id: int
    text: str
    segment_started_at: float
    first_partial_at: float
    observed_at: float


@dataclass(frozen=True, slots=True)
class ASRBoundaryUpdate:
    segment_id: int | None
    text: str
    had_activity: bool


def _noop(*_args, **_kwargs):
    return None


class ASRSubtitleCoordinator:
    """Convert accepted ASR events into partial and semantic-final callbacks.

    The coordinator owns only source-side state: stable prefix tracking,
    semantic segmentation, segment numbering, and pause/reset boundaries.
    Downstream code decides how each partial is translated and displayed.
    """

    _HOST_SEAL_SECONDS = 0.35
    _HOST_SEAL_OBSERVATIONS = 2

    def __init__(
        self,
        *,
        session_generation: int,
        stable_prefix_window: float,
        stable_prefix_min_words: int,
        on_first_partial: Callable[[ASRFirstPartial], object] = _noop,
        on_stable_prefix: Callable[[ASRStablePrefix], object] = _noop,
        on_partial: Callable[[ASRPartialUpdate], object] = _noop,
        on_semantic_final: Callable[[ASRSemanticFinal], object] = _noop,
        on_source_idle: Callable[[], object] = _noop,
        on_boundary: Callable[[ASRBoundaryUpdate], object] = _noop,
        meaningful_text: Callable[[str], bool] = is_meaningful_final,
        host_semantic_boundaries: bool = False,
    ):
        self._gate = ASREventAcceptanceGate(session_generation)
        self._stable_prefix_window = float(stable_prefix_window)
        self._stable_prefix_min_words = int(stable_prefix_min_words)
        self._on_first_partial = on_first_partial
        self._on_stable_prefix = on_stable_prefix
        self._on_partial = on_partial
        self._on_semantic_final = on_semantic_final
        self._on_source_idle = on_source_idle
        self._on_boundary = on_boundary
        self._meaningful_text = meaningful_text
        self._host_semantic_boundaries = bool(host_semantic_boundaries)
        self._lock = threading.RLock()
        self._next_segment_id = 1
        self._stream_id: int | None = None
        self._audio_started_at: float | None = None
        self._first_partial_at: float | None = None
        self._latest_remainder = ""
        self._stable_tracker = self._new_stable_tracker()
        self._segmenter = IncrementalSegmenter(
            host_semantic_boundaries=self._host_semantic_boundaries,
        )
        self._host_candidates: list[_HostCandidate] = []

    @property
    def session_generation(self) -> int:
        return self._gate.session_generation

    @property
    def active_stream_id(self) -> int | None:
        return self._gate.active_stream_id

    def accept(self, event: ASRHypothesis | ASRStreamBoundary) -> AcceptanceDecision:
        """Accept one source event and dispatch its derived callbacks in order."""
        with self._lock:
            decision = self._gate.accept(event)
            if not decision.accepted:
                return decision
            if isinstance(event, ASRStreamBoundary):
                boundary = self._accept_boundary_locked(event)
                callbacks = [(self._on_boundary, boundary)]
            else:
                callbacks = self._accept_hypothesis_locked(event)

        # Translation and signal callbacks may schedule background work.  They
        # run outside the state lock so a slow callback cannot block an ASR
        # callback or a pause boundary from being accepted.
        for callback, value in callbacks:
            if value is None:
                callback()
            else:
                callback(value)
        return decision

    def _accept_hypothesis_locked(self, event: ASRHypothesis):
        self._ensure_stream_locked(event.stream_id, event.audio_anchor)
        now = event.emitted_at
        segment_started_at = self._audio_started_at or now
        first_partial_at = self._first_partial_at
        callbacks: list[tuple[Callable, object | None]] = []

        stable_text = event.text if event.source_final else ""
        if not event.source_final:
            if first_partial_at is None:
                first_partial_at = now
                self._first_partial_at = now
                callbacks.append((
                    self._on_first_partial,
                    ASRFirstPartial(
                        segment_id=self._next_segment_id,
                        text=event.text,
                        segment_started_at=segment_started_at,
                        first_partial_at=now,
                        anchored=event.audio_anchor is not None,
                    ),
                ))
            stable_text = self._stable_tracker.observe(event.text, now=now)
            if stable_text:
                callbacks.append((
                    self._on_stable_prefix,
                    ASRStablePrefix(
                        segment_id=self._next_segment_id,
                        text=stable_text,
                        segment_started_at=segment_started_at,
                        first_partial_at=first_partial_at,
                        observed_at=now,
                    ),
                ))

        candidate_finals: list[ASRSemanticFinal] = []
        candidate_partials: list[ASRPartialUpdate] = []
        if self._host_semantic_boundaries and not event.source_final:
            candidate_finals, candidate_partials = (
                self._observe_host_candidates_locked(
                    event.text, stable_text, event.sequence, now,
                )
            )

        segments, remainder = self._segmenter.observe(
            event.text,
            stable_text=stable_text,
            is_final=event.source_final,
            now=now,
        )
        self._latest_remainder = "" if event.source_final else remainder
        if not event.source_final and stable_text and remainder:
            stable_word_count = len(stable_text.split())
            committed_word_count = self._segmenter.committed_words
            stable_remainder_count = max(0, stable_word_count - committed_word_count)
            preview_stable_text = " ".join(remainder.split()[:stable_remainder_count])
        else:
            preview_stable_text = ""

        cut_reasons = list(self._segmenter.last_cut_reasons)
        finalized = list(candidate_finals)
        if self._host_semantic_boundaries and not event.source_final:
            for index, segment in enumerate(segments):
                words = self._words(segment)
                end_word = self._segmenter.committed_words
                candidate = _HostCandidate(
                    segment_id=self._next_segment_id,
                    text=segment,
                    start_word=end_word - len(words),
                    end_word=end_word,
                    segment_started_at=segment_started_at,
                    first_partial_at=first_partial_at,
                    cut_reason=(
                        cut_reasons[index]
                        if index < len(cut_reasons) else "host_boundary"
                    ),
                    created_at=now,
                    last_observation_sequence=event.sequence,
                )
                self._host_candidates.append(candidate)
                candidate_partials.append(ASRPartialUpdate(
                    segment_id=candidate.segment_id,
                    text=candidate.text,
                    stable_source_text=candidate.text,
                    segment_started_at=candidate.segment_started_at,
                    first_partial_at=candidate.first_partial_at or now,
                    observed_at=now,
                ))
                self._next_segment_id += 1
                segment_started_at = now
                first_partial_at = now
        elif event.source_final and self._host_semantic_boundaries:
            finalized.extend(self._resolve_host_candidates_locked(event.text))

        normal_segments = (
            [] if (self._host_semantic_boundaries and not event.source_final)
            else segments
        )
        for index, segment in enumerate(normal_segments):
            finalized.append(ASRSemanticFinal(
                segment_id=self._next_segment_id,
                text=segment,
                segment_started_at=segment_started_at,
                first_partial_at=first_partial_at,
                cut_reason=(
                    cut_reasons[index] if index < len(cut_reasons) else "unknown"
                ),
            ))
            self._next_segment_id += 1
            segment_started_at = now
            first_partial_at = now

        if event.source_final:
            self._audio_started_at = None
            self._first_partial_at = None
            self._latest_remainder = ""
            self._stable_tracker = self._new_stable_tracker()
        elif finalized:
            self._audio_started_at = now
            self._first_partial_at = now

        callbacks.extend((self._on_semantic_final, final) for final in finalized)
        if event.source_final:
            callbacks.append((self._on_source_idle, None))
            return callbacks

        if not remainder or not self._meaningful_text(remainder):
            callbacks.extend((self._on_partial, update) for update in candidate_partials)
            return callbacks
        callbacks.extend((self._on_partial, update) for update in candidate_partials)
        callbacks.append((
            self._on_partial,
            ASRPartialUpdate(
                segment_id=self._next_segment_id,
                text=remainder,
                stable_source_text=preview_stable_text,
                segment_started_at=segment_started_at,
                first_partial_at=first_partial_at or now,
                observed_at=now,
            ),
        ))
        return callbacks

    @staticmethod
    def _words(text: str) -> list[str]:
        return re.findall(r"\S+", " ".join(str(text or "").split()))

    @staticmethod
    def _same_words(left: str, right: str) -> bool:
        def normalise(value: str) -> str:
            return re.sub(
                r"^[^A-Za-z0-9']+|[^A-Za-z0-9']+$", "", value,
            ).casefold()

        return [normalise(item) for item in ASRSubtitleCoordinator._words(left)] == [
            normalise(item) for item in ASRSubtitleCoordinator._words(right)
        ]

    def _candidate_text(self, words: list[str], candidate: _HostCandidate) -> str:
        if len(words) < candidate.end_word:
            return ""
        return " ".join(words[candidate.start_word:candidate.end_word])

    def _observe_host_candidates_locked(
        self,
        text: str,
        stable_text: str,
        sequence: int,
        now: float,
    ) -> tuple[list[ASRSemanticFinal], list[ASRPartialUpdate]]:
        """Refresh unsealed Parakeet candidates from a later stable prefix."""
        full_words = self._words(text)
        stable_words = self._words(stable_text)
        finals = []
        partials = []
        for candidate in self._host_candidates:
            if candidate.sealed:
                continue
            replacement = self._candidate_text(full_words, candidate)
            if replacement and not self._same_words(replacement, candidate.text):
                candidate.text = replacement
                partials.append(ASRPartialUpdate(
                    segment_id=candidate.segment_id,
                    text=replacement,
                    stable_source_text="",
                    segment_started_at=candidate.segment_started_at,
                    first_partial_at=candidate.first_partial_at or now,
                    observed_at=now,
                ))
            stable_candidate = self._candidate_text(stable_words, candidate)
            if (
                stable_candidate
                and self._same_words(stable_candidate, candidate.text)
                and candidate.last_observation_sequence != sequence
            ):
                candidate.stable_observations += 1
                candidate.last_observation_sequence = sequence
            if (
                candidate.stable_observations >= self._HOST_SEAL_OBSERVATIONS
                and now - candidate.created_at >= self._HOST_SEAL_SECONDS
            ):
                candidate.sealed = True
                finals.append(ASRSemanticFinal(
                    segment_id=candidate.segment_id,
                    text=candidate.text,
                    segment_started_at=candidate.segment_started_at,
                    first_partial_at=candidate.first_partial_at,
                    cut_reason=candidate.cut_reason,
                ))
        return finals, partials

    def _resolve_host_candidates_locked(self, source_text: str) -> list[ASRSemanticFinal]:
        """Let a native Parakeet final seal or correct host-owned segments."""
        source_words = self._words(source_text)
        finals = []
        for candidate in self._host_candidates:
            native_text = self._candidate_text(source_words, candidate) or candidate.text
            if candidate.sealed:
                if not self._same_words(native_text, candidate.text):
                    finals.append(ASRSemanticFinal(
                        segment_id=candidate.segment_id,
                        text=native_text,
                        segment_started_at=candidate.segment_started_at,
                        first_partial_at=candidate.first_partial_at,
                        cut_reason="native_final_correction",
                        source_correction=True,
                    ))
                continue
            finals.append(ASRSemanticFinal(
                segment_id=candidate.segment_id,
                text=native_text,
                segment_started_at=candidate.segment_started_at,
                first_partial_at=candidate.first_partial_at,
                cut_reason="native_final",
            ))
        self._host_candidates.clear()
        return finals

    def _accept_boundary_locked(self, event: ASRStreamBoundary) -> ASRBoundaryUpdate:
        self._ensure_stream_locked(event.stream_id, event.audio_anchor)
        remainder = self._latest_remainder
        had_activity = bool(
            remainder
            or self._audio_started_at is not None
            or self._first_partial_at is not None
        )
        segment_id = None
        if remainder and self._meaningful_text(remainder):
            segment_id = self._next_segment_id
        if had_activity:
            self._next_segment_id += 1
        self._reset_source_state_locked()
        return ASRBoundaryUpdate(
            segment_id=segment_id,
            text=remainder if segment_id is not None else "",
            had_activity=had_activity,
        )

    def _ensure_stream_locked(self, stream_id: int, audio_anchor: float | None) -> None:
        if self._stream_id == stream_id:
            if self._audio_started_at is None and audio_anchor is not None:
                self._audio_started_at = audio_anchor
            return
        self._stream_id = stream_id
        self._reset_source_state_locked()
        if audio_anchor is not None:
            self._audio_started_at = audio_anchor

    def _reset_source_state_locked(self) -> None:
        self._audio_started_at = None
        self._first_partial_at = None
        self._latest_remainder = ""
        self._stable_tracker = self._new_stable_tracker()
        self._segmenter = IncrementalSegmenter(
            host_semantic_boundaries=self._host_semantic_boundaries,
        )
        self._host_candidates = []

    def _new_stable_tracker(self) -> StablePrefixTracker:
        return StablePrefixTracker(
            agreement_window=self._stable_prefix_window,
            min_growth_words=self._stable_prefix_min_words,
        )
