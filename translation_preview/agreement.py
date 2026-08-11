"""Conservative target-side local agreement for changing translations."""

from dataclasses import dataclass
import threading


@dataclass(frozen=True, slots=True)
class AgreementProjection:
    display_text: str
    committed_prefix: str
    accepted: bool


@dataclass(slots=True)
class _AgreementState:
    previous_candidate: str = ""
    displayed_candidate: str = ""
    committed_prefix: str = ""


class TargetLocalAgreement:
    """Commit repeated target prefixes while keeping a mutable tail."""

    def __init__(self, holdback_characters=10):
        self.holdback_characters = max(0, int(holdback_characters))
        self._lock = threading.RLock()
        self._states = {}

    @staticmethod
    def _common_prefix(left, right):
        limit = min(len(left), len(right))
        index = 0
        while index < limit and left[index] == right[index]:
            index += 1
        return left[:index]

    def observe(self, segment_id, candidate):
        """Accept one complete translation hypothesis and extend agreement."""
        candidate = str(candidate or "").strip()
        with self._lock:
            state = self._states.setdefault(int(segment_id), _AgreementState())
            if not candidate:
                return AgreementProjection(
                    state.displayed_candidate,
                    state.committed_prefix,
                    False,
                )
            if state.committed_prefix and not candidate.startswith(
                state.committed_prefix
            ):
                # A single divergent hypothesis cannot rewrite already agreed
                # text. The authoritative finalized result may still replace it.
                state.previous_candidate = candidate
                return AgreementProjection(
                    state.displayed_candidate,
                    state.committed_prefix,
                    False,
                )
            if state.previous_candidate:
                common = self._common_prefix(state.previous_candidate, candidate)
                safe_length = max(0, len(common) - self.holdback_characters)
                proposed = common[:safe_length].rstrip()
                if (
                    len(proposed) > len(state.committed_prefix)
                    and proposed.startswith(state.committed_prefix)
                ):
                    state.committed_prefix = proposed
            state.previous_candidate = candidate
            state.displayed_candidate = candidate
            return AgreementProjection(candidate, state.committed_prefix, True)

    def project_stream(self, segment_id, candidate):
        """Render one token-stream snapshot without committing new text."""
        candidate = str(candidate or "").strip()
        with self._lock:
            state = self._states.setdefault(int(segment_id), _AgreementState())
            if not candidate:
                return AgreementProjection(
                    state.displayed_candidate,
                    state.committed_prefix,
                    False,
                )
            if state.committed_prefix and not candidate.startswith(
                state.committed_prefix
            ):
                return AgreementProjection(
                    state.displayed_candidate,
                    state.committed_prefix,
                    False,
                )
            state.displayed_candidate = candidate
            return AgreementProjection(candidate, state.committed_prefix, True)

    def displayed_candidate(self, segment_id):
        """Return the last visible preview without exposing mutable state."""
        with self._lock:
            state = self._states.get(int(segment_id))
            return state.displayed_candidate if state is not None else ""

    def reset(self, segment_id=None):
        with self._lock:
            if segment_id is None:
                self._states.clear()
            else:
                self._states.pop(int(segment_id), None)
