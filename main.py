"""
Live Caption — capture WhatsApp/Viber (or any) call audio and show real-time captions.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk
from tkinter import ttk, filedialog

from audio_capture import list_devices
from caption_engine import run_caption_engine
from config import MODEL_SIZES, load_settings, save_settings
from overlay import CaptionOverlay
from whisper_engine import find_local_model_dir

# Unconditional imports so PyInstaller bundles them (used in audio_capture)
import sounddevice  # noqa: F401
if sys.platform == "win32":
    try:
        import pyaudiowpatch  # noqa: F401
    except ImportError:
        pass


def main() -> None:
    devices = list_devices()
    if not devices:
        return

    settings = load_settings()
    stop_event = threading.Event()
    overlay: CaptionOverlay | None = None
    overlay_root: tk.Tk | None = None
    is_captioning = False
    # UI-level audio meter (in "Audio source" section)
    audio_level: float = 0.0
    audio_meter_canvas: tk.Canvas | None = None
    audio_meter_rect: int | None = None
    meter_stop_event = threading.Event()
    meter_thread: threading.Thread | None = None

    def _update_audio_meter(level: float) -> None:
        """Update the horizontal volume bar in the Audio source section."""
        nonlocal audio_level
        audio_level = max(0.0, min(float(level), 1.0))
        if audio_meter_canvas is None or audio_meter_rect is None:
            return
        canvas = audio_meter_canvas
        try:
            width = max(1, int(canvas.winfo_width()))
        except tk.TclError:
            width = 1
        filled = int(width * audio_level)
        # Simple green→yellow→red gradient
        if audio_level < 0.5:
            t = audio_level / 0.5
            r = int(0 + (255 - 0) * t)
            g = 255
        else:
            t = (audio_level - 0.5) / 0.5
            r = 255
            g = int(255 + (0 - 255) * t)
        color = f"#{r:02x}{g:02x}00"
        canvas.coords(audio_meter_rect, 0, 0, filled, int(canvas.winfo_height() or 6))
        canvas.itemconfig(audio_meter_rect, fill=color)

    def _compute_level_from_chunk(data: bytes) -> float:
        """Compute simple RMS-based level (0–1) from 16-bit mono PCM bytes."""
        if not data:
            return 0.0
        try:
            import struct

            sample_count = len(data) // 2
            if not sample_count:
                return 0.0
            samples = struct.unpack("<" + "h" * sample_count, data)
            sq_sum = 0.0
            for s in samples:
                sq_sum += float(s) * float(s)
            rms = (sq_sum / sample_count) ** 0.5
            return min(rms / 20000.0, 1.0)
        except Exception:
            return 0.0

    def stop_level_monitor() -> None:
        """Stop background audio-level capture (if running)."""
        nonlocal meter_thread
        meter_stop_event.set()
        meter_thread = None

    def start_level_monitor(device_index: int | None, is_loopback: bool) -> None:
        """
        Start lightweight audio capture for the level meter, even when captioning is stopped.
        Uses the same device indices/backends as captioning.
        """
        nonlocal meter_thread
        # Stop any existing monitor
        stop_level_monitor()
        meter_stop_event.clear()

        def _stop_flag() -> bool:
            return meter_stop_event.is_set()

        def _on_data(chunk: bytes) -> None:
            level = _compute_level_from_chunk(chunk)
            try:
                # Always marshal UI updates to Tk main loop
                if audio_meter_canvas is not None:
                    audio_meter_canvas.after(0, lambda lv=level: _update_audio_meter(lv))
            except tk.TclError:
                pass

        def _run() -> None:
            from audio_capture import capture_audio

            try:
                capture_audio(
                    device_index,
                    on_data=_on_data,
                    stop_event=_stop_flag,
                    use_pyaudiowpatch=is_loopback,
                    is_loopback=is_loopback,
                )
            except Exception:
                # Meter is best-effort only; don't crash app.
                pass

        t = threading.Thread(target=_run, daemon=True)
        meter_thread = t
        t.start()

    def start_captioning(device_index: int | None, is_loopback: bool) -> None:
        nonlocal overlay, overlay_root, stop_event
        stop_event.clear()
        if overlay is None:
            w = max(200, min(1200, int(caption_width_var.get())))
            h = max(80, min(600, int(caption_height_var.get())))
            fs = max(8, min(72, int(font_size_var.get())))
            overlay = CaptionOverlay(
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

        def on_level(level: float) -> None:
            # Ensure UI updates happen on Tk main thread
            def apply_level() -> None:
                overlay.set_volume_level(level)
                _update_audio_meter(level)

            if overlay_root and overlay_root.winfo_exists():
                overlay_root.after(0, apply_level)

        run_caption_engine(
            model_size_var.get(),
            device_index,
            on_partial=on_partial,
            on_final=on_final,
            stop_event=lambda: stop_event.is_set(),
            use_loopback=is_loopback,
            on_level=on_level,
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
            save_settings({
                "caption_width": w,
                "caption_height": h,
                "font_size": fs,
                "model_size": model_size_var.get(),
            })
            status_var.set("Settings saved.")
        except (ValueError, tk.TclError):
            status_var.set("Please enter valid numbers.")

    # ---- Color palette: modern dark theme, blue accent ----
    BG = "#14161b"
    SURFACE = "#1b1e25"
    SURFACE_ALT = "#232730"
    BORDER = "#2b2f3a"
    TEXT = "#eceef1"
    TEXT_MUTED = "#8b93a3"
    ACCENT = "#3b82f6"
    ACCENT_HOVER = "#2f6fe0"
    ACCENT_ACTIVE = "#2563eb"
    DANGER = "#ef4444"
    DANGER_HOVER = "#e13636"
    DANGER_ACTIVE = "#dc2626"
    SUCCESS = "#22c55e"

    root = tk.Tk()
    root.title("Live Caption")
    root.geometry("640x800")
    root.minsize(640, 800)
    root.maxsize(640, 800)
    root.resizable(True, True)
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass

    # Theme: 'clam' is the only built-in ttk theme that fully honors custom
    # colors on Windows (native themes like 'vista' mostly ignore ttk.Style
    # and render with the OS theme engine), so it's required for real dark mode.
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    def _safe_configure(name: str, **kw: object) -> None:
        try:
            style.configure(name, **kw)
        except tk.TclError:
            pass

    def _safe_map(name: str, **kw: object) -> None:
        try:
            style.map(name, **kw)
        except tk.TclError:
            pass

    BODY_FONT = ("Segoe UI", 10)
    MUTED_FONT = ("Segoe UI", 9)
    SECTION_FONT = ("Segoe UI", 10, "bold")

    _safe_configure("TFrame", background=BG)
    # Most labels live inside a LabelFrame (SURFACE background); the header and
    # status bar sit directly on the window background instead (BG variants below).
    _safe_configure("TLabel", background=SURFACE, foreground=TEXT, font=BODY_FONT)
    _safe_configure("Muted.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=MUTED_FONT)
    _safe_configure("Header.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 19, "bold"))
    _safe_configure("HeaderMuted.TLabel", background=BG, foreground=TEXT_MUTED, font=MUTED_FONT)
    _safe_configure("StatusMuted.TLabel", background=BG, foreground=TEXT_MUTED, font=MUTED_FONT)
    _safe_configure(
        "TLabelframe",
        background=SURFACE,
        bordercolor=BORDER,
        darkcolor=SURFACE,
        lightcolor=SURFACE,
        borderwidth=1,
        relief=tk.SOLID,
    )
    _safe_configure("TLabelframe.Label", background=SURFACE, foreground=TEXT, font=SECTION_FONT, padding=(4, 2))
    _safe_configure("TSeparator", background=BORDER)

    _safe_configure(
        "TButton",
        background=SURFACE_ALT,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        borderwidth=1,
        focusthickness=0,
        focuscolor=SURFACE_ALT,
        padding=(12, 8),
        font=BODY_FONT,
    )
    _safe_map(
        "TButton",
        background=[("active", BORDER), ("pressed", BORDER)],
        bordercolor=[("focus", ACCENT)],
    )

    _safe_configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="#ffffff",
        bordercolor=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        borderwidth=0,
        focusthickness=0,
        focuscolor=ACCENT,
        padding=(28, 14),
        font=("Segoe UI", 11, "bold"),
    )
    _safe_map(
        "Accent.TButton",
        background=[("active", ACCENT_HOVER), ("pressed", ACCENT_ACTIVE)],
    )

    _safe_configure(
        "Danger.TButton",
        background=DANGER,
        foreground="#ffffff",
        bordercolor=DANGER,
        lightcolor=DANGER,
        darkcolor=DANGER,
        borderwidth=0,
        focusthickness=0,
        focuscolor=DANGER,
        padding=(28, 14),
        font=("Segoe UI", 11, "bold"),
    )
    _safe_map(
        "Danger.TButton",
        background=[("active", DANGER_HOVER), ("pressed", DANGER_ACTIVE)],
    )

    _safe_configure(
        "TCombobox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        arrowcolor=TEXT_MUTED,
        borderwidth=1,
        padding=(8, 6),
        font=BODY_FONT,
    )
    _safe_map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_ALT)],
        foreground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        arrowcolor=[("active", ACCENT)],
    )
    _safe_configure(
        "TSpinbox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=SURFACE_ALT,
        darkcolor=SURFACE_ALT,
        arrowcolor=TEXT_MUTED,
        borderwidth=1,
        padding=(8, 6),
        font=BODY_FONT,
    )
    _safe_map("TSpinbox", bordercolor=[("focus", ACCENT)])

    # Combobox/Listbox popdowns and plain tk widgets aren't ttk elements, so
    # they need direct color options to match the dark theme.
    root.option_add("*TCombobox*Listbox.background", SURFACE_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*Font", ("Segoe UI", 10))

    main = ttk.Frame(root, padding=(24, 20))
    main.pack(fill=tk.BOTH, expand=True)

    # Header: thin accent bar + logo mark for a bit of visual identity
    accent_bar = tk.Frame(root, bg=ACCENT, height=3)
    accent_bar.pack(side=tk.TOP, fill=tk.X)

    header = ttk.Frame(main)
    header.pack(fill=tk.X, pady=(0, 22))
    header_row = ttk.Frame(header)
    header_row.pack(fill=tk.X, anchor=tk.W)
    logo_mark = tk.Canvas(header_row, width=28, height=28, highlightthickness=0, bd=0, bg=BG)
    logo_mark.pack(side=tk.LEFT, padx=(0, 10))
    logo_mark.create_rectangle(0, 0, 28, 28, fill=ACCENT, outline="")
    logo_mark.create_text(14, 15, text="LC", fill="#ffffff", font=("Segoe UI", 9, "bold"))
    title_col = ttk.Frame(header_row)
    title_col.pack(side=tk.LEFT, fill=tk.X)
    ttk.Label(title_col, text="Live Caption", style="Header.TLabel").pack(anchor=tk.W)
    ttk.Label(title_col, text="Real-time captions from call audio · Close to tray", style="HeaderMuted.TLabel").pack(anchor=tk.W)

    # Need these for on_start/on_stop; create vars early for status_var
    status_var = tk.StringVar(value="")
    device_var = tk.StringVar(value=devices[0].name if devices else "")
    caption_width_var = tk.StringVar(value=str(settings["caption_width"]))
    caption_height_var = tk.StringVar(value=str(settings["caption_height"]))
    font_size_var = tk.StringVar(value=str(settings["font_size"]))
    model_size_var = tk.StringVar(value=settings.get("model_size", MODEL_SIZES[2]))

    def on_toggle() -> None:
        nonlocal is_captioning
        if is_captioning:
            stop_captioning()
            # Resume background level monitor when captioning stops
            name = device_var.get()
            dev = next((d for d in devices if d.name == name), devices[0] if devices else None)
            if dev:
                start_level_monitor(dev.index, dev.is_loopback)
            is_captioning = False
            toggle_btn.configure(text="Start", style="Accent.TButton")
            _set_status_dot(False)
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
                save_settings({
                    "caption_width": w,
                    "caption_height": h,
                    "font_size": fs,
                    "model_size": model_size_var.get(),
                })
                # Stop background meter and let caption engine drive the level updates
                stop_level_monitor()
                start_captioning(dev.index, dev.is_loopback)
                is_captioning = True
                toggle_btn.configure(text="Stop", style="Danger.TButton")
                _set_status_dot(True)
                status_var.set("Capturing. Drag caption window to move.")
            except FileNotFoundError as e:
                status_var.set(str(e))
            except Exception as e:
                status_var.set(str(e))

    # ---- Section: Audio + Start (top row) ----
    top_row = ttk.Frame(main)
    top_row.pack(fill=tk.X, pady=(0, 20))
    top_row.columnconfigure(0, weight=1, minsize=220)
    top_row.columnconfigure(1, weight=1, minsize=180)
    audio_frame = ttk.LabelFrame(top_row, text="Audio source", padding=(16, 14))
    audio_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 10))
    ttk.Label(audio_frame, text="Capture from", style="Muted.TLabel").pack(anchor=tk.W)
    combo = ttk.Combobox(audio_frame, textvariable=device_var, height=6, state="readonly", font=("Segoe UI", 10))
    combo["values"] = [d.name for d in devices]
    combo.pack(fill=tk.X, pady=(8, 4))
    # Horizontal audio level meter under device list
    meter_container = tk.Frame(audio_frame, bg=SURFACE)
    meter_container.pack(fill=tk.X, pady=(2, 0))
    meter_label = ttk.Label(meter_container, text="Input level", style="Muted.TLabel")
    meter_label.pack(anchor=tk.W)
    audio_meter_canvas = tk.Canvas(
        meter_container,
        height=8,
        highlightthickness=0,
        bd=0,
        bg=SURFACE_ALT,
    )
    audio_meter_canvas.pack(fill=tk.X, pady=(2, 0))
    audio_meter_rect = audio_meter_canvas.create_rectangle(
        0,
        0,
        0,
        8,
        width=0,
        fill=SUCCESS,
    )

    def _on_device_change(_event: tk.Event | None = None) -> None:
        """Restart level monitor for newly selected device."""
        name = device_var.get()
        dev = next((d for d in devices if d.name == name), devices[0] if devices else None)
        if dev:
            start_level_monitor(dev.index, dev.is_loopback)

    combo.bind("<<ComboboxSelected>>", _on_device_change)
    ctrl_frame = ttk.LabelFrame(top_row, text="Captioning", padding=(16, 14))
    ctrl_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(10, 0))
    toggle_btn = ttk.Button(ctrl_frame, text="Start", command=on_toggle, style="Accent.TButton")
    toggle_btn.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(ctrl_frame, text="Model size", style="Muted.TLabel").pack(anchor=tk.W)
    model_combo = ttk.Combobox(
        ctrl_frame, textvariable=model_size_var, values=list(MODEL_SIZES), state="readonly", font=("Segoe UI", 10)
    )
    model_combo.pack(fill=tk.X, pady=(4, 4))

    def _model_status_text(model_size: str) -> str:
        if find_local_model_dir(model_size) is not None:
            return f"Model '{model_size}' ready."
        return f"Model '{model_size}' will download on first use (~150–500MB)."

    model_status_var = tk.StringVar(value=_model_status_text(model_size_var.get()))
    ttk.Label(ctrl_frame, textvariable=model_status_var, style="Muted.TLabel", wraplength=220).pack(anchor=tk.W)

    def _on_model_change(_event: tk.Event | None = None) -> None:
        model_status_var.set(_model_status_text(model_size_var.get()))
        save_settings({"model_size": model_size_var.get()})

    model_combo.bind("<<ComboboxSelected>>", _on_model_change)

    # ---- Section: Caption window ----
    opts_frame = ttk.LabelFrame(main, text="Caption window", padding=(16, 14))
    opts_frame.pack(fill=tk.X, pady=(0, 18))
    grid = ttk.Frame(opts_frame)
    grid.pack(fill=tk.X)
    for c in (1, 3, 5):
        grid.columnconfigure(c, weight=1, minsize=70)
    label_opts = {"sticky": tk.W, "padx": (0, 10), "pady": 6}
    field_opts = {"sticky": tk.W, "pady": 6}
    ttk.Label(grid, text="Width", width=10, anchor=tk.W).grid(row=0, column=0, **label_opts)
    ttk.Spinbox(grid, from_=200, to=1200, width=10, textvariable=caption_width_var).grid(row=0, column=1, padx=(0, 24), **field_opts)
    ttk.Label(grid, text="Height", width=10, anchor=tk.W).grid(row=0, column=2, **label_opts)
    ttk.Spinbox(grid, from_=80, to=600, width=10, textvariable=caption_height_var).grid(row=0, column=3, padx=(0, 24), **field_opts)
    ttk.Label(grid, text="Font size", width=10, anchor=tk.W).grid(row=0, column=4, **label_opts)
    ttk.Spinbox(grid, from_=8, to=72, width=8, textvariable=font_size_var).grid(row=0, column=5, **field_opts)
    ttk.Button(grid, text="Save defaults", command=apply_settings).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(14, 0))

    # ---- Programs to start with Live Caption ----
    launch_list: list[str] = list(settings.get("launch_on_start") or [])

    def save_launch_list() -> None:
        s = load_settings()
        s["launch_on_start"] = list(launch_list)
        save_settings(s)

    def refresh_launch_listbox() -> None:
        launch_listbox.delete(0, tk.END)
        for p in launch_list:
            display = p if len(p) <= 56 else p[:26] + "..." + p[-27:]
            launch_listbox.insert(tk.END, display)

    def add_launch_program() -> None:
        p = filedialog.askopenfilename(
            title="Select program to start with Live Caption",
            filetypes=[("Executables", "*.exe;*.bat;*.cmd"), ("All files", "*.*")],
            parent=root,
        )
        if p and p not in launch_list:
            launch_list.append(p)
            refresh_launch_listbox()
            save_launch_list()

    def remove_launch_program() -> None:
        sel = list(launch_listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            if 0 <= i < len(launch_list):
                launch_list.pop(i)
        refresh_launch_listbox()
        save_launch_list()

    def run_launch_list() -> None:
        for path in launch_list:
            path = (path or "").strip()
            if not path or not os.path.isfile(path):
                continue
            try:
                cwd = os.path.dirname(path) or None
                if sys.platform == "win32":
                    low = path.lower()
                    if low.endswith(".bat") or low.endswith(".cmd"):
                        subprocess.Popen(
                            ["cmd", "/c", "start", "", path],
                            cwd=cwd,
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                            close_fds=True,
                        )
                    else:
                        subprocess.Popen(
                            [path],
                            cwd=cwd,
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                            close_fds=True,
                        )
                else:
                    subprocess.Popen([path], cwd=cwd, start_new_session=True)
            except Exception:
                pass

    launch_frame = ttk.LabelFrame(main, text="Start with Live Caption", padding=(16, 14))
    launch_frame.pack(fill=tk.X, pady=(0, 18))
    launch_frame.columnconfigure(0, weight=1)
    launch_inner = ttk.Frame(launch_frame)
    launch_inner.pack(fill=tk.X)
    launch_listbox = tk.Listbox(
        launch_inner,
        height=3,
        selectmode=tk.EXTENDED,
        font=("Segoe UI", 10),
        relief=tk.FLAT,
        highlightthickness=0,
        borderwidth=0,
        bg=SURFACE_ALT,
        fg=TEXT,
        selectbackground=ACCENT,
        selectforeground="#ffffff",
    )
    launch_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(0, 8))
    launch_btns = ttk.Frame(launch_inner)
    launch_btns.pack(side=tk.RIGHT, padx=(12, 0))
    ttk.Button(launch_btns, text="Start", command=run_launch_list).pack(fill=tk.X, pady=3)
    ttk.Button(launch_btns, text="Add...", command=add_launch_program).pack(fill=tk.X, pady=3)
    ttk.Button(launch_btns, text="Remove", command=remove_launch_program).pack(fill=tk.X, pady=3)
    refresh_launch_listbox()
    ttk.Label(launch_frame, text="Click Start to run the programs in the list (.exe, .bat).", style="Muted.TLabel", wraplength=520).pack(anchor=tk.W)

    # ---- Status bar ----
    ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(16, 12))
    status_frame = ttk.Frame(main)
    status_frame.pack(fill=tk.X)
    status_dot = tk.Canvas(status_frame, width=8, height=8, highlightthickness=0, bd=0, bg=BG)
    status_dot.pack(side=tk.LEFT, padx=(0, 8))
    status_dot_id = status_dot.create_oval(0, 0, 8, 8, fill=TEXT_MUTED, outline="")

    def _set_status_dot(active: bool) -> None:
        status_dot.itemconfig(status_dot_id, fill=SUCCESS if active else TEXT_MUTED)

    status_lbl = ttk.Label(status_frame, textvariable=status_var, style="StatusMuted.TLabel", wraplength=540)
    status_lbl.pack(side=tk.LEFT, anchor=tk.W)

    # ---- System tray: close (X) hides to tray; restore via tray icon ----
    tray_cmd_queue: queue.Queue[str] = queue.Queue()

    def show_window() -> None:
        try:
            root.deiconify()
            root.lift()
            root.focus_force()
        except tk.TclError:
            pass

    def hide_to_tray() -> None:
        root.withdraw()

    def quit_app() -> None:
        stop_captioning()
        if tray_stop[0]:
            try:
                tray_stop[0]()
            except Exception:
                pass
        root.quit()

    def poll_tray_queue() -> None:
        """Process tray actions on the main thread (Tk is not thread-safe)."""
        try:
            while True:
                cmd = tray_cmd_queue.get_nowait()
                if cmd == "show":
                    show_window()
                elif cmd == "quit":
                    quit_app()
        except queue.Empty:
            pass
        root.after(150, poll_tray_queue)

    tray_stop: list = [None]  # [Callable | None]

    if sys.platform == "win32":
        # Windows: use native tray (ctypes). X always hides to tray.
        root.protocol("WM_DELETE_WINDOW", hide_to_tray)
        try:
            from tray_win32 import run_tray as run_tray_win32
            tray_stop[0] = run_tray_win32(
                tooltip="Live Caption",
                on_activate=lambda: tray_cmd_queue.put("show"),
                on_quit=lambda: tray_cmd_queue.put("quit"),
            )
            root.after(150, poll_tray_queue)
        except Exception:
            root.protocol("WM_DELETE_WINDOW", lambda: (stop_captioning(), root.destroy()))
    else:
        root.protocol("WM_DELETE_WINDOW", lambda: (stop_captioning(), root.destroy()))

    # Start initial level monitor for default selected device
    try:
        initial_name = device_var.get()
        initial_dev = next((d for d in devices if d.name == initial_name), devices[0] if devices else None)
        if initial_dev:
            start_level_monitor(initial_dev.index, initial_dev.is_loopback)
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()
