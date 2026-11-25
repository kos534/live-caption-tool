"""The ⚙ Settings view: fills the caption window's body with a scrollable form.

Sections: Display (font size, screen-share hiding; applied immediately), Personal info, Job (resume
upload + job description) and Security (OpenAI API key). The form edits a UserSettings object only
when Save is pressed; Cancel puts the fields back to the saved values.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from theme import (
    BG, ERROR_FG, FIELD_BG, FIELD_BORDER, FIELD_FOCUS, HOVER, ICON_FG, MUTED, PANEL_BG, PILL_BG,
    PILL_HOVER_BG, SELECT_BG, SWITCH_H, SWITCH_ON, SWITCH_W, TEXT_FINAL, TITLE_FG,
)
from answerer import DEFAULT_ANSWER_PROMPT
from user_settings import DOCUMENT_TYPES, UserSettings, read_document

LABEL_W = 11  # characters: width of the field labels column


class SettingsView(tk.Frame):
    def __init__(self, parent, font_family: str, on_font_delta, on_share_toggle, on_save, on_cancel):
        super().__init__(parent, bg=BG)
        self.ff = font_family
        self._on_share_toggle = on_share_toggle
        self._share_hidden = False
        self._key_shown = False

        # Action bar pinned to the bottom, then the scrolling form above it.
        bar = tk.Frame(self, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(4, 4))
        self.message = tk.Label(bar, text="", bg=BG, fg=MUTED, font=(font_family, 9), anchor="w")
        self.message.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self._pill(bar, "✓ Save", on_save).pack(side="right", padx=(6, 10))
        self._pill(bar, "Cancel", on_cancel).pack(side="right")

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0, yscrollincrement=24)
        self.canvas.pack(side="top", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))

        tk.Label(
            self.content, text="✧  Settings", bg=BG, fg=TITLE_FG, font=(font_family, 13, "bold"), anchor="w"
        ).pack(side="top", fill="x", padx=6, pady=(8, 2))

        self._build_display(on_font_delta)
        self._build_personal()
        self._build_job()
        self._build_prompt()
        self._build_security()

    # ---- building blocks ------------------------------------------------------------------

    def _pill(self, parent, text, command, bg=PILL_BG):
        btn = tk.Label(parent, text=text, bg=bg, fg=ICON_FG, font=(self.ff, 10, "bold"), cursor="hand2", padx=12, pady=3)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(fg=HOVER, bg=PILL_HOVER_BG))
        btn.bind("<Leave>", lambda e: btn.configure(fg=ICON_FG, bg=bg))
        return btn

    def _card(self, title: str) -> tk.Frame:
        card = tk.Frame(self.content, bg=PANEL_BG, padx=14, pady=10)
        card.pack(side="top", fill="x", padx=6, pady=6)
        tk.Label(card, text=f"✦  {title}", bg=PANEL_BG, fg=TITLE_FG, font=(self.ff, 10, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        card.columnconfigure(1, weight=1)
        return card

    def _label(self, card, row, text, top=False):
        tk.Label(card, text=text, bg=PANEL_BG, fg=MUTED, font=(self.ff, 9), width=LABEL_W, anchor="nw" if top else "w").grid(
            row=row, column=0, sticky="nw" if top else "w", pady=4, padx=(0, 8)
        )

    def _field_style(self):
        return dict(
            bg=FIELD_BG, fg=TEXT_FINAL, insertbackground=TEXT_FINAL, relief="flat", font=(self.ff, 10),
            highlightthickness=1, highlightbackground=FIELD_BORDER, highlightcolor=FIELD_FOCUS,
            selectbackground=SELECT_BG, selectforeground="#ffffff",
        )

    def _entry(self, card, row, label, **kw) -> tk.Entry:
        self._label(card, row, label)
        entry = tk.Entry(card, **self._field_style(), **kw)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4, ipady=4)
        return entry

    def _text_area(self, card, row, label, height) -> tk.Text:
        self._label(card, row, label, top=True)
        text = tk.Text(card, height=height, wrap="word", padx=8, pady=6, undo=True, **self._field_style())
        text.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        return text

    def _hint(self, card, row, text, fg=MUTED) -> tk.Label:
        hint = tk.Label(card, text=text, bg=PANEL_BG, fg=fg, font=(self.ff, 8), anchor="w", justify="left")
        hint.grid(row=row, column=1, columnspan=2, sticky="w")
        return hint

    # ---- sections -------------------------------------------------------------------------

    def _build_display(self, on_font_delta):
        card = self._card("Display")
        self._label(card, 1, "Font size")
        row = tk.Frame(card, bg=PANEL_BG)
        row.grid(row=1, column=1, sticky="w", pady=4)
        self._pill(row, "−", lambda: on_font_delta(-1)).pack(side="left", padx=(0, 4))
        self.font_size_label = tk.Label(row, text="", bg=PANEL_BG, fg=TITLE_FG, font=(self.ff, 10, "bold"), width=3)
        self.font_size_label.pack(side="left")
        self._pill(row, "+", lambda: on_font_delta(1)).pack(side="left", padx=(4, 0))

        self._label(card, 2, "Screen share")
        row = tk.Frame(card, bg=PANEL_BG)
        row.grid(row=2, column=1, sticky="w", pady=4)
        self.share_switch = tk.Canvas(row, width=SWITCH_W, height=SWITCH_H, bg=PANEL_BG, highlightthickness=0, bd=0, cursor="hand2")
        self.share_switch.pack(side="left")
        self.share_switch.bind("<Button-1>", lambda e: self._on_share_toggle())
        self.share_state_label = tk.Label(row, text="", bg=PANEL_BG, fg=MUTED, font=(self.ff, 9))
        self.share_state_label.pack(side="left", padx=(8, 0))
        self.set_share_hidden(False)

    def _build_personal(self):
        card = self._card("Personal info")
        self.name_entry = self._entry(card, 1, "Name")
        self.birthday_entry = self._entry(card, 2, "Birthday")
        self._hint(card, 3, "e.g. 1995-04-01")
        self.address_entry = self._entry(card, 4, "Address")
        self.university_entry = self._entry(card, 5, "University")

    def _build_job(self):
        card = self._card("Job")
        self._label(card, 1, "Resume")
        row = tk.Frame(card, bg=PANEL_BG)
        row.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self._pill(row, "⇪ Upload…", self._upload_resume).pack(side="left")
        self.resume_file_label = tk.Label(row, text="", bg=PANEL_BG, fg=TEXT_FINAL, font=(self.ff, 9), anchor="w")
        self.resume_file_label.pack(side="left", padx=(10, 0), fill="x", expand=True)
        self._pill(row, "Remove", self._remove_resume).pack(side="right")
        self.resume_status = self._hint(card, 2, "PDF, Word (.docx) or text file. The text below is what the AI sees; you can edit it.")
        self.resume_text = self._text_area(card, 3, "", height=7)
        self.jd_text = self._text_area(card, 4, "Job\ndescription", height=7)
        self._hint(card, 5, "Paste the job description (JD) here.")
        self._resume_file = ""

    def _build_prompt(self):
        card = self._card("Answer prompt")
        self.prompt_text = self._text_area(card, 1, "Instructions", height=9)
        row = tk.Frame(card, bg=PANEL_BG)
        row.grid(row=2, column=1, columnspan=2, sticky="ew")
        tk.Label(
            row, bg=PANEL_BG, fg=MUTED, font=(self.ff, 8), anchor="w", justify="left",
            text="How the AI should write answers. Your personal info, resume\nand job description are added after it automatically.",
        ).pack(side="left")
        self._pill(row, "Reset to default", self._reset_prompt).pack(side="right")

    def _reset_prompt(self):
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", DEFAULT_ANSWER_PROMPT)

    def _build_security(self):
        card = self._card("Security")
        self._label(card, 1, "OpenAI key")
        self.key_entry = tk.Entry(card, show="•", **self._field_style())
        self.key_entry.grid(row=1, column=1, sticky="ew", pady=4, ipady=4)
        self.key_toggle = self._pill(card, "Show", self._toggle_key)
        self.key_toggle.grid(row=1, column=2, sticky="e", padx=(8, 0))
        self._hint(
            card, 2,
            "Stored encrypted for your Windows account (settings.json next to the app).\n"
            "Leave empty to use the OPENAI_API_KEY environment variable instead.",
        )

    # ---- actions --------------------------------------------------------------------------

    def _upload_resume(self):
        documents = Path.home() / "Documents"
        path = filedialog.askopenfilename(
            parent=self, title="Upload resume", filetypes=DOCUMENT_TYPES,
            initialdir=str(documents if documents.is_dir() else Path.home()),
        )
        if not path:
            return
        try:
            text = read_document(Path(path))
        except ValueError as exc:
            self.resume_status.configure(text=str(exc), fg=ERROR_FG)
            return
        self.resume_text.delete("1.0", "end")
        self.resume_text.insert("1.0", text)
        self._resume_file = Path(path).name
        self.resume_file_label.configure(text=self._resume_file)
        self.resume_status.configure(text=f"Loaded {len(text):,} characters. Press Save to keep it.", fg=MUTED)

    def _remove_resume(self):
        self.resume_text.delete("1.0", "end")
        self._resume_file = ""
        self.resume_file_label.configure(text="No resume uploaded", fg=MUTED)

    def _toggle_key(self):
        self._key_shown = not self._key_shown
        self.key_entry.configure(show="" if self._key_shown else "•")
        self.key_toggle.configure(text="Hide" if self._key_shown else "Show")

    # ---- state ----------------------------------------------------------------------------

    def set_font_size(self, size: int):
        self.font_size_label.configure(text=str(size))

    def set_share_hidden(self, on: bool):
        """A rounded on/off switch: violet with the knob right when on, dim with the knob left when off."""
        self._share_hidden = on
        c = self.share_switch
        c.delete("all")
        w, h = SWITCH_W, SWITCH_H
        track = SWITCH_ON if on else PILL_BG
        c.create_oval(0, 0, h, h, fill=track, width=0)
        c.create_oval(w - h, 0, w, h, fill=track, width=0)
        c.create_rectangle(h / 2, 0, w - h / 2, h, fill=track, width=0)
        pad = 3
        x0 = w - h + pad if on else pad
        c.create_oval(x0, pad, x0 + h - 2 * pad, h - pad, fill=TEXT_FINAL if on else MUTED, width=0)
        self.share_state_label.configure(
            text="Hidden from screen sharing" if on else "Visible in screen sharing", fg=TITLE_FG if on else MUTED
        )

    def load(self, s: UserSettings):
        """Fill the form from saved settings (on open, and to discard edits on Cancel)."""
        for entry, value in (
            (self.name_entry, s.name), (self.birthday_entry, s.birthday), (self.address_entry, s.address),
            (self.university_entry, s.university), (self.key_entry, s.openai_api_key),
        ):
            entry.delete(0, "end")
            entry.insert(0, value)
        for text, value in (
            (self.resume_text, s.resume_text),
            (self.jd_text, s.job_description),
            (self.prompt_text, s.answer_prompt or DEFAULT_ANSWER_PROMPT),  # show the default to edit
        ):
            text.delete("1.0", "end")
            text.insert("1.0", value)
            text.edit_reset()
        self._resume_file = s.resume_file
        self.resume_file_label.configure(
            text=s.resume_file or ("Pasted text" if s.resume_text.strip() else "No resume uploaded"),
            fg=TEXT_FINAL if s.resume_file or s.resume_text.strip() else MUTED,
        )
        self.resume_status.configure(
            text="PDF, Word (.docx) or text file. The text below is what the AI sees; you can edit it.", fg=MUTED
        )
        if self._key_shown:
            self._toggle_key()
        self.message.configure(text="")
        self.canvas.yview_moveto(0)

    def store(self, s: UserSettings):
        """Copy the form into the settings object."""
        s.name = self.name_entry.get().strip()
        s.birthday = self.birthday_entry.get().strip()
        s.address = self.address_entry.get().strip()
        s.university = self.university_entry.get().strip()
        s.resume_text = self.resume_text.get("1.0", "end-1c").strip()
        s.resume_file = self._resume_file if s.resume_text else ""
        s.job_description = self.jd_text.get("1.0", "end-1c").strip()
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        # Unchanged (or emptied) = use the default, so improvements to the default still apply later.
        s.answer_prompt = "" if prompt == DEFAULT_ANSWER_PROMPT.strip() else prompt
        s.openai_api_key = self.key_entry.get().strip()

    def show_message(self, text: str, error: bool = False):
        self.message.configure(text=text, fg=ERROR_FG if error else MUTED)

    # ---- scrolling (driven by the window's overlay scrollbar and the mouse wheel) -----------

    def yview(self, *args):
        return self.canvas.yview(*args)

    def yview_moveto(self, fraction):
        self.canvas.yview_moveto(fraction)

    def yview_scroll(self, number, what):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(number, what)

    def on_wheel(self, event):
        """Scroll the form, unless the pointer is over a text area that can scroll itself."""
        widget = event.widget
        if not str(widget).startswith(str(self)):
            return
        if isinstance(widget, tk.Text) and widget.yview() != (0.0, 1.0):
            return  # Tk's own Text binding scrolls it
        self.yview_scroll(-1 if event.delta > 0 else 1, "units")
