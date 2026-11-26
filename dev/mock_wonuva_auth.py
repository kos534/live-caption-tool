"""Mock Wonuva account server, for testing the app's sign-in without the real backend.

It implements docs/WONUVA_AUTH_API.md (and is a compact reference for the real implementation):
authorization code + PKCE (S256), loopback redirect URIs on any port, single-use codes that
expire after 60 s, rotating refresh tokens, revocation, and /api/me.

    python dev/mock_wonuva_auth.py                 # serves http://127.0.0.1:8765
    python main.py --auth-url http://127.0.0.1:8765

Sign in with any email and the password "wonuva". Open /dev/revoke-all to end every session
(the app locks on its next check). Everything is in memory: restarting the server signs everyone out.
"""

import base64
import hashlib
import html
import http.server
import json
import secrets
import sys
import time
import urllib.parse

CLIENT_ID = "live-caption"
PASSWORD = "wonuva"
ACCESS_TTL = 3600

codes = {}  # code -> {user, client_id, redirect_uri, challenge, expires}
access_tokens = {}  # token -> {user, expires}
refresh_tokens = {}  # token -> user
users = {}  # email -> {id, email, name}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Wonuva sign in (mock)</title>
<style>body{{font-family:Segoe UI,Arial;background:#110b22;color:#f3eeff;display:grid;place-items:center;height:100vh;margin:0}}
form{{background:#1a1236;padding:28px;border-radius:12px;width:320px}}h1{{color:#f6d98b;font-size:20px}}
input{{width:100%;box-sizing:border-box;margin:6px 0 12px;padding:8px;border-radius:6px;border:1px solid #3a2b6e;background:#0c0719;color:#fff}}
button{{background:#8b5cf6;color:#fff;border:0;padding:9px 16px;border-radius:6px;cursor:pointer}}.err{{color:#ff8fb4}}</style></head>
<body><form method="post"><h1>Sign in to Wonuva</h1><p>Mock server for testing.</p>{error}
<label>Email<input name="email" type="email" required autofocus></label>
<label>Password<input name="password" type="password" required placeholder="wonuva"></label>
{hidden}<button type="submit">Sign in</button></form></body></html>"""


def is_loopback_redirect(uri: str) -> bool:
    """RFC 8252 7.3: http://127.0.0.1:<any port>/callback is allowed; nothing else."""
    p = urllib.parse.urlparse(uri)
    return p.scheme == "http" and p.hostname == "127.0.0.1" and p.port is not None and p.path == "/callback"


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def issue_tokens(user: dict) -> dict:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    access_tokens[access] = {"user": user, "expires": time.time() + ACCESS_TTL}
    refresh_tokens[refresh] = user
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL, "refresh_token": refresh}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status: int, body, content_type="application/json", headers=None):
        data = (json.dumps(body) if content_type == "application/json" else body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, error: str, description: str):
        self._send(status, {"error": error, "error_description": description})

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8")).items()}

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/oauth/authorize":
            problem = self._check_authorize(q)
            if problem:
                return self._send(400, f"<h1>Invalid sign-in request</h1><p>{html.escape(problem)}</p>", "text/html")
            return self._send(200, self._login_page(q), "text/html")
        if url.path == "/api/me":
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            entry = access_tokens.get(token)
            if not entry or entry["expires"] < time.time():
                return self._error(401, "invalid_token", "Access token is invalid or expired")
            return self._send(200, entry["user"])
        if url.path == "/signup":
            return self._send(200, "<h1>Create a Wonuva account (mock)</h1>", "text/html")
        if url.path == "/dev/revoke-all":
            refresh_tokens.clear()
            access_tokens.clear()
            return self._send(200, "<h1>All sessions revoked</h1>", "text/html")
        self._error(404, "not_found", "Not found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/oauth/authorize":  # the login form posts back here
            form = self._form()
            problem = self._check_authorize(form)
            if problem:
                return self._send(400, f"<h1>Invalid sign-in request</h1><p>{html.escape(problem)}</p>", "text/html")
            if form.get("password") != PASSWORD:
                return self._send(200, self._login_page(form, "Wrong email or password."), "text/html")
            email = form["email"].strip().lower()
            user = users.setdefault(email, {"id": f"u_{len(users) + 1}", "email": email, "name": email.split("@")[0].title()})
            code = secrets.token_urlsafe(32)
            codes[code] = {
                "user": user, "client_id": form["client_id"], "redirect_uri": form["redirect_uri"],
                "challenge": form["code_challenge"], "expires": time.time() + 60,
            }
            location = form["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": form.get("state", "")})
            return self._send(302, "", "text/html", {"Location": location})
        if url.path == "/oauth/token":
            return self._token(self._form())
        if url.path == "/oauth/revoke":
            refresh_tokens.pop(self._form().get("token", ""), None)
            return self._send(200, {})
        self._error(404, "not_found", "Not found")

    def _check_authorize(self, q: dict) -> str:
        if q.get("client_id") != CLIENT_ID:
            return "Unknown client_id"
        if q.get("response_type", "code") != "code":
            return "response_type must be code"
        if not is_loopback_redirect(q.get("redirect_uri", "")):
            return "redirect_uri must be http://127.0.0.1:<port>/callback"
        if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
            return "PKCE (S256) is required"
        return ""

    def _login_page(self, q: dict, error: str = "") -> str:
        keep = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope")
        hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(q.get(k, ""))}">' for k in keep)
        return PAGE.format(error=f'<p class="err">{error}</p>' if error else "", hidden=hidden)

    def _token(self, form: dict):
        if form.get("client_id") != CLIENT_ID:
            return self._error(401, "invalid_client", "Unknown client_id")
        grant = form.get("grant_type")
        if grant == "authorization_code":
            entry = codes.pop(form.get("code", ""), None)  # single use
            if not entry or entry["expires"] < time.time():
                return self._error(400, "invalid_grant", "Code is invalid or expired")
            if entry["redirect_uri"] != form.get("redirect_uri") or entry["client_id"] != form["client_id"]:
                return self._error(400, "invalid_grant", "redirect_uri mismatch")
            if s256(form.get("code_verifier", "")) != entry["challenge"]:
                return self._error(400, "invalid_grant", "PKCE verification failed")
            return self._send(200, issue_tokens(entry["user"]))
        if grant == "refresh_token":
            user = refresh_tokens.pop(form.get("refresh_token", ""), None)  # rotate: old token dies
            if not user:
                return self._error(400, "invalid_grant", "Refresh token is invalid or revoked")
            return self._send(200, issue_tokens(user))
        return self._error(400, "unsupported_grant_type", "Unsupported grant_type")

    def log_message(self, fmt, *args):
        sys.stderr.write("[mock-wonuva] " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Mock Wonuva auth on http://127.0.0.1:{port}  (password: {PASSWORD})", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
