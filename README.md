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
  and `livecaption.log` in the data folder (see below) records model loading and any errors.
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
- **Wonuva account**: the app is locked behind a "Sign in to Wonuva" screen until the user signs in.
  Signing in opens the Wonuva login page in the browser (OAuth 2.0 with PKCE and a `127.0.0.1`
  redirect; the app never sees the password), then the app unlocks and starts the model download or
  captions. The session is remembered, encrypted with DPAPI in `account.json` in the data folder,
  and re-checked at every launch and every 6 hours; if Wonuva revokes it, the app locks again. If
  Wonuva can't be reached, a session verified within the last 7 days keeps working. The Wonuva
  backend must implement [docs/WONUVA_AUTH_API.md](docs/WONUVA_AUTH_API.md).
- **⚙ Settings**: opens a settings view that fills the window (same 680×600 default size as the
  captions; it scrolls if the window is resized smaller). Sections:
  - **Wonuva account**: who is signed in, and **Sign out**.
  - **Display**: font size and *Hide from screen share* (both apply immediately).
  - **Personal info**: name, birthday, address, university.
  - **Job**: upload a resume (PDF, .docx or text; its text is extracted into an editable box) and a
    job description text area.
  - **Answer prompt**: the instructions the AI follows when writing answers (tone, length, language,
    format...). It starts with the built-in prompt; **Reset to default** brings it back. Your
    personal info, resume and job description are appended after it automatically.
  - **Security**: the OpenAI API key (masked, with Show/Hide).

  **Save** (or the ⚙ button) stores everything in `settings.json` in the data folder; **Cancel**
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
python download_models.py   # optional: the app also downloads them on first run (~4.4 GB)
```

**Where things are kept.** Everything the app writes goes to `%LOCALAPPDATA%\Wonuva Live Caption\`
(the install folder may be read-only): `settings.json`, `account.json` (the Wonuva session),
`livecaption.log` and `models\`. Settings
saved next to the app by v2.0.0 are copied there on the first launch.

For the Answer button, enter an OpenAI API key in ⚙ Settings → Security. As fallbacks, the app also
reads the `OPENAI_API_KEY` environment variable, then `openai_api_key.txt` in the data folder (key on its
first line). Without a key, captions work as usual and the answer block says what's missing.

**Speech models.** On first launch, if the models aren't installed, a "One more step" screen offers
to download them (large-v3 + distil-large-v3, about 4.4 GB) from their Hugging Face repos into the
data folder's `models\`. It shows size, speed and time left, can be paused, resumes interrupted
downloads (also after a restart), and checks every file's SHA-256. Captions start as soon as it
finishes; Answer and Settings work meanwhile. Models are also found in a `models\` folder next to the
app (a source checkout, or an offline build), in either the plain or the Hugging Face cache layout.

## Run

```bash
python main.py
```

Or just double-click `run.bat`, which creates the venv and installs dependencies on first run.

To try the window and the Answer button without any audio, run `python main.py --fake` (or
double-click `run_fake.bat`). It skips audio capture and Whisper and adds a box at the bottom: type
what the other person says and press Enter, and the line plays in word by word like a live caption.
Then click **✦ Answer** as usual. (`run_fake.bat` also passes `--no-auth`, see below.)

Developer switches for the Wonuva sign-in, honored only when running from source (the built .exe
ignores them):

```bash
python dev/mock_wonuva_auth.py                      # mock Wonuva server on http://127.0.0.1:8765
python main.py --auth-url http://127.0.0.1:8765     # sign in against it (any email, password "wonuva")
python main.py --no-auth                            # skip sign-in entirely
```

Play some audio (a video, a call, music) and captions will appear once speech is detected. If nothing
is playing, WASAPI loopback capture idles by design and no captions will appear — that's expected.

## Building and publishing

```bash
build_exe.bat           # app + installer (models are downloaded by the app on first run)
build_exe.bat offline   # same, plus the models copied into the app folder (portable, ~6 GB)
build_exe.bat nosignin  # an app that doesn't ask for a Wonuva sign-in (until the endpoints are live)
```

The result in `dist\WonuvaLiveCaption\` runs on any Windows 10/11 PC without Python. Copy the
whole folder, not just the .exe. Options can be combined (`build_exe.bat nosignin offline`).

It installs dependencies plus `pyinstaller`, builds `dist\WonuvaLiveCaption\WonuvaLiveCaption.exe` from
`WonuvaLiveCaption.spec`, signs it, then builds and signs the installer
`dist\installer\WonuvaLiveCaptionSetup-<version>.exe` with [Inno Setup 6](https://jrsoftware.org/isdl.php)
(skipped with a note if Inno Setup isn't installed).

- **Installer** (`installer\WonuvaLiveCaption.iss`): per-user install into
  `%LOCALAPPDATA%\Programs\Wonuva Live Caption` (no admin prompt; all-users is offered too), Start menu
  and optional desktop shortcut, closes a running copy before upgrading, Windows 10 2004+ x64.
  Uninstalling asks whether to also delete the data folder (settings and the 4.4 GB of models).
  Keep its `AppId` unchanged forever: it's how Windows matches upgrades.
- **Code signing** (`sign.bat`): signs the app exe, the installer and its uninstaller when configured,
  otherwise builds unsigned with a warning. Set either `AZURE_SIGNING_DLIB` + `AZURE_SIGNING_METADATA`
  (Azure Trusted Signing; see `installer\signing-metadata.example.json`, sign in with `az login`) or
  `SIGN_PFX` + `SIGN_PFX_PASSWORD` (a .pfx certificate). Needs `signtool.exe` from the Windows SDK
  (or set `SIGNTOOL`). Keep the variables in a `signing-env.bat` you `call` first; it's git-ignored.
- **Update check**: a few seconds after launch the app fetches `UPDATE_URL` (`config.py`). If it names
  a newer version, a gold "Update vX.Y.Z" button appears in the title strip and opens the download
  page. Upload `installerersion.json` to that URL and bump it with each release:
  `{"version": "2.1.0", "url": "https://wonuva.com/live-caption", "notes": "one line"}`.
  Any failure (offline, 404) is only logged.

To release: bump `APP_VERSION` in `config.py`, run `build_exe.bat`, upload the installer to your
site (or storage), then update `version.json`.

## Configuration

Tweak `config.py`:

- `DEFAULT_MODEL` — the preset the app uses (default `large-v3`); `MODEL_PRESETS` maps each preset to
  a (partial, final) model pair. Changing it requires a rebuild; the app downloads the new models.
- `MAX_QUEUE_LAG_S` — how much buffered audio backlog is tolerated before older audio is dropped to
  keep captions in sync. Lower this if captions still drift behind on a slow machine.
- `SILENCE_RMS_THRESHOLD` — raise if background noise triggers false captions, lower if quiet speech
  is missed.
- `FINALIZE_SILENCE_MS` — how long a pause must be before a line is finalized.
- `DEFAULT_FONT_SIZE` / `MIN_FONT_SIZE` / `MAX_FONT_SIZE` — also adjustable live via the ⚙ settings panel.
- `OPENAI_MODEL` — the model the Answer button uses (default `gpt-4.1-mini`); `ANSWER_HISTORY_TURNS`
  and `ANSWER_MAX_TOKENS` control the context sent along and the answer length.
- `WINDOW_WIDTH` / `WINDOW_HEIGHT` — initial caption window size.
- `UPDATE_URL` — where the update check looks for `version.json` (`""` turns it off).

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
├── model_download.py        # Finds installed models; resumable, verified first-run download
├── download_view.py         # First-run "One more step" download screen
├── updater.py               # Startup check of version.json on the website
├── auth.py                  # Wonuva sign-in (OAuth 2.0 + PKCE, loopback redirect, DPAPI session)
├── signin_view.py           # "Sign in to Wonuva" lock screen
├── docs\WONUVA_AUTH_API.md  # What the Wonuva backend must implement for sign-in
├── dev\mock_wonuva_auth.py  # Mock Wonuva auth server for testing
├── download_models.py       # Command-line model download (optional)
├── assets\                  # Wonuva logo PNGs (16/32/48/128) + icon.ico for the exe
├── requirements.txt         # PyAudioWPatch, faster-whisper, numpy, scipy, CUDA libraries, openai, pypdf
├── requirements-build.txt    # pyinstaller (only needed to build the .exe)
├── WonuvaLiveCaption.spec     # PyInstaller build spec
├── build_exe.bat               # Builds the exe and the installer (signed if configured)
├── sign.bat                    # Code-signs one file (Azure Trusted Signing or .pfx)
├── installer\                  # Inno Setup script, version.json, signing metadata example
├── run.bat                      # Sets up the venv and runs from source
└── run_fake.bat                 # Same, in fake caption mode (type captions to test Answer)
```
