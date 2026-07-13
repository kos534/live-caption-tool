# Live Caption

Real-time speech-to-text overlay that captures audio from **WhatsApp Desktop**, **Viber**, or any app and displays live captions in an always-on-top window.

## How it works

- **Audio source**: Microphone, Stereo Mix (what you hear), or **WASAPI loopback** (speaker output) on Windows.
- **Speech-to-text**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — offline, no API keys. Much higher accuracy than the previous Vosk-based engine, with real punctuation and capitalization.
- **Segmentation**: incoming audio is split into speech utterances with voice activity detection (silence is never sent to the model). Interim ("partial") captions are shown while you're speaking by periodically re-transcribing the in-progress utterance; a higher-quality pass runs once you pause to produce the finalized, punctuated line.
- **Display**: Draggable, transparent caption window that stays on top.

## Setup

### 1. Create virtual environment and install

```bash
cd live-caption-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> Note: `webrtcvad` (used for voice activity detection) is pinned alongside `setuptools<81`, since newer setuptools removed the `pkg_resources` module that webrtcvad imports. If either fails to install on your platform, that's fine — the app falls back to a built-in energy-based VAD automatically and still works.

### 2. Capture speaker output on Windows (USB PnP Sound Device, etc.)

To caption **what's playing through your speakers** (calls, videos, USB PnP Sound Device):

- **WASAPI loopback (recommended)**
  Install [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) so the app can record speaker output:
  ```bash
  pip install PyAudioWPatch
  ```
  Then run the app and in **Audio source** choose the device that has **(loopback)** in the name and matches your speakers, e.g.:
  - **Speakers (USB PnP Sound Device) (loopback)**
  - **Speakers (Realtek) (loopback)**
  If you don't see any "(loopback)" option, PyAudioWPatch is not installed or not in use.

- **Stereo Mix**
  Enable "Stereo Mix" in Windows Sound settings and set it as default recording device, then select it in the app.

- **Microphone**
  Use the microphone to caption your voice or room audio (no speaker output).

### 3. Download the faster-whisper model (optional pre-fetch)

The app auto-downloads its model on first use. To pre-fetch it (so first launch works fully offline), run:

```bash
python download_model.py --model-size small.en
```

You can pick a different size in the app's **Model size** dropdown (`tiny.en`/`base.en`/`small.en`/`medium.en`) — smaller is faster/lower-latency, larger is more accurate. `small.en` is the default and a good balance for most machines.

### 4. Run the app

```bash
python main.py
```

1. Select the **audio input** (loopback for call audio, or microphone).
2. Click **Start** — captions appear in the overlay.
3. Drag the overlay where you want it; it stays on top of WhatsApp/Viber.

## Usage tips

- Use **loopback** (with PyAudioWPatch) to caption the **remote** side of the call.
- Use **microphone** to caption **your** side or room audio.
- Keep the overlay over the call window so you can read captions without looking away.
- If partial captions feel laggy on your machine, switch to a smaller model size (`base.en` or `tiny.en`) in the Captioning section.

## Building the exe (Windows)

To build a single `.exe` file:

1. Install build dependency and run the build script:
   ```bash
   pip install -r requirements.txt -r requirements-build.txt
   build_exe.bat
   ```
2. `build_exe.bat` automatically pre-fetches the default model (`small.en`) into `models/` if it isn't already there, and `live-caption.spec` bundles whatever's in `models/faster-whisper-*` straight into the exe — so the built exe works offline out of the box. To bundle a different size, run `python download_model.py --model-size <size>` first, then build.
3. The executable is created at `dist\LiveCaption\LiveCaption.exe`.
4. Config and settings are stored as `live-caption-config.json` next to the exe.

## Project structure

```
live-caption-tool/
├── main.py              # Entry point, device selection, start/stop, settings UI
├── caption_engine.py     # VAD-based streaming/endpointing engine on top of faster-whisper
├── whisper_engine.py     # faster-whisper model lifecycle + partial/final transcription passes
├── vad.py                # Voice activity detection (webrtcvad, with energy-based fallback)
├── audio_capture.py       # Audio device capture + anti-aliased resampling to 16kHz mono
├── caption_utils.py       # Text normalization helpers
├── overlay.py             # Always-on-top caption window
├── config.py               # Settings persistence
├── tray_win32.py           # Windows system tray icon
├── download_model.py       # Optional model pre-fetch script
├── live-caption.spec       # PyInstaller spec for building exe
├── build_exe.bat           # Build script (Windows)
├── requirements.txt
├── requirements-build.txt
├── models/                 # faster-whisper model cache (downloaded, not checked in)
└── README.md
```

## License

MIT.
