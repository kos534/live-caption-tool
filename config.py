"""
Load/save user settings for the caption overlay (width, height, font size).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "live-caption-config.json"
DEFAULTS = {
    "caption_width": 560,
    "caption_height": 180,
    "font_size": 18,
    "capture_hotkey": "Ctrl+Q",
    "tesseract_path": "",
    "launch_on_start": [],  # list of paths to start when app starts
}


def get_app_base() -> Path:
    """Directory containing the app (script folder when run from source, exe folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _config_path() -> Path:
    return get_app_base() / CONFIG_NAME


def load_settings() -> dict:
    """Return settings dict (caption_width, caption_height, font_size, capture_hotkey, tesseract_path)."""
    path = _config_path()
    if not path.is_file():
        return DEFAULTS.copy()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return DEFAULTS.copy()
        out = DEFAULTS.copy()
        for k in DEFAULTS:
            if k not in data:
                continue
            if k == "capture_hotkey":
                v = data[k]
                if isinstance(v, str) and v.strip():
                    out[k] = v.strip()
            elif k == "tesseract_path":
                v = data[k]
                if isinstance(v, str):
                    out[k] = (v or "").strip()
            elif k in ("caption_width", "caption_height", "font_size"):
                v = data[k]
                if isinstance(v, (int, float)):
                    out[k] = max(1, int(v))
                elif isinstance(v, str) and v.strip().isdigit():
                    out[k] = max(1, int(v.strip()))
            elif k == "launch_on_start":
                v = data[k]
                if isinstance(v, list):
                    out[k] = [str(x).strip() for x in v if isinstance(x, str) and x.strip()]
        return out
    except Exception:
        return DEFAULTS.copy()


def save_settings(settings: dict) -> None:
    """Persist settings to config file. Merges with existing config so keys not in settings are kept."""
    path = _config_path()
    existing = load_settings()
    data = {}
    for k in DEFAULTS:
        v = settings.get(k) if k in settings else existing.get(k, DEFAULTS[k])
        if k == "capture_hotkey":
            data[k] = (v if isinstance(v, str) and (v or "").strip() else DEFAULTS[k])
        elif k == "tesseract_path":
            data[k] = (v if isinstance(v, str) else DEFAULTS[k]) or ""
        elif k == "launch_on_start":
            data[k] = [str(x).strip() for x in (v if isinstance(v, list) else []) if isinstance(x, str) and x.strip()]
        else:
            data[k] = v
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
