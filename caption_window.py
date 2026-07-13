import queue
import tkinter as tk


class CaptionWindow:
    def __init__(
        self,
        width: int,
        height: int,
        min_width: int,
        min_height: int,
        model_choices: list,
        default_model: str,
        font_size: int,
        min_font_size: int,
        max_font_size: int,
    ):
        self.min_width = min_width
        self.min_height = min_height
        self.model_choices = model_choices
        self.font_family = "Segoe UI"
        self.font_size = font_size
        self.min_font_size = min_font_size
        self.max_font_size = max_font_size

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg="#1e1e1e")
        self.root.minsize(self.min_width, self.min_height)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = screen_h - height - 90
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self._partial_start_index = None
        self._on_close_callback = None
        self._on_model_change_callback = None

        self._build_ui(default_model)
        self._bind_drag()
        self._bind_resize()

    def _build_ui(self, default_model: str):
        bg = "#1e1e1e"
        fg = "#f2f2f2"

        self.title_bar = tk.Frame(self.root, bg="#2b2b2b", height=26)
        self.title_bar.pack(side="top", fill="x")
        self.title_bar.pack_propagate(False)

        self.drag_label = tk.Label(
            self.title_bar, text="Live Caption", bg="#2b2b2b", fg="#9a9a9a", font=("Segoe UI", 9)
        )
        self.drag_label.pack(side="left", padx=8)

        self.close_btn = tk.Label(
            self.title_bar, text="✕", bg="#2b2b2b", fg="#9a9a9a", font=("Segoe UI", 10), cursor="hand2"
        )
        self.close_btn.pack(side="right", padx=8)
        self.close_btn.bind("<Button-1>", lambda e: self._handle_close())

        self.copy_btn = tk.Label(
            self.title_bar,
            text="Copy",
            bg="#2b2b2b",
            fg="#d0d0d0",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=6,
        )
        self.copy_btn.pack(side="right", padx=4)
        self.copy_btn.bind("<Button-1>", lambda e: self.copy_to_clipboard())

        self.clear_btn = tk.Label(
            self.title_bar,
            text="Clear",
            bg="#2b2b2b",
            fg="#d0d0d0",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=6,
        )
        self.clear_btn.pack(side="right", padx=4)
        self.clear_btn.bind("<Button-1>", lambda e: self.clear_text())

        self.settings_btn = tk.Label(
            self.title_bar, text="⚙", bg="#2b2b2b", fg="#9a9a9a", font=("Segoe UI", 10), cursor="hand2", padx=4
        )
        self.settings_btn.pack(side="right", padx=4)
        self.settings_btn.bind("<Button-1>", lambda e: self._toggle_settings())

        self.settings_frame = tk.Frame(self.root, bg="#242424")
        self._build_settings_panel(default_model)

        self.body = tk.Frame(self.root, bg=bg)
        self.body.pack(side="top", fill="both", expand=True)

        self.text = tk.Text(
            self.body,
            bg=bg,
            fg=fg,
            insertbackground=fg,
            wrap="word",
            font=(self.font_family, self.font_size),
            relief="flat",
            padx=12,
            pady=8,
            highlightthickness=0,
            borderwidth=0,
            state="disabled",
            selectbackground="#3a6ea5",
            selectforeground="#ffffff",
        )
        self.text.pack(side="left", fill="both", expand=True)

        self.grip = tk.Label(self.body, text="⤡", bg=bg, fg="#5a5a5a", cursor="size_nw_se")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")

    def _build_settings_panel(self, default_model: str):
        panel_bg = "#242424"
        row_bg = "#2b2b2b"

        model_row = tk.Frame(self.settings_frame, bg=panel_bg)
        model_row.pack(side="top", fill="x", padx=8, pady=(6, 3))
        tk.Label(model_row, text="Model:", bg=panel_bg, fg="#9a9a9a", font=("Segoe UI", 9)).pack(side="left")

        self.model_var = tk.StringVar(value=default_model)
        model_menu = tk.OptionMenu(model_row, self.model_var, *self.model_choices, command=self._handle_model_change)
        model_menu.configure(
            bg=row_bg,
            fg="#d0d0d0",
            activebackground="#3a3a3a",
            activeforeground="#ffffff",
            highlightthickness=0,
            bd=0,
            font=("Segoe UI", 9),
        )
        model_menu["menu"].configure(bg=row_bg, fg="#d0d0d0")
        model_menu.pack(side="left", padx=6)

        font_row = tk.Frame(self.settings_frame, bg=panel_bg)
        font_row.pack(side="top", fill="x", padx=8, pady=(3, 6))
        tk.Label(font_row, text="Font size:", bg=panel_bg, fg="#9a9a9a", font=("Segoe UI", 9)).pack(side="left")

        minus_btn = tk.Label(
            font_row, text="−", bg=row_bg, fg="#d0d0d0", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=8
        )
        minus_btn.pack(side="left", padx=(6, 2))
        minus_btn.bind("<Button-1>", lambda e: self._change_font_size(-1))

        self.font_size_label = tk.Label(
            font_row, text=str(self.font_size), bg=panel_bg, fg="#f2f2f2", font=("Segoe UI", 9), width=3
        )
        self.font_size_label.pack(side="left")

        plus_btn = tk.Label(
            font_row, text="+", bg=row_bg, fg="#d0d0d0", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=8
        )
        plus_btn.pack(side="left", padx=(2, 6))
        plus_btn.bind("<Button-1>", lambda e: self._change_font_size(1))

    def _toggle_settings(self):
        if self.settings_frame.winfo_manager():
            self.settings_frame.pack_forget()
        else:
            self.settings_frame.pack(side="top", fill="x", before=self.body)

    def _handle_model_change(self, value):
        if self._on_model_change_callback:
            self._on_model_change_callback(value)

    def _change_font_size(self, delta: int):
        new_size = max(self.min_font_size, min(self.max_font_size, self.font_size + delta))
        if new_size == self.font_size:
            return
        self.font_size = new_size
        self.text.configure(font=(self.font_family, self.font_size))
        self.font_size_label.configure(text=str(self.font_size))

    def _bind_drag(self):
        drag_data = {"x": 0, "y": 0}

        def start_drag(event):
            drag_data["x"] = event.x
            drag_data["y"] = event.y

        def do_drag(event):
            x = self.root.winfo_x() + (event.x - drag_data["x"])
            y = self.root.winfo_y() + (event.y - drag_data["y"])
            self.root.geometry(f"+{x}+{y}")

        for widget in (self.title_bar, self.drag_label):
            widget.bind("<ButtonPress-1>", start_drag)
            widget.bind("<B1-Motion>", do_drag)

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

    def set_on_model_change(self, callback):
        self._on_model_change_callback = callback

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

    def clear_text(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._partial_start_index = None

    def _set_editable(self, editable: bool):
        self.text.configure(state="normal" if editable else "disabled")

    def append_final(self, line: str):
        if not line:
            return
        if line[-1] not in ".!?":
            line += "."
        self._set_editable(True)
        if self._partial_start_index is not None:
            self.text.delete(self._partial_start_index, "end")
        self.text.insert("end", line + "\n")
        self._partial_start_index = None
        self.text.see("end")
        self._set_editable(False)

    def update_partial(self, line: str):
        self._set_editable(True)
        if self._partial_start_index is None:
            self._partial_start_index = self.text.index("end-1c")
        else:
            self.text.delete(self._partial_start_index, "end")
        self.text.insert(self._partial_start_index, line)
        self.text.see("end")
        self._set_editable(False)

    def poll_queue(self, text_queue: queue.Queue, interval_ms: int = 80):
        drained = 0
        try:
            while drained < 20:
                kind, text = text_queue.get_nowait()
                if kind == "final":
                    self.append_final(text)
                else:
                    self.update_partial(text)
                drained += 1
        except queue.Empty:
            pass
        self.root.after(interval_ms, lambda: self.poll_queue(text_queue, interval_ms))

    def run(self):
        self.root.mainloop()
