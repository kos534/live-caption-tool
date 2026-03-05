"""
Screen region selector:
  1. Draw a visible rectangle on screen as the user moves the mouse.
  2. On left-click: capture that region from the screen (screenshot).
  3. Extract text from the captured image with OCR.
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Tuple

# Optional: PIL for screen grab, pytesseract for OCR
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None  # type: ignore

pytesseract = None  # set after import and finding tesseract
try:
    import pytesseract as _pytesseract
    pytesseract = _pytesseract

    def _find_tesseract() -> str | None:
        """Return path to tesseract.exe or None. Tries config, env, PATH, then common Windows paths."""
        try:
            from config import load_settings
            cfg = load_settings()
            p = (cfg.get("tesseract_path") or "").strip()
            if p and os.path.isfile(p):
                return p
        except Exception:
            pass
        if os.environ.get("TESSERACT_CMD") and os.path.isfile(os.environ["TESSERACT_CMD"]):
            return os.environ["TESSERACT_CMD"]
        found = shutil.which("tesseract")
        if found:
            return found
        if sys.platform == "win32":
            for path in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expandvars(r"%ProgramFiles%\Tesseract-OCR\tesseract.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe"),
            ):
                if path and os.path.isfile(path):
                    return path
        return None

    _tesseract_path = _find_tesseract()
    if _tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = _tesseract_path
except ImportError:
    pass


def _get_virtual_screen_bounds(parent: tk.Tk | tk.Toplevel) -> tuple[int, int, int, int]:
    """
    Return (x, y, width, height) of the area to cover for capture.
    On Windows with multiple monitors: virtual screen spanning all displays.
    Otherwise: primary screen at (0, 0) with primary size.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            if w > 0 and h > 0:
                return (x, y, w, h)
        except Exception:
            pass
    return (0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight())


