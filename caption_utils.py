"""
Text normalization and formatting for live captions.
Makes recognized text cleaner and more readable.
"""
from __future__ import annotations


def normalize_caption(text: str) -> str:
    """Collapse whitespace and strip. Keep single spaces between words."""
    if not text or not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip()


def capitalize_first(text: str) -> str:
    """Capitalize first character; leave the rest unchanged."""
    text = normalize_caption(text)
    if not text:
        return ""
    return text[0].upper() + text[1:]


def is_likely_noise_partial(text: str) -> bool:
    """True if partial is too short or looks like recognition noise."""
    t = normalize_caption(text)
    if len(t) < 2:
        return True
    if len(t) == 2 and t.isalpha() and t.lower() not in ("i", "a", "oh", "um", "uh", "ok", "go", "to", "no", "so"):
        return True
    return False


def should_show_partial(text: str, min_words: int = 1, min_chars: int = 3) -> bool:
    """Only show partial if it has enough content to be useful."""
    t = normalize_caption(text)
    if not t:
        return False
    if is_likely_noise_partial(t):
        return False
    if len(t) < min_chars:
        return False
    return True


def format_final(text: str) -> str:
    """Normalize and capitalize first letter for final caption segment."""
    t = normalize_caption(text)
    if not t:
        return ""
    return capitalize_first(t)
