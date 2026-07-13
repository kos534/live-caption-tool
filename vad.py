"""
Voice activity detection for 16 kHz mono 16-bit PCM frames.
Prefers webrtcvad (fast, well-tested); falls back to a pure-numpy energy
detector if webrtcvad isn't installed (e.g. no prebuilt wheel for the
running Python version), so captioning still works either way.
"""
from __future__ import annotations


class VoiceActivityDetector:
    def __init__(self, aggressiveness: int = 2, sample_rate: int = 16000, frame_ms: int = 30) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_bytes = int(sample_rate * frame_ms / 1000) * 2  # 16-bit samples
        self.backend = "energy"
        self._vad = None
        self._noise_floor = 300.0  # adaptive RMS noise floor for the energy fallback

        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(aggressiveness)
            self.backend = "webrtcvad"
        except Exception:
            self._vad = None
            self.backend = "energy"

    def is_speech(self, frame: bytes) -> bool:
        """frame must be exactly self.frame_bytes bytes of 16-bit mono PCM at self.sample_rate."""
        if len(frame) != self.frame_bytes:
            return False
        if self._vad is not None:
            try:
                return self._vad.is_speech(frame, self.sample_rate)
            except Exception:
                pass
        return self._energy_is_speech(frame)

    def _energy_is_speech(self, frame: bytes) -> bool:
        import numpy as np

        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return False
        rms = float(np.sqrt(np.mean(samples * samples)))
        # Adapt the noise floor slowly toward quiet frames so it tracks background noise.
        if rms < self._noise_floor:
            self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
        return rms > max(self._noise_floor * 3.0, 400.0)
