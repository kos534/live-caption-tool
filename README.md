# Wonuva Live Caption

Real-time captions for whatever is playing through your Windows speakers — like Chrome Live Caption,
but at the OS level, so it works for any app (browser, Zoom, VLC, games, etc.).

## How it works

- **Audio source**: WASAPI loopback capture of the current default output device (via `PyAudioWPatch`),
  so it captures system audio without needing a microphone or "Stereo Mix". Audio is buffered at its
  native sample rate and resampled once per utterance with a proper anti-aliasing filter
  (`scipy.signal.resample_poly`) right before each Whisper call, rather than resampling every small
  audio callback (which introduces boundary artifacts).
- **Speech-to-text**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), running fully offline,
  no API keys, no audio leaves the machine. Two models are used: a fast model for low-latency interim
  captions while you're mid-utterance, and a more accurate model (with a wider beam search) for the
  finalized line once a pause is detected. The app always uses the `large-v3` preset: OpenAI's most
  accurate Whisper model for the final line, with `distil-large-v3` (a distilled, English-only
  large-v3) for the live interim text. There's no model picker in the app; to use a different preset,
  change `DEFAULT_MODEL` in `config.py`, download it, and rebuild. Decoding is forced to English
  (`LANGUAGE = "en"`).
- **GPU**: on an NVIDIA GPU the models run with CUDA in float16 (cuBLAS/cuDNN come from the
  `nvidia-*-cu12` pip packages, nothing to install system-wide). Without a usable GPU the app falls
  back to CPU (int8) automatically — `large-v3` works there too but is much slower; for CPU-only
  machines, build with `DEFAULT_MODEL = "small.en"` or `"medium.en"`. The title strip shows which device is in use,
  and `livecaption.log` next to the app records model loading and any errors.
- **Segmentation**: an energy-based voice activity detector splits the audio stream into utterances.
  A short lead-in before each detected speech onset is kept, so first words aren't clipped.
  Whisper's own VAD filter is used too, and the temperature fallback ladder is disabled
  (`temperature=0.0`), since retries at higher temperature are a known source of hallucinated/looping
  text; any immediately repeated phrase that still slips through is collapsed. (No repetition penalty:
  it made the model end sentences early and drop their last words.) Confidence-score filtering (to suppress hallucination on silence)
  is only applied to the final pass — the fast partial-pass model is naturally less confident, so the
  same thresholds would filter out nearly all of its output.
- **Staying in sync**: each cycle drains and merges all currently buffered audio in one pass rather than
  processing it chunk by chunk; if transcription ever falls behind real time, older buffered audio is
  dropped so captions stay close to live instead of drifting further and further behind.
- **Caption flow**: the sentence being spoken is shown live and corrected in place as more audio
  arrives (on GPU the whole sentence so far is re-transcribed twice a second), then replaced by the
  accurate final version once a pause is detected. Each caption that ends a sentence gets its own
  paragraph; a caption cut off mid-sentence continues on the same line, and a pause of 6 seconds or
  more always starts a new paragraph. Status messages (model loading, device in use) appear in the
  title strip.
- **Scrolling**: while the view is at the end, it follows new captions. Scroll up (mouse wheel, or the
  Windows 11-style scrollbar on the right edge, which widens on hover) to reread, and the view stays
  put; scroll back to the end and it follows again.
