"""Keep the caption window out of screen sharing and screen recording (Windows).

Uses SetWindowDisplayAffinity on the caption window itself:
  - WDA_EXCLUDEFROMCAPTURE (Windows 10 version 2004+): the window is invisible in screen shares,
    recordings and screenshots (Teams, Zoom, Meet, OBS, Snipping Tool, ...); viewers see what's
    behind it. It stays fully visible on your own screen.
  - WDA_MONITOR (older Windows): fallback; captures show a black box where the window is.
"""

import ctypes
import logging

log = logging.getLogger(__name__)

WDA_NONE = 0x00
WDA_MONITOR = 0x01
WDA_EXCLUDEFROMCAPTURE = 0x11
GA_ROOT = 2


def _top_level_hwnd(root) -> int:
    """The Win32 handle of a Tk root window's top-level frame (what screen capture sees)."""
    root.update_idletasks()  # make sure the native window exists
    user32 = ctypes.windll.user32
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    return user32.GetAncestor(root.winfo_id(), GA_ROOT) or root.winfo_id()


def set_screen_share_hidden(window, hidden: bool) -> bool:
    """Hide (hidden=True) or show the given CaptionWindow (or Tk root) in screen capture.

    Returns True if the change was applied. Only this app's own window is changed. Failure is
    logged and harmless: the window just keeps its previous visibility in screen shares.
    """
    root = getattr(window, "root", window)
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        hwnd = _top_level_hwnd(root)
        if not hidden:
            if user32.SetWindowDisplayAffinity(hwnd, WDA_NONE):
                log.info("Caption window visible in screen sharing")
                return True
        else:
            for mode, name in ((WDA_EXCLUDEFROMCAPTURE, "excluded from capture"), (WDA_MONITOR, "black in captures")):
                if user32.SetWindowDisplayAffinity(hwnd, mode):
                    log.info("Caption window hidden from screen sharing (%s)", name)
                    return True
        log.warning("Could not change screen-share visibility (error %d)", ctypes.GetLastError())
    except Exception:
        log.exception("Could not change screen-share visibility")
    return False


def hide_window_from_screen_share(window) -> bool:
    """Hide the given CaptionWindow (or Tk root) from screen capture. Returns True on success."""
    return set_screen_share_hidden(window, True)
