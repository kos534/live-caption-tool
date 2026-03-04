"""
Audio capture for live captioning.
Uses PyAudioWPatch on Windows for WASAPI loopback (speaker output), 
otherwise sounddevice for microphone/default input.
"""
from __future__ import annotations

import queue
import struct
import sys
from dataclasses import dataclass
from typing import Callable

# Vosk expects 16 kHz mono 16-bit PCM
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SEC = 0.2
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_SEC)
CHUNK_BYTES = CHUNK_FRAMES * 2  # 16-bit = 2 bytes per sample


@dataclass
class AudioDevice:
    index: int
    name: str
    is_loopback: bool


def list_devices() -> list[AudioDevice]:
    """List input devices. Prefer PyAudioWPatch to include WASAPI loopback."""
    devices: list[AudioDevice] = []
    if sys.platform == "win32":
        try:
            import pyaudiowpatch as pyaudio
            with pyaudio.PyAudio() as p:
                try:
                    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                except OSError:
                    wasapi = None
                # Add loopback devices (speaker output)
                if wasapi is not None:
                    for dev in p.get_loopback_device_info_generator():
                        devices.append(AudioDevice(
                            index=dev["index"],
                            name=f"{dev['name']} (loopback)",
                            is_loopback=True,
                        ))
                # Add regular input devices
                for i in range(p.get_device_count()):
                    try:
                        dev = p.get_device_info_by_index(i)
                        if dev.get("maxInputChannels", 0) > 0 and not dev.get("isLoopbackDevice", False):
                            devices.append(AudioDevice(
                                index=dev["index"],
                                name=dev["name"],
                                is_loopback=False,
                            ))
                    except Exception:
                        continue
            if devices:
                return devices
        except ImportError:
            pass
    # Fallback: sounddevice
    import sounddevice as sd
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append(AudioDevice(
                index=i,
                name=dev["name"],
                is_loopback=False,
            ))
    return devices


def _resample_to_16k_mono(frames: bytes, in_rate: int, in_channels: int) -> bytes:
    """Downsample to 16 kHz mono 16-bit. Stereo: average channels. Linear interpolation for cleaner speech."""
    import struct
    out: list[int] = []
    bytes_per_sample = 2
    frame_size = bytes_per_sample * in_channels
    num_samples = len(frames) // frame_size
    for i in range(num_samples):
        chunk = frames[i * frame_size : (i + 1) * frame_size]
        if in_channels == 2:
            l, r = struct.unpack_from("<hh", chunk)
            sample = (l + r) // 2
        else:
            sample, = struct.unpack_from("<h", chunk)
        out.append(sample)
    # Resample with linear interpolation (smoother than nearest-neighbor, better for speech)
    if in_rate != SAMPLE_RATE:
        ratio = in_rate / SAMPLE_RATE
        n_out = int(len(out) * SAMPLE_RATE / in_rate)
        if n_out <= 0:
            return b""
        resampled: list[int] = []
        for i in range(n_out):
            src_pos = i * ratio
            idx = int(src_pos)
            frac = src_pos - idx
            if idx >= len(out) - 1:
                resampled.append(out[-1])
            else:
                a, b = out[idx], out[idx + 1]
                resampled.append(int(a + frac * (b - a)))
        out = resampled
    return struct.pack(f"<{len(out)}h", *out)


def _has_pyaudiowpatch() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except ImportError:
        return False


def capture_audio(
    device_index: int | None,
    *,
    on_data: Callable[[bytes], None],
    stop_event: Callable[[], bool],
    use_pyaudiowpatch: bool = False,
    is_loopback: bool = False,
) -> None:
    """
    Capture audio and call on_data with raw 16-bit mono 16 kHz PCM chunks.
    Runs until stop_event() returns True.
    When PyAudioWPatch is installed we use it for all devices so indices match list_devices().
    If is_loopback is True and PyAudioWPatch fails, we re-raise (no fallback to sounddevice).
    """
    if sys.platform == "win32" and _has_pyaudiowpatch():
        try:
            import pyaudiowpatch as pyaudio
            _capture_pyaudio(device_index, on_data, stop_event, pyaudio)
            return
        except Exception as e:
            if is_loopback:
                raise RuntimeError(
                    "Failed to capture from speaker output (loopback). "
                    "Try closing other apps using the sound device, or use a different output device."
                ) from e
            # Non-loopback: fall back to sounddevice
            pass
    _capture_sounddevice(device_index, on_data, stop_event)


def _capture_pyaudio(
    device_index: int | None,
    on_data: Callable[[bytes], None],
    stop_event: Callable[[], bool],
    pyaudio,
) -> None:
    with pyaudio.PyAudio() as p:
        if device_index is not None:
            dev = p.get_device_info_by_index(device_index)
        else:
            try:
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_out = wasapi["defaultOutputDevice"]
                dev = p.get_device_info_by_index(default_out)
                if not dev.get("isLoopbackDevice"):
                    for loopback in p.get_loopback_device_info_generator():
                        if dev["name"] in loopback["name"]:
                            dev = loopback
                            break
            except Exception:
                dev = p.get_default_input_device_info()
        rate = int(dev.get("defaultSampleRate", SAMPLE_RATE))
        channels = dev.get("maxInputChannels", 1)
        if rate != SAMPLE_RATE or channels != CHANNELS:
            def callback(in_data, frame_count, time_info, status):
                if stop_event():
                    return (None, pyaudio.paComplete)
                out = _resample_to_16k_mono(in_data, rate, channels)
                if out:
                    on_data(out)
                return (None, pyaudio.paContinue)
        else:
            def callback(in_data, frame_count, time_info, status):
                if stop_event():
                    return (None, pyaudio.paComplete)
                if in_data:
                    on_data(in_data)
                return (None, pyaudio.paContinue)
        # Use a smaller buffer for better compatibility with USB/speaker loopback devices
        frames_per_buffer = 1024 if dev.get("isLoopbackDevice") else CHUNK_FRAMES
        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=frames_per_buffer,
            stream_callback=callback,
        )
        try:
            while not stop_event():
                import time
                time.sleep(0.1)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass


def _capture_sounddevice(
    device_index: int | None,
    on_data: Callable[[bytes], None],
    stop_event: Callable[[], bool],
) -> None:
    import sounddevice as sd
    q: queue.Queue[bytes | None] = queue.Queue()

    def callback(indata, frame_count, time_info, status):
        if status:
            return
        q.put(indata.tobytes())

    stream = sd.InputStream(
        device=device_index,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_FRAMES,
        callback=callback,
    )
    stream.start()
    try:
        while not stop_event():
            try:
                chunk = q.get(timeout=0.2)
                if chunk is not None and chunk:
                    on_data(chunk)
            except queue.Empty:
                continue
    finally:
        stream.stop()
        stream.close()