def run_region_selector(
    parent: tk.Tk | tk.Toplevel,
    on_done: Callable[[str | None, str | None], None],
    start_xy: tuple[int, int] | None = None,
) -> None:
    """
    Show a fullscreen overlay. Selection starts at start_xy (screen coords at hotkey press) or current mouse.
    Move mouse to draw the rectangle; left-click to capture and run OCR.
    """
    root = parent
    initial_xy = start_xy  # (x, y) in screen coords
    # Cover all monitors on Windows; primary only elsewhere
    scr_x, scr_y, scr_w, scr_h = _get_virtual_screen_bounds(root)

    sel = tk.Toplevel(root)
    sel.overrideredirect(True)
    sel.attributes("-topmost", True)
    sel.attributes("-alpha", 0.3)
    sel.configure(bg="#000000", cursor="arrow")
    sel.geometry(f"{scr_w}x{scr_h}+{scr_x}+{scr_y}")

    # Hint so user sees the overlay is active
    hint = tk.Label(sel, text="Move mouse to draw area • Left-click to capture • Esc to cancel", fg="white", bg="#000000", font=("Segoe UI", 12))
    hint.pack(pady=12)
    canvas = tk.Canvas(sel, highlightthickness=0, bg="#000000", cursor="arrow", width=scr_w, height=scr_h)
    canvas.pack(fill=tk.BOTH, expand=True)

    start_x: int | None = None
    start_y: int | None = None
    rect_id = None
    result_sent = [False]  # avoid double callback

    def send_result(text: str | None, error: str | None = None) -> None:
        if result_sent[0]:
            return
        result_sent[0] = True
        try:
            sel.destroy()
        except tk.TclError:
            pass
        root.after(0, lambda: on_done(text, error))

    def on_cancel() -> None:
        send_result(None)

    def init_start_position() -> None:
        """Set start from hotkey-time mouse position (or current if not provided) and create initial rect."""
        nonlocal start_x, start_y, rect_id
        sel.update_idletasks()
        sel.update()
        # Use canvas position (not overlay): canvas is below the hint label so Y would be wrong with sel position
        cx = canvas.winfo_rootx()
        cy = canvas.winfo_rooty()
        if initial_xy is not None:
            start_x = initial_xy[0] - cx
            start_y = initial_xy[1] - cy
        else:
            start_x = sel.winfo_pointerx() - cx
            start_y = sel.winfo_pointery() - cy
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        start_x = max(0, min(start_x, cw - 1))
        start_y = max(0, min(start_y, ch - 1))
        # Start with 0x0 rect; it grows as user moves mouse. 1px border.
        rect_id = canvas.create_rectangle(
            start_x, start_y, start_x, start_y,
            outline="white", width=1, fill=""
        )
        canvas.tag_raise(rect_id)
        sel.lift()
        sel.attributes("-topmost", True)
        sel.focus_force()
        sel.update()

    def on_motion(event: tk.Event) -> None:
        if rect_id is None or start_x is None or start_y is None:
            return
        x1 = min(start_x, event.x)
        y1 = min(start_y, event.y)
        x2 = max(start_x, event.x)
        y2 = max(start_y, event.y)
        canvas.coords(rect_id, x1, y1, x2, y2)
        canvas.tag_raise(rect_id)
        canvas.update_idletasks()

    def on_left_click(event: tk.Event) -> None:
        """End selection: capture screen region, then extract text from image with OCR."""
        if rect_id is None or start_x is None or start_y is None:
            on_cancel()
            return
        x1, y1, x2, y2 = canvas.coords(rect_id)
        x1, x2 = int(min(x1, x2)), int(max(x1, x2))
        y1, y2 = int(min(y1, y2)), int(max(y1, y2))
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            on_cancel()
            return

        if ImageGrab is None:
            send_result(None, "Pillow (PIL) not installed. pip install Pillow")
            return
        if pytesseract is None:
            send_result(None, "pytesseract not installed. pip install pytesseract")
            return

        cx = canvas.winfo_rootx()
        cy = canvas.winfo_rooty()
        bbox = (int(cx + x1), int(cy + y1), int(cx + x2), int(cy + y2))
        sel.withdraw()
        sel.update()

        def do_capture() -> None:
            err: str | None = None
            text: str | None = None
            try:
                time.sleep(0.1)
                # On Windows, grab(all_screens=True) captures all monitors; then crop to selection.
                # Plain grab(bbox=...) often only captures the primary display.
                if sys.platform == "win32":
                    try:
                        full = ImageGrab.grab(all_screens=True)
                        if full is not None and full.size[0] > 0 and full.size[1] > 0:
                            # Virtual screen origin: image (0,0) = screen (scr_x, scr_y)
                            left = max(0, min(bbox[0] - scr_x, full.size[0] - 1))
                            top = max(0, min(bbox[1] - scr_y, full.size[1] - 1))
                            right = max(left + 1, min(bbox[2] - scr_x, full.size[0]))
                            bottom = max(top + 1, min(bbox[3] - scr_y, full.size[1]))
                            img = full.crop((left, top, right, bottom))
                        else:
                            img = ImageGrab.grab(bbox=bbox)
                    except TypeError:
                        img = ImageGrab.grab(bbox=bbox)
                else:
                    img = ImageGrab.grab(bbox=bbox)
                if img is None or img.size[0] < 2 or img.size[1] < 2:
                    err = "Screenshot failed or area too small."
                else:
                    # Ensure tesseract path is set (e.g. from config)
                    _path = _find_tesseract()
                    if _path:
                        pytesseract.pytesseract.tesseract_cmd = _path
                    # Preprocess for better OCR: grayscale; scale up small regions so Tesseract can read
                    if img.mode != "L":
                        img = img.convert("L")
                    w, h = img.size
                    min_side = 150
                    if w > 0 and h > 0 and (w < min_side or h < min_side):
                        scale = max(2, (min_side + min(w, h) - 1) // min(w, h))
                        from PIL import Image as PILImage
                        img = img.resize((w * scale, h * scale), PILImage.LANCZOS)
                    # PSM 6 = single block of text; PSM 3 = default (auto)
                    text = pytesseract.image_to_string(img, config="--psm 6").strip()
                    if not text:
                        text = pytesseract.image_to_string(img, config="--psm 3").strip()
            except Exception as e:
                err = str(e)
                if "tesseract" in err.lower() or "not found" in err.lower():
                    err = (
                        "Tesseract not found. Install from https://github.com/UB-Mannheim/tesseract/wiki "
                        "then add to PATH, or set 'Tesseract path' in the app (Save defaults)."
                    )
            root.after(0, lambda: send_result(text, err))

        threading.Thread(target=do_capture, daemon=True).start()

    sel.bind("<Escape>", lambda e: on_cancel())
    sel.bind("<Motion>", on_motion)
    canvas.bind("<Motion>", on_motion)
    canvas.bind("<Button-1>", on_left_click)

    sel.focus_set()
    sel.grab_set()
    sel.lift()
    sel.attributes("-topmost", True)
    sel.update_idletasks()
    sel.update()
    # Start selection once overlay is drawn
    sel.after(150, init_start_position)


# Modifier names for parsing and display
MODIFIER_NAMES = {"ctrl", "control", "alt", "shift", "win", "cmd", "super"}


def parse_hotkey(hotkey: str) -> tuple[bool, bool, bool, bool, str]:
    """Parse 'Ctrl+Alt+Q' into (ctrl, alt, shift, win, key). Key is one character or F1-style."""
    if not hotkey or not hotkey.strip():
        return (True, False, False, False, "q")
    parts = [p.strip() for p in hotkey.replace("+", " ").split() if p.strip()]
    ctrl = alt = shift = win = False
    key = "q"
    for p in parts:
        lower = p.lower()
        if lower in ("ctrl", "control"):
            ctrl = True
        elif lower == "alt":
            alt = True
        elif lower == "shift":
            shift = True
        elif lower in ("win", "cmd", "super"):
            win = True
        else:
            key = lower if len(p) > 1 else lower  # F1 -> f1, Q -> q
    return (ctrl, alt, shift, win, key)


def build_hotkey_string(ctrl: bool, alt: bool, shift: bool, win: bool, key: str) -> str:
    """Build 'Ctrl+Alt+Q' from modifier flags and key."""
    parts = []
    if ctrl:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if shift:
        parts.append("Shift")
    if win:
        parts.append("Win")
    k = (key or "q").strip()
    if k:
        parts.append(k.upper() if len(k) <= 1 else (k[0].upper() + k[1:].lower()))
    return "+".join(parts) if parts else "Ctrl+Q"


def hotkey_string_to_pynput(hotkey: str) -> str:
    """Convert 'Ctrl+Q' style to pynput format '<<ctrl>>+q'."""
    if not hotkey or not hotkey.strip():
        return "<<ctrl>>+q"
    parts = [p.strip() for p in hotkey.replace("+", " ").split() if p.strip()]
    if not parts:
        return "<<ctrl>>+q"
    mods = []
    key = None
    for p in parts:
        lower = p.lower()
        if lower in ("ctrl", "control"):
            mods.append("<<ctrl>>")
        elif lower == "alt":
            mods.append("<<alt>>")
        elif lower == "shift":
            mods.append("<<shift>>")
        elif lower in ("win", "cmd", "super"):
            mods.append("<<cmd>>")  # Windows/Super key on pynput
        else:
            key = lower
    if not key:
        return "<<ctrl>>+q"
    return "+".join(mods + [key])


def hotkey_to_tk_bind_sequence(hotkey: str) -> str:
    """Convert 'Ctrl+Q' to Tk bind sequence '<Control-q>'. Works when main window has focus."""
    if not hotkey or not hotkey.strip():
        return "<Control-q>"
    parts = [p.strip() for p in hotkey.replace("+", " ").split() if p.strip()]
    if not parts:
        return "<Control-q>"
    mods = []
    key = None
    for p in parts:
        lower = p.lower()
        if lower in ("ctrl", "control"):
            mods.append("Control")
        elif lower == "alt":
            mods.append("Alt")
        elif lower == "shift":
            mods.append("Shift")
        elif lower in ("win", "cmd", "super"):
            mods.append("Meta")  # Windows key in Tk
        else:
            key = lower  # Tk uses lowercase for letter keys in bind (e.g. <Control-q>)
    if not key:
        return "<Control-q>"
    # Tk: <Control-Alt-q> or <Control-F1>
    seq = "-".join(mods + [key])
    return f"<{seq}>"


def hotkey_string_to_keyboard_lib(hotkey: str) -> str:
    """Convert 'Ctrl+Alt+Q' to keyboard library format 'ctrl+alt+q' (works when app not focused)."""
    if not hotkey or not hotkey.strip():
        return "ctrl+q"
    parts = [p.strip().lower() for p in hotkey.replace("+", " ").split() if p.strip()]
    if not parts:
        return "ctrl+q"
    mod_map = {"control": "ctrl", "ctrl": "ctrl", "alt": "alt", "shift": "shift", "win": "windows", "cmd": "windows", "super": "windows"}
    out = []
    key = None
    for p in parts:
        if p in mod_map:
            m = mod_map[p]
            if m not in out:
                out.append(m)
        else:
            key = p
    if not key:
        return "ctrl+q"
    return "+".join(out + [key])


# Virtual key codes (Windows)
_VK = {
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "menu": 0x12,
    "shift": 0x10,
    "win": 0x5B, "cmd": 0x5B, "super": 0x5B,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK[_c] = 0x41 + ord(_c) - ord("a")  # A=0x41
for _i in range(10):
    _VK[str(_i)] = 0x30 + _i  # 0=0x30
for _i in range(1, 13):
    _VK[f"f{_i}"] = 0x70 + (_i - 1)  # F1=0x70, F12=0x7B


def _parse_hotkey_to_vk(hotkey: str) -> tuple[bool, bool, bool, bool, int]:
    """Return (ctrl, alt, shift, win, key_vk). key_vk is the main key virtual code."""
    ctrl = alt = shift = win = False
    key_vk = 0x51  # Q
    if not hotkey or not hotkey.strip():
        return (True, False, False, False, 0x51)
    parts = [p.strip().lower() for p in hotkey.replace("+", " ").split() if p.strip()]
    for p in parts:
        if p in ("ctrl", "control"):
            ctrl = True
        elif p == "alt":
            alt = True
        elif p == "shift":
            shift = True
        elif p in ("win", "cmd", "super"):
            win = True
        elif p in _VK:
            key_vk = _VK[p]
        else:
            key_vk = _VK.get(p, 0x51)
    return (ctrl, alt, shift, win, key_vk)


def _start_win_hook(hotkey: str, trigger_queue: queue.Queue[int]) -> Tuple[bool, Callable[[], None] | None]:
    """Start Windows low-level keyboard hook. Returns (success, stop_callable)."""
    if sys.platform != "win32":
        return (False, None)
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return (False, None)
    ctrl, alt, shift, win, key_vk = _parse_hotkey_to_vk(hotkey)
    user32 = ctypes.windll.user32
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_QUIT = 0x0012
    VK_CONTROL, VK_MENU, VK_SHIFT = 0x11, 0x12, 0x10
    VK_LWIN, VK_RWIN = 0x5B, 0x5C
    hook_id = [None]
    running = [True]
    installed = threading.Event()
    thread_id = [None]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    LRESULT = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p]
    user32.CallNextHookEx.restype = LRESULT

    def low_level_handler(nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) and lParam:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.vkCode == key_vk:
                c = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                a = user32.GetAsyncKeyState(VK_MENU) & 0x8000
                s = user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
                w = (user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
                if c == (0x8000 if ctrl else 0) and a == (0x8000 if alt else 0) and s == (0x8000 if shift else 0) and w == (0x8000 if win else 0):
                    try:
                        trigger_queue.put_nowait(1)
                    except Exception:
                        pass
        hhook = ctypes.c_void_p(hook_id[0]) if hook_id[0] is not None else ctypes.c_void_p(0)
        lp = ctypes.c_void_p(lParam)
        return user32.CallNextHookEx(hhook, nCode, wParam, lp)

    CMPFUNC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p)
    hook_proc = CMPFUNC(low_level_handler)

    def hook_thread() -> None:
        hook_id[0] = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc, None, 0)
        installed.set()
        if not hook_id[0]:
            return
        msg = wintypes.MSG()
        while running[0] and user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if hook_id[0]:
            user32.UnhookWindowsHookEx(hook_id[0])

    def stop() -> None:
        running[0] = False
        tid = thread_id[0]
        if tid is not None:
            try:
                user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass

    t = threading.Thread(target=hook_thread, daemon=True)
    t.start()
    thread_id[0] = t.ident
    installed.wait(timeout=1.0)
    if hook_id[0] is None:
        return (False, None)
    return (True, stop)


