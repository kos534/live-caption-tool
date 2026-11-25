import sys
from pathlib import Path

APP_VERSION = "1.0.0"  # shown in the title strip and written to the log

TARGET_SAMPLE_RATE = 16000  # what the Whisper models expect; captured audio is resampled to this
FRAME_MS = 30


def _app_base() -> Path:
    """Directory containing the app: the exe's folder when frozen, this file's folder otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _app_base()
# Bundled read-only assets (logo/icons): inside _internal when frozen, next to this file otherwise.
ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
MODELS_DIR = APP_DIR / "models"  # downloaded faster-whisper models are cached here, not
                                      # in the user's global HF cache, so they travel with the app
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Each preset maps to (partial_model, final_model): a fast model for low-latency interim
# captions, and a more accurate model for the finalized line.
#
# "large-v3" is OpenAI's most accurate Whisper release. There's no English-only (.en) large
# model, so English is forced via LANGUAGE below. Its partial model, distil-large-v3, is a
# distilled English-only large-v3: much faster, close to large-v3 accuracy on English.
MODEL_PRESETS = {
    "tiny.en": ("tiny.en", "tiny.en"),
    "base.en": ("tiny.en", "base.en"),
    "small.en": ("tiny.en", "small.en"),
    "medium.en": ("base.en", "medium.en"),
    "large-v3": ("distil-large-v3", "large-v3"),
}
DEFAULT_MODEL = "large-v3"
LANGUAGE = "en"  # always decode as English (skips language detection, avoids non-English output)

# "auto" uses an NVIDIA GPU (CUDA, float16) when available and falls back to CPU (int8).
DEVICE = "auto"
GPU_COMPUTE_TYPE = "float16"
CPU_COMPUTE_TYPE = "int8"

SILENCE_RMS_THRESHOLD = 0.015
FINALIZE_SILENCE_MS = 700
MAX_UTTERANCE_S = 20
# Live preview of the in-progress utterance, per device. On GPU the whole utterance so far is
# re-transcribed (None = no window limit) every 0.5s, so the line grows smoothly like Windows Live
# Caption. On CPU only the last 5s is previewed, once a second, so it keeps up with real time.
PARTIAL_INTERVAL_S = {"cuda": 0.5, "cpu": 1.0}
PARTIAL_WINDOW_S = {"cuda": None, "cpu": 5.0}
MAX_QUEUE_LAG_S = 3.0  # drop older buffered audio beyond this to avoid captions drifting behind real time

WINDOW_WIDTH = 680
WINDOW_HEIGHT = 180
MIN_WIDTH = 300
MIN_HEIGHT = 130

DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 36