- **Window**: a fantasy-styled overlay in the Wonuva logo's colors: deep midnight-violet body, a glowing
  cyan → violet → magenta → amber gradient frame, a dusk-gradient title strip with the logo, a gold
  script title and gently twinkling sparkles. In-progress words are tinted violet until the accurate
  final pass replaces them. Borderless, always-on-top, resizable (drag the bottom-right corner), and
  can be dragged anywhere by its title strip. Caption text is read-only but selectable. Title strip
  controls: ⚙ settings (see below), **Clear**, **Copy** (copies the current selection, or the whole
  transcript if nothing is selected), and close. Logo/icon images live in `assets\`.
- **Answer**: the **✦ Answer** button under the captions sends the caption text spoken since the
  previous click (or since the start/Clear) to OpenAI and shows the reply right below it. That
  caption text is tinted as a question block, an answer block shows "loading..." and then the
  reply as it streams in, and new captions continue underneath, ready for the next click. A caption
  still in progress at the click stays in that question block. The last few earlier transcript
  segments are sent along as context (not the AI's own earlier answers, so replies don't fall
  into one template), together with your profile from ⚙ Settings. With a resume or job
  description filled in, interview-style questions are answered in the first person, as you would
  answer them. The AI can also search the web (OpenAI's web search tool) when an answer needs facts
  it doesn't have, such as what the interviewer's company does; the answer block shows "searching
  the web..." meanwhile, and links/citations are stripped from the answer. Turn it off with
  `ANSWER_WEB_SEARCH = False` in `config.py`. Only text leaves the machine (the captions plus your profile), never audio, and only
  when you click Answer.
- **⚙ Settings**: opens a settings view that fills the window (same 680×600 default size as the
  captions; it scrolls if the window is resized smaller). Sections:
  - **Display**: font size and *Hide from screen share* (both apply immediately).
  - **Personal info**: name, birthday, address, university.
  - **Job**: upload a resume (PDF, .docx or text; its text is extracted into an editable box) and a
    job description text area.
  - **Answer prompt**: the instructions the AI follows when writing answers (tone, length, language,
    format...). It starts with the built-in prompt; **Reset to default** brings it back. Your
    personal info, resume and job description are appended after it automatically.
  - **Security**: the OpenAI API key (masked, with Show/Hide).

  **Save** (or the ⚙ button) stores everything in `settings.json` next to the app; **Cancel**
  discards the edits. The API key is encrypted with Windows DPAPI, so it only decrypts for the same
  Windows user on the same PC; the other fields are plain JSON.

## Setup

Requires **Python 3.12 or older** — `faster-whisper` depends on `onnxruntime`, which has no wheels for
newer Python versions yet.

```bash
cd live-caption-tool
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python download_models.py   # fetch the models for DEFAULT_MODEL (~4.5 GB for large-v3)
```

For the Answer button, enter an OpenAI API key in ⚙ Settings → Security. As fallbacks, the app also
reads the `OPENAI_API_KEY` environment variable, then `openai_api_key.txt` next to the app (key on its
first line). Without a key, captions work as usual and the answer block says what's missing.

The app itself never downloads models: it only uses what's in the `models\` folder next to it. If the
model is missing, the title strip and caption area say so.

## Run

```bash
python main.py
```

Or just double-click `run.bat`, which creates the venv and installs dependencies on first run.

To try the window and the Answer button without any audio, run `python main.py --fake` (or
double-click `run_fake.bat`). It skips audio capture and Whisper and adds a box at the bottom: type
what the other person says and press Enter, and the line plays in word by word like a live caption.
Then click **✦ Answer** as usual.

Play some audio (a video, a call, music) and captions will appear once speech is detected. If nothing
is playing, WASAPI loopback capture idles by design and no captions will appear — that's expected.

## Building a standalone .exe

```bash
build_exe.bat
```

This installs dependencies plus `pyinstaller` (see `requirements-build.txt`), downloads the models for
`DEFAULT_MODEL`, builds using `WonuvaLiveCaption.spec`, and copies `models\` into the output. The result
is `dist\WonuvaLiveCaption\WonuvaLiveCaption.exe` (with the Wonuva icon) — a folder (~6 GB with the large-v3 models and CUDA libraries) you
can copy/zip and run on another Windows machine without Python or an internet connection.

## Configuration

Tweak `config.py`:

- `DEFAULT_MODEL` — the preset the app uses (default `large-v3`); `MODEL_PRESETS` maps each preset to
  a (partial, final) model pair. Changing it requires `download_models.py` and a rebuild.
- `MAX_QUEUE_LAG_S` — how much buffered audio backlog is tolerated before older audio is dropped to
  keep captions in sync. Lower this if captions still drift behind on a slow machine.
- `SILENCE_RMS_THRESHOLD` — raise if background noise triggers false captions, lower if quiet speech
  is missed.
- `FINALIZE_SILENCE_MS` — how long a pause must be before a line is finalized.
- `DEFAULT_FONT_SIZE` / `MIN_FONT_SIZE` / `MAX_FONT_SIZE` — also adjustable live via the ⚙ settings panel.
- `OPENAI_MODEL` — the model the Answer button uses (default `gpt-4.1-mini`); `ANSWER_HISTORY_TURNS`
  and `ANSWER_MAX_TOKENS` control the context sent along and the answer length.
- `WINDOW_WIDTH` / `WINDOW_HEIGHT` — initial caption window size.

## Project structure

```
live-caption-tool/
├── main.py              # Entry point, wires capture -> transcriber -> window together
├── audio_capture.py      # WASAPI loopback capture (PyAudioWPatch) at the device's native rate
├── transcriber.py         # VAD-based segmentation + faster-whisper partial/final transcription
├── caption_window.py      # Fantasy-styled overlay: captions, settings, Clear, Copy, Answer
├── answerer.py            # Answer button backend: streams OpenAI replies to the window
├── settings_view.py       # Full-window ⚙ Settings form (display, personal info, job, security)
├── user_settings.py       # settings.json load/save (DPAPI-encrypted key) + resume text extraction
├── theme.py               # Shared color palette
├── config.py               # Tunable settings
├── gpu.py                   # CUDA DLL setup + GPU detection
├── download_models.py       # Fetches the models into models\ (run by build_exe.bat)
├── assets\                  # Wonuva logo PNGs (16/32/48/128) + icon.ico for the exe
├── requirements.txt         # PyAudioWPatch, faster-whisper, numpy, scipy, CUDA libraries, openai, pypdf
├── requirements-build.txt    # pyinstaller (only needed to build the .exe)
├── WonuvaLiveCaption.spec     # PyInstaller build spec
├── build_exe.bat               # Builds dist\WonuvaLiveCaption\WonuvaLiveCaption.exe
├── run.bat                      # Sets up the venv and runs from source
└── run_fake.bat                 # Same, in fake caption mode (type captions to test Answer)
```
