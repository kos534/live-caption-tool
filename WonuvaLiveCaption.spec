# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# CUDA runtime DLLs for GPU inference; gpu.py adds _internal/nvidia/*/bin to the DLL search path.
cuda_binaries = collect_dynamic_libs('nvidia.cublas') + collect_dynamic_libs('nvidia.cudnn')

# faster-whisper's non-Python assets, notably the Silero VAD model (assets/silero_vad_v6.onnx)
# used by vad_filter=True. PyInstaller only picks up code, so these must be listed explicitly.
whisper_datas = collect_data_files('faster_whisper')

# App logo/icons, loaded at runtime from _internal/assets (config.ASSETS_DIR).
app_datas = [('assets/*.png', 'assets')]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=cuda_binaries,
    datas=whisper_datas + app_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WonuvaLiveCaption',
    icon='assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WonuvaLiveCaption',
)
