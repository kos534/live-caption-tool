"""
Live Caption — capture WhatsApp/Viber (or any) call audio and show real-time captions.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

from audio_capture import list_devices
from caption_engine import find_model_dir, run_caption_engine
from config import load_settings, save_settings
from overlay import CaptionOverlay


def main() -> None:
    model_dir = find_model_dir()
    devices = list_devices()
    if not devices:
        messagebox.showerror("Live Caption", "No audio input devices found.")
        return

    settings = load_settings()
    stop_event = threading.Event()
    overlay: CaptionOverlay | None = None
    overlay_root: tk.Tk | None = None

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
            save_settings({"caption_width": w, "caption_height": h, "font_size": fs})
            status_var.set("Settings saved. They apply when you next click Start.")
        except (ValueError, tk.TclError):
            status_var.set("Please enter valid numbers.")

    root = tk.Tk()
    root.title("Live Caption")
    root.geometry("420x400")
    root.resizable(True, False)
    root.minsize(380, 380)

    # Style: emphasize Start button where supported
    start_btn_style: str | None = None
    try:
        style = ttk.Style()
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 8))
        start_btn_style = "Primary.TButton"
    except tk.TclError:
        pass
    root.option_add("*Font", ("Segoe UI", 10))

    main = ttk.Frame(root, padding=16)
    main.pack(fill=tk.BOTH, expand=True)

    # Need these for on_start/on_stop; create vars early for status_var
    status_var = tk.StringVar(value="Choose an audio source and click Start.")
    device_var = tk.StringVar(value=devices[0].name if devices else "")
    caption_width_var = tk.StringVar(value=str(settings["caption_width"]))
    caption_height_var = tk.StringVar(value=str(settings["caption_height"]))
    font_size_var = tk.StringVar(value=str(settings["font_size"]))

    def on_start() -> None:
        name = device_var.get()
        dev = next((d for d in devices if d.name == name), devices[0] if devices else None)
        if not dev:
            return
        try:
            w = max(200, min(1200, int(caption_width_var.get())))
            h = max(80, min(600, int(caption_height_var.get())))
            fs = max(8, min(72, int(font_size_var.get())))
            save_settings({"caption_width": w, "caption_height": h, "font_size": fs})
            start_captioning(dev.index, dev.is_loopback)
            status_var.set("Capturing. Drag caption window to move; drag ⋰ to resize.")
        except FileNotFoundError as e:
            messagebox.showerror("Live Caption", str(e))
        except Exception as e:
            messagebox.showerror("Live Caption", str(e))

    def on_stop_click() -> None:
        stop_captioning()
        status_var.set("Stopped.")

    # ---- Section: Control (primary action) ----
    ctrl_frame = ttk.LabelFrame(main, text=" Control ", padding=(12, 10))
    ctrl_frame.pack(fill=tk.X, pady=(0, 12))
    ctrl_inner = ttk.Frame(ctrl_frame)
    ctrl_inner.pack(fill=tk.X)
    start_btn = ttk.Button(ctrl_inner, text="Start", command=on_start)
    if start_btn_style:
        start_btn.configure(style=start_btn_style)
    start_btn.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(ctrl_inner, text="Stop", command=on_stop_click).pack(side=tk.LEFT)
    ttk.Label(ctrl_frame, text="Start shows the caption window; stop closes it.", foreground="gray").pack(anchor=tk.W, pady=(6, 0))

    # ---- Section: Audio source ----
    audio_frame = ttk.LabelFrame(main, text=" Audio source ", padding=(12, 10))
    audio_frame.pack(fill=tk.X, pady=(0, 12))
    ttk.Label(audio_frame, text="Where to capture speech from (e.g. microphone or speaker output for calls):").pack(anchor=tk.W)
    combo = ttk.Combobox(audio_frame, textvariable=device_var, width=52, state="readonly")
    combo["values"] = [d.name for d in devices]
    combo.pack(fill=tk.X, pady=(6, 0))

    # ---- Section: Caption window settings ----
    opts_frame = ttk.LabelFrame(main, text=" Caption window ", padding=(12, 10))
    opts_frame.pack(fill=tk.X, pady=(0, 12))
    grid = ttk.Frame(opts_frame)
    grid.pack(fill=tk.X)
    ttk.Label(grid, text="Width:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=2)
    ttk.Spinbox(grid, from_=200, to=1200, width=8, textvariable=caption_width_var).grid(row=0, column=1, sticky=tk.W, padx=(0, 16), pady=2)
    ttk.Label(grid, text="Height:").grid(row=0, column=2, sticky=tk.W, padx=(0, 6), pady=2)
    ttk.Spinbox(grid, from_=80, to=600, width=8, textvariable=caption_height_var).grid(row=0, column=3, sticky=tk.W, padx=(0, 16), pady=2)
    ttk.Label(grid, text="Font size:").grid(row=0, column=4, sticky=tk.W, padx=(0, 6), pady=2)
    ttk.Spinbox(grid, from_=8, to=72, width=6, textvariable=font_size_var).grid(row=0, column=5, sticky=tk.W, padx=(0, 0), pady=2)
    ttk.Button(grid, text="Save defaults", command=apply_settings).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=(0, 0), pady=(8, 0))
    ttk.Label(opts_frame, text="Used when you next click Start. Resize the caption window with the ⋰ handle.", foreground="gray").pack(anchor=tk.W, pady=(8, 0))

    # ---- Status bar ----
    status_frame = ttk.Frame(main)
    status_frame.pack(fill=tk.X, pady=(4, 0))
    status_lbl = ttk.Label(status_frame, textvariable=status_var, foreground="gray")
    status_lbl.pack(anchor=tk.W)

    # ---- Model warning ----
    if not model_dir:
        warn = ttk.Label(main, text="Vosk model not found. Add a model to the 'models' folder.", foreground="orange", wraplength=380)
        warn.pack(anchor=tk.W, pady=(8, 0))

    root.protocol("WM_DELETE_WINDOW", lambda: (stop_captioning(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
