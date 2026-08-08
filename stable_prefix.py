import re
import time
import unicodedata


_WORD_RE = re.compile(r"\b[^\W_]+(?:[\u2019'-][^\W_]+)*\b", re.UNICODE)


def _normalise_word(word):
    return unicodedata.normalize("NFKC", word).replace("\u2019", "'").casefold()


class StablePrefixTracker:
    """Find a monotonic word prefix shared by hypotheses a short time apart."""

    def __init__(self, agreement_window=0.25, min_growth_words=3):
        self.agreement_window = max(0.0, float(agreement_window))
        self.min_growth_words = max(1, int(min_growth_words))
        self._reference = None
        self._reference_at = None
        self._stable_words = 0
        self.stable_text = ""

    @staticmethod
    def _tokens(text):
        return [
            (_normalise_word(match.group(0)), match.end())
            for match in _WORD_RE.finditer(text)
        ]

    def observe(self, text, now=None):
        """Return a newly extended stable prefix, otherwise ``None``.

        The reference snapshot is intentionally sampled at ``agreement_window``
        intervals. Rapid hypotheses remain visible and translatable, while the
        stable marker only advances when words survive across the window.
        """
        now = time.monotonic() if now is None else float(now)
        tokens = self._tokens(text)
        if not tokens:
            return None

        if self._reference is None:
            self._reference = tokens
            self._reference_at = now
            return None

        if now - self._reference_at < self.agreement_window:
            return None

        reference = self._reference
        self._reference = tokens
        self._reference_at = now

        common_words = 0
        for (old_word, _), (new_word, _) in zip(reference, tokens):
            if old_word != new_word:
                break
            common_words += 1

        if common_words - self._stable_words < self.min_growth_words:
            return None

        # Stable text is monotonic. A later Apple hypothesis may still revise a
        # committed word; the native final result remains authoritative.
        self._stable_words = common_words
        end = tokens[common_words - 1][1]
        self.stable_text = text[:end].strip()
        return self.stable_text

