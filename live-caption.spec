# PyInstaller spec for Live Caption (one-folder: dist/LiveCaption/LiveCaption.exe + deps)
# Run: pyinstaller live-caption.spec
# Requires: pip install -r requirements.txt -r requirements-build.txt

import os
import sys

block_cipher = None

# Explicitly bundle sounddevice (and its _sounddevice_data) so the exe finds it
extra_datas = []
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

# Hidden imports; sounddevice needs its CFFI and data submodules for PortAudio
hidden_imports = [
    'vosk',
    'numpy',
    'numpy.core._methods',
    'numpy.lib.format',
    'sounddevice',
    '_sounddevice_data',
    'pyaudiowpatch',
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',
    'pytesseract',
    'keyboard',
    'pynput',
    'tray_win32',  # Windows tray (ctypes) for hide-on-close
]

# Exclude heavy unused deps (e.g. matplotlib pulled in by pynput) to speed build and shrink exe
excludes = [
    'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'tkinter.test', 'test', 'unittest',
]
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
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
