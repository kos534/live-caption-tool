import queue
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

from settings_view import SettingsView
from theme import *  # noqa: F401,F403  (palette constants)
from user_settings import UserSettings

APP_NAME = "Wonuva Live Caption"
PARAGRAPH_GAP_S = 6.0  # start a new paragraph when captions resume after a pause this long

BORDER = 2  # width of the glowing gradient frame around the window
RADIUS = 10  # corner radius of the window
INSET = 6  # keeps the (rectangular) caption area clear of the rounded bottom corners
TITLE_H = 44
# Windows 11-style overlay scrollbar along the window's right edge: a thin line at rest that
# widens into a rounded thumb (with a faint track) while the mouse is over it.
SCROLL_ZONE = 12  # width of the strip reserved for the scrollbar at the right edge
SCROLL_THIN = 3
SCROLL_WIDE = 7
SCROLL_THUMB = "#6a58b0"
SCROLL_THUMB_HOVER = "#a48bff"
SCROLL_TRACK = "#1d1540"
GRIP_ZONE = 34  # space kept clear at the bottom-right for the resize grip
# Window pixels painted this color become fully transparent (-transparentcolor), which is what
# cuts the rectangular Tk window down to the rounded shape. Must not be used anywhere else.
TRANSPARENT_KEY = "#010203"
# Sparkle decorations in the title strip: (fraction of free width, y, glyph, size).
SPARKLES = [(0.18, 11, "✦", 7), (0.42, 30, "✧", 8), (0.63, 13, "✦", 6), (0.86, 28, "✧", 7)]


def _rgb(color: str):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def _gradient_at(stops: list, t: float) -> str:
    pos = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    return _mix(stops[i], stops[i + 1], pos - i)


def _corner_inset(pos: float, length: int, radius: float) -> float:
    """How far a rounded-rect edge is pulled in at `pos` along a side of `length` (0 away from corners)."""
    d = min(pos + 0.5, length - pos - 0.5)  # distance (pixel center) to the nearer end of the side
    if d >= radius:
        return 0.0
    dy = radius - d
    return radius - (max(0.0, radius * radius - dy * dy)) ** 0.5


def _pick_font(*families: str) -> str:
    available = set(tkfont.families())
    return next((f for f in families if f in available), "TkDefaultFont")


