import queue

import numpy as np
import pyaudiowpatch as pyaudio


class LoopbackCapture:
    """Captures Windows system output audio (WASAPI loopback) as mono float32 frames at the
    device's native sample rate. Resampling to whatever rate the STT model needs is left to the
    consumer, so it can be done once per utterance on a continuous buffer instead of on tiny
    independent chunks (which introduces boundary artifacts with every capture callback)."""

    def __init__(self, out_queue: queue.Queue, frame_ms: int = 30):
        self.out_queue = out_queue
        self.frame_ms = frame_ms
        self.device_name = None
        self.device_rate = None
        self.channels = None
        self._pa = None
        self._stream = None

    def start(self):
        self._pa = pyaudio.PyAudio()
        try:
            device = self._find_loopback_device(self._pa)
        except Exception:
            self._pa.terminate()
            self._pa = None
            raise

        self.device_name = device["name"]
        self.device_rate = int(device["defaultSampleRate"])
        self.channels = int(device["maxInputChannels"])
        frame_samples = max(1, int(self.device_rate * self.frame_ms / 1000))

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.device_rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=frame_samples,
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def _callback(self, in_data, frame_count, time_info, status):
        data = np.frombuffer(in_data, dtype=np.float32)
        if self.channels > 1:
            data = data.reshape(-1, self.channels).mean(axis=1)
        try:
            self.out_queue.put_nowait(data.astype(np.float32))
        except queue.Full:
            pass
        return (None, pyaudio.paContinue)

    @staticmethod
    def _find_loopback_device(pa: "pyaudio.PyAudio") -> dict:
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        if default_speakers.get("isLoopbackDevice"):
            return default_speakers
        for loopback in pa.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback
        raise RuntimeError("No WASAPI loopback device found for the default output speaker.")