def start_hotkey_listener(
    hotkey: str, on_activate: Callable[[], None], trigger_queue: queue.Queue[int] | None = None
) -> tuple[bool, str, Callable[[], None]]:
    """
    Register a global hotkey. Returns (success, method_used, stop_callable).
    Call stop_callable() to unregister before re-registering with a new hotkey.
    """
    def noop() -> None:
        pass

    # 1. On Windows: try low-level hook first (works when another app is focused, no admin)
    if sys.platform == "win32" and trigger_queue is not None:
        ok, stop_fn = _start_win_hook(hotkey, trigger_queue)
        if ok and stop_fn is not None:
            return (True, "win_hook", stop_fn)
    # 2. pynput
    try:
        from pynput import keyboard as pynput_kb
        combo = hotkey_string_to_pynput(hotkey)
        stop_event = threading.Event()

        def run() -> None:
            try:
                with pynput_kb.GlobalHotKeys({combo: on_activate}) as h:
                    stop_event.wait()
            except Exception:
                pass

        t = threading.Thread(target=run, daemon=True)
        t.start()

        def stop() -> None:
            stop_event.set()

        return (True, "pynput", stop)
    except ImportError:
        pass
    except Exception:
        pass
    # 3. keyboard library
    try:
        import keyboard as kb
        combo = hotkey_string_to_keyboard_lib(hotkey)
        hook_id = kb.add_hotkey(combo, on_activate, suppress=False)

        def stop() -> None:
            try:
                kb.remove_hotkey(hook_id)
            except Exception:
                pass

        return (True, "keyboard", stop)
    except ImportError:
        pass
    except Exception:
        pass
    return (False, "none", noop)
