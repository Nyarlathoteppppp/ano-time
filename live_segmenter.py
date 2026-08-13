import re
import time


class IncrementalSegmenter:
    """Commit only semantically safe stable prefixes.

    Provisional text is intentionally outside this policy: callers may display
    and translate every partial while this class waits for a safe finalized
    boundary for remote refinement.
    """

    _END = re.compile(r"[.!?。！？][\"')\]]*$")
    # A comma can end a dependent clause, so it is never strong enough to
    # finalize semantic text. Semicolons and colons are safe early boundaries.
    _SOFT = re.compile(r"[;:；：][\"')\]]*$")

    _FORBIDDEN_LEFT = {
        "a", "an", "the", "to", "of", "in", "on", "at", "for", "from",
        "with", "by", "and", "or", "but", "because", "although", "while",
        "if", "when", "that", "which", "who", "whose", "is", "are", "was",
        "were", "have", "has", "had", "will", "would", "can", "could",
        "should", "may", "might", "must",
    }
    _FORBIDDEN_RIGHT = {
        "and", "or", "but", "of", "to", "than", "as", "quote",
    }
    _FORBIDDEN_SUFFIXES = {
        ("as", "well"), ("according", "to"), ("in", "order"),
        ("due", "to"), ("one", "of"), ("such", "as"), ("rest", "of"),
        ("kind", "of"), ("part", "of"), ("number", "of"),
    }

    # Streaming recognizers such as Parakeet can emit long, unpunctuated
    # cumulative hypotheses for a whole lecture. These are discourse starters
    # that can safely begin a new *product* cue when the preceding stable
    # phrase is already substantial. They deliberately exclude dependent-clause
    # starters such as ``because``, ``if``, ``when`` and ``that``.
    _HOST_DISCOURSE_STARTERS = {
        "also", "anyway", "but", "finally", "however", "meanwhile",
        "next", "now", "okay", "otherwise", "so", "then", "therefore",
        "well",
    }
    _HOST_WINDOW_FORBIDDEN_LEFT = _FORBIDDEN_LEFT | {
        "all", "any", "each", "every", "few", "many", "most", "much",
        "no", "some", "such", "the", "this", "those", "these", "very",
    }
    _HOST_WINDOW_FORBIDDEN_RIGHT = _FORBIDDEN_RIGHT | {
        "a", "an", "at", "because", "before", "between", "by", "can",
        "could", "during", "for", "from", "has", "have", "if", "in",
        "into", "is", "may", "might", "of", "on", "onto", "over", "that",
        "the", "then", "there", "these", "this", "through", "to", "under",
        "was", "were", "when", "where", "which", "while", "will", "with",
        "without", "would",
    }

    def __init__(self, target_words=18, max_words=28, timeout_seconds=1.2,
                 timeout_min_words=12, min_words=6,
                 host_semantic_boundaries=False, host_min_words=10,
                 host_force_words=36):
        self.target_words = target_words
        self.max_words = max_words
        self.timeout_seconds = timeout_seconds
        self.timeout_min_words = timeout_min_words
        self.min_words = min_words
        self.host_semantic_boundaries = bool(host_semantic_boundaries)
        self.host_min_words = max(self.min_words, int(host_min_words))
        self.host_force_words = max(self.host_min_words, int(host_force_words))
        self.started_at = None
        self.last_stable_growth_at = None
        self.stable_word_count = 0
        self.committed_words = 0
        self.last_cut_reasons = []

    @staticmethod
    def _words(text):
        return re.findall(r"\S+", " ".join((text or "").split()))

    @staticmethod
    def _plain(word):
        return re.sub(r"^[^A-Za-z']+|[^A-Za-z']+$", "", word).casefold()

    def _safe_boundary(self, stable_words, full_words, index):
        left = self._plain(stable_words[index - 1])
        if not left or left in self._FORBIDDEN_LEFT:
            return False
        suffix = tuple(self._plain(word) for word in stable_words[max(0, index - 2):index])
        if suffix in self._FORBIDDEN_SUFFIXES:
            return False
        if index < len(full_words):
            raw_right = re.sub(r"^[\"'([{]+", "", full_words[index])
            right = self._plain(raw_right)
            if right in self._FORBIDDEN_RIGHT:
                return False
        return True

    def _host_discourse_boundary(self, words, full_words, index):
        """Return whether a stable, unpunctuated cue can end before `index`.

        This is intentionally more conservative than a generic word limit. It
        only considers a known discourse starter at the beginning of the next
        clause. The result is still a semantic product segment (not merely a
        UI wrap), so dependent starts are never accepted here.
        """
        if index < self.host_min_words or index >= len(full_words):
            return False
        left = self._plain(words[index - 1])
        right = self._plain(full_words[index])
        if not left or left in self._FORBIDDEN_LEFT:
            return False
        if right not in self._HOST_DISCOURSE_STARTERS:
            return False
        suffix = tuple(self._plain(word) for word in words[max(0, index - 2):index])
        if suffix in self._FORBIDDEN_SUFFIXES:
            return False
        # "so that" starts a dependent purpose clause rather than a new cue.
        if (
            right == "so"
            and index + 1 < len(full_words)
            and self._plain(full_words[index + 1]) == "that"
        ):
            return False
        return True

    def _host_stable_window_boundary(self, words, full_words, index):
        """Return a last-resort stable cut for an indefinitely open stream.

        It is enabled only for hosts that never report EOU. The cut must lie
        between two content words and therefore cannot end on a determiner,
        preposition, auxiliary or conjunction. This is not used by Apple and
        does not change its native-final semantics.
        """
        if index < self.host_min_words or index >= len(full_words):
            return False
        left = self._plain(words[index - 1])
        right = self._plain(full_words[index])
        if not left or not right:
            return False
        if left in self._HOST_WINDOW_FORBIDDEN_LEFT:
            return False
        if right in self._HOST_WINDOW_FORBIDDEN_RIGHT:
            return False
        suffix = tuple(self._plain(word) for word in words[max(0, index - 2):index])
        return suffix not in self._FORBIDDEN_SUFFIXES

    def _cut_count(self, words, full_words, stalled=False, final=False):
        if not words:
            return 0, ""
        for index, word in enumerate(words, start=1):
            if index >= self.min_words and self._END.search(word):
                return index, "sentence_punctuation"
        if final:
            return len(words), "native_final"

        upper = min(len(words), self.max_words)
        candidates = [
            index for index in range(self.min_words, upper + 1)
            if self._SOFT.search(words[index - 1])
            and self._safe_boundary(words, full_words, index)
        ]
        if candidates and len(words) >= self.target_words:
            return min(candidates, key=lambda item: (abs(item - self.target_words), -item)), "soft_boundary"
        if candidates and stalled and len(words) >= self.timeout_min_words:
            return candidates[-1], "stable_pause"
        if self.host_semantic_boundaries:
            host_upper = min(len(words), self.max_words)
            host_candidates = [
                index
                for index in range(self.host_min_words, host_upper)
                if self._host_discourse_boundary(words, full_words, index)
            ]
            if host_candidates:
                return (
                    min(
                        host_candidates,
                        key=lambda item: (abs(item - self.target_words), -item),
                    ),
                    "host_discourse_boundary",
                )
            if len(words) >= self.host_force_words:
                window_upper = min(len(words), self.host_force_words)
                window_candidates = [
                    index
                    for index in range(self.host_min_words, window_upper)
                    if self._host_stable_window_boundary(words, full_words, index)
                ]
                if window_candidates:
                    return (
                        min(
                            window_candidates,
                            key=lambda item: (abs(item - self.target_words), -item),
                        ),
                        "host_stable_window",
                    )
        # A word limit is a search window, never permission to split grammar.
        # If no safe boundary exists, keep the text provisional until Apple
        # finalizes it or more stable context exposes a real clause boundary.
        return 0, ""

    def observe(self, text, stable_text="", is_final=False, now=None):
        now = time.monotonic() if now is None else now
        self.last_cut_reasons = []
        full_words = self._words(text)
        if self.started_at is None:
            self.started_at = now

        if is_final:
            stable_words = full_words
        else:
            stable_count = len(self._words(stable_text))
            if stable_count > self.stable_word_count:
                self.stable_word_count = stable_count
                self.last_stable_growth_at = now
            # StablePrefixTracker intentionally strips trailing punctuation.
            # Reuse the same stable word count from the full hypothesis so a
            # confirmed sentence-ending token still carries its punctuation.
            stable_words = full_words[:min(self.stable_word_count, len(full_words))]
        available_stable = stable_words[self.committed_words:]
        full_available = full_words[self.committed_words:]
        finalized = []
        stalled = (
            self.last_stable_growth_at is not None
            and now - self.last_stable_growth_at >= self.timeout_seconds
        )

        while available_stable:
            cut, reason = self._cut_count(
                available_stable,
                full_available,
                stalled=stalled,
                final=is_final,
            )
            if not cut:
                break
            finalized.append(" ".join(available_stable[:cut]))
            self.last_cut_reasons.append(reason)
            self.committed_words += cut
            available_stable = stable_words[self.committed_words:]
            full_available = full_words[self.committed_words:]
            self.started_at = now
            stalled = False
            if not is_final:
                break

        remainder = " ".join(full_words[self.committed_words:])
        if is_final:
            self.reset()
        return finalized, remainder

    def reset(self):
        self.started_at = None
        self.last_stable_growth_at = None
        self.stable_word_count = 0
        self.committed_words = 0
