# Live Caption

Real-time speech-to-text overlay that captures audio from **WhatsApp Desktop**, **Viber**, or any app and displays live captions in an always-on-top window.

## How it works

- **Audio source**: Microphone, Stereo Mix (what you hear), or **WASAPI loopback** (speaker output) on Windows.
- **Speech-to-text**: [Vosk](https://alphacephei.com/vosk/) — offline, low-latency, no API keys.
- **Display**: Draggable, transparent caption window that stays on top.

## Setup

### 1. Create virtual environment and install

```bash
cd live-caption
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Capture speaker output on Windows (USB PnP Sound Device, etc.)

To caption **what’s playing through your speakers** (calls, videos, USB PnP Sound Device):

- **WASAPI loopback (recommended)**  
  Install [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) so the app can record speaker output:
  ```bash
  pip install PyAudioWPatch
  ```
  Then run the app and in **Audio source** choose the device that has **(loopback)** in the name and matches your speakers, e.g.:
  - **Speakers (USB PnP Sound Device) (loopback)**
  - **Speakers (Realtek) (loopback)**  
  If you don’t see any “(loopback)” option, PyAudioWPatch is not installed or not in use.

- **Stereo Mix**  
  Enable “Stereo Mix” in Windows Sound settings and set it as default recording device, then select it in the app.

- **Microphone**  
  Use the microphone to caption your voice or room audio (no speaker output).

### 3. Download Vosk language model (first run)

Run the helper script to download a small English model (~40 MB):

```bash
python download_model.py
```

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

## Project structure

```
live-caption/
├── main.py           # Entry point, device selection, start/stop
├── caption_engine.py # Vosk streaming + audio capture
├── overlay.py        # Always-on-top caption window
├── requirements.txt
├── models/           # Vosk model (download separately)
└── README.md
```

## License

MIT.
