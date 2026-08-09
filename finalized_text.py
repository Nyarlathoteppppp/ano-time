import re


_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?")
_ONE_WORD_REPEATS = {
    "a", "an", "and", "but", "for", "if", "in", "informal", "into",
    "of", "on", "or", "so", "the", "to", "um", "uh", "we", "you",
}
_SHORT_INTERJECTIONS = {
    "okay", "ok", "yes", "yeah", "no", "right", "thanks", "thank you",
}


def clean_finalized_text(text):
    """Clean only conservative ASR repetitions in finalized display text."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""

    # Exact repeated two-word phrases are normally streaming-ASR duplication,
    # e.g. "if you if you". Keep emphasis such as "very, very" untouched.
    phrase_pattern = re.compile(
        r"(?<!\w)([A-Za-z]+\s+[A-Za-z]+)([,.]?\s+)\1(?!\w)",
        re.IGNORECASE,
    )
    cleaned = phrase_pattern.sub(r"\1 ", cleaned)

    for word in _ONE_WORD_REPEATS:
        pattern = re.compile(
            rf"(?<!\w)({re.escape(word)})([,.]?\s+)\1(?!\w)",
            re.IGNORECASE,
        )
        cleaned = pattern.sub(r"\1 ", cleaned)
    return " ".join(cleaned.split())


def should_request_remote(text):
    """Keep short/noise finals visible locally without spending remote quota."""
    words = _WORD.findall(text or "")
    if len(words) <= 3:
        return False
    normalized = " ".join(word.casefold() for word in words)
    return normalized not in _SHORT_INTERJECTIONS


def is_meaningful_final(text):
    """Reject empty or punctuation-only native finals."""
    return bool(_WORD.search(text or ""))
