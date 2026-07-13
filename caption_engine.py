"""
Streaming caption engine built on faster-whisper + VAD-based endpointing.

faster-whisper has no incremental/streaming decode API - it only transcribes
a full audio buffer at a time. "Live" captioning is built on top of that here:
incoming audio is segmented into speech utterances using voice activity
detection (silence at the edges is never sent to the model), the growing
utterance buffer is periodically re-transcribed for interim ("partial")
captions while the person is still speaking, and a higher-quality pass runs
once the utterance is endpointed (silence, or a max-duration safety cut) to
produce the final, punctuated caption line.
"""
from __future__ import annotations

import queue
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from audio_capture import SAMPLE_RATE, capture_audio
from caption_utils import is_blank, normalize_caption
from vad import VoiceActivityDetector
from whisper_engine import (
    DEFAULT_MODEL_SIZE,
    load_model,
    pcm16_to_float32,
    transcribe_final,
    transcribe_partial,
)

FRAME_MS = 30
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * 2  # 16-bit mono samples

START_RING_FRAMES = 8       # ~240ms lead-in window used to trigger an utterance
START_TRIGGER_RATIO = 0.9   # fraction of frames in the ring that must be speech
END_RING_FRAMES = 20        # ~600ms trailing window used to detect an endpoint
END_TRIGGER_RATIO = 0.9     # fraction of frames in the ring that must be silence

MAX_UTTERANCE_SEC = 18.0
PARTIAL_INTERVAL_SEC = 1.2
MIN_PARTIAL_SEC = 0.6


def _level_from_pcm16(data: bytes) -> float:
    """Simple RMS-based level (0-1) from 16-bit mono PCM bytes, for the volume meter."""
    if not data:
        return 0.0
    sample_count = len(data) // 2
    if not sample_count:
        return 0.0
    samples = struct.unpack("<" + "h" * sample_count, data)
    sq_sum = sum(float(s) * float(s) for s in samples)
    rms = (sq_sum / sample_count) ** 0.5
    return min(rms / 20000.0, 1.0)


