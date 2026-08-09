import re
import time


class IncrementalSegmenter:
    """Commit stable prefixes before Apple's full utterance becomes final."""

    _END = re.compile(r"[.!?。！？][\"')\]]*$")
    _SOFT = re.compile(r"[,;:，；：][\"')\]]*$")

    def __init__(self, target_words=16, max_words=18, timeout_seconds=1.8,
                 timeout_min_words=12, min_words=6):
        self.target_words = target_words
        self.max_words = max_words
        self.timeout_seconds = timeout_seconds
        self.timeout_min_words = timeout_min_words
        self.min_words = min_words
        self.started_at = None
        self.committed_words = 0

    @staticmethod
    def _words(text):
        return re.findall(r"\S+", " ".join((text or "").split()))

    def _cut_count(self, words, timed_out=False, final=False):
        if not words:
            return 0
        for index, word in enumerate(words[:self.max_words], start=1):
            if index >= self.min_words and self._END.search(word):
                return index
        if len(words) >= self.max_words:
            lower = max(self.min_words, self.target_words - 4)
            for index in range(min(self.max_words, len(words)), lower - 1, -1):
                if self._SOFT.search(words[index - 1]):
                    return index
            return min(self.target_words, len(words))
        if timed_out and len(words) >= self.timeout_min_words:
            return len(words)
        if final:
            return len(words)
        return 0

    def observe(self, text, stable_text="", is_final=False, now=None):
        now = time.monotonic() if now is None else now
        full_words = self._words(text)
        if self.started_at is None:
            self.started_at = now

        if is_final:
            stable_words = full_words
        else:
            stable_count = len(self._words(stable_text))
            # StablePrefixTracker intentionally strips trailing punctuation.
            # Reuse the same stable word count from the full hypothesis so a
            # confirmed sentence-ending token still carries its punctuation.
            stable_words = full_words[:stable_count]
        available_stable = stable_words[self.committed_words:]
        finalized = []
        timed_out = now - self.started_at >= self.timeout_seconds

        while available_stable:
            cut = self._cut_count(
                available_stable,
                timed_out=timed_out,
                final=is_final,
            )
            if not cut:
                break
            finalized.append(" ".join(available_stable[:cut]))
            self.committed_words += cut
            available_stable = stable_words[self.committed_words:]
            self.started_at = now
            timed_out = False
            if not is_final:
                break

        remainder = " ".join(full_words[self.committed_words:])
        if is_final:
            self.reset()
        return finalized, remainder

    def reset(self):
        self.started_at = None
        self.committed_words = 0
