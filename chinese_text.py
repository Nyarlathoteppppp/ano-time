"""Chinese subtitle output normalization.

Providers occasionally ignore a Simplified-Chinese instruction and return
Traditional characters. Normalizing at the shared subtitle-store boundary
keeps every translation lane consistent without adding a network request or
touching ASR source text.
"""

from __future__ import annotations

from functools import lru_cache


def is_simplified_chinese_target(target_lang):
    """Return whether a configured target explicitly asks for Simplified Chinese."""
    normalized = str(target_lang or "").strip().lower().replace("_", "-")
    return normalized in {
        "chinese",
        "zh",
        "zh-cn",
        "zh-hans",
        "simplified chinese",
    }


@lru_cache(maxsize=1)
def _traditional_to_simplified():
    try:
        from opencc import OpenCC

        return OpenCC("t2s")
    except Exception:
        # Startup stays usable with older local environments. New installs get
        # the dependency from requirements.txt.
        return None


def force_simplified_chinese(text):
    """Convert translated text to Simplified Chinese when the converter exists."""
    value = str(text or "")
    converter = _traditional_to_simplified()
    return converter.convert(value) if converter is not None else value
