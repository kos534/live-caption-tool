# Live Caption

Real-time captions for whatever is playing through your Windows speakers — like Chrome Live Caption,
but at the OS level, so it works for any app (browser, Zoom, VLC, games, etc.).

## How it works

- **Audio source**: WASAPI loopback capture of the current default output device (via `PyAudioWPatch`),
  so it captures system audio without needing a microphone or "Stereo Mix". Audio is buffered at its
  native sample rate and resampled once per utterance with a proper anti-aliasing filter
  (`scipy.signal.resample_poly`) right before each Whisper call, rather than resampling every small
  audio callback (which introduces boundary artifacts).
- **Speech-to-text**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), running fully offline,
  no API keys, no audio leaves the machine. Two models are used per preset: a fast model for low-latency
  interim captions while you're mid-utterance, and a more accurate model (with a wider beam search) for
  the finalized line once a pause is detected. Pick a preset from the ⚙ settings panel in the caption
  window (`tiny.en` / `base.en` / `small.en` / `medium.en`) — it hot-swaps without restarting the app.
- **Segmentation**: an energy-based voice activity detector splits the audio stream into utterances.
  Whisper's own VAD filter is used too, and the temperature fallback ladder is disabled
  (`temperature=0.0`) along with a repetition penalty, since retries at higher temperature are a known
  source of hallucinated/looping text. Confidence-score filtering (to suppress hallucination on silence)
  is only applied to the final pass — the fast partial-pass model is naturally less confident, so the
  same thresholds would filter out nearly all of its output.
- **Staying in sync**: each cycle drains and merges all currently buffered audio in one pass rather than
  processing it chunk by chunk; if transcription ever falls behind real time, older buffered audio is
  dropped so captions stay close to live instead of drifting further and further behind.
- **Window**: borderless, always-on-top, resizable (drag the bottom-right corner), and can be dragged
  anywhere by its title strip. Caption text is read-only but selectable. Title strip controls: ⚙ settings
  (model preset, font size), **Clear**, **Copy** (copies the current selection, or the whole transcript
  if nothing is selected), and close.

## Setup

```bash
cd live-caption-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The first run downloads the selected preset's faster-whisper models automatically (cached under your
user profile) — this needs an internet connection once per model size.

## Run

```bash
python main.py
```

Or just double-click `run.bat`, which creates the venv and installs dependencies on first run.

Play some audio (a video, a call, music) and captions will appear once speech is detected. If nothing
is playing, WASAPI loopback capture idles by design and no captions will appear — that's expected.

## Building a standalone .exe

```bash
build_exe.bat
```

This installs `pyinstaller` (see `requirements-build.txt`) and builds using `LiveCaption.spec`. The
result is `dist\LiveCaption\LiveCaption.exe` — a folder you can copy/zip and run on another Windows
machine without Python installed. Models still download on first launch (same as running from source)
and are cached under the user profile, so they aren't bundled into the exe itself.

## Configuration

Tweak `config.py`:

- `MODEL_PRESETS` / `DEFAULT_MODEL` — each preset maps to a (partial, final) model pair. Also
  selectable at runtime from the ⚙ settings panel.
- `MAX_QUEUE_LAG_S` — how much buffered audio backlog is tolerated before older audio is dropped to
  keep captions in sync. Lower this if captions still drift behind on a slow machine.
- `SILENCE_RMS_THRESHOLD` — raise if background noise triggers false captions, lower if quiet speech
  is missed.
- `FINALIZE_SILENCE_MS` — how long a pause must be before a line is finalized.
- `DEFAULT_FONT_SIZE` / `MIN_FONT_SIZE` / `MAX_FONT_SIZE` — also adjustable live via the ⚙ settings panel.
- `WINDOW_WIDTH` / `WINDOW_HEIGHT` — initial caption window size.

## Project structure

```
live-caption-tool/
├── main.py              # Entry point, wires capture -> transcriber -> window together
├── audio_capture.py      # WASAPI loopback capture (PyAudioWPatch) at the device's native rate
├── transcriber.py         # VAD-based segmentation + faster-whisper partial/final transcription
├── caption_window.py      # Borderless, draggable, resizable overlay: text, settings, Clear, Copy
├── config.py               # Tunable settings
├── requirements.txt         # PyAudioWPatch, faster-whisper, numpy, scipy
├── requirements-build.txt    # pyinstaller (only needed to build the .exe)
├── LiveCaption.spec           # PyInstaller build spec
├── build_exe.bat               # Builds dist\LiveCaption\LiveCaption.exe
└── run.bat                      # Sets up the venv and runs from source
```
