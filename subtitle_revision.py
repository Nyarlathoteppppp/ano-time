"""Pure display-side planning for local subtitle revisions."""

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class RevisionSpan:
    text: str
    changed: bool


@dataclass(frozen=True, slots=True)
class SubtitleRevision:
    old_text: str
    new_text: str
    spans: tuple[RevisionSpan, ...]
    preserved_characters: int

    @property
    def preserved_ratio(self):
        return self.preserved_characters / max(1, len(self.new_text))


class SubtitleRevisionPlanner:
    """Keep equal character runs stable and mark only inserted/replaced runs."""

    @staticmethod
    def plan(old_text, new_text):
        old_text = str(old_text or "")
        new_text = str(new_text or "")
        if old_text == new_text:
            spans = (RevisionSpan(new_text, False),) if new_text else ()
            return SubtitleRevision(
                old_text, new_text, spans, len(new_text)
            )
        if not old_text:
            spans = (RevisionSpan(new_text, False),) if new_text else ()
            return SubtitleRevision(old_text, new_text, spans, 0)

        matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
        spans = []
        preserved = 0
        for tag, _old_start, _old_end, new_start, new_end in matcher.get_opcodes():
            if tag == "delete" or new_start == new_end:
                continue
            text = new_text[new_start:new_end]
            changed = tag != "equal"
            if not changed:
                preserved += len(text)
            if spans and spans[-1].changed == changed:
                previous = spans.pop()
                text = previous.text + text
            spans.append(RevisionSpan(text, changed))
        return SubtitleRevision(old_text, new_text, tuple(spans), preserved)
