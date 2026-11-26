import logging
import queue
import threading
import time
from fractions import Fraction

import numpy as np
from faster_whisper import WhisperModel
from scipy.signal import resample_poly

import gpu
from model_download import find_model

log = logging.getLogger(__name__)


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
        gpu_compute_type: str,
        cpu_compute_type: str,
        language: str,
        model_dirs: list,
        native_sample_rate: int,
        target_sample_rate: int,
        frame_ms: int,
        silence_threshold: float,
        finalize_silence_ms: int,
        max_utterance_s: float,
        partial_interval_s: dict,
        partial_window_s: dict,
        max_queue_lag_s: float,
    ):
        self.audio_queue = audio_queue
        self.text_queue = text_queue
        self.model_presets = model_presets
        self.device = device
        self.gpu_compute_type = gpu_compute_type
        self.cpu_compute_type = cpu_compute_type
        self.language = language
        self.model_dirs = list(model_dirs)  # searched in order for installed models
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
        self.active_device = None
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

        if self.device == "auto":
            devices = ["cuda", "cpu"] if gpu.cuda_available() else ["cpu"]
        else:
            devices = [self.device]

        last_exc = None
        for device in devices:
            compute_type = self.gpu_compute_type if device == "cuda" else self.cpu_compute_type
            log.info("Loading %s (%s + %s) on %s (%s)", preset_name, partial_size, final_size, device, compute_type)
            try:
                partial_model = self._load_model(partial_size, device, compute_type)
                final_model = self._load_model(final_size, device, compute_type)
                # Run one tiny inference so problems surface here instead of on the first real
                # utterance: a missing cuBLAS/cuDNN DLL (falls back to CPU), or a missing VAD
                # model asset (vad_filter=True), which would otherwise only fail once speech plays.
                silence = np.zeros(self.target_sample_rate, dtype=np.float32)
                list(final_model.transcribe(silence, language=self.language, beam_size=1, vad_filter=True)[0])
                if device == "cuda":
                    for m in (partial_model, final_model):
                        list(m.transcribe(silence, language=self.language, beam_size=1)[0])
            except Exception as exc:
                log.exception("Loading %s on %s (%s) failed", preset_name, device, compute_type)
                last_exc = exc
                partial_model = final_model = None
                continue
            log.info("Loaded %s on %s (%s)", preset_name, device, compute_type)
            break
        else:
            self.text_queue.put(("status", f"Failed to load speech model: {last_exc}"))
            return self.current_preset is not None

        self.partial_model = partial_model
        self.final_model = final_model
        self.partial_model_size = partial_size
        self.final_model_size = final_size
        self.current_preset = preset_name
        self.active_device = device
        self.text_queue.put(("status", f"Listening for audio... ({preset_name} on {device.upper()})"))
        return True

    def _load_model(self, size: str, device: str, compute_type: str) -> WhisperModel:
        """Load an installed model (downloaded on first run by model_download); never downloads."""
        path = find_model(size, self.model_dirs)
        if not path:
            raise FileNotFoundError(f"Model '{size}' is not installed in {self.model_dirs[0]}")
        return WhisperModel(path, device=device, compute_type=compute_type, local_files_only=True)

    def _run(self):
        try:
            self._run_loop()
        except Exception as exc:
            log.exception("Transcriber thread crashed")
            self.text_queue.put(("status", f"Transcriber error: {exc}"))

    def _run_loop(self):
        if not self._load_pending_preset():
            return

        buffer = np.zeros(0, dtype=np.float32)
        speaking = False
        silence_ms = 0.0
        last_partial = 0.0
        last_final = ""
        # Audio heard while not (yet) speaking: the few chunks used to confirm a speech onset plus a
        # short lead-in before it. It's prepended to the utterance so the first word isn't clipped;
        # previously those chunks were discarded, which dropped the start of sentences.
        preroll = []
        preroll_ms = 0.0
        onset_ms = 0.0
        onset_required_ms = 90  # sustained signal needed to start an utterance, to ignore noise blips
        preroll_max_ms = 400

        while not self._stop.is_set():
            if not self._pending_preset.empty():
                self._load_pending_preset()
                buffer = np.zeros(0, dtype=np.float32)
                speaking = False
                silence_ms = 0.0
                preroll, preroll_ms, onset_ms = [], 0.0, 0.0

            chunk = self._drain_audio()
            if chunk is None:
                continue
            if len(chunk) == 0:
                continue

            chunk_ms = len(chunk) / self.native_sample_rate * 1000
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            loud = rms >= self.silence_threshold

            if speaking:
                buffer = np.concatenate([buffer, chunk])
                silence_ms = 0.0 if loud else silence_ms + chunk_ms
            else:
                preroll.append(chunk)
                preroll_ms += chunk_ms
                onset_ms = onset_ms + chunk_ms if loud else 0.0
                if onset_ms < onset_required_ms:
                    # Not speech yet: keep only the most recent lead-in audio.
                    while preroll_ms > preroll_max_ms and len(preroll) > 1:
                        preroll_ms -= len(preroll.pop(0)) / self.native_sample_rate * 1000
                    continue
                buffer = np.concatenate(preroll)
                preroll, preroll_ms, onset_ms = [], 0.0, 0.0
                speaking = True
                silence_ms = 0.0

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
                last_partial = 0.0
                continue

            now = time.time()
            interval_s = self.partial_interval_s[self.active_device]
            if utterance_s >= 0.5 and (now - last_partial) >= interval_s:
                # Preview the whole utterance so far (like Windows Live Caption, the current line
                # grows and gets corrected in place). On CPU only the most recent window is used,
                # since re-transcribing up to MAX_UTTERANCE_S every interval would fall behind.
                window_s = self.partial_window_s[self.active_device]
                window = buffer
                if window_s is not None:
                    window = buffer[-int(window_s * self.native_sample_rate):]
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
        segments, _ = model.transcribe(
            audio,
            language=self.language,
            beam_size=beam_size,
            temperature=0.0,  # disable the temperature fallback ladder: retries at higher (noisier)
                               # temperature are a well-known source of repetition/hallucination
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            # No repetition_penalty / no_repeat_ngram_size: the penalty made the model end
            # sentences early (dropping their tail), and banning repeated 3-word phrases breaks
            # normal speech, which repeats phrases constantly. Decoding loops are handled by
            # temperature=0, condition_on_previous_text=False and _collapse_repeats below.
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
