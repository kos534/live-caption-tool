"""
faster-whisper model lifecycle and the two transcription passes used by the
streaming caption engine: a fast low-latency pass for interim/partial text,
and a higher-quality pass for finalized utterances.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from config import DEFAULTS, get_app_base

if TYPE_CHECKING:
    import numpy as np
    from faster_whisper import WhisperModel

DEFAULT_MODEL_SIZE = DEFAULTS["model_size"]


def models_dir() -> Path:
    """Where newly auto-downloaded models are saved: next to the exe/script."""
    return get_app_base() / "models"


def _bundled_models_dir() -> Path | None:
    """
    Where PyInstaller onedir builds actually put bundled data files.
    Since PyInstaller 6.x, COLLECT places datas under an '_internal' folder
    (sys._MEIPASS) rather than next to the exe itself, so a model bundled via
    the spec's `datas` entries lives here, not under models_dir().
    """
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) / "models" if meipass else None


def find_local_model_dir(model_size: str) -> Path | None:
    """
    Return a pre-baked local model folder if present: checks a PyInstaller-
    bundled copy first, then the models/ folder next to the exe/script (where
    download_model.py and prior auto-downloads save).
    """
    name = f"faster-whisper-{model_size}"
    bundled = _bundled_models_dir()
    candidates = ([bundled / name] if bundled else []) + [models_dir() / name]
    for d in candidates:
        if d.is_dir() and any(d.iterdir()):
            return d
    return None


def load_model(model_size: str = DEFAULT_MODEL_SIZE, download_root: Path | str | None = None) -> "WhisperModel":
    """
    Load a faster-whisper model, preferring a local pre-baked copy, otherwise
    letting faster-whisper auto-download (and cache) it from Hugging Face.
    Falls back to CPU int8 if GPU auto-detection fails on the host machine.
    """
    from faster_whisper import WhisperModel

    local = find_local_model_dir(model_size)
    source = str(local) if local else model_size
    root = str(download_root) if download_root else str(models_dir())
    try:
        return WhisperModel(source, device="auto", compute_type="auto", download_root=root)
    except Exception:
        return WhisperModel(source, device="cpu", compute_type="int8", download_root=root)


def pcm16_to_float32(audio_bytes: bytes) -> "np.ndarray":
    import numpy as np

    samples = np.frombuffer(audio_bytes, dtype="<i2")
    return (samples.astype(np.float32) / 32768.0).copy()


def transcribe_partial(model: "WhisperModel", audio: "np.ndarray") -> str:
    """Fast, low-latency pass for interim captions shown while speech is ongoing."""
    if audio.size == 0:
        return ""
    segments, _info = model.transcribe(
        audio,
        beam_size=1,
        best_of=1,
        condition_on_previous_text=False,
        vad_filter=False,
        without_timestamps=True,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_final(
    model: "WhisperModel",
    audio: "np.ndarray",
    previous_text: str | None = None,
) -> str:
    """
    Higher-quality pass run once an utterance has been endpointed. Uses a
    larger beam, faster-whisper's own VAD filter as an extra hallucination
    guard, and drops low-confidence/likely-silence segments.
    """
    if audio.size == 0:
        return ""
    segments, _info = model.transcribe(
        audio,
        beam_size=5,
        condition_on_previous_text=bool(previous_text),
        initial_prompt=previous_text or None,
        vad_filter=True,
        without_timestamps=True,
    )
    parts: list[str] = []
    for seg in segments:
        if seg.no_speech_prob is not None and seg.no_speech_prob > 0.6:
            continue
        if seg.avg_logprob is not None and seg.avg_logprob < -1.5:
            continue
        text = seg.text.strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()
