"""
Live Caption — capture WhatsApp/Viber (or any) call audio and show real-time captions.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk
from tkinter import ttk, font as tkfont, filedialog

from audio_capture import list_devices
from area_capture import build_hotkey_string, hotkey_to_tk_bind_sequence, parse_hotkey, run_region_selector, start_hotkey_listener
from caption_engine import find_model_dir, run_caption_engine
from config import load_settings, save_settings
from overlay import CaptionOverlay


def _get_screen_cursor_pos(root: tk.Tk) -> tuple[int, int]:
    """Return current mouse position in screen coordinates (reliable across monitors/DPI)."""
    if sys.platform == "win32":
        try:
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)
        except Exception:
            pass
    try:
        return (root.winfo_pointerxy())
    except Exception:
        return (0, 0)


def main() -> None:
    model_dir = find_model_dir()
    devices = list_devices()
    if not devices:
        return

    settings = load_settings()
    stop_event = threading.Event()
    overlay: CaptionOverlay | None = None
    overlay_root: tk.Tk | None = None
    is_captioning = False

    def start_captioning(device_index: int | None, is_loopback: bool) -> None:
        nonlocal overlay, overlay_root, stop_event
        stop_event.clear()
        if overlay is None:
            w = max(200, min(1200, int(caption_width_var.get())))
            h = max(80, min(600, int(caption_height_var.get())))
            fs = max(8, min(72, int(font_size_var.get())))
            overlay = CaptionOverlay(
                max_lines=4,
                font_size=fs,
                width=w,
                height=h,
                parent=root,
            )
            overlay_root = overlay._root

        def on_main_thread(f: Callable[[], None]) -> None:
            if overlay_root and overlay_root.winfo_exists():
                overlay_root.after(0, f)

        def on_partial(text: str) -> None:
            on_main_thread(lambda: overlay.set_partial(text))

        def on_final(text: str) -> None:
            on_main_thread(lambda: overlay.append_final(text))

        run_caption_engine(
            model_dir,
            device_index,
            on_partial=on_partial,
            on_final=on_final,
            stop_event=lambda: stop_event.is_set(),
            use_loopback=is_loopback,
        )
        overlay._root.lift()
        overlay._root.attributes("-topmost", True)

    def stop_captioning() -> None:
        stop_event.set()
        nonlocal overlay, overlay_root
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
            overlay = None
            overlay_root = None

    def apply_settings() -> None:
        try:
            w = max(200, min(1200, int(caption_width_var.get())))
            h = max(80, min(600, int(caption_height_var.get())))
            fs = max(8, min(72, int(font_size_var.get())))
            hk = build_hotkey_string(
                ctrl_hk_var.get(), alt_hk_var.get(), shift_hk_var.get(), win_hk_var.get(),
                capture_key_var.get().strip() or "q",
            )
            tp = tesseract_path_var.get().strip()
            save_settings({"caption_width": w, "caption_height": h, "font_size": fs, "capture_hotkey": hk, "tesseract_path": tp})
            status_var.set("Settings saved.")
            reregister_hotkey()
        except (ValueError, tk.TclError):
            status_var.set("Please enter valid numbers.")

    def copy_to_os_clipboard(text: str) -> None:
        """Copy plain text to OS clipboard so user can paste anywhere."""
        if not text:
            return
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                CF_UNICODETEXT = 13
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                user32.OpenClipboard(0)
                user32.EmptyClipboard()
                data = text.encode("utf-16-le")
                size = len(data) + 2  # +2 for UTF-16 null terminator
                h = kernel32.GlobalAlloc(0x0042, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
                ptr = kernel32.GlobalLock(h)
                ctypes.memmove(ptr, data, len(data))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(CF_UNICODETEXT, h)
                user32.CloseClipboard()
                return
            except Exception:
                pass
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
        except tk.TclError:
            pass

    def on_area_capture_done(text: str | None, error: str | None = None) -> None:
        root.lift()
        root.focus_force()
        if error:
            status_var.set(f"Capture failed: {error}")
            return
        if text is None:
            status_var.set("Area capture cancelled or OCR unavailable.")
            return
        if not text.strip():
            status_var.set("No text detected in selected area.")
            return
        copy_to_os_clipboard(text)
        if overlay is not None:
            overlay.append_final(text)
            status_var.set("Area text captured and copied to clipboard.")
        else:
            status_var.set("Area text copied to clipboard.")

    _last_area_selector_time = [0.0]
    DEBOUNCE_SEC = 0.5

    def start_area_selector() -> None:
        now = time.monotonic()
        if now - _last_area_selector_time[0] < DEBOUNCE_SEC:
            return
        _last_area_selector_time[0] = now
        # Mouse position at hotkey press = start of selection (screen coords)
        px, py = _get_screen_cursor_pos(root)
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.after(80, lambda: run_region_selector(root, _after_capture, start_xy=(px, py)))

    def _after_capture(text: str | None, error: str | None = None) -> None:
        root.attributes("-topmost", False)
        on_area_capture_done(text, error)

    root = tk.Tk()
    root.title("Live Caption")
    root.geometry("600x560")
    root.minsize(500, 480)
    root.resizable(True, True)
    root.minsize(440, 420)

    # Styles: primary button and section spacing
    toggle_btn_style: str | None = None
    try:
        style = ttk.Style()
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(24, 12))
        toggle_btn_style = "Primary.TButton"
    except tk.TclError:
        pass
    root.option_add("*Font", ("Segoe UI", 10))

    main = ttk.Frame(root, padding=(20, 20))
    main.pack(fill=tk.BOTH, expand=True)

    # Need these for on_start/on_stop; create vars early for status_var
    status_var = tk.StringVar(value="Choose an audio source and click Start.")
    device_var = tk.StringVar(value=devices[0].name if devices else "")
    caption_width_var = tk.StringVar(value=str(settings["caption_width"]))
    caption_height_var = tk.StringVar(value=str(settings["caption_height"]))
    font_size_var = tk.StringVar(value=str(settings["font_size"]))
    # Hotkey: modifiers (checkboxes) + single key (must come from saved config)
    _hotkey_str = (settings.get("capture_hotkey") or "").strip() or "Ctrl+Q"
    _hc, _ha, _hs, _hw, _hk = parse_hotkey(_hotkey_str)
    ctrl_hk_var = tk.BooleanVar(value=_hc)
    alt_hk_var = tk.BooleanVar(value=_ha)
    shift_hk_var = tk.BooleanVar(value=_hs)
    win_hk_var = tk.BooleanVar(value=_hw)
    capture_key_var = tk.StringVar(value=_hk.upper() if len(_hk) <= 1 else (_hk[0].upper() + _hk[1:].lower()))
    tesseract_path_var = tk.StringVar(value=settings.get("tesseract_path", ""))

    def on_toggle() -> None:
        nonlocal is_captioning
        if is_captioning:
            stop_captioning()
            is_captioning = False
            toggle_btn.configure(text="Start")
            status_var.set("Stopped.")
        else:
            name = device_var.get()
            dev = next((d for d in devices if d.name == name), devices[0] if devices else None)
            if not dev:
                return
            try:
                w = max(200, min(1200, int(caption_width_var.get())))
                h = max(80, min(600, int(caption_height_var.get())))
                fs = max(8, min(72, int(font_size_var.get())))
                hk = build_hotkey_string(
                    ctrl_hk_var.get(), alt_hk_var.get(), shift_hk_var.get(), win_hk_var.get(),
                    capture_key_var.get().strip() or "q",
                )
                tp = (tesseract_path_var.get() or "").strip()
                save_settings({"caption_width": w, "caption_height": h, "font_size": fs, "capture_hotkey": hk, "tesseract_path": tp})
                start_captioning(dev.index, dev.is_loopback)
                is_captioning = True
                toggle_btn.configure(text="Stop")
                status_var.set("Capturing. Drag caption window to move.")
            except FileNotFoundError as e:
                status_var.set(str(e))
            except Exception as e:
                status_var.set(str(e))

    # ---- Section 1: Audio source (choose first, then start) ----
    audio_frame = ttk.LabelFrame(main, text="  Audio source  ", padding=(14, 12))
    audio_frame.pack(fill=tk.X, pady=(0, 16))
    ttk.Label(audio_frame, text="Capture from").pack(anchor=tk.W)
    combo = ttk.Combobox(audio_frame, textvariable=device_var, height=8, state="readonly")
    combo["values"] = [d.name for d in devices]
    combo.pack(fill=tk.X, pady=(6, 0))

    # ---- Section 2: Primary action ----
    ctrl_frame = ttk.Frame(main)
    ctrl_frame.pack(fill=tk.X, pady=(0, 20))
    toggle_btn = ttk.Button(ctrl_frame, text="Start", command=on_toggle)
    if toggle_btn_style:
        toggle_btn.configure(style=toggle_btn_style)
    toggle_btn.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(ctrl_frame, text="Start captioning; click again to stop.", foreground="gray", font=("Segoe UI", 9), wraplength=520).pack(anchor=tk.W)

    # ---- Section 3: Caption window (optional tweaks) ----
    opts_frame = ttk.LabelFrame(main, text="  Caption window  ", padding=(14, 12))
    opts_frame.pack(fill=tk.X, pady=(0, 16))
    grid = ttk.Frame(opts_frame)
    grid.pack(fill=tk.X)
    for c in (1, 3, 5):
        grid.columnconfigure(c, weight=1, minsize=60)
    label_opts = {"sticky": tk.W, "padx": (0, 8), "pady": 4}
    field_opts = {"sticky": tk.W, "pady": 4}
    ttk.Label(grid, text="Width", width=10, anchor=tk.W).grid(row=0, column=0, **label_opts)
    ttk.Spinbox(grid, from_=200, to=1200, width=8, textvariable=caption_width_var).grid(row=0, column=1, padx=(0, 20), **field_opts)
    ttk.Label(grid, text="Height", width=10, anchor=tk.W).grid(row=0, column=2, **label_opts)
    ttk.Spinbox(grid, from_=80, to=600, width=8, textvariable=caption_height_var).grid(row=0, column=3, padx=(0, 20), **field_opts)
    ttk.Label(grid, text="Font size", width=10, anchor=tk.W).grid(row=0, column=4, **label_opts)
    ttk.Spinbox(grid, from_=8, to=72, width=6, textvariable=font_size_var).grid(row=0, column=5, **field_opts)
    ttk.Button(grid, text="Save defaults", command=apply_settings).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(12, 0))

    # ---- Section 4: Hotkey (area capture) ----
    hotkey_frame = ttk.LabelFrame(main, text="  Capture area hotkey  ", padding=(14, 12))
    hotkey_frame.pack(fill=tk.X, pady=(0, 16))
    hotkey_frame.columnconfigure(0, weight=1)
    hk_row = ttk.Frame(hotkey_frame)
    hk_row.pack(fill=tk.X, expand=True)
    hk_row.columnconfigure(1, weight=1)
    ttk.Label(hk_row, text="Modifiers", width=10, anchor=tk.W).grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=2)
    mod_frame = ttk.Frame(hk_row)
    mod_frame.grid(row=0, column=1, sticky=tk.W, pady=2)
    ttk.Checkbutton(mod_frame, text="Ctrl", variable=ctrl_hk_var).pack(side=tk.LEFT, padx=(0, 10))
    ttk.Checkbutton(mod_frame, text="Alt", variable=alt_hk_var).pack(side=tk.LEFT, padx=(0, 10))
    ttk.Checkbutton(mod_frame, text="Shift", variable=shift_hk_var).pack(side=tk.LEFT, padx=(0, 10))
    ttk.Checkbutton(mod_frame, text="Win", variable=win_hk_var).pack(side=tk.LEFT)
    ttk.Label(hk_row, text="Key", width=10, anchor=tk.W).grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=2)
    key_btn_frame = ttk.Frame(hk_row)
    key_btn_frame.grid(row=1, column=1, sticky=tk.W, pady=2)
    key_display_btn = ttk.Button(key_btn_frame, width=4, command=lambda: None)
    key_display_btn.pack(side=tk.LEFT, padx=(0, 6))

    def update_key_btn_text() -> None:
        key_display_btn.configure(text=capture_key_var.get() or "?")

    def ask_for_key() -> None:
        popup = tk.Toplevel(root)
        popup.title("Set hotkey key")
        popup.attributes("-topmost", True)
        popup.geometry("280x80")
        ttk.Label(popup, text="Press the key to use (one letter, number, or F1–F12):").pack(pady=(12, 6), padx=12)
        skip_keys = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Win_L", "Win_R", "Super_L", "Super_R"}

        def on_key(event: tk.Event) -> None:
            if event.keysym in skip_keys:
                return
            k = event.keysym
            if len(k) == 1:
                capture_key_var.set(k.upper())
            else:
                capture_key_var.set(k.upper() if len(k) <= 2 else (k[0].upper() + k[1:].lower()))
            update_key_btn_text()
            try:
                hk = build_hotkey_string(
                    ctrl_hk_var.get(), alt_hk_var.get(), shift_hk_var.get(), win_hk_var.get(),
                    capture_key_var.get().strip() or "q",
                )
                w = max(200, min(1200, int(caption_width_var.get())))
                h = max(80, min(600, int(caption_height_var.get())))
                fs = max(8, min(72, int(font_size_var.get())))
                save_settings({"caption_width": w, "caption_height": h, "font_size": fs, "capture_hotkey": hk, "tesseract_path": (tesseract_path_var.get() or "").strip()})
                reregister_hotkey()
            except (ValueError, tk.TclError):
                pass
            popup.destroy()

        popup.bind("<KeyPress>", on_key)
        popup.focus_set()
        popup.grab_set()

    key_display_btn.configure(command=ask_for_key)
    update_key_btn_text()
    ttk.Label(hk_row, text="Tesseract path", width=10, anchor=tk.W).grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=2)

    def tesseract_btn_text() -> str:
        p = (tesseract_path_var.get() or "").strip()
        if not p:
            return "Set Tesseract path..."
        if len(p) > 45:
            return p[:22] + "..." + p[-20:]
        return p

    def ask_tesseract_path() -> None:
        popup = tk.Toplevel(root)
        popup.title("Tesseract path")
        popup.attributes("-topmost", True)
        popup.geometry("540x120")
        popup.minsize(540, 120)
        popup.maxsize(540, 120)
        popup.resizable(True, False)
        popup.transient(root)
        ttk.Label(popup, text="Path to tesseract.exe (optional; leave empty to use PATH):").pack(anchor=tk.W, padx=14, pady=(14, 6))
        entry_frame = ttk.Frame(popup)
        entry_frame.pack(fill=tk.X, padx=14, pady=(0, 12))
        path_entry = ttk.Entry(entry_frame, width=58)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        current = tesseract_path_var.get() or ""
        path_entry.insert(0, current)
        if current:
            path_entry.select_range(0, tk.END)
        path_entry.focus_set()

        def browse() -> None:
            p = filedialog.askopenfilename(
                title="Select tesseract.exe",
                filetypes=[("Executable", "tesseract.exe"), ("All files", "*.*")],
                parent=popup,
            )
            if p:
                path_entry.delete(0, tk.END)
                path_entry.insert(0, p)

        def ok() -> None:
            tesseract_path_var.set(path_entry.get().strip())
            tesseract_btn.configure(text=tesseract_btn_text())
            try:
                w = max(200, min(1200, int(caption_width_var.get())))
                h = max(80, min(600, int(caption_height_var.get())))
                fs = max(8, min(72, int(font_size_var.get())))
                hk = build_hotkey_string(
                    ctrl_hk_var.get(), alt_hk_var.get(), shift_hk_var.get(), win_hk_var.get(),
                    capture_key_var.get().strip() or "q",
                )
                save_settings({"caption_width": w, "caption_height": h, "font_size": fs, "capture_hotkey": hk, "tesseract_path": tesseract_path_var.get().strip()})
            except (ValueError, tk.TclError):
                pass
            popup.destroy()

        ttk.Button(entry_frame, text="Browse...", command=browse).pack(side=tk.LEFT)
        btn_frame = ttk.Frame(popup)
        btn_frame.pack(pady=(4, 16))
        ttk.Button(btn_frame, text="OK", command=ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=popup.destroy).pack(side=tk.LEFT)
        popup.bind("<Return>", lambda e: ok())
        popup.bind("<Escape>", lambda e: popup.destroy())

    tesseract_btn = ttk.Button(hk_row, text=tesseract_btn_text(), command=ask_tesseract_path)
    tesseract_btn.grid(row=2, column=1, sticky=tk.EW, pady=2)
    ttk.Label(hk_row, text="Optional: click to set path to tesseract.exe if not on PATH. Settings are saved when you click OK or Start.", foreground="gray", font=("Segoe UI", 9), wraplength=520).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))
    ttk.Label(hk_row, text="If hotkey doesn't work: right-click app → Run as administrator. Restart to apply hotkey.", foreground="gray", font=("Segoe UI", 9), wraplength=520).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

    # ---- Status bar (fixed at bottom) ----
    ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(8, 10))
    status_frame = ttk.Frame(main)
    status_frame.pack(fill=tk.X)
    status_lbl = ttk.Label(status_frame, textvariable=status_var, foreground="gray", font=("Segoe UI", 9), wraplength=540)
    status_lbl.pack(anchor=tk.W)

    # ---- Model warning ----
    if not model_dir:
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 8))
        warn = ttk.Label(main, text="Vosk model not found. Add a model to the 'models' folder.", foreground="orange", font=("Segoe UI", 9), wraplength=540)
        warn.pack(anchor=tk.W)

    root.protocol("WM_DELETE_WINDOW", lambda: (stop_captioning(), root.destroy()))
    # Capture hotkey: register once, then re-register when user changes it
    hotkey_registered = [False]
    hotkey_stop: list[Callable[[], None] | None] = [None]
    hotkey_tk_seq: list[str | None] = [None]
    hotkey_queue: list[queue.Queue[int] | None] = [None]

    def poll_hotkey_queue() -> None:
        q = hotkey_queue[0]
        if q is None:
            return
        try:
            while True:
                q.get_nowait()
                start_area_selector()
        except queue.Empty:
            pass
        root.after(50, poll_hotkey_queue)

    def do_register_hotkey() -> None:
        """Register or re-register the capture hotkey from current UI state."""
        if hotkey_stop[0] is not None:
            try:
                hotkey_stop[0]()
            except Exception:
                pass
            hotkey_stop[0] = None
        old_seq = hotkey_tk_seq[0]
        if old_seq:
            try:
                root.unbind(old_seq)
                root.unbind_all(old_seq)
            except tk.TclError:
                pass
            hotkey_tk_seq[0] = None
        hk = build_hotkey_string(
            ctrl_hk_var.get(), alt_hk_var.get(), shift_hk_var.get(), win_hk_var.get(),
            capture_key_var.get().strip().lower() or "q",
        )
        callback = lambda: root.after(0, start_area_selector)
        try:
            tk_seq = hotkey_to_tk_bind_sequence(hk)
            root.bind(tk_seq, lambda e: callback())
            root.bind_all(tk_seq, lambda e: callback())
            hotkey_tk_seq[0] = tk_seq
        except tk.TclError:
            pass
        trigger_q: queue.Queue[int] = queue.Queue()
        hotkey_queue[0] = trigger_q
        ok, method, stop_fn = start_hotkey_listener(hk, callback, trigger_queue=trigger_q)
        hotkey_stop[0] = stop_fn
        if ok:
            if method == "win_hook":
                root.after(50, poll_hotkey_queue)
                status_var.set(f"Capture hotkey: {hk} (works in all apps).")
            else:
                status_var.set(f"Capture hotkey: {hk} (window + {method}).")
        else:
            status_var.set(f"Capture hotkey: {hk} (window only). Run as administrator for other apps.")

    def register_hotkey_once(_event: tk.Event | None = None) -> None:
        if hotkey_registered[0]:
            return
        hotkey_registered[0] = True
        try:
            root.unbind("<Map>", hotkey_bind_id)
        except tk.TclError:
            pass
        do_register_hotkey()

    def reregister_hotkey() -> None:
        """Re-register hotkey with current UI state (so change takes effect immediately)."""
        if hotkey_registered[0]:
            do_register_hotkey()

    # Re-register when modifier checkboxes change (Ctrl, Alt, Shift, Win)
    def _on_modifier_change(*args: object) -> None:
        reregister_hotkey()

    for var in (ctrl_hk_var, alt_hk_var, shift_hk_var, win_hk_var):
        var.trace_add("write", _on_modifier_change)

    hotkey_bind_id = root.bind("<Map>", register_hotkey_once)
    root.after(500, register_hotkey_once)
    root.mainloop()


if __name__ == "__main__":
    main()