def run_caption_engine(
    model_size: str,
    device_index: int | None,
    *,
    on_partial: Callable[[str], None],
    on_final: Callable[[str], None],
    stop_event: Callable[[], bool],
    use_loopback: bool = False,
    on_level: Callable[[float], None] | None = None,
) -> None:
    """
    Start audio capture, VAD segmentation, and faster-whisper transcription on
    background daemon threads and return immediately. Runs until stop_event()
    returns True. on_partial is called with full-replacement interim text
    while an utterance is in progress; on_final is called once per completed,
    punctuated utterance.
    """
    model = load_model(model_size or DEFAULT_MODEL_SIZE)
    vad = VoiceActivityDetector(sample_rate=SAMPLE_RATE, frame_ms=FRAME_MS)

    audio_queue: "queue.Queue[bytes | None]" = queue.Queue()
    partial_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="caption-partial")
    final_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="caption-final")

    state_lock = threading.Lock()
    state = {"last_finalized_id": 0, "partial_inflight": False, "last_final_text": None}

    def on_audio_data(data: bytes) -> None:
        if stop_event():
            return
        if on_level is not None and data:
            try:
                on_level(_level_from_pcm16(data))
            except Exception:
                pass
        try:
            audio_queue.put_nowait(data)
        except queue.Full:
            pass

    def submit_partial(buf: bytes, uid: int) -> None:
        with state_lock:
            if state["partial_inflight"] or uid <= state["last_finalized_id"]:
                return
            state["partial_inflight"] = True

        def job() -> None:
            try:
                if stop_event():
                    return
                text = transcribe_partial(model, pcm16_to_float32(buf))
                with state_lock:
                    stale = uid <= state["last_finalized_id"]
                if not stale and not is_blank(text) and not stop_event():
                    on_partial(normalize_caption(text))
            except Exception:
                pass
            finally:
                with state_lock:
                    state["partial_inflight"] = False

        partial_executor.submit(job)

    def submit_final(buf: bytes, uid: int) -> None:
        def job() -> None:
            try:
                if stop_event():
                    return
                with state_lock:
                    previous_text = state["last_final_text"]
                text = transcribe_final(model, pcm16_to_float32(buf), previous_text=previous_text)
                with state_lock:
                    state["last_finalized_id"] = max(state["last_finalized_id"], uid)
                    if not is_blank(text):
                        state["last_final_text"] = text
                if not is_blank(text) and not stop_event():
                    on_final(normalize_caption(text))
            except Exception:
                pass

        final_executor.submit(job)

    def segmenter() -> None:
        leftover = b""
        pretrigger: list[tuple[bytes, bool]] = []
        end_ring: list[bool] = []
        triggered = False
        utterance_buf = bytearray()
        utterance_id = 0
        last_partial_fire_len = 0
        utterance_start = 0.0

        def reset_utterance() -> None:
            nonlocal utterance_buf, last_partial_fire_len, utterance_start, end_ring
            utterance_buf = bytearray()
            last_partial_fire_len = 0
            utterance_start = time.monotonic()
            end_ring = []

        while True:
            try:
                chunk = audio_queue.get(timeout=0.2)
            except queue.Empty:
                if stop_event():
                    break
                continue
            if chunk is None or stop_event():
                break

            leftover += chunk
            while len(leftover) >= FRAME_BYTES:
                frame = leftover[:FRAME_BYTES]
                leftover = leftover[FRAME_BYTES:]
                speech = vad.is_speech(frame)

                if not triggered:
                    pretrigger.append((frame, speech))
                    if len(pretrigger) > START_RING_FRAMES:
                        pretrigger.pop(0)
                    if len(pretrigger) == START_RING_FRAMES:
                        speech_ratio = sum(1 for _f, s in pretrigger if s) / len(pretrigger)
                        if speech_ratio >= START_TRIGGER_RATIO:
                            triggered = True
                            utterance_id += 1
                            reset_utterance()
                            for f, _s in pretrigger:
                                utterance_buf.extend(f)
                            pretrigger.clear()
                    continue

                utterance_buf.extend(frame)
                end_ring.append(speech)
                if len(end_ring) > END_RING_FRAMES:
                    end_ring.pop(0)

                duration = len(utterance_buf) / 2 / SAMPLE_RATE
                endpoint = (
                    len(end_ring) == END_RING_FRAMES
                    and (1.0 - sum(end_ring) / len(end_ring)) >= END_TRIGGER_RATIO
                )
                force_cut = duration >= MAX_UTTERANCE_SEC

                if endpoint or force_cut:
                    submit_final(bytes(utterance_buf), utterance_id)
                    if force_cut and not endpoint:
                        utterance_id += 1
                        reset_utterance()
                    else:
                        triggered = False
                        pretrigger.clear()
                        end_ring = []
                    continue

                if duration >= MIN_PARTIAL_SEC:
                    since_last = (len(utterance_buf) - last_partial_fire_len) / 2 / SAMPLE_RATE
                    if since_last >= PARTIAL_INTERVAL_SEC:
                        last_partial_fire_len = len(utterance_buf)
                        submit_partial(bytes(utterance_buf), utterance_id)

        if triggered and len(utterance_buf) > 0:
            submit_final(bytes(utterance_buf), utterance_id)

    def capture_thread_fn() -> None:
        try:
            capture_audio(
                device_index,
                on_data=on_audio_data,
                stop_event=stop_event,
                use_pyaudiowpatch=use_loopback,
                is_loopback=use_loopback,
            )
        finally:
            try:
                audio_queue.put_nowait(None)
            except queue.Full:
                pass

    threading.Thread(target=capture_thread_fn, daemon=True).start()
    threading.Thread(target=segmenter, daemon=True).start()
