"""
Load/save user settings for the caption overlay (width, height, font size).
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_NAME = "live-caption-config.json"
DEFAULTS = {
    "caption_width": 560,
    "caption_height": 180,
    "font_size": 18,
}


def _config_path() -> Path:
    return Path(__file__).resolve().parent / CONFIG_NAME


def load_settings() -> dict:
    """Return settings dict (caption_width, caption_height, font_size)."""
    path = _config_path()
    if not path.is_file():
        return DEFAULTS.copy()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = DEFAULTS.copy()
        for k in DEFAULTS:
            if k in data and isinstance(data[k], (int, float)):
                out[k] = max(1, int(data[k]))
        return out
    except Exception:
        return DEFAULTS.copy()


def save_settings(settings: dict) -> None:
    """Persist settings to config file."""
    path = _config_path()
    data = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
