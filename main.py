import logging
import queue
import sys
import threading

import config
import gpu

# The exe has no console, so log to a file next to it (overwritten each launch).
logging.basicConfig(
    filename=str(config.APP_DIR / "livecaption.log"),
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

from audio_capture import LoopbackCapture
from caption_window import CaptionWindow
from transcriber import Transcriber


def main():
    audio_queue = queue.Queue(maxsize=200)
    text_queue = queue.Queue()

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
    )

    capture = LoopbackCapture(audio_queue, frame_ms=config.FRAME_MS)
    transcriber = None

    def shutdown():
        if transcriber is not None:
            transcriber.stop()
        capture.stop()

    window.set_on_close(shutdown)

    try:
        capture.start()
    except Exception as exc:
        text_queue.put(("status", f"Audio capture error: {exc}"))
        window.poll_queue(text_queue)
        window.run()
        return

    transcriber = Transcriber(
        audio_queue,
        text_queue,
        # Fixed model (no in-app model picker); it must be bundled in models\ -- the app never downloads.
        model_presets={config.DEFAULT_MODEL: config.MODEL_PRESETS[config.DEFAULT_MODEL]},
        default_model=config.DEFAULT_MODEL,
        device=config.DEVICE,
        gpu_compute_type=config.GPU_COMPUTE_TYPE,
        cpu_compute_type=config.CPU_COMPUTE_TYPE,
        language=config.LANGUAGE,
        download_root=str(config.MODELS_DIR),
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

    transcriber.start()
    window.poll_queue(text_queue)
    window.run()


if __name__ == "__main__":
    main()
