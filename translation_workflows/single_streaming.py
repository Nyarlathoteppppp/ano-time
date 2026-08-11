"""Streaming compatibility isolated to the portable Single Model workflow."""

import threading


_UNSUPPORTED_STREAM_MARKERS = (
    "stream is not supported",
    "streaming is not supported",
    "streaming is unsupported",
    "streaming not supported",
    "does not support streaming",
    "doesn't support streaming",
    "unsupported stream",
    "stream unsupported",
    "stream must be false",
)


def is_streaming_unsupported(exc):
    message = str(exc or "").casefold()
    if any(marker in message for marker in _UNSUPPORTED_STREAM_MARKERS):
        return True
    return "stream" in message and any(
        marker in message
        for marker in ("not support", "unsupported", "must be false", "non-stream")
    )


class SingleModelStreamingAdapter:
    """Use streaming when available and remember a confirmed incompatibility."""

    def __init__(self, translator, mode="auto"):
        self.translator = translator
        normalized = str(mode or "auto").casefold()
        self.mode = normalized if normalized in {"auto", "on", "off"} else "auto"
        self._streaming_supported = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.translator, name)

    def translate(self, *args, **kwargs):
        on_update = kwargs.get("on_update")
        if on_update is None or self.mode == "on":
            return self.translator.translate(*args, **kwargs)
        with self._lock:
            supported = self._streaming_supported
        if self.mode == "off" or supported is False:
            non_streaming = dict(kwargs)
            non_streaming.pop("on_update", None)
            return self.translator.translate(*args, **non_streaming)

        try:
            result = self.translator.translate(*args, **kwargs)
        except Exception as exc:
            if not is_streaming_unsupported(exc):
                raise
            with self._lock:
                self._streaming_supported = False
            non_streaming = dict(kwargs)
            non_streaming.pop("on_update", None)
            return self.translator.translate(*args, **non_streaming)
        else:
            with self._lock:
                self._streaming_supported = True
            return result
