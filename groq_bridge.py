import re
import threading
import time
from collections import deque


class GroqBridgeGate:
    """Cheap local admission control for optional Groq bridge requests."""

    _FILLER_PHRASES = {
        "all right",
        "okay",
        "okay then",
        "okay thank you very much",
        "right",
        "so",
        "thank you",
        "thank you very much",
        "thanks",
        "uh huh",
        "you know",
        "you know what i mean",
    }

    def __init__(self, max_per_minute=15, duplicate_window=30.0, clock=None):
        self.max_per_minute = max_per_minute
        self.duplicate_window = duplicate_window
        self._clock = clock or time.monotonic
        self._attempts = deque()
        self._recent_text = {}
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(text):
        return " ".join(re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", text.casefold()))

    def allow(self, text):
        normalized = self._normalize(text)
        words = normalized.split()
        if len(words) <= 3:
            return False, "segment has 3 words or fewer"
        if not any(character.isalpha() for character in normalized):
            return False, "segment contains no words"
        if normalized in self._FILLER_PHRASES:
            return False, "low-value filler phrase"

        now = self._clock()
        with self._lock:
            while self._attempts and now - self._attempts[0] >= 60:
                self._attempts.popleft()
            expired = [
                item
                for item, seen_at in self._recent_text.items()
                if now - seen_at >= self.duplicate_window
            ]
            for item in expired:
                self._recent_text.pop(item, None)

            if normalized in self._recent_text:
                return False, "duplicate finalized segment within 30 seconds"
            if len(self._attempts) >= self.max_per_minute:
                return False, "15 requests/minute soft budget reached"

            # Reserve before the request starts so concurrent finalized segments
            # cannot exceed the soft budget or dispatch duplicates.
            self._attempts.append(now)
            self._recent_text[normalized] = now
            return True, "accepted"
