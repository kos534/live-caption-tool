"""
Always-on-top caption overlay window. Resizable by dragging the bottom-right handle.
Caption text is scrollable when it exceeds the window height.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

MIN_WIDTH = 200
MIN_HEIGHT = 80
RESIZE_HANDLE_SIZE = 20
PADX = 12
PADY = 8
MAX_LINES_STORED = 500  # keep full history for scrolling, cap for memory


class CaptionOverlay:
    def __init__(
        self,
        max_lines: int = 4,
        font_size: int = 18,
        width: int = 560,
        height: int = 180,
        parent: tk.Tk | tk.Toplevel | None = None,
    ) -> None:
        if parent is not None:
            self._root = tk.Toplevel(parent)
        else:
            self._root = tk.Tk()
        self._root.title("Live Caption")
        self._root.attributes("-topmost", True)
        self._root.overrideredirect(True)
        self._root.configure(bg="#1a1a1a")
        self._root.attributes("-alpha", 0.92)
        self._max_lines = max_lines  # used only for merging short segments
        self._font_size = font_size
        self._width = max(MIN_WIDTH, width)
        self._height = max(MIN_HEIGHT, height)
        self._lines: list[str] = []
        self._partial = ""
        self._level = 0.0  # 0–1, current audio level for volume bar

        self._drag_x = 0
        self._drag_y = 0
        self._resize_start: tuple[int, int, int, int] | None = None

        # Root content frame
        self._frame = tk.Frame(self._root, bg="#1a1a1a", padx=PADX, pady=PADY)
        self._frame.pack(fill=tk.BOTH, expand=True)

        # Top: text area
        text_frame = tk.Frame(self._frame, bg="#1a1a1a")
        text_frame.pack(fill=tk.BOTH, expand=True)

        font = tkfont.Font(family="Segoe UI", size=font_size, weight="normal")
        # Approximate chars that fit in width; height in lines from window height
        char_width = max(20, (self._width - PADX * 2 - RESIZE_HANDLE_SIZE - 24) // 10)
        line_height_px = max(12, int(font_size * 1.4))
        height_lines = max(3, (self._height - PADY * 2 - 24) // line_height_px)
        self._text = tk.Text(
            text_frame,
            font=font,
            fg="#e0e0e0",
            bg="#1a1a1a",
            wrap=tk.WORD,
            width=char_width,
            height=height_lines,
            state=tk.DISABLED,
            cursor="arrow",
            relief=tk.FLAT,
            padx=4,
            pady=4,
            insertwidth=0,
        )
        self._text.tag_configure("final", foreground="#e0e0e0")
        self._text.tag_configure("partial", foreground="#888888")
        self._text.configure(yscrollcommand=lambda *a: None)  # no scrollbar; mouse wheel still scrolls
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._frame.bind("<Button-1>", self._on_press)
        self._frame.bind("<B1-Motion>", self._on_drag)
        self._text.bind("<Button-1>", self._on_press)
        self._text.bind("<B1-Motion>", self._on_drag)
        # Mousewheel scroll (no scrollbar shown)
        self._frame.bind("<MouseWheel>", self._on_mousewheel)
        self._text.bind("<MouseWheel>", self._on_mousewheel)

        # Bottom: compact volume bar (shows current audio level)
        vol_frame = tk.Frame(self._frame, bg="#1a1a1a")
        vol_frame.pack(fill=tk.X, pady=(4, 0))
        self._vol_canvas_height = 10
        self._vol_canvas = tk.Canvas(
            vol_frame,
            height=self._vol_canvas_height,
            highlightthickness=0,
            bd=0,
            bg="#1a1a1a",
        )
        self._vol_canvas.pack(fill=tk.X, expand=True)
        self._vol_rect = self._vol_canvas.create_rectangle(
            0,
            0,
            0,
            self._vol_canvas_height,
            fill="#22c55e",
            width=0,
        )

        # Resize handle (bottom-right)
        handle_frame = tk.Frame(self._root, bg="#2a2a2a", width=RESIZE_HANDLE_SIZE, height=RESIZE_HANDLE_SIZE)
        handle_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 2), pady=(0, 2))
        handle_frame.pack_propagate(False)
        grip = tk.Label(
            handle_frame,
            text="⋰",
            font=tkfont.Font(size=10),
            fg="#666",
            bg="#2a2a2a",
            cursor="sizing",
        )
        grip.pack(expand=True)
        grip.bind("<Button-1>", self._on_resize_press)
        grip.bind("<B1-Motion>", self._on_resize_drag)
        grip.bind("<ButtonRelease-1>", self._on_resize_release)
        handle_frame.bind("<Button-1>", self._on_resize_press)
        handle_frame.bind("<B1-Motion>", self._on_resize_drag)
        handle_frame.bind("<ButtonRelease-1>", self._on_resize_release)

        self._root.geometry(f"{self._width}x{self._height}+100+100")
        self._root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._update_display()

    def _update_volume_bar(self) -> None:
        """Render the small audio level bar based on self._level (0–1)."""
        level = max(0.0, min(float(self._level), 1.0))
        width = max(1, self._vol_canvas.winfo_width() or self._width - PADX * 2)
        filled = int(width * level)
        # Simple green→yellow→red gradient
        if level < 0.5:
            t = level / 0.5
            r = int(0 + (255 - 0) * t)
            g = 255
        else:
            t = (level - 0.5) / 0.5
            r = 255
            g = int(255 + (0 - 255) * t)
        color = f"#{r:02x}{g:02x}00"
        self._vol_canvas.coords(self._vol_rect, 0, 0, filled, self._vol_canvas_height)
        self._vol_canvas.itemconfig(self._vol_rect, fill=color)

    def _on_mousewheel(self, event: tk.Event) -> None:
        self._text.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_press(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag(self, event: tk.Event) -> None:
        self._root.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def _on_resize_press(self, event: tk.Event) -> None:
        self._resize_start = (event.x_root, event.y_root, self._root.winfo_width(), self._root.winfo_height())

    def _on_resize_drag(self, event: tk.Event) -> None:
        if self._resize_start is None:
            return
        sx, sy, sw, sh = self._resize_start
        new_w = sw + (event.x_root - sx)
        new_h = sh + (event.y_root - sy)
        new_w = max(MIN_WIDTH, min(new_w, 1200))
        new_h = max(MIN_HEIGHT, min(new_h, 600))
        self._width = new_w
        self._height = new_h
        self._root.geometry(f"{new_w}x{new_h}")
        char_width = max(20, (new_w - PADX * 2 - RESIZE_HANDLE_SIZE - 24) // 10)
        line_height_px = max(12, int(self._font_size * 1.4))
        height_lines = max(3, (new_h - PADY * 2 - 24) // line_height_px)
        self._text.config(width=char_width, height=height_lines)

    def _on_resize_release(self, event: tk.Event) -> None:
        self._resize_start = None

    def set_partial(self, text: str) -> None:
        self._partial = text or ""
        self._update_display()

    def append_final(self, text: str) -> None:
        if not text:
            return
        text = text.strip()
        max_merge_chars = 25
        if self._lines and len(text) <= max_merge_chars and text.count(" ") <= 1:
            last = self._lines[-1]
            if len(last) + 1 + len(text) <= 72:
                self._lines[-1] = f"{last} {text}"
                self._partial = ""
                self._update_display()
                return
        self._lines.append(text)
        while len(self._lines) > MAX_LINES_STORED:
            self._lines.pop(0)
        self._partial = ""
        self._update_display()

    def _update_display(self) -> None:
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        if self._lines:
            full = " ".join(self._lines).strip()
            self._text.insert(tk.END, full + " ", "final")
        if self._partial:
            if self._lines:
                self._text.insert(tk.END, " ", "final")
            self._text.insert(tk.END, self._partial.strip(), "partial")
        if not self._lines and not self._partial.strip():
            self._text.insert(tk.END, "—", "final")
        self._text.config(state=tk.DISABLED)
        # Scroll to bottom so latest text is visible (user can scroll up to see rest)
        self._text.see(tk.END)
        self._update_volume_bar()

    def set_volume_level(self, level: float) -> None:
        """
        Update the current audio level for the volume bar.
        level expected in [0, 1].
        """
        try:
            self._level = float(level)
        except (TypeError, ValueError):
            self._level = 0.0
        self._update_volume_bar()

    def run(self) -> None:
        self._root.mainloop()

    def update_idletasks(self) -> None:
        self._root.update_idletasks()

    def destroy(self) -> None:
        self._root.destroy()
