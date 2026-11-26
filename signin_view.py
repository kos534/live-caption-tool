"""Sign-in screen: covers the whole window until the user is signed in to their Wonuva account."""

import threading
import tkinter as tk
import webbrowser

from auth import AuthError, AuthUnavailable, SignInCancelled
from theme import BG, ERROR_FG, HOVER, ICON_FG, MUTED, PANEL_BG, PILL_BG, PILL_HOVER_BG, TEXT_FINAL, TITLE_FG


class SignInView(tk.Frame):
    def __init__(self, parent, font_family: str, auth, call_soon, on_signed_in):
        super().__init__(parent, bg=BG)
        self.ff = font_family
        self.auth = auth
        self.call_soon = call_soon  # runs a function on the Tk thread (results come from workers)
        self.on_signed_in = on_signed_in
        self._cancel = threading.Event()
        self._busy = False

        card = tk.Frame(self, bg=PANEL_BG, padx=24, pady=20)
        card.place(relx=0.5, rely=0.45, anchor="center", relwidth=0.86)
        tk.Label(card, text="✧  Sign in to Wonuva", bg=PANEL_BG, fg=TITLE_FG, font=(font_family, 14, "bold"), anchor="w").pack(
            fill="x"
        )
        self.body = tk.Label(
            card, bg=PANEL_BG, fg=TEXT_FINAL, font=(font_family, 10), anchor="w", justify="left",
            text="Live Caption needs your Wonuva account. Signing in opens the Wonuva page in your "
            "browser; come back here when you're done.",
        )
        self.body.pack(fill="x", pady=(8, 14))
        self.body.bind("<Configure>", lambda e: self.body.configure(wraplength=max(200, e.width)))

        row = tk.Frame(card, bg=PANEL_BG)
        row.pack(fill="x")
        self.button = self._pill(row, "Sign in with Wonuva", self._on_button)
        self.button.pack(side="left")
        self.signup = tk.Label(row, text="Create an account", bg=PANEL_BG, fg=MUTED, font=(font_family, 9, "underline"), cursor="hand2")
        self.signup.pack(side="left", padx=(14, 0))
        self.signup.bind("<Button-1>", lambda e: webbrowser.open(self.auth.signup_url))
        self.signup.bind("<Enter>", lambda e: self.signup.configure(fg=HOVER))
        self.signup.bind("<Leave>", lambda e: self.signup.configure(fg=MUTED))

        self.status = tk.Label(card, text="", bg=PANEL_BG, fg=MUTED, font=(font_family, 9), anchor="w", justify="left")
        self.status.pack(fill="x", pady=(12, 0))
        self.status.bind("<Configure>", lambda e: self.status.configure(wraplength=max(200, e.width)))

    def _pill(self, parent, text, command):
        btn = tk.Label(parent, text=text, bg=PILL_BG, fg=ICON_FG, font=(self.ff, 10, "bold"), cursor="hand2", padx=16, pady=5)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(fg=HOVER, bg=PILL_HOVER_BG))
        btn.bind("<Leave>", lambda e: btn.configure(fg=ICON_FG, bg=PILL_BG))
        return btn

    def set_status(self, text: str, error: bool = False):
        self.status.configure(text=text, fg=ERROR_FG if error else MUTED)

    def checking(self):
        """Shown while a saved session is verified at startup."""
        self.button.pack_forget()
        self.signup.pack_forget()
        self.set_status("Checking your Wonuva account…")

    def ready(self, message: str = "", error: bool = False):
        """Show the Sign in button (after startup check, a sign-out, or a failure)."""
        self._busy = False
        self.button.configure(text="Sign in with Wonuva")
        self.button.pack(side="left")
        self.signup.pack(side="left", padx=(14, 0))
        self.set_status(message, error)

    def _on_button(self):
        if self._busy:
            self._cancel.set()  # the button reads "Cancel" while waiting for the browser
            return
        self._busy = True
        self._cancel.clear()
        self.button.configure(text="Cancel")
        self.set_status("Waiting for you to sign in in your browser…")
        threading.Thread(target=self._sign_in, name="sign-in", daemon=True).start()

    def _sign_in(self):
        try:
            user = self.auth.sign_in(self._cancel)
        except SignInCancelled:
            self.call_soon(lambda: self.ready())
        except AuthError as exc:
            self.call_soon(lambda m=str(exc): self.ready(m, error=True))
        except AuthUnavailable as exc:
            self.call_soon(lambda m=str(exc): self.ready(f"{m}. Check your internet connection and try again.", error=True))
        except Exception as exc:
            self.call_soon(lambda m=str(exc): self.ready(f"Sign-in failed: {m}", error=True))
        else:
            self.call_soon(lambda: self.on_signed_in(user))
