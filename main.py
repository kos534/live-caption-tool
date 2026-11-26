import logging
import queue
import shutil
import sys
import threading

import config
import gpu
import single_instance

# Only one copy at a time: a second launch brings the running window to the front and exits.
# Checked before logging is set up, so a second launch doesn't overwrite the running copy's log.
if not single_instance.acquire():
    from caption_window import APP_NAME  # the running window's title

    single_instance.focus_existing(APP_NAME)
    sys.exit(0)

# The exe has no console, so log to a file in the data folder (overwritten each launch).
logging.basicConfig(
    filename=str(config.LOG_FILE),
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
sys.excepthook = lambda *exc: logging.critical("Unhandled exception", exc_info=exc)
threading.excepthook = lambda a: logging.critical(
    "Unhandled exception in thread %s", a.thread, exc_info=(a.exc_type, a.exc_value, a.exc_traceback)
)

logging.info("Wonuva Live Caption v%s", config.APP_VERSION)
gpu.register_cuda_dlls()  # must run before faster-whisper/CTranslate2 load any CUDA libraries

from answerer import Answerer
from auth import WonuvaAuth
from audio_capture import LoopbackCapture
from caption_window import CaptionWindow
from model_download import APPROX_BYTES, ModelDownloader, missing_models
from transcriber import Transcriber
from screen_share_hide import set_screen_share_hidden
from updater import check_in_background
from user_settings import UserSettings


# `python main.py --fake` (or WonuvaLiveCaption.exe --fake): try the caption window and the Answer
# button without audio. Typed lines appear as live captions, word by word.
FAKE_CAPTIONS = "--fake" in sys.argv[1:]

# Developer switches, only honored when running from source (never in the built exe):
#   --no-auth           skip Wonuva sign-in
#   --auth-url URL      sign in against another server, e.g. dev/mock_wonuva_auth.py
FROM_SOURCE = not getattr(sys, "frozen", False)
SKIP_AUTH = (FROM_SOURCE and "--no-auth" in sys.argv[1:]) or not config.REQUIRE_SIGN_IN
AUTH_URL = config.WONUVA_URL
if FROM_SOURCE and "--auth-url" in sys.argv[1:-1]:
    AUTH_URL = sys.argv[sys.argv.index("--auth-url") + 1]


def migrate_legacy_settings():
    """v2.0.0 kept settings.json next to the app; move it to the per-user data folder once."""
    old, new = config.LEGACY_SETTINGS_FILE, config.SETTINGS_FILE
    if old.exists() and not new.exists() and old.resolve() != new.resolve():
        try:
            shutil.copy2(old, new)
            logging.info("Moved settings from %s to %s", old, new)
        except OSError as exc:
            logging.warning("Couldn't move %s: %s", old, exc)


def main():
    audio_queue = queue.Queue(maxsize=200)
    text_queue = queue.Queue()
    migrate_legacy_settings()
    user_settings = UserSettings.load(config.SETTINGS_FILE)

    window = CaptionWindow(
        width=config.WINDOW_WIDTH,
        height=config.WINDOW_HEIGHT,
        min_width=config.MIN_WIDTH,
        min_height=config.MIN_HEIGHT,
        font_size=config.DEFAULT_FONT_SIZE,
        min_font_size=config.MIN_FONT_SIZE,
        max_font_size=config.MAX_FONT_SIZE,
        assets_dir=config.ASSETS_DIR,
        version=config.APP_VERSION,
        user_settings=user_settings,
        settings_path=config.SETTINGS_FILE,
    )
    window.set_answerer(
        Answerer(
            model=config.OPENAI_MODEL,
            key_file=config.OPENAI_KEY_FILE,
            settings=user_settings,
            history_turns=config.ANSWER_HISTORY_TURNS,
            max_tokens=config.ANSWER_MAX_TOKENS,
            web_search=config.ANSWER_WEB_SEARCH,
            web_search_context=config.WEB_SEARCH_CONTEXT,
        )
    )

    # Hide the window from screen share NOW that it's initialized (if enabled); the ⚙ panel's
    # "Hide from screen share" switch turns it on/off while the app runs.
    hidden = config.HIDE_FROM_SCREEN_SHARE and set_screen_share_hidden(window, True)
    window.set_on_screen_share_toggle(lambda on: set_screen_share_hidden(window, on), hidden)

    # Announce a newer version from the website with an "Update" button in the title strip.
    window.root.after(
        3000,
        lambda: check_in_background(
            config.UPDATE_URL, config.APP_VERSION, lambda info: window.call_soon(lambda: window.show_update(info))
        ),
    )

    state = {"capture": None, "transcriber": None, "downloader": None}

    def shutdown():
        if state["downloader"] is not None:
            state["downloader"].cancel()  # partial files stay; the next launch resumes
        if state["transcriber"] is not None:
            state["transcriber"].stop()
        if state["capture"] is not None:
            state["capture"].stop()

    window.set_on_close(shutdown)

    def start_app():
        """Everything that needs a signed-in user: fake mode, or model download + listening."""
        if FAKE_CAPTIONS:
            # Test mode: no audio or Whisper; captions are typed into a box at the bottom instead.
            window.enable_fake_captions()
            text_queue.put(("status", "Fake caption mode: type a line and press Enter"))
            return

        def start_listening():
            state["downloader"] = None
            capture = LoopbackCapture(audio_queue, frame_ms=config.FRAME_MS)
            try:
                capture.start()
            except Exception as exc:
                text_queue.put(("status", f"Audio capture error: {exc}"))
                return
            state["capture"] = capture
            transcriber = Transcriber(
                audio_queue,
                text_queue,
                # Fixed model (no in-app model picker); installed in MODELS_DIR on first run.
                model_presets={config.DEFAULT_MODEL: config.MODEL_PRESETS[config.DEFAULT_MODEL]},
                default_model=config.DEFAULT_MODEL,
                device=config.DEVICE,
                gpu_compute_type=config.GPU_COMPUTE_TYPE,
                cpu_compute_type=config.CPU_COMPUTE_TYPE,
                language=config.LANGUAGE,
                model_dirs=config.MODEL_SEARCH_DIRS,
                native_sample_rate=capture.device_rate,
                target_sample_rate=config.TARGET_SAMPLE_RATE,
                frame_ms=config.FRAME_MS,
                silence_threshold=config.SILENCE_RMS_THRESHOLD,
                finalize_silence_ms=config.FINALIZE_SILENCE_MS,
                max_utterance_s=config.MAX_UTTERANCE_S,
                partial_interval_s=config.PARTIAL_INTERVAL_S,
                partial_window_s=config.PARTIAL_WINDOW_S,
                max_queue_lag_s=config.MAX_QUEUE_LAG_S,
            )
            state["transcriber"] = transcriber
            transcriber.start()

        # First run (or an interrupted download): fetch the speech models before listening.
        needed = list(dict.fromkeys(config.MODEL_PRESETS[config.DEFAULT_MODEL]))
        missing = missing_models(needed, config.MODEL_SEARCH_DIRS)
        if missing:
            logging.info("Speech models missing: %s", ", ".join(missing))
            downloader = ModelDownloader(missing, config.MODELS_DIR, user_agent=f"WonuvaLiveCaption/{config.APP_VERSION}")
            state["downloader"] = downloader
            window.show_model_download(
                downloader, sum(APPROX_BYTES.get(s, 0) for s in missing), config.MODELS_DIR, on_done=start_listening
            )
            text_queue.put(("status", "Speech models needed"))
        else:
            start_listening()

    # Nothing runs until the user is signed in to their Wonuva account.
    if SKIP_AUTH:
        logging.info("Sign-in skipped (%s)", "build without sign-in" if not config.REQUIRE_SIGN_IN else "--no-auth")
        start_app()
    else:
        auth = WonuvaAuth(
            AUTH_URL,
            config.AUTH_CLIENT_ID,
            config.ACCOUNT_FILE,
            user_agent=f"WonuvaLiveCaption/{config.APP_VERSION}",
            offline_grace_days=config.AUTH_OFFLINE_GRACE_DAYS,
        )
        window.require_sign_in(auth, on_ready=start_app, recheck_hours=config.AUTH_RECHECK_HOURS)

    window.poll_queue(text_queue)
    window.run()


if __name__ == "__main__":
    main()
