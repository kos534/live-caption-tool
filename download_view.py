"""First-run screen that downloads the speech models, shown over the caption area.

Offers the download (with its size and where it goes), then shows a progress bar with size,
speed and time left. Pause/Resume keep the partial files, so a later start (or the next launch)
continues where it stopped. When everything is in place it removes itself and calls on_done.
"""

import os
import tkinter as tk

from model_download import format_size
from theme import BG, ERROR_FG, HOVER, ICON_FG, MUTED, PANEL_BG, PILL_BG, PILL_HOVER_BG, TEXT_FINAL, TITLE_FG, GRADIENT

BAR_H = 10


class DownloadView(tk.Frame):
    def __init__(self, parent, font_family: str, downloader, approx_bytes: int, target_dir, on_done):
        super().__init__(parent, bg=BG)
        self.ff = font_family
        self.downloader = downloader
        self.approx_bytes = approx_bytes
        self.on_done = on_done
        self._job = None

        card = tk.Frame(self, bg=PANEL_BG, padx=22, pady=18)
        card.place(relx=0.5, rely=0.42, anchor="center", relwidth=0.9)
        tk.Label(card, text="✧  One more step", bg=PANEL_BG, fg=TITLE_FG, font=(font_family, 13, "bold"), anchor="w").pack(
            fill="x"
        )
        self.body = tk.Label(
            card, bg=PANEL_BG, fg=TEXT_FINAL, font=(font_family, 10), anchor="w", justify="left",
            text=(
                "Live captions need the speech recognition models, about "
                f"{format_size(approx_bytes)}. They're downloaded once from Hugging Face and "
                f"saved in {_short(target_dir)}.\n\n"
                "The Answer button and ⚙ Settings already work while you wait."
            ),
        )
        self.body.pack(fill="x", pady=(8, 12))
        self.body.bind("<Configure>", lambda e: self.body.configure(wraplength=max(200, e.width)))

        self.bar = tk.Canvas(card, height=BAR_H, bg=BG, highlightthickness=0, bd=0)
        self.bar.pack(fill="x")
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        self.status = tk.Label(card, text="", bg=PANEL_BG, fg=MUTED, font=(font_family, 9), anchor="w", justify="left")
        self.status.pack(fill="x", pady=(6, 10))

        row = tk.Frame(card, bg=PANEL_BG)
        row.pack(fill="x")
        self.button = tk.Label(row, text="", bg=PILL_BG, fg=ICON_FG, font=(font_family, 10, "bold"), cursor="hand2", padx=16, pady=4)
        self.button.pack(side="right")
        self.button.bind("<Button-1>", lambda e: self._on_button())
        self.button.bind("<Enter>", lambda e: self.button.configure(fg=HOVER, bg=PILL_HOVER_BG))
        self.button.bind("<Leave>", lambda e: self.button.configure(fg=ICON_FG, bg=PILL_BG))

        self._fraction = 0.0
        self._set_idle("Download", "")

    # ---- states ---------------------------------------------------------------------------

    def _set_idle(self, button: str, status: str, error: bool = False):
        self._mode = "idle"
        self.button.configure(text=button)
        self.status.configure(text=status, fg=ERROR_FG if error else MUTED)

    def _on_button(self):
        if self._mode == "running":
            self.downloader.cancel()
            self.button.configure(text="Pausing…")
            self._mode = "pausing"
        elif self._mode == "idle":
            self._mode = "running"
            self.button.configure(text="Pause")
            self.status.configure(text="Starting…", fg=MUTED)
            self.downloader.start()
            self._poll()

    def _poll(self):
        d = self.downloader
        done, total, speed = d.progress()
        total = total or self.approx_bytes
        self._fraction = min(1.0, done / total) if total else 0.0
        self._draw_bar()
        if d.finished:
            self.status.configure(text="Done. Loading the speech model…", fg=MUTED)
            self.after(400, self._finish)
            return
        if not d.running:
            if d.error:
                self._set_idle("Retry", f"Download stopped: {d.error}", error=True)
            else:
                self._set_idle("Resume", f"Paused at {format_size(done)} of {format_size(total)}.")
            return
        if done and self._mode == "running":
            text = f"{format_size(done)} of {format_size(total)}"
            if speed > 0:
                text += f"  ·  {format_size(speed)}/s  ·  {_eta((total - done) / speed)} left"
            self.status.configure(text=text)
        self._job = self.after(300, self._poll)

    def _finish(self):
        self.destroy()
        self.on_done()

    def destroy(self):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        super().destroy()

    def _draw_bar(self):
        c = self.bar
        c.delete("all")
        w = c.winfo_width()
        if w <= 1:
            return
        fill_w = round(w * self._fraction)
        # Fill painted in the window's flame gradient, in a few steps.
        step = 6
        for x in range(0, fill_w, step):
            t = x / max(1, w - 1)
            pos = t * (len(GRADIENT) - 1)
            i = min(int(pos), len(GRADIENT) - 2)
            c.create_rectangle(x, 0, min(x + step, fill_w), BAR_H, fill=_mix(GRADIENT[i], GRADIENT[i + 1], pos - i), width=0)


def _mix(a: str, b: str, t: float) -> str:
    ra = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    rb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def _eta(seconds: float) -> str:
    if seconds < 90:
        return f"{max(1, round(seconds))} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def _short(path) -> str:
    """Path with %LOCALAPPDATA% abbreviated, for display."""
    text = str(path)
    local = os.environ.get("LOCALAPPDATA", "")
    if local and text.lower().startswith(local.lower()):
        return "%LOCALAPPDATA%" + text[len(local):]
    return text
