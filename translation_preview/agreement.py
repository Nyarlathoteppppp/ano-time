"""Conservative target-side local agreement for changing translations.

The agreement is deliberately presentation-only: it never changes a request or
the authoritative final translation.  It only decides how much of a changing
preview is safe to show as stable text.
"""

from dataclasses import dataclass
import threading


@dataclass(frozen=True, slots=True)
class AgreementProjection:
    display_text: str
    committed_prefix: str
    accepted: bool

    @property
    def stable_prefix(self):
        """The already-agreed part of the visible preview."""
        return self.committed_prefix

    @property
    def mutable_tail(self):
        """The still-revisable part of the visible preview."""
        if self.display_text.startswith(self.committed_prefix):
            return self.display_text[len(self.committed_prefix) :]
        return self.display_text


@dataclass(slots=True)
class _AgreementState:
    previous_candidate: str = ""
    displayed_candidate: str = ""
    committed_prefix: str = ""


class TargetLocalAgreement:
    """Commit repeated target prefixes while keeping a mutable tail.

    A character-level common prefix is useful for detecting agreement, but it
    must never freeze half of an English token or an unfinished LaTex fragment.
    Chinese characters are individually displayable, so a CJK-only tail may be
    committed at its exact boundary when no safer word boundary is available.
    """

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

    @staticmethod
    def _is_ascii_token_character(character):
        return character.isascii() and (
            character.isalnum() or character in "_+-*/^.#"
        )

    @classmethod
    def _outside_math_boundary(cls, text, limit):
        """Move *limit* before an unfinished ``$...$`` / LaTex group."""
        prefix = text[:limit]
        if prefix.count("$") % 2:
            return prefix.rfind("$")

        # A simple brace balance is enough here: it only protects the common
        # `\\hat{...}`, `\\mathbf{...}` forms produced by translation models.
        depth = 0
        for index, character in enumerate(prefix):
            if character == "\\" and index + 1 < len(prefix):
                continue
            if character == "{":
                depth += 1
            elif character == "}" and depth:
                depth -= 1
        if depth:
            last_command = max(prefix.rfind("\\"), prefix.rfind("{"))
            if last_command >= 0:
                return last_command
        return limit

    @classmethod
    def _natural_commit_boundary(cls, text, limit, continues_ascii_token=False):
        """Return the largest safe display boundary at or before ``limit``."""
        limit = max(0, min(int(limit), len(text)))
        while limit and text[limit - 1].isspace():
            limit -= 1
        math_safe_limit = cls._outside_math_boundary(text, limit)
        if math_safe_limit < limit:
            # The new boundary is deliberately before a math expression, so
            # a token after that expression cannot make the preceding prose
            # look like a partially emitted word.
            continues_ascii_token = False
        limit = math_safe_limit
        while limit and text[limit - 1].isspace():
            limit -= 1

        # Do not make a partial Latin token look permanent.  Roll back only
        # when the candidate ends *inside* a token; a complete word remains.
        if limit and cls._is_ascii_token_character(text[limit - 1]):
            token_start = limit
            while token_start and cls._is_ascii_token_character(text[token_start - 1]):
                token_start -= 1
            if token_start and cls._is_ascii_token_character(text[token_start - 1]):
                limit = token_start
            elif continues_ascii_token:
                limit = token_start
        return text[:limit].rstrip()

    @classmethod
    def agreed_prefix(cls, previous, candidate, holdback_characters=0):
        """Calculate a word/phrase-safe common prefix without mutating state."""
        previous = str(previous or "")
        candidate = str(candidate or "")
        common = cls._common_prefix(previous, candidate)
        safe_length = max(0, len(common) - max(0, int(holdback_characters)))
        continuation = (
            (previous[safe_length:safe_length + 1])
            + (candidate[safe_length:safe_length + 1])
        )
        return cls._natural_commit_boundary(
            common,
            safe_length,
            any(cls._is_ascii_token_character(char) for char in continuation),
        )

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
                proposed = self.agreed_prefix(
                    state.previous_candidate,
                    candidate,
                    self.holdback_characters,
                )
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
