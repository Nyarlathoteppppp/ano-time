import re
import time


class IncrementalSegmenter:
    """Commit only semantically safe stable prefixes.

    Provisional text is intentionally outside this policy: callers may display
    and translate every partial while this class waits for a safe finalized
    boundary for remote refinement.
    """

    _END = re.compile(r"[.!?。！？][\"')\]]*$")
    _SOFT = re.compile(r"[,;:，；：][\"')\]]*$")
    _COMMA = re.compile(r"[,，][\"')\]]*$")

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

    def __init__(self, target_words=18, max_words=28, timeout_seconds=1.2,
                 timeout_min_words=12, min_words=6):
        self.target_words = target_words
        self.max_words = max_words
        self.timeout_seconds = timeout_seconds
        self.timeout_min_words = timeout_min_words
        self.min_words = min_words
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
            # A comma alone is too weak to prove that an English clause is
            # complete. Only treat it as an early boundary when the following
            # token visibly starts a new named/quoted clause. Lowercase
            # continuations such as "years, the government" and lists such as
            # "research, development, or" remain one semantic segment.
            if self._COMMA.search(stable_words[index - 1]):
                if not raw_right or not raw_right[0].isupper():
                    return False
        elif self._COMMA.search(stable_words[index - 1]):
            return False
        return True

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