class CaptionWindow:
    def __init__(
        self,
        width: int,
        height: int,
        min_width: int,
        min_height: int,
        font_size: int,
        min_font_size: int,
        max_font_size: int,
        assets_dir: Path = None,
        version: str = "",
        user_settings: UserSettings = None,
        settings_path: Path = None,
    ):
        self.version = version
        self.user_settings = user_settings if user_settings is not None else UserSettings()
        self.settings_path = settings_path
        self.min_width = min_width
        self.min_height = min_height
        self.font_size = font_size
        self.min_font_size = min_font_size
        self.max_font_size = max_font_size
        self.assets_dir = Path(assets_dir) if assets_dir else None

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.minsize(self.min_width, self.min_height)

        self.font_family = _pick_font("Segoe UI", "Arial")
        self.title_font = (_pick_font("Gabriola", "Palatino Linotype", "Georgia"), 19, "bold")
        self.status_font = tkfont.Font(family=self.font_family, size=8, slant="italic")
        self.icon_font = (_pick_font("Segoe UI Symbol", "Segoe UI"), 12)
        self.button_font = (_pick_font("Segoe UI Semibold", "Segoe UI"), 9)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = screen_h - height - 90
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self._partial_active = False
        self._last_activity = None
        self._on_close_callback = None
        self._on_share_toggle = None
        self._share_hidden = False
        self._flash_job = None
        self._status_before_flash = ""
        self._status = ""
        self._images = {}
        self._sparkle_ids = []
        self._sparkle_step = 0
        self._partial_tags = ()  # extra tags for the in-progress caption (e.g. "question")
        self._answerer = None
        self._next_answer_id = 0
        self._loading = {}  # answer id -> placeholder label ('loading', 'searching the web') until text arrives
        self._loading_step = 0
        self._loading_job = None
        self._answer_floor = 0  # answer ids below this were asked before the last Clear

        self._load_icons()
        self._build_ui()
        self._bind_drag()
        self._bind_resize()
        self._twinkle()

    # ---- assets ---------------------------------------------------------------------------

    def _load_icons(self):
        if not self.assets_dir:
            return
        try:
            for size in (16, 32, 48, 128):
                path = self.assets_dir / f"icon{size}.png"
                if path.exists():
                    self._images[size] = tk.PhotoImage(file=str(path))
            if self._images:
                self.root.iconphoto(True, *[self._images[s] for s in sorted(self._images, reverse=True)])
        except tk.TclError:
            self._images = {}  # missing/unreadable icons only cost the decoration

    # ---- layout ---------------------------------------------------------------------------

    def _build_ui(self):
        # One canvas fills the window and paints the rounded shape: the gradient frame, the title
        # strip and the body background. Everything outside the shape is TRANSPARENT_KEY, i.e. see-
        # through. The title strip's logo/text/buttons are items on this same canvas.
        self.title_bar = tk.Canvas(self.root, bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.title_bar.place(x=0, y=0, relwidth=1, relheight=1)

        # Settings panel + caption text sit in a plain frame inside the shape, inset from the
        # rounded bottom corners.
        self.inner = tk.Frame(self.root, bg=BG)
        side = BORDER + INSET
        self.inner.place(
            x=side,
            y=TITLE_H + 1,
            relwidth=1,
            relheight=1,
            width=-(side + BORDER + SCROLL_ZONE),
            height=-(TITLE_H + 1 + side),
        )

        # Scrollbar strip hugging the right edge, from the title seam down to just above the
        # resize grip (which would otherwise cover the bottom of the thumb).
        self.scrollbar = tk.Canvas(self.root, width=SCROLL_ZONE, bg=BG, highlightthickness=0, bd=0)
        self.scrollbar.place(
            relx=1.0, x=-BORDER, y=TITLE_H + 6, anchor="ne", relheight=1, height=-(TITLE_H + 6 + GRIP_ZONE)
        )

        self._build_title_bar()


        # Footer with the Answer button, packed before the body so it keeps its space when small.
        self.footer = tk.Frame(self.inner, bg=BG)
        self.footer.pack(side="bottom", fill="x")
        self._build_answer_button()

        self.body = tk.Frame(self.inner, bg=BG)
        self.body.pack(side="top", fill="both", expand=True)

        self.text = tk.Text(
            self.body,
            bg=BG,
            fg=TEXT_FINAL,
            insertbackground=TEXT_FINAL,
            wrap="word",
            font=(self.font_family, self.font_size),
            relief="flat",
            padx=16,
            pady=10,
            spacing1=2,
            spacing3=10,  # extra space after each paragraph (each sentence-ending caption)
            highlightthickness=0,
            borderwidth=0,
            state="disabled",
            selectbackground=SELECT_BG,
            selectforeground="#ffffff",
            cursor="arrow",
        )
        self.text.tag_configure("partial", foreground=TEXT_PARTIAL)
        self.text.tag_configure("question", background=QUESTION_BG, lmargin1=6, lmargin2=6, rmargin=6)
        self.text.tag_configure(
            "answer_head", foreground=TITLE_FG, font=(self.font_family, 9, "bold"), spacing1=4, spacing3=2
        )
        self.text.tag_configure("answer", foreground=ANSWER_FG, lmargin1=14, lmargin2=14)
        self.text.tag_configure("answer_loading", foreground=MUTED, lmargin1=14, lmargin2=14)
        self.text.tag_configure("answer_error", foreground=ERROR_FG, lmargin1=14, lmargin2=14)
        self.text.tag_raise("sel")
        # Everything after this mark is the caption text the next Answer click will send.
        self.text.mark_set("segment_start", "1.0")
        self.text.mark_gravity("segment_start", "left")

        self.text.pack(side="left", fill="both", expand=True)

        # Full-size Settings view, placed over the captions while open.
        self.settings_view = SettingsView(
            self.inner,
            self.font_family,
            on_font_delta=self._change_font_size,
            on_share_toggle=self._handle_share_toggle,
            on_save=self._save_settings,
            on_cancel=self._cancel_settings,
        )
        self.settings_view.set_font_size(self.font_size)
        self._scroll_target = self.text  # what the overlay scrollbar scrolls

        self._scroll_pos = (0.0, 1.0)
        self._scroll_hover = False
        self._bind_scrollbar()
        self._poll_scroll()

        # Resize grip in the bottom-right corner, below the scrollbar strip.
        self.grip = tk.Label(self.root, text="⤡", bg=BG, fg=SPARKLE_DIM, cursor="size_nw_se", font=self.icon_font)
        self.grip.place(relx=1.0, rely=1.0, anchor="se", x=-(BORDER + 4), y=-(BORDER + 2))
        self._hover(self.grip, SPARKLE_DIM, HOVER)

    # ---- scrolling ------------------------------------------------------------------------

    def _poll_scroll(self):
        """Keep the scrollbar in sync with the text view.

        Polled instead of relying on the Text widget's yscrollcommand, which Tk doesn't fire
        reliably in this window. Cheap: it only redraws when the view actually moved.
        """
        pos = tuple(self._scroll_target.yview())
        if pos != self._scroll_pos:
            self._scroll_pos = pos
            self._draw_scroll_thumb()
        self.root.after(120, self._poll_scroll)

    def _bar(self, canvas, x0, y0, x1, y1, fill, tags):
        """A slim vertical bar with softened ends.

        Built from two overlapping rectangles (one 1px narrower, one 1px shorter) for 1px rounded
        corners. Tk's ovals are avoided: at 3-7px they render as a stray 1px sliver, not a cap.
        """
        x0, y0, x1, y1 = round(x0), round(y0), round(x1), round(y1)
        canvas.create_rectangle(x0 + 1, y0, x1 - 1, y1, fill=fill, width=0, tags=tags)
        canvas.create_rectangle(x0, y0 + 1, x1, y1 - 1, fill=fill, width=0, tags=tags)

    def _draw_scroll_thumb(self):
        sb = self.scrollbar
        sb.delete("bar")
        first, last = self._scroll_pos
        if first <= 0.0 and last >= 1.0:
            return  # everything fits: no scrollbar, like Windows 11
        h = sb.winfo_height()
        width = SCROLL_WIDE if self._scroll_hover else SCROLL_THIN
        x1 = SCROLL_ZONE - 3
        x0 = x1 - width
        if self._scroll_hover:
            self._bar(sb, x0, 0, x1, h, SCROLL_TRACK, "bar")
        y0 = first * h
        y1 = max(y0 + 18, last * h)  # keep the thumb grabbable when the transcript is long
        if y1 > h:
            y0, y1 = h - (y1 - y0), h
        self._bar(sb, x0, y0, x1, y1, SCROLL_THUMB_HOVER if self._scroll_hover else SCROLL_THUMB, "bar")

    def _bind_scrollbar(self):
        sb = self.scrollbar
        drag = {"y": 0, "first": 0.0}

        def set_hover(on):
            self._scroll_hover = on
            self._draw_scroll_thumb()

        def press(event):
            first, last = self._scroll_pos
            h = max(1, sb.winfo_height())
            if not (first * h <= event.y <= last * h):
                # Clicked the track: center the thumb there.
                self._scroll_target.yview_moveto(event.y / h - (last - first) / 2)
                first = self._scroll_target.yview()[0]
            drag["y"], drag["first"] = event.y, first

        def motion(event):
            h = max(1, sb.winfo_height())
            self._scroll_target.yview_moveto(drag["first"] + (event.y - drag["y"]) / h)
            self._scroll_pos = tuple(self._scroll_target.yview())
            self._draw_scroll_thumb()

        def wheel(event):
            self._scroll_target.yview_scroll(-1 if event.delta > 0 else 1, "units")

        sb.bind("<Enter>", lambda e: set_hover(True))
        sb.bind("<Leave>", lambda e: set_hover(False))
        sb.bind("<ButtonPress-1>", press)
        sb.bind("<B1-Motion>", motion)
        sb.bind("<Configure>", lambda e: self._draw_scroll_thumb())
        sb.bind("<MouseWheel>", wheel)

    def _at_end(self) -> bool:
        """True if the view shows the end of the transcript (so new captions should be followed)."""
        if not self.text.winfo_ismapped():
            return True  # not laid out yet: its view fractions are meaningless, so keep following
        return self.text.yview()[1] >= 0.999

    def _build_title_bar(self):
        c = self.title_bar
        mid = TITLE_H // 2 + 1
        x = BORDER + 14
        logo = self._images.get(32)
        if logo is not None:
            c.create_image(x, mid, image=logo, anchor="w", tags="fixed")
            x += 32 + 8
        self.title_id = c.create_text(x, mid + 1, text=APP_NAME, anchor="w", fill=TITLE_FG, font=self.title_font, tags="fixed")
        self.version_id = c.create_text(
            0, mid, text=f"v{self.version}" if self.version else "", anchor="w", fill=MUTED,
            font=(self.font_family, 8), tags="fixed",
        )
        self.status_id = c.create_text(0, mid + 1, text="", anchor="w", fill=MUTED, font=self.status_font, tags="fixed")

        for _, y, glyph, size in SPARKLES:
            self._sparkle_ids.append(c.create_text(0, y, text=glyph, fill=SPARKLE_DIM, font=(self.font_family, size)))

        # Right-aligned controls, laid out right to left on every resize.
        self.buttons = []
        for name, label, font, hover, action in (
            ("close", "✕", self.icon_font, CLOSE_HOVER, self._handle_close),
            ("save", "Save", self.button_font, HOVER, self.save_transcript),
            ("copy", "Copy", self.button_font, HOVER, self.copy_to_clipboard),
            ("clear", "Clear", self.button_font, HOVER, self.clear_text),
            ("settings", "⚙", self.icon_font, HOVER, self._toggle_settings),
        ):
            item = c.create_text(0, mid, text=label, anchor="e", fill=ICON_FG, font=font, tags=("button", name))
            c.tag_bind(item, "<Enter>", lambda e, i=item, h=hover: (c.itemconfigure(i, fill=h), c.configure(cursor="hand2")))
            c.tag_bind(item, "<Leave>", lambda e, i=item: (c.itemconfigure(i, fill=ICON_FG), c.configure(cursor="")))
            c.tag_bind(item, "<ButtonRelease-1>", lambda e, a=action: a())
            self.buttons.append(item)

        c.bind("<Configure>", lambda e: self._draw_chrome(e.width, e.height))

    def _draw_chrome(self, w: int, h: int):
        """Paint the rounded window: gradient frame, title strip, seam and body background."""
        c = self.title_bar
        c.delete("chrome")
        # Outer rounded shape filled with the horizontal flame gradient, one column at a time
        # (1px columns in the corners for a clean curve, wider ones along the straight edge).
        x = 0
        while x < w:
            step = 1 if x < RADIUS or x >= w - RADIUS else 3
            inset = _corner_inset(x, w, RADIUS)
            color = _gradient_at(GRADIENT, x / max(1, w - 1))
            c.create_rectangle(x, inset, x + step, h - inset, fill=color, width=0, tags="chrome")
            x += step
        # Inner rounded shape, BORDER px in, so only a thin ring of the gradient stays visible.
        # Drawn row by row: dusk gradient for the title strip, then the body color.
        ih, iw, ir = h - 2 * BORDER, w - 2 * BORDER, RADIUS - BORDER
        for row in range(ih):
            y = BORDER + row
            inset = _corner_inset(row, ih, ir)
            if y < TITLE_H:
                color = _mix(TITLE_TOP, TITLE_BOTTOM, y / (TITLE_H - 1))
            else:
                color = BG
            c.create_rectangle(BORDER + inset, y, BORDER + iw - inset, y + 1, fill=color, width=0, tags="chrome")
        # Glowing gradient seam under the title strip.
        step = 4
        for x in range(BORDER, w - BORDER, step):
            color = _gradient_at(GRADIENT, x / max(1, w - 1))
            c.create_rectangle(x, TITLE_H, x + step, TITLE_H + 1, fill=color, width=0, tags="chrome")
        c.tag_lower("chrome")
        self._layout_title(w)

    def _layout_title(self, w: int):
        c = self.title_bar
        if w <= 1:
            return
        right = w - BORDER - 14
        for item in self.buttons:
            c.coords(item, right, TITLE_H // 2 + 1)
            x0, _, x1, _ = c.bbox(item)
            right -= (x1 - x0) + 16
        buttons_left = right + 16

        # Version tag right after the title. Narrow window: drop the title text and version (the
        # logo stays) rather than run into the buttons.
        c.itemconfigure(self.title_id, state="normal")
        c.itemconfigure(self.version_id, state="normal")
        title_left, _, title_right, _ = c.bbox(self.title_id)
        c.coords(self.version_id, title_right + 6, TITLE_H // 2 + 3)
        title_right = c.bbox(self.version_id)[2] if self.version else title_right
        if title_right > buttons_left - 10:
            c.itemconfigure(self.title_id, state="hidden")
            c.itemconfigure(self.version_id, state="hidden")
            title_right = title_left - 8
        c.coords(self.status_id, title_right + 10, TITLE_H // 2 + 2)
        self._fit_status(buttons_left - (title_right + 10) - 12)

        # Sparkles only in the empty stretch after the status text, never over it; hidden if no room.
        status_box = c.bbox(self.status_id)
        free_left = (status_box[2] if status_box and c.itemcget(self.status_id, "text") else title_right) + 14
        free_right = buttons_left - 14
        room = free_right - free_left
        for item, (frac, y, _, _) in zip(self._sparkle_ids, SPARKLES):
            c.coords(item, free_left + frac * max(0, room), y)
            c.itemconfigure(item, state="normal" if room >= 40 else "hidden")

    def _fit_status(self, max_px: int):
        """Show as much of the status as fits between the title and the buttons."""
        text = self._status
        if max_px < 30:
            text = ""
        elif self.status_font.measure(text) > max_px:
            while text and self.status_font.measure(text + "…") > max_px:
                text = text[:-1]
            text = text.rstrip() + "…" if text else ""
        self.title_bar.itemconfigure(self.status_id, text=text)

    def _twinkle(self):
        """Gently cycle one sparkle at a time to bright gold."""
        if self._sparkle_ids:
            lit = self._sparkle_step % len(self._sparkle_ids)
            for i, item in enumerate(self._sparkle_ids):
                self.title_bar.itemconfigure(item, fill=SPARKLE_BRIGHT if i == lit else SPARKLE_DIM)
            self._sparkle_step += 1
        self.root.after(900, self._twinkle)

    def _hover(self, widget, normal_fg, hover_fg, normal_bg=None, hover_bg=None):
        def enter(_):
            widget.configure(fg=hover_fg, **({"bg": hover_bg} if hover_bg else {}))

        def leave(_):
            widget.configure(fg=normal_fg, **({"bg": normal_bg} if normal_bg else {}))

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _build_answer_button(self):
        """A rounded violet-outlined pill, right-aligned under the captions."""
        c = tk.Canvas(self.footer, width=ANSWER_W, height=ANSWER_H, bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        c.pack(side="right", padx=(0, 10), pady=(2, 4))
        r, w, h = 12, ANSWER_W - 2, ANSWER_H - 2
        pts = [1 + r, 1, w - r, 1, w, 1, w, 1 + r, w, h - r, w, h, w - r, h, 1 + r, h, 1, h, 1, h - r, 1, 1 + r, 1, 1]
        shape = c.create_polygon(pts, smooth=True, fill=PILL_BG, outline=ANSWER_BUTTON_OUTLINE, width=1.5)
        label = c.create_text(ANSWER_W // 2, ANSWER_H // 2, text="✦  Answer", fill=ICON_FG, font=self.button_font)
        c.bind("<Enter>", lambda e: (c.itemconfigure(shape, fill=PILL_HOVER_BG), c.itemconfigure(label, fill=HOVER)))
        c.bind("<Leave>", lambda e: (c.itemconfigure(shape, fill=PILL_BG), c.itemconfigure(label, fill=ICON_FG)))
        c.bind("<ButtonRelease-1>", lambda e: self.request_answer())
        self.answer_button = c

    # ---- fake captions (test mode: main.py --fake) ------------------------------------------

    def enable_fake_captions(self, word_ms: int = 160):
        """Add a box left of the Answer button; each line typed there plays in as a live caption.

        The words appear one by one as an in-progress (partial) caption, then the line is finalized,
        just like real speech, so the Answer flow can be tried without any audio.
        """
        self._fake_lines = []  # lines waiting to be played in
        self._fake_playing = False
        self._fake_word_ms = word_ms
        entry = tk.Entry(
            self.footer, bg=FIELD_BG, fg=TEXT_FINAL, insertbackground=TEXT_FINAL, relief="flat",
            font=(self.font_family, 10), highlightthickness=1, highlightbackground=FIELD_BORDER,
            highlightcolor=FIELD_FOCUS, selectbackground=SELECT_BG, selectforeground="#ffffff",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(6, 10), pady=(2, 4), ipady=5)
        hint = "Fake caption: type what they say, press Enter"

        def show_hint():
            if not entry.get():
                entry.insert(0, hint)
                entry.configure(fg=MUTED)

        def clear_hint(_=None):
            if entry.cget("fg") == MUTED:
                entry.delete(0, "end")
                entry.configure(fg=TEXT_FINAL)

        def submit(_=None):
            if entry.cget("fg") == MUTED:
                return
            line = " ".join(entry.get().split())
            entry.delete(0, "end")
            if line:
                self._fake_lines.append(line)
                if not self._fake_playing:
                    self._play_fake_line()

        entry.bind("<FocusIn>", clear_hint)
        entry.bind("<FocusOut>", lambda e: show_hint())
        entry.bind("<Return>", submit)
        show_hint()
        self.fake_entry = entry

    def _play_fake_line(self):
        if not self._fake_lines:
            self._fake_playing = False
            return
        self._fake_playing = True
        words = self._fake_lines.pop(0).split()

        def step(n):
            if n < len(words):
                self.update_partial(" ".join(words[:n]))
                self.root.after(self._fake_word_ms, lambda: step(n + 1))
            else:
                self.append_final(" ".join(words))
                self.root.after(300, self._play_fake_line)  # short pause between queued lines

        step(1)

    def _handle_share_toggle(self):
        want = not self._share_hidden
        if self._on_share_toggle is not None and not self._on_share_toggle(want):
            self.set_status("Couldn't change screen-share hiding on this Windows version")
            return
        self._share_hidden = want
        self.settings_view.set_share_hidden(want)

    def set_on_screen_share_toggle(self, callback, hidden: bool):
        """Wire the 'Hide from screen share' switch: callback(hidden) -> bool applied; shows `hidden`."""
        self._on_share_toggle = callback
        self._share_hidden = hidden
        self.settings_view.set_share_hidden(hidden)

    # ---- settings view --------------------------------------------------------------------

    def _settings_open(self) -> bool:
        return bool(self.settings_view.winfo_manager())

    def _toggle_settings(self):
        if self._settings_open():
            self._save_settings()  # the ⚙ button closes it like Save, so edits are never lost
        else:
            self._open_settings()

    def _open_settings(self):
        self.settings_view.load(self.user_settings)
        self.settings_view.place(x=0, y=0, relwidth=1, relheight=1)
        self.settings_view.lift()
        self._scroll_target = self.settings_view
        self.root.bind_all("<MouseWheel>", self.settings_view.on_wheel, add="+")

    def _close_settings(self):
        self.settings_view.place_forget()
        self.root.unbind_all("<MouseWheel>")
        self._scroll_target = self.text
        self.text.see("end")

    def _save_settings(self):
        self.settings_view.store(self.user_settings)
        if self.settings_path is not None:
            try:
                self.user_settings.save(self.settings_path)
            except OSError as exc:
                self.settings_view.show_message(f"Couldn't save: {exc.strerror or exc}", error=True)
                return
        self._close_settings()
        self._flash_status("Settings saved")

    def _cancel_settings(self):
        self._close_settings()

    def _change_font_size(self, delta: int):
        new_size = max(self.min_font_size, min(self.max_font_size, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size
        follow = self._at_end()
        self.text.configure(font=(self.font_family, self.font_size))
        if follow:
            self.text.see("end")
        self.settings_view.set_font_size(self.font_size)

    # ---- window behavior ------------------------------------------------------------------

    def _bind_drag(self):
        drag_data = {"x": 0, "y": 0}

        def start_drag(event):
            drag_data["x"] = event.x
            drag_data["y"] = event.y

        def do_drag(event):
            x = self.root.winfo_x() + (event.x - drag_data["x"])
            y = self.root.winfo_y() + (event.y - drag_data["y"])
            self.root.geometry(f"+{x}+{y}")

        self.title_bar.bind("<ButtonPress-1>", start_drag)
        self.title_bar.bind("<B1-Motion>", do_drag)

    def _bind_resize(self):
        resize_data = {"x": 0, "y": 0, "w": 0, "h": 0}

        def start_resize(event):
            resize_data["x"] = event.x_root
            resize_data["y"] = event.y_root
            resize_data["w"] = self.root.winfo_width()
            resize_data["h"] = self.root.winfo_height()

        def do_resize(event):
            dx = event.x_root - resize_data["x"]
            dy = event.y_root - resize_data["y"]
            new_w = max(self.min_width, resize_data["w"] + dx)
            new_h = max(self.min_height, resize_data["h"] + dy)
            self.root.geometry(f"{new_w}x{new_h}")

        self.grip.bind("<ButtonPress-1>", start_resize)
        self.grip.bind("<B1-Motion>", do_resize)

    def set_on_close(self, callback):
        self._on_close_callback = callback

    def _handle_close(self):
        if self._on_close_callback:
            self._on_close_callback()
        self.root.destroy()

    def copy_to_clipboard(self):
        try:
            selected = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            selected = ""
        content = selected if selected.strip() else self.text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def save_transcript(self):
        """Save the whole transcript as a UTF-8 .txt file, chosen in a standard Save dialog."""
        content = self.text.get("1.0", "end-1c").strip()
        if not content:
            self._flash_status("Nothing to save yet")
            return
        documents = Path.home() / "Documents"
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save transcript",
            initialdir=str(documents if documents.is_dir() else Path.home()),
            initialfile=time.strftime("Wonuva Caption %Y-%m-%d %H%M.txt"),
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return  # dialog cancelled
        try:
            # utf-8-sig so Notepad and other Windows apps detect the encoding reliably.
            Path(path).write_text(content + "\n", encoding="utf-8-sig")
        except OSError as exc:
            self._flash_status(f"Couldn't save: {exc.strerror or exc}")
            return
        self._flash_status(f"Saved {Path(path).name}")

    def _flash_status(self, message: str, ms: int = 4000):
        """Show a short message in the title strip, then put the previous status back."""
        if self._flash_job is None:
            self._status_before_flash = self._status
        else:
            self.root.after_cancel(self._flash_job)
        self._status = message
        self._layout_title(self.title_bar.winfo_width())

        def restore():
            self._flash_job = None
            self._status = self._status_before_flash
            self._layout_title(self.title_bar.winfo_width())

        self._flash_job = self.root.after(ms, restore)

    def clear_text(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        for name in self.text.mark_names():
            if name.startswith("ans"):
                self.text.mark_unset(name)
        self.text.mark_set("segment_start", "1.0")
        self._partial_active = False
        self._partial_tags = ()
        self._last_activity = None
        self._loading.clear()
        self._next_answer_id += 1  # answers still in flight belong to the cleared text: drop them
        self._answer_floor = self._next_answer_id
        if self._answerer is not None:
            self._answerer.reset()

    # ---- answers --------------------------------------------------------------------------

    # Each Answer click sends the caption text since the previous click (everything after the
    # "segment_start" mark), tints it as a question block, and adds an answer block below it that
    # shows "loading..." until the reply streams in. New captions continue after the answer block,
    # and form the next question. A caption still in progress at the click stays in the question
    # block and is finalized there (its region has its own start/end marks).

    def set_answerer(self, answerer):
        self._answerer = answerer
        self._poll_answers()

    def request_answer(self):
        if self._answerer is None:
            self._flash_status("Answering isn't available")
            return
        question = self.text.get("segment_start", "end-1c").strip()
        if not question:
            self._flash_status("No new captions to answer yet")
            return
        answer_id = self._next_answer_id
        self._next_answer_id += 1

        follow = self._at_end()
        self._set_editable(True)
        if not self.text.get("end-2c", "end-1c") == "\n":
            self.text.insert("end-1c", "\n")
        self.text.tag_add("question", "segment_start", "end-1c")
        if self._partial_active:
            self._partial_tags = ("question",)  # its final text lands inside the question block
        self.text.insert("end-1c", "✦ Answer\n", ("answer_head",))
        start = self.text.index("end-1c")
        self.text.insert("end-1c", "loading", ("answer_loading",))
        self.text.mark_set(f"ans{answer_id}_start", start)
        self.text.mark_gravity(f"ans{answer_id}_start", "left")
        self.text.mark_set(f"ans{answer_id}_end", "end-1c")
        self.text.mark_gravity(f"ans{answer_id}_end", "left")
        self.text.insert("end-1c", "\n")
        self.text.mark_set("segment_start", "end-1c")
        self._last_activity = None  # the next caption starts its own paragraph after the answer
        if follow:
            self.text.see("end")
        self._set_editable(False)

        self._loading[answer_id] = "loading"
        if self._loading_job is None:
            self._animate_loading()
        self._answerer.ask(answer_id, question)

    def _set_answer_text(self, answer_id: int, text: str, tag: str, append: bool = False):
        start, end = f"ans{answer_id}_start", f"ans{answer_id}_end"
        if start not in self.text.mark_names():
            return
        follow = self._at_end()
        self._set_editable(True)
        if not append:
            self.text.delete(start, end)
        idx = self.text.index(end)
        self.text.insert(idx, text, (tag,))
        self.text.mark_set(end, f"{idx} + {len(text)} chars")
        if follow:
            self.text.see("end")
        self._set_editable(False)

    def _animate_loading(self):
        """Cycle 'loading', 'loading.', ... on every answer still waiting for its first text."""
        self._loading_job = None
        if not self._loading:
            return
        self._loading_step = (self._loading_step + 1) % 4
        for answer_id, label in list(self._loading.items()):
            self._set_answer_text(answer_id, label + "." * self._loading_step, "answer_loading")
        self._loading_job = self.root.after(350, self._animate_loading)

    def _poll_answers(self):
        try:
            while True:
                answer_id, kind, text = self._answerer.events.get_nowait()
                if answer_id < self._answer_floor:
                    continue  # the transcript was cleared since this was asked
                if kind == "status":
                    if answer_id in self._loading:
                        self._loading[answer_id] = text  # e.g. "searching the web"
                    continue
                first = self._loading.pop(answer_id, None) is not None
                if kind == "delta":
                    self._set_answer_text(answer_id, text.lstrip() if first else text, "answer", append=not first)
                elif kind == "done":
                    # The final text has any links/citations stripped: show that version.
                    if text:
                        self._set_answer_text(answer_id, text, "answer")
                    elif first:
                        self._set_answer_text(answer_id, "(no answer)", "answer_loading")
                elif kind == "error":
                    self._set_answer_text(answer_id, f"⚠ {text}", "answer_error", append=not first)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_answers)

    def _set_editable(self, editable: bool):
        self.text.configure(state="normal" if editable else "disabled")

    # ---- captions -------------------------------------------------------------------------

    # Each finished caption that ends a sentence closes its paragraph, so the next caption starts
    # a new one (with extra spacing below, spacing3). A caption that was cut mid-sentence (e.g. by
    # MAX_UTTERANCE_S) continues on the same line, and a long pause always starts a new paragraph.
    # The in-progress (partial) text sits after the "partial_start" mark and is replaced in place.
    #
    # Ranges always end at "end-1c", never "end": a Tk Text widget keeps a permanent trailing
    # newline, and deleting up to "end" makes Tk delete the newline *before* the range instead.
    # That merged lines and left the saved partial position pointing past the text, so every later
    # partial was appended instead of replacing the previous one (the run-on, repeated captions).

    def _separator(self) -> str:
        """Text to put between existing captions and a new caption, decided when the caption starts."""
        before = self.text.get("1.0", "end-1c")
        if not before or before.endswith("\n"):
            return ""
        if before.rstrip().endswith((".", "!", "?", "…", '."', '?"', '!"')):
            return "\n"
        silent_for = time.monotonic() - self._last_activity if self._last_activity is not None else 0.0
        return "\n" if silent_for >= PARAGRAPH_GAP_S else " "

    def _replace_partial(self, text: str, tags=()):
        """Replace the in-progress region with text (starting a new region if there is none).

        Auto-scroll only if the view was already at the end: if the user has scrolled up to read
        something, leave the view where it is; once they scroll back to the end, follow again.
        """
        follow = self._at_end()
        self._set_editable(True)
        if self._partial_active:
            self.text.delete("partial_start", "partial_end")
        else:
            self.text.mark_set("partial_start", "end-1c")
            self.text.mark_gravity("partial_start", "left")
            self._partial_active = True
            self._partial_sep = self._separator()
            self._partial_tags = ()
        # Both marks have left gravity, so an answer block added after the region (Answer clicked
        # mid-caption) doesn't get swallowed into it; partial_end is moved explicitly instead.
        idx = self.text.index("partial_start")
        if text:
            content = self._partial_sep + text
            self.text.insert(idx, content, tuple(tags) + self._partial_tags)
            self.text.mark_set("partial_end", f"{idx} + {len(content)} chars")
            self._last_activity = time.monotonic()
        else:
            self.text.mark_set("partial_end", idx)
        self.text.mark_gravity("partial_end", "left")
        if follow:
            self.text.see("end")
        self._set_editable(False)

    def append_final(self, line: str):
        self._replace_partial(line.strip())
        self._partial_active = False  # the text now stays; the next partial starts a new region

    def update_partial(self, line: str):
        self._replace_partial(line.strip(), ("partial",))

    def set_status(self, message: str):
        if self._flash_job is not None:
            self._status_before_flash = message  # shown once the short message ends
        else:
            self._status = message
            self._layout_title(self.title_bar.winfo_width())
        if "error" in message.lower() or "failed" in message.lower():
            self.append_final(f"[{message}]")

    def poll_queue(self, text_queue: queue.Queue, interval_ms: int = 80):
        drained = 0
        try:
            while drained < 20:
                kind, text = text_queue.get_nowait()
                if kind == "final":
                    self.append_final(text)
                elif kind == "partial":
                    self.update_partial(text)
                else:
                    self.set_status(text)
                drained += 1
        except queue.Empty:
            pass
        self.root.after(interval_ms, lambda: self.poll_queue(text_queue, interval_ms))

    def run(self):
        self.root.mainloop()
