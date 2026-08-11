"""Pure trigger policy for incremental source hypotheses."""

import time


class PreviewTriggerPolicy:
    """Trigger on useful source growth without repeating identical text."""

    def __init__(
        self,
        first_words=6,
        growth_words=6,
        minimum_interval=0.6,
        minimum_words=4,
    ):
        self.first_words = int(first_words)
        self.growth_words = int(growth_words)
        self.minimum_interval = float(minimum_interval)
        self.minimum_words = int(minimum_words)
        self.reset()

    def reset(self):
        self._segment_id = None
        self._last_word_count = 0
        self._last_source_text = ""
        self._last_requested_at = float("-inf")

    def should_request(self, segment_id, source_text, now=None):
        now = time.monotonic() if now is None else float(now)
        source_text = " ".join(str(source_text or "").split())
        word_count = len(source_text.split())
        if int(segment_id) != self._segment_id:
            self._segment_id = int(segment_id)
            self._last_word_count = 0
            self._last_source_text = ""
            self._last_requested_at = float("-inf")
        elif self._last_source_text and not source_text.startswith(
            self._last_source_text
        ):
            # ASR revised an already requested prefix. Treat the correction as
            # a fresh hypothesis so it does not wait for artificial word growth.
            self._last_word_count = 0
            self._last_source_text = ""
            self._last_requested_at = float("-inf")
        if source_text == self._last_source_text or word_count < self.minimum_words:
            return False
        punctuation = source_text.endswith(
            (".", "?", "!", ";", ":", "。", "？", "！", "；", "：")
        )
        enough_growth = (
            word_count >= self.first_words
            if self._last_word_count == 0
            else word_count - self._last_word_count >= self.growth_words
        )
        if not punctuation and not enough_growth:
            return False
        if now - self._last_requested_at < self.minimum_interval:
            return False
        self._last_word_count = word_count
        self._last_source_text = source_text
        self._last_requested_at = now
        return True
