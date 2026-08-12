"""Small, provider-neutral context budgets for remote translation requests.

This module deliberately owns only immutable request context.  It does not
know about Qt, executors, providers, prompts, or the live subtitle pipeline.
Keeping that boundary narrow makes context changes unable to delay Apple's
local draft path.
"""

from dataclasses import dataclass
import re
from typing import Iterable


def estimate_tokens(text: str) -> int:
    """Fast conservative token estimate used only to cap optional context."""
    text = str(text or "")
    if not text:
        return 0
    ascii_count = sum(1 for character in text if ord(character) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def _normalise(text: str) -> str:
    return " ".join(str(text or "").split())


def _history_items(history: Iterable[str] | str, limit: int) -> list[str]:
    if isinstance(history, str):
        items = history.splitlines()
    else:
        items = list(history or ())
    return [item for item in (_normalise(value) for value in items) if item][-limit:]


def _trim_at_word_boundaries(text: str, budget: int) -> tuple[str, bool]:
    """Keep an intelligible head and tail rather than cutting formula text raw."""
    text = _normalise(text)
    if not text or budget <= 0:
        return "", bool(text)
    if estimate_tokens(text) <= budget:
        return text, False

    words = re.findall(r"\S+", text)
    if len(words) < 3:
        # Chinese drafts may be a single whitespace-free run.  It still must
        # obey the optional-context budget; keep its readable ends rather than
        # allowing an arbitrarily large request through.
        allowance = max(1, budget - estimate_tokens("…"))
        head_size = max(1, allowance // 2)
        tail_size = max(0, allowance - head_size)
        compact = text[:head_size]
        if tail_size and len(text) > head_size:
            compact += "…" + text[-tail_size:]
        return compact, True
    head: list[str] = []
    tail: list[str] = []
    left = 0
    right = len(words) - 1
    # The marker costs a few tokens.  Alternating preserves both antecedent
    # and conclusion for an unusually long finalized sentence.
    remaining = max(1, budget - estimate_tokens(" … "))
    take_head = True
    while left <= right and remaining > 0:
        candidate = words[left] if take_head else words[right]
        cost = estimate_tokens(candidate)
        if cost > remaining and (head or tail):
            break
        if take_head:
            head.append(candidate)
            left += 1
        else:
            tail.insert(0, candidate)
            right -= 1
        remaining -= cost
        take_head = not take_head
    compact = " ".join(head + (["…"] if left <= right else []) + tail)
    return compact, True


@dataclass(frozen=True, slots=True)
class TranslationContext:
    """Immutable optional inputs captured when a remote request is triggered."""

    context_text: str = ""
    previous_preview: str = ""
    live_hint: str = ""
    estimated_tokens: int = 0
    truncated: bool = False


class ContextPolicy:
    """One bounded policy shared by preview, final, and bridge requests."""

    PREVIEW_BUDGET = 300
    FINAL_BUDGET = 800
    BRIDGE_BUDGET = 120

    def first_preview(self, history, *, live_hint="") -> TranslationContext:
        return self._build(
            history,
            history_limit=1,
            total_budget=self.PREVIEW_BUDGET,
            live_hint=live_hint,
        )

    def continuing_preview(
        self, history, *, previous_preview="", live_hint=""
    ) -> TranslationContext:
        return self._build(
            history,
            history_limit=1,
            total_budget=self.PREVIEW_BUDGET,
            previous_preview=previous_preview,
            live_hint=live_hint,
        )

    def final(self, history, *, previous_preview="", live_hint="", history_limit=3):
        return self._build(
            history,
            history_limit=max(0, int(history_limit)),
            total_budget=self.FINAL_BUDGET,
            previous_preview=previous_preview,
            live_hint=live_hint,
        )

    def bridge(self, *, live_hint="") -> TranslationContext:
        # Bridge is explicitly history-free.  Its provider receives the
        # manually selected course topic through the existing domain prompt.
        hint, truncated = _trim_at_word_boundaries(
            _normalise(live_hint), self.BRIDGE_BUDGET
        )
        return TranslationContext(
            live_hint=hint,
            estimated_tokens=estimate_tokens(hint),
            truncated=truncated,
        )

    def _build(
        self,
        history,
        *,
        history_limit: int,
        total_budget: int,
        previous_preview="",
        live_hint="",
    ) -> TranslationContext:
        previous_preview = _normalise(previous_preview)
        live_hint = _normalise(live_hint)
        items = _history_items(history, history_limit)
        truncated = False

        # Preview continuity is useful but cannot consume the whole request.
        # First retain the current draft and live hint, then fill remaining
        # capacity with newest complete finalized sentences.
        preview_budget = min(
            estimate_tokens(previous_preview),
            max(0, total_budget // 2),
        )
        previous_preview, preview_cut = _trim_at_word_boundaries(
            previous_preview, preview_budget
        )
        truncated |= preview_cut

        hint_budget = min(
            estimate_tokens(live_hint),
            max(0, total_budget // 5),
        )
        live_hint, hint_cut = _trim_at_word_boundaries(live_hint, hint_budget)
        truncated |= hint_cut

        remaining = max(
            0,
            total_budget - estimate_tokens(previous_preview) - estimate_tokens(live_hint),
        )
        kept_reversed: list[str] = []
        for item in reversed(items):
            compact, cut = _trim_at_word_boundaries(item, remaining)
            if not compact:
                truncated |= bool(item)
                break
            kept_reversed.append(compact)
            truncated |= cut
            remaining -= estimate_tokens(compact)
            if cut or remaining <= 0:
                if len(kept_reversed) < len(items):
                    truncated = True
                break
        context_text = "\n".join(reversed(kept_reversed))
        total = (
            estimate_tokens(context_text)
            + estimate_tokens(previous_preview)
            + estimate_tokens(live_hint)
        )
        return TranslationContext(
            context_text=context_text,
            previous_preview=previous_preview,
            live_hint=live_hint,
            estimated_tokens=total,
            truncated=truncated,
        )
