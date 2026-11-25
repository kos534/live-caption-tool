"""Allow only one running copy of the app (Windows).

The first copy creates a named mutex and holds it until it exits. A second launch finds the
mutex already exists, brings the running caption window to the front, and quits.
"""

import ctypes

MUTEX_NAME = "Local\\WonuvaLiveCaption.SingleInstance"  # per Windows session (per signed-in user)
ERROR_ALREADY_EXISTS = 183
SW_SHOWNORMAL = 1

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
_mutex = None  # held for the life of the process; Windows releases it when the app exits


def acquire() -> bool:
    """True if this is the only running copy (and claim that), False if another copy is running."""
    global _mutex
    handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # couldn't check: don't block the app from starting
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _mutex = handle
    return True


def focus_existing(title: str) -> bool:
    """Bring the running copy's window (found by its title) to the front."""
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOWNORMAL)
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    return True
