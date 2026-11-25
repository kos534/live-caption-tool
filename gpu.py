"""CUDA runtime setup for faster-whisper / CTranslate2 on Windows.

CTranslate2 needs cuBLAS and cuDNN DLLs at runtime. They come from the nvidia-cublas-cu12 and
nvidia-cudnn-cu12 pip packages (see requirements.txt), whose DLLs live in
site-packages/nvidia/<pkg>/bin, or in <exe>/_internal/nvidia/<pkg>/bin in the frozen build.
Those folders aren't on the DLL search path by default, so register them before any model
is loaded.
"""

import logging
import os
import sys
from pathlib import Path


def _nvidia_roots():
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "nvidia")
    try:
        import nvidia  # namespace package provided by the nvidia-*-cu12 wheels

        roots.extend(Path(p) for p in nvidia.__path__)
    except ImportError:
        pass
    return list(dict.fromkeys(r.resolve() for r in roots))  # frozen: both point at the same dir


def register_cuda_dlls():
    for root in _nvidia_roots():
        for bin_dir in root.glob("*/bin"):
            if not bin_dir.is_dir():
                continue
            logging.getLogger(__name__).info("CUDA DLL dir: %s", bin_dir)
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(str(bin_dir))
            except (AttributeError, OSError):
                pass


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
