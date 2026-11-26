import os
import sys
from pathlib import Path

APP_VERSION = "2.0.0"  # shown in the title strip and written to the log

# Start with the caption window hidden from screen sharing/recording (toggle in the ⚙ panel).
HIDE_FROM_SCREEN_SHARE = False

TARGET_SAMPLE_RATE = 16000  # what the Whisper models expect; captured audio is resampled to this
FRAME_MS = 30


def _app_base() -> Path:
    """Directory containing the app: the exe's folder when frozen, this file's folder otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _data_base() -> Path:
    """Per-user writable folder: %LOCALAPPDATA%\\Wonuva Live Caption.

    The app may be installed somewhere read-only (e.g. Program Files), so settings, the log and
    downloaded models never go next to the exe.
    """
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "Wonuva Live Caption"


APP_DIR = _app_base()
DATA_DIR = _data_base()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# Bundled read-only assets (logo/icons): inside _internal when frozen, next to this file otherwise.
ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
# Speech models are downloaded here on first run (~4.4 GB for large-v3).
MODELS_DIR = DATA_DIR / "models"
# Where models are looked for, in order: the download folder, then a models\ folder next to the
# app (a source checkout, or a build that ships the models for offline use).
MODEL_SEARCH_DIRS = [MODELS_DIR, APP_DIR / "models"]
LOG_FILE = DATA_DIR / "livecaption.log"

# Wonuva account: the app is locked until the user signs in (OAuth 2.0 + PKCE in the browser;
# server side: docs/WONUVA_AUTH_API.md). The session is saved encrypted in ACCOUNT_FILE.
WONUVA_URL = "https://wonuva.com"  # serves /oauth/authorize, /oauth/token, /oauth/revoke, /api/me, /signup
AUTH_CLIENT_ID = "live-caption"
ACCOUNT_FILE = DATA_DIR / "account.json"
AUTH_OFFLINE_GRACE_DAYS = 7  # keep working this long since the last successful check if Wonuva is unreachable
AUTH_RECHECK_HOURS = 6  # re-check the session while the app runs (a revoked session locks the app)
# Sign-in is required unless the app was built with "build_exe.bat nosignin", which writes
# build_info.py (for builds made before the Wonuva sign-in endpoints are live).
try:
    from build_info import REQUIRE_SIGN_IN
except ImportError:
    REQUIRE_SIGN_IN = True

# Update check: on startup the app fetches this small JSON file and shows an "Update" button in
# the title strip if it names a newer version. Format: see installer\version.json. "" = off.
UPDATE_URL = "https://wonuva.com/downloads/live-caption/version.json"

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

# ⚙ Settings (personal info, resume, job description, OpenAI API key) are saved here.
SETTINGS_FILE = DATA_DIR / "settings.json"
# Settings saved next to the app by v2.0.0 are moved here on first run (see main.py).
LEGACY_SETTINGS_FILE = APP_DIR / "settings.json"

# Answer button: sends the captions since the previous click to OpenAI and shows the reply.
# The API key comes from ⚙ Settings → Security, else the OPENAI_API_KEY environment variable,
# else this file next to the app (first line = the key). Only text is sent, never audio.
OPENAI_MODEL = "gpt-4.1-mini"
OPENAI_KEY_FILE = DATA_DIR / "openai_api_key.txt"
ANSWER_HISTORY_TURNS = 3  # earlier transcript segments sent along for context (0 = none)
ANSWER_MAX_TOKENS = 600
# Let the model search the web (OpenAI's web_search tool) when an answer needs facts it doesn't
# have, e.g. what the interviewer's company does. It decides per question; searching adds a few
# seconds and OpenAI bills each search call. "low" | "medium" | "high" = how much it reads.
ANSWER_WEB_SEARCH = True
WEB_SEARCH_CONTEXT = "low"

# Initial window size, shared by the captions and the ⚙ Settings view (which fills the window
# and scrolls when it's resized smaller).
WINDOW_WIDTH = 680
WINDOW_HEIGHT = 600
MIN_WIDTH = 300
MIN_HEIGHT = 170

DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 36
