import queue
import threading
import time
from fractions import Fraction

import numpy as np
from faster_whisper import WhisperModel
from scipy.signal import resample_poly


class Transcriber:
    """Buffers loopback audio, segments it by silence, and transcribes with faster-whisper.

    Audio arrives at the capture device's native sample rate and is buffered as-is; it's only
    resampled (once, with a proper anti-aliasing filter) right before each Whisper call. Doing
    this per-utterance instead of per-callback avoids the boundary artifacts that a naive
    chunk-by-chunk resample introduces at every ~30ms callback edge.

    Uses a small/fast model for low-latency interim ("partial") captions while speech is
    ongoing, and a larger/more accurate model for the finalized line once a pause is detected.

    Emits ("status" | "partial" | "final", text) tuples onto text_queue.
    """

    def __init__(
        self,
        audio_queue: queue.Queue,
        text_queue: queue.Queue,
        model_presets: dict,
        default_model: str,
        device: str,
        compute_type: str,
        download_root: str,
        native_sample_rate: int,
        target_sample_rate: int,
        frame_ms: int,
        silence_threshold: float,
        finalize_silence_ms: int,
        max_utterance_s: float,
        partial_interval_s: float,
        partial_window_s: float,
        max_queue_lag_s: float,
    ):
        self.audio_queue = audio_queue
        self.text_queue = text_queue
        self.model_presets = model_presets
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.native_sample_rate = native_sample_rate
        self.target_sample_rate = target_sample_rate
        self.frame_ms = frame_ms
        self.silence_threshold = silence_threshold
        self.finalize_silence_ms = finalize_silence_ms
        self.max_utterance_s = max_utterance_s
        self.partial_interval_s = partial_interval_s
        self.partial_window_s = partial_window_s
        self.max_queue_lag_s = max_queue_lag_s

        self.current_preset = None
        self.partial_model_size = None
        self.final_model_size = None
        self.partial_model = None
        self.final_model = None
        self._pending_preset = queue.Queue()
        self._pending_preset.put(default_model)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def set_model(self, preset_name: str):
        """Request a model switch; picked up by the worker thread on its next loop iteration."""
        if preset_name in self.model_presets:
            self._pending_preset.put(preset_name)

    def _load_pending_preset(self) -> bool:
        preset_name = None
        try:
            while True:
                preset_name = self._pending_preset.get_nowait()
        except queue.Empty:
            pass
        if preset_name is None or preset_name == self.current_preset:
            return self.current_preset is not None

        partial_size, final_size = self.model_presets[preset_name]
        self.text_queue.put(("status", f"Loading {preset_name} model..."))
        try:
            self.partial_model = WhisperModel(
                partial_size, device=self.device, compute_type=self.compute_type, download_root=self.download_root
            )
            self.final_model = WhisperModel(
                final_size, device=self.device, compute_type=self.compute_type, download_root=self.download_root
            )
        except Exception as exc:
            self.text_queue.put(("status", f"Failed to load speech model: {exc}"))
            return self.current_preset is not None
        self.partial_model_size = partial_size
        self.final_model_size = final_size
        self.current_preset = preset_name
        self.text_queue.put(("status", "Listening for audio..."))
        return True

    def _run(self):
        if not self._load_pending_preset():
            return

        buffer = np.zeros(0, dtype=np.float32)
        speaking = False
        silence_ms = 0.0
        last_partial = 0.0
        last_final = ""
        onset_frames = 0
        onset_required = 3  # require ~90ms of sustained signal before starting an utterance, to ignore noise blips

        while not self._stop.is_set():
            if not self._pending_preset.empty():
                self._load_pending_preset()
                buffer = np.zeros(0, dtype=np.float32)
                speaking = False
                silence_ms = 0.0
                onset_frames = 0

            chunk = self._drain_audio()
            if chunk is None:
                continue
            if len(chunk) == 0:
                continue

            chunk_ms = len(chunk) / self.native_sample_rate * 1000
            rms = float(np.sqrt(np.mean(np.square(chunk))))

            if rms >= self.silence_threshold:
                if not speaking:
                    onset_frames += 1
                    if onset_frames < onset_required:
                        continue
                    onset_frames = 0
                buffer = np.concatenate([buffer, chunk])
                speaking = True
                silence_ms = 0.0
            elif speaking:
                buffer = np.concatenate([buffer, chunk])
                silence_ms += chunk_ms
            else:
                onset_frames = 0
                continue

            utterance_s = len(buffer) / self.native_sample_rate
            should_finalize = silence_ms >= self.finalize_silence_ms or utterance_s >= self.max_utterance_s

            if should_finalize:
                text = self._transcribe(self.final_model, buffer, beam_size=5, strict=True)
                if text and text.lower() != last_final.lower():
                    self.text_queue.put(("final", text))
                last_final = text
                buffer = np.zeros(0, dtype=np.float32)
                speaking = False
                silence_ms = 0.0
                onset_frames = 0
                last_partial = 0.0
                continue

            now = time.time()
            if utterance_s >= 0.5 and (now - last_partial) >= self.partial_interval_s:
                window_samples = int(self.partial_window_s * self.native_sample_rate)
                window = buffer[-window_samples:] if len(buffer) > window_samples else buffer
                text = self._transcribe(self.partial_model, window, beam_size=1, strict=False)
                if text:
                    self.text_queue.put(("partial", text))
                last_partial = now

    def _drain_audio(self):
        """Pull all currently queued audio chunks and concatenate them into one block.

        If a backlog has built up (transcription fell behind real time), drop the older
        excess chunks so captions stay close to live instead of drifting further and
        further behind the longer the app runs.
        """
        try:
            chunks = [self.audio_queue.get(timeout=0.2)]
        except queue.Empty:
            return None

        while True:
            try:
                chunks.append(self.audio_queue.get_nowait())
            except queue.Empty:
                break

        max_chunks = int(self.max_queue_lag_s * 1000 / self.frame_ms)
        if len(chunks) > max_chunks:
            chunks = chunks[-max_chunks:]

        return np.concatenate(chunks)

    def _resample_to_target(self, audio: np.ndarray) -> np.ndarray:
        if self.native_sample_rate == self.target_sample_rate or len(audio) == 0:
            return audio
        ratio = Fraction(self.target_sample_rate, self.native_sample_rate).limit_denominator(1000)
        return resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float32)

    def _transcribe(self, model: WhisperModel, audio: np.ndarray, beam_size: int, strict: bool) -> str:
        if len(audio) == 0:
            return ""
        audio = self._resample_to_target(audio)
        model_size = self.final_model_size if model is self.final_model else self.partial_model_size
        language = "en" if model_size.endswith(".en") else None
        segments, _ = model.transcribe(
            audio,
            language=language,
            beam_size=beam_size,
            temperature=0.0,  # disable the temperature fallback ladder: retries at higher (noisier)
                               # temperature are a well-known source of repetition/hallucination
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
        )
        # Confidence-based hallucination filtering is only applied to the final pass. The fast
        # partial-pass model (e.g. tiny.en) is inherently less confident than the final model, so
        # the same thresholds would reject most of its output and partial captions would never
        # show up; partials are a best-effort live preview anyway, corrected by the final pass.
        parts = []
        for seg in segments:
            if strict and (seg.no_speech_prob > 0.6 or seg.avg_logprob < -1.0):
                continue
            text = seg.text.strip()
            if not text:
                continue
            if parts and parts[-1][-1] not in ".!?" and text[:1].isupper():
                parts[-1] += "."
            parts.append(text)
        return _collapse_repeats(" ".join(parts).strip())


def _collapse_repeats(text: str) -> str:
    """Collapse an immediately-repeated run of 2+ words (Whisper's classic decoding loop failure).

    Single-word repeats (e.g. "yes yes", "no no") are left alone since those can be intentional.
    """
    words = text.split()
    n = len(words)
    out = []
    i = 0
    while i < n:
        collapsed = False
        max_len = (n - i) // 2
        for length in range(min(8, max_len), 1, -1):
            if words[i:i + length] == words[i + length:i + 2 * length]:
                out.extend(words[i:i + length])
                i += 2 * length
                while words[i:i + length] == words[i - length:i]:
                    i += length
                collapsed = True
                break
        if not collapsed:
            out.append(words[i])
            i += 1
    return " ".join(out)
