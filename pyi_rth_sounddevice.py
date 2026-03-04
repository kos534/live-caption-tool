# PyInstaller runtime hook: ensure bundle root is first on sys.path so sounddevice is found.
import os
import sys

if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if base and base not in sys.path:
        sys.path.insert(0, base)
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        pass
    try:
        import pyaudiowpatch  # noqa: F401
    except ImportError:
        pass
