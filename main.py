import queue

import config
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
        model_choices=list(config.MODEL_PRESETS.keys()),
        default_model=config.DEFAULT_MODEL,
        font_size=config.DEFAULT_FONT_SIZE,
        min_font_size=config.MIN_FONT_SIZE,
        max_font_size=config.MAX_FONT_SIZE,
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
        model_presets=config.MODEL_PRESETS,
        default_model=config.DEFAULT_MODEL,
        device=config.DEVICE,
        compute_type=config.COMPUTE_TYPE,
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
    window.set_on_model_change(transcriber.set_model)

    transcriber.start()
    window.poll_queue(text_queue)
    window.run()


if __name__ == "__main__":
    main()
