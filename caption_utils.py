"""
Text normalization helpers for live captions.
"""
from __future__ import annotations


def normalize_caption(text: str) -> str:
    """Collapse whitespace and strip. Keep single spaces between words."""
    if not text or not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip()


def is_blank(text: str) -> bool:
    """True if text has no visible content once normalized."""
    return not normalize_caption(text)
