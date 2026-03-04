"""
Vosk-based streaming caption engine.
Consumes raw PCM audio and produces partial + final text for the overlay.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from audio_capture import SAMPLE_RATE, capture_audio
from caption_utils import format_final, normalize_caption, should_show_partial
from config import get_app_base


def find_model_dir() -> Path | None:
    """Locate Vosk model under app dir (next to exe when frozen, else project root)."""
    base = get_app_base()
    for name in ("models", "model"):
        d = base / name
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir() and (sub / "am").is_dir():
                    return sub
            # Allow single model dir: models/vosk-model-small-en-us-0.15
            if (d / "am").is_dir():
                return d
    return None


def load_model(model_path: str | Path | None = None) -> "Model":
    from vosk import Model
    path = model_path or find_model_dir()
    if not path or not Path(path).is_dir():
        raise FileNotFoundError(
            "Vosk model not found. Download a model and put it in the 'models' folder.\n"
            "Example: https://alphacephei.com/vosk/models (e.g. vosk-model-small-en-us-0.15)"
        )
    return Model(str(path))


def run_caption_engine(
    model_path: str | Path | None,
    device_index: int | None,
    *,
    on_partial: Callable[[str], None],
    on_final: Callable[[str], None],
    stop_event: Callable[[], bool],
    use_loopback: bool = False,
) -> None:
    """
    Run audio capture and Vosk recognition in a background thread.
    Calls on_partial with interim text and on_final with stable phrases.
    """
    model = load_model(model_path)
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(True)

    def on_audio_data(data: bytes) -> None:
        if stop_event():
            return
        if rec.AcceptWaveform(data):
            result = rec.Result()
            if result:
                obj = json.loads(result)
                raw = (obj.get("text") or "").strip()
                text = format_final(raw)
                if text:
                    on_final(text)
        else:
            partial = rec.PartialResult()
            if partial:
                obj = json.loads(partial)
                raw = (obj.get("partial") or "").strip()
                if raw and should_show_partial(raw):
                    on_partial(normalize_caption(raw))

    def run() -> None:
        capture_audio(
            device_index,
            on_data=on_audio_data,
            stop_event=stop_event,
            use_pyaudiowpatch=use_loopback,
            is_loopback=use_loopback,
        )
        # Flush final result
        try:
            final = rec.FinalResult()
            if final:
                obj = json.loads(final)
                raw = (obj.get("text") or "").strip()
                text = format_final(raw)
                if text:
                    on_final(text)
        except Exception:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
