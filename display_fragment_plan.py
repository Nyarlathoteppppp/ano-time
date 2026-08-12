"""Stable, display-only fragmentation for the native notch projection."""

from __future__ import annotations

from dataclasses import dataclass


def _normalise(text):
    return " ".join(str(text or "").split())


def _append_text(left, right):
    """Join a suffix exactly as it appeared in the newest ASR hypothesis."""
    left = str(left or "")
    right = str(right or "")
    if not left:
        return right.lstrip()
    # ``right`` is sliced from the normalised full source. It already carries
    # a separating space for English word growth, and no separator for CJK.
    # Adding one here would create a fake wrap boundary.
    return left + right


@dataclass(slots=True)
class _FragmentState:
    source_text: str
    parts: tuple[str, ...]


class DisplayFragmentPlan:
    """Retain stable display cuts while one ASR segment only grows.

    This is deliberately a visual cache: it holds at most the cues currently
    eligible for the notch. The semantic transcript remains untouched and the
    caller supplies its own width-aware splitter.
    """

    def __init__(self):
        self._states: dict[int, _FragmentState] = {}

    def project(self, segment_id, text, splitter):
        """Return fragments, preserving completed earlier fragments on append."""
        segment_id = int(segment_id)
        source_text = _normalise(text)
        state = self._states.get(segment_id)
        if state is None or not state.source_text:
            return self._replace(segment_id, source_text, splitter)
        if source_text == state.source_text:
            return list(state.parts)
        stable_prefix = "".join(state.parts[:-1])
        if source_text.startswith(state.source_text):
            # Keep completed fragments exactly intact. Re-split only the old
            # tail plus its appended suffix, so a sentence growing by one word
            # does not rebalance every earlier display fragment.
            prefix = list(state.parts[:-1])
            suffix = source_text[len(state.source_text):]
            tail = _append_text(state.parts[-1], suffix)
            tail_parts = [str(part) for part in splitter(tail) if str(part)]
            parts = tuple(prefix + tail_parts) or (source_text,)
            self._states[segment_id] = _FragmentState(source_text, parts)
            return list(parts)
        if stable_prefix and source_text.startswith(stable_prefix):
            # Providers often revise only the active tail. Completed fragments
            # still exactly match, so retain those visual rows and re-split the
            # changed tail only. Corrected wording is never held back.
            tail = source_text[len(stable_prefix):]
            tail_parts = [str(part) for part in splitter(tail) if str(part)]
            parts = tuple(list(state.parts[:-1]) + tail_parts) or (source_text,)
            self._states[segment_id] = _FragmentState(source_text, parts)
            return list(parts)
        # A correction or a shorter model revision is not append-only. Render
        # the current text faithfully; layout hysteresis handles its later
        # shrink without preserving incorrect deleted wording.
        return self._replace(segment_id, source_text, splitter)

    def retain(self, segment_ids):
        keep = {int(segment_id) for segment_id in segment_ids}
        self._states = {
            segment_id: state
            for segment_id, state in self._states.items()
            if segment_id in keep
        }

    def clear(self):
        self._states.clear()

    def _replace(self, segment_id, source_text, splitter):
        parts = tuple(str(part) for part in splitter(source_text) if str(part))
        if not parts:
            parts = (source_text,)
        self._states[segment_id] = _FragmentState(source_text, parts)
        return list(parts)
