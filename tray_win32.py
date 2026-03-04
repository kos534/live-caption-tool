"""
Windows system tray icon using ctypes (no pystray). Used so X button can hide to tray.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import threading
from typing import Callable

if sys.platform != "win32":
    raise RuntimeError("tray_win32 is Windows only")

# Constants
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_SHOWTIP = 0x80
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
IDI_APPLICATION = 32512
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
CW_USEDEFAULT = -2147483648
WS_OVERLAPPED = 0
WM_DESTROY = 0x0002
WM_TRAYICON = WM_USER + 1
TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

NOTIFYICONDATAW_SIZE = 504  # Win7+ expected size for Shell_NotifyIconW

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.wintypes.UINT),
        ("uFlags", ctypes.wintypes.UINT),
        ("uCallbackMessage", ctypes.wintypes.UINT),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("szTip", ctypes.wintypes.WCHAR * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.wintypes.WCHAR * 256),
        ("uVersion", ctypes.wintypes.UINT),
        ("szInfoTitle", ctypes.wintypes.WCHAR * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.wintypes.HANDLE),
    ]


# WNDPROC type (LPARAM/WPARAM as c_void_p on 64-bit to avoid overflow)
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
)

_win_class_registered = False
_win_class_atom = None


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HANDLE),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HANDLE),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ("hIconSm", ctypes.wintypes.HANDLE),
    ]


_tray_callbacks: dict[int, tuple[Callable[[], None], Callable[[], None]]] = {}
_tray_hwnds: dict[int, ctypes.wintypes.HWND] = {}
_tray_threads: dict[int, threading.Thread] = {}
_wndproc_ref = None  # keep reference so it is not garbage collected

_win_class_registered = False
_win_class_atom = None


def _register_class() -> int:
    global _win_class_registered, _win_class_atom, _wndproc_ref
    if _win_class_registered:
        return _win_class_atom

    def wndproc(hwnd, msg, wparam, lparam):
        h = int(hwnd) if hwnd else 0
        lp = int(lparam) if lparam is not None else 0
        if msg == WM_TRAYICON:
            if lp == WM_LBUTTONUP or lp == WM_RBUTTONUP or lp == WM_CONTEXTMENU:
                if h in _tray_callbacks:
                    on_activate, on_quit = _tray_callbacks[h]
                    if lp == WM_RBUTTONUP or lp == WM_CONTEXTMENU:
                        _show_context_menu(ctypes.wintypes.HWND(hwnd), h)
                    else:
                        on_activate()
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
        return user32.DefWindowProcW(hwnd, msg, ctypes.wintypes.WPARAM(int(wparam or 0)), ctypes.wintypes.LPARAM(int(lparam or 0)))

    _wndproc_ref = WNDPROC(wndproc)
    hinst = kernel32.GetModuleHandleW(None)
    class_name = "LiveCaptionTray"
    wc = WNDCLASSEXW(
        cbSize=ctypes.sizeof(WNDCLASSEXW),
        style=CS_HREDRAW | CS_VREDRAW,
        lpfnWndProc=_wndproc_ref,
        cbClsExtra=0,
        cbWndExtra=0,
        hInstance=hinst,
        hIcon=0,
        hCursor=0,
        hbrBackground=0,
        lpszMenuName=None,
        lpszClassName=class_name,
        hIconSm=0,
    )
    _win_class_atom = user32.RegisterClassExW(ctypes.byref(wc))
    _win_class_registered = True
    return _win_class_atom


def _message_loop(hwnd: ctypes.wintypes.HWND, hwnd_key: int) -> None:
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0):
        if msg.hwnd == hwnd and msg.message == WM_TRAYICON:
            if msg.lParam == WM_RBUTTONUP or msg.lParam == WM_CONTEXTMENU:
                _show_context_menu(hwnd, hwnd_key)
                continue
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _show_context_menu(hwnd: ctypes.wintypes.HWND, hwnd_key: int) -> None:
    if hwnd_key not in _tray_callbacks:
        return
    on_activate, on_quit = _tray_callbacks[hwnd_key]
    # CreatePopupMenu, AppendMenuW, TrackPopupMenuEx
    CreatePopupMenu = user32.CreatePopupMenu
    CreatePopupMenu.restype = ctypes.wintypes.HMENU
    AppendMenuW = user32.AppendMenuW
    TrackPopupMenuEx = user32.TrackPopupMenuEx
    GetCursorPos = user32.GetCursorPos

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    menu = CreatePopupMenu()
    if not menu:
        on_activate()
        return
    AppendMenuW(menu, MF_STRING, 1, "Show Live Caption")
    AppendMenuW(menu, MF_SEPARATOR, 0, None)
    AppendMenuW(menu, MF_STRING, 2, "Quit")
    pt = POINT()
    GetCursorPos(ctypes.byref(pt))
    user32.SetForegroundWindow(hwnd)
    cmd = TrackPopupMenuEx(
        menu,
        TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_NONOTIFY | TPM_RETURNCMD,
        pt.x,
        pt.y,
        hwnd,
        None,
    )
    user32.DestroyMenu(menu)
    user32.PostMessageW(hwnd, 0, 0, 0)
    if cmd == 1:
        on_activate()
    elif cmd == 2:
        on_quit()


def run_tray(
    tooltip: str,
    on_activate: Callable[[], None],
    on_quit: Callable[[], None],
) -> Callable[[], None]:
    """
    Add a tray icon. on_activate = show window, on_quit = exit app.
    Returns a stop() function to remove the icon and exit the message loop.
    """
    _register_class()
    hinst = kernel32.GetModuleHandleW(None)
    HWND_MESSAGE = ctypes.wintypes.HWND(-3)
    hwnd = user32.CreateWindowExW(
        0,
        "LiveCaptionTray",
        "",
        0,
        0,
        0,
        0,
        0,
        HWND_MESSAGE,
        0,
        hinst,
        None,
    )
    if not hwnd:
        return lambda: None
    hwnd_key = int(hwnd)
    icon_id = 1
    _tray_hwnds[icon_id] = hwnd
    _tray_callbacks[hwnd_key] = (on_activate, on_quit)

    # Use default icon: NIF_ICON optional; omit icon for simplicity (tray shows default)
    hicon = None
    nid = NOTIFYICONDATAW()
    nid.cbSize = NOTIFYICONDATAW_SIZE
    nid.hWnd = hwnd
    nid.uID = icon_id
    nid.uFlags = NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = 0
    nid.szTip = tooltip[:127]
    if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
        _tray_callbacks.pop(hwnd_key, None)
        _tray_hwnds.pop(icon_id, None)
        return lambda: None

    def stop() -> None:
        nid_del = NOTIFYICONDATAW()
        nid_del.cbSize = NOTIFYICONDATAW_SIZE
        nid_del.hWnd = hwnd
        nid_del.uID = icon_id
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid_del))
        _tray_callbacks.pop(hwnd_key, None)
        _tray_hwnds.pop(icon_id, None)
        user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)

    def loop() -> None:
        _message_loop(hwnd, hwnd_key)

    t = threading.Thread(target=loop, daemon=True)
    _tray_threads[icon_id] = t
    t.start()
    return stop
