"""Wonuva account sign-in for the desktop app.

OAuth 2.0 authorization code flow with PKCE and a loopback redirect (RFC 8252, "OAuth for native
apps"): the app opens the Wonuva sign-in page in the user's browser; after signing in, Wonuva
redirects to http://127.0.0.1:<port>/callback with a one-time code, which the app exchanges for
tokens. The app never sees the user's password. The server side is specified in
docs/WONUVA_AUTH_API.md (dev/mock_wonuva_auth.py implements it for testing).

The refresh token is stored in account.json in the data folder, encrypted with Windows DPAPI.
Each launch refreshes it and fetches the profile; if Wonuva can't be reached, a session verified
within the last offline_grace_days keeps working, so a server outage doesn't lock users out.
"""

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from user_settings import _protect, _unprotect

log = logging.getLogger(__name__)


class AuthError(Exception):
    """The session is not valid (or sign-in was refused): the user has to sign in."""


class AuthUnavailable(Exception):
    """Wonuva couldn't be reached or failed; not the user's fault."""


class SignInCancelled(Exception):
    pass


class WonuvaAuth:
    def __init__(self, base_url: str, client_id: str, account_file: Path, user_agent: str, offline_grace_days: float = 7):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.account_file = Path(account_file)
        self.user_agent = user_agent
        self.offline_grace_s = offline_grace_days * 86400
        self.user = None  # {"id", "email", "name"} while signed in
        self.access_token = ""
        self._lock = threading.Lock()

    @property
    def signup_url(self) -> str:
        return f"{self.base_url}/signup"

    # ---- public API (all blocking: call from a worker thread) -------------------------------

    def restore(self):
        """Resume the saved session. Returns the user, or None if the user must sign in.

        Raises AuthUnavailable if Wonuva can't be reached and there's no recent enough session.
        """
        saved = self._load()
        if not saved or not saved.get("refresh_token"):
            return None
        try:
            self._refresh(saved["refresh_token"])
            return self.user
        except AuthError as exc:
            log.info("Saved session is no longer valid: %s", exc)
            self._delete()
            return None
        except AuthUnavailable:
            age = time.time() - float(saved.get("last_verified", 0))
            if saved.get("user") and age < self.offline_grace_s:
                log.warning("Wonuva unreachable; using the session verified %.1f h ago", age / 3600)
                self.user = saved["user"]
                return self.user
            raise

    def revalidate(self) -> bool:
        """Periodic check while running. False only if the session was revoked/expired."""
        saved = self._load()
        if not saved or not saved.get("refresh_token"):
            return False
        try:
            self._refresh(saved["refresh_token"])
            return True
        except AuthError:
            self._delete()
            return False
        except AuthUnavailable:
            return True  # offline: keep going (restore() enforces the grace period at launch)

    def sign_in(self, cancel: threading.Event, timeout_s: float = 600):
        """Run the browser sign-in. Returns the user; raises AuthError/AuthUnavailable/SignInCancelled."""
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = _b64url(secrets.token_bytes(24))

        server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
        server.timeout = 0.3
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/callback"
        url = f"{self.base_url}/oauth/authorize?" + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "scope": "profile",
            }
        )
        try:
            if not webbrowser.open(url):
                raise AuthUnavailable("Couldn't open the web browser")
            deadline = time.monotonic() + timeout_s
            while server.result is None:
                if cancel.is_set():
                    raise SignInCancelled()
                if time.monotonic() > deadline:
                    raise AuthError("Sign-in timed out. Please try again.")
                server.handle_request()
        finally:
            server.server_close()

        params = server.result
        if params.get("state") != state:
            raise AuthError("Sign-in response didn't match this request. Please try again.")
        if params.get("error"):
            raise AuthError(params.get("error_description") or f"Sign-in failed ({params['error']})")
        if not params.get("code"):
            raise AuthError("Sign-in didn't return a code. Please try again.")

        tokens = self._post_form(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": params["code"],
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            },
        )
        self._accept_tokens(tokens)
        log.info("Signed in as %s", (self.user or {}).get("email", "?"))
        return self.user

    def sign_out(self):
        """Forget the session locally and ask Wonuva to revoke it (best effort)."""
        saved = self._load()
        self._delete()
        self.user, self.access_token = None, ""
        token = (saved or {}).get("refresh_token")
        if token:
            try:
                self._post_form("/oauth/revoke", {"token": token, "client_id": self.client_id})
            except Exception as exc:
                log.info("Token revoke failed (ignored): %s", exc)

    # ---- tokens ---------------------------------------------------------------------------

    def _refresh(self, refresh_token: str):
        tokens = self._post_form(
            "/oauth/token", {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}
        )
        tokens.setdefault("refresh_token", refresh_token)  # servers that don't rotate refresh tokens
        self._accept_tokens(tokens)

    def _accept_tokens(self, tokens: dict):
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        if not access or not refresh:
            raise AuthUnavailable("Wonuva returned an incomplete token response")
        me = self._get_json("/api/me", access)
        if not me.get("id"):
            raise AuthUnavailable("Wonuva returned no account id")
        with self._lock:
            self.access_token = access
            self.user = {"id": str(me["id"]), "email": str(me.get("email", "")), "name": str(me.get("name", ""))}
            self._save({"user": self.user, "refresh_token": refresh, "last_verified": time.time()})

    # ---- HTTP -----------------------------------------------------------------------------

    def _open(self, request):
        try:
            with urllib.request.urlopen(request, timeout=20) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {}
            message = body.get("error_description") or body.get("error") or f"HTTP {exc.code}"
            if exc.code in (400, 401, 403):
                raise AuthError(message) from exc
            raise AuthUnavailable(message) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AuthUnavailable(f"Couldn't reach Wonuva ({getattr(exc, 'reason', exc)})") from exc

    def _post_form(self, path: str, data: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=urllib.parse.urlencode(data).encode("ascii"),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        return self._open(request)

    def _get_json(self, path: str, token: str) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"User-Agent": self.user_agent, "Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
        return self._open(request)

    # ---- storage --------------------------------------------------------------------------

    def _load(self):
        try:
            data = json.loads(self.account_file.read_text(encoding="utf-8"))
            if data.get("refresh_token_dpapi"):
                data["refresh_token"] = _unprotect(base64.b64decode(data.pop("refresh_token_dpapi"))).decode("utf-8")
            return data
        except FileNotFoundError:
            return None
        except Exception as exc:  # corrupted, or copied from another Windows user/PC
            log.warning("Couldn't read the saved Wonuva session: %s", exc)
            return None

    def _save(self, data: dict):
        data = dict(data)
        token = data.pop("refresh_token")
        try:
            data["refresh_token_dpapi"] = base64.b64encode(_protect(token.encode("utf-8"))).decode("ascii")
        except Exception as exc:
            # Never store the token unencrypted: the user just signs in again next launch.
            log.warning("Can't encrypt the session (%s); it won't be remembered", exc)
            return
        tmp = self.account_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.account_file)

    def _delete(self):
        try:
            self.account_file.unlink()
        except FileNotFoundError:
            pass


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---- loopback redirect receiver -------------------------------------------------------------

_DONE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Wonuva Live Caption</title>
<style>body{margin:0;height:100vh;display:grid;place-items:center;background:#110b22;color:#f3eeff;
font-family:"Segoe UI",Arial,sans-serif}div{text-align:center;padding:24px}
h1{color:#f6d98b;font-weight:600;font-size:22px}p{color:#cbbcff}</style></head>
<body><div><h1>%s</h1><p>%s</p></div></body></html>"""


class _CallbackServer(http.server.HTTPServer):
    result = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        ok = "code" in params and "error" not in params
        page = _DONE_PAGE % (
            ("You're signed in", "You can close this tab and go back to Wonuva Live Caption.")
            if ok
            else ("Sign-in didn't complete", "Go back to Wonuva Live Caption and try again.")
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.server.result = params

    def log_message(self, *args):  # keep the code out of the log
        pass
