import sys
from pathlib import Path

TARGET_SAMPLE_RATE = 16000  # what the Whisper models expect; captured audio is resampled to this
FRAME_MS = 30


def _app_base() -> Path:
    """Directory containing the app: the exe's folder when frozen, this file's folder otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


MODELS_DIR = _app_base() / "models"  # downloaded faster-whisper models are cached here, not
                                      # in the user's global HF cache, so they travel with the app
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Each preset maps to (partial_model, final_model): a fast model for low-latency interim
# captions, and a more accurate model for the finalized line.
MODEL_PRESETS = {
    "tiny.en": ("tiny.en", "tiny.en"),
    "base.en": ("tiny.en", "base.en"),
    "small.en": ("tiny.en", "small.en"),
    "medium.en": ("base.en", "medium.en"),
}
DEFAULT_MODEL = "small.en"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

SILENCE_RMS_THRESHOLD = 0.015
FINALIZE_SILENCE_MS = 700
MAX_UTTERANCE_S = 20
PARTIAL_INTERVAL_S = 1.0
PARTIAL_WINDOW_S = 5.0
MAX_QUEUE_LAG_S = 3.0  # drop older buffered audio beyond this to avoid captions drifting behind real time

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 160
MIN_WIDTH = 300
MIN_HEIGHT = 120

DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 36
