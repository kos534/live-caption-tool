# PyInstaller spec for Live Caption (one-folder: dist/LiveCaption/LiveCaption.exe + deps)
# Run: pyinstaller live-caption.spec
# Requires: pip install -r requirements.txt -r requirements-build.txt

import os
import sys

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Explicitly bundle sounddevice (and its _sounddevice_data) so the exe finds it
extra_datas = []
extra_binaries = []
extra_hidden = []
try:
    import sounddevice as _sd
    _sd_dir = os.path.dirname(_sd.__file__)
    extra_datas.append((_sd_dir, 'sounddevice'))
    # If sounddevice uses a separate _sounddevice_data package, include it
    try:
        import _sounddevice_data as _sdd
        _sdd_dir = os.path.dirname(_sdd.__file__)
        extra_datas.append((_sdd_dir, '_sounddevice_data'))
    except ImportError:
        pass
except ImportError:
    pass

# faster-whisper's stack (ctranslate2, onnxruntime, av) ship native shared
# libraries that PyInstaller's default import-graph analysis can miss.
# collect_all() pulls in their binaries/datas/hidden submodules explicitly,
# the same class of fix already applied above for sounddevice.
for _pkg in ('ctranslate2', 'onnxruntime', 'av', 'faster_whisper', 'tokenizers', 'huggingface_hub'):
    try:
        _datas, _binaries, _hidden = collect_all(_pkg)
        extra_datas += _datas
        extra_binaries += _binaries
        extra_hidden += _hidden
    except Exception:
        pass

# Bundle any faster-whisper model(s) pre-fetched locally via download_model.py
# (models/faster-whisper-<size>/) so the packaged exe works fully offline with
# no first-run download. Run `python download_model.py --model-size small.en`
# (or your chosen size) before building to include it.
_models_root = os.path.join(SPECPATH, 'models')
if os.path.isdir(_models_root):
    for _name in os.listdir(_models_root):
        _mdir = os.path.join(_models_root, _name)
        if os.path.isdir(_mdir) and _name.startswith('faster-whisper-'):
            extra_datas.append((_mdir, f'models/{_name}'))

# Hidden imports; sounddevice needs its CFFI and data submodules for PortAudio
hidden_imports = [
    'numpy',
    'numpy.core._methods',
    'numpy.lib.format',
    'scipy',
    'scipy.signal',
    'sounddevice',
    '_sounddevice_data',
    'pyaudiowpatch',
    'PIL',
    'PIL.Image',
    'webrtcvad',  # optional VAD backend; vad.py falls back gracefully if missing
    'faster_whisper',
    'tray_win32',  # Windows tray (ctypes) for hide-on-close
] + extra_hidden

# Exclude heavy unused deps to speed build and shrink exe. torch/torchaudio/
# torchvision are excluded defensively - nothing here should pull them in,
# but this guarantees a loud failure instead of multi-GB exe bloat if a
# future transitive dependency ever tries to.
excludes = [
    'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'torch', 'torchaudio', 'torchvision',
    'tkinter.test', 'test', 'unittest',
]
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=extra_binaries,
    datas=extra_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_sounddevice.py'],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,  # Keep exe small; avoid Windows 4GB exe limit
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-folder build: exe + dependencies in dist/LiveCaption/ (faster, more reliable than one-file)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LiveCaption',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LiveCaption',
)
