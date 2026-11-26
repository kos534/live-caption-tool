# Wonuva account API for Wonuva Live Caption

What the Wonuva website backend must provide so the desktop app can sign users in. It's standard
**OAuth 2.0 authorization code flow with PKCE** for a native app ([RFC 6749], [RFC 7636], [RFC 8252]);
any OAuth 2.0 server library can do it. `dev/mock_wonuva_auth.py` in this repo is a small working
reference of exactly this API (in-memory, for testing only).

Base URL: `https://wonuva.com` (`WONUVA_URL` in the app's `config.py`). Everything over HTTPS.

## How sign-in works

1. The app starts a temporary web listener on `http://127.0.0.1:<random port>/callback`.
2. It opens the user's browser at `GET /oauth/authorize?...` (below).
3. The user signs in on the Wonuva page (or is already signed in on the website).
4. Wonuva redirects the browser to `http://127.0.0.1:<port>/callback?code=...&state=...`.
5. The app exchanges the code at `POST /oauth/token` and gets an access token + refresh token.
6. The app calls `GET /api/me` to show who is signed in.
7. Each launch (and every 6 hours while running), the app uses the refresh token at
   `POST /oauth/token` to get new tokens. If that's refused, the app asks the user to sign in again.

The app is a **public client**: it has no client secret (anything shipped in an .exe can be
extracted). PKCE is what protects the code exchange, so it's required.

## Client registration

| Setting | Value |
|---|---|
| `client_id` | `live-caption` |
| Client type | public (no secret) |
| Allowed redirect URI | `http://127.0.0.1:<any port>/callback`. Accept **any port** (RFC 8252 §7.3); require host `127.0.0.1`, scheme `http`, path `/callback`; reject everything else |
| PKCE | required, `S256` only |
| Scope | `profile` |

## `GET /oauth/authorize`

Query parameters from the app:

| Parameter | Value |
|---|---|
| `response_type` | `code` |
| `client_id` | `live-caption` |
| `redirect_uri` | `http://127.0.0.1:53124/callback` (port varies) |
| `code_challenge` | base64url(SHA-256(code_verifier)), no padding |
| `code_challenge_method` | `S256` |
| `state` | random string; must be returned unchanged |
| `scope` | `profile` |

Behavior:
- Invalid `client_id` or `redirect_uri`: show an error page; **never redirect** to an unvalidated URI.
- Not signed in: show the normal Wonuva login (and a link to sign up). Already signed in on the
  website: skip straight to the redirect.
- Success: `302` to `redirect_uri?code=<code>&state=<state>`. The code is random, **single use**,
  expires within **60 seconds**, and is bound to `client_id`, `redirect_uri` and `code_challenge`.
- User cancels or is blocked: `302` to `redirect_uri?error=access_denied&error_description=<text>&state=<state>`.
  The app shows `error_description` to the user, so keep it human-readable.

## `POST /oauth/token`

`Content-Type: application/x-www-form-urlencoded`. Responses are JSON.

**Exchange the code:**

| Field | Value |
|---|---|
| `grant_type` | `authorization_code` |
| `code` | from the redirect |
| `redirect_uri` | the same URI as in `/oauth/authorize` |
| `client_id` | `live-caption` |
| `code_verifier` | the PKCE verifier; check `base64url(SHA-256(code_verifier)) == code_challenge` |

**Refresh:**

| Field | Value |
|---|---|
| `grant_type` | `refresh_token` |
| `refresh_token` | current refresh token |
| `client_id` | `live-caption` |

Success `200`:

```json
{
  "access_token": "…",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "…"
}
```

- Access tokens: short-lived (about 1 hour).
- Refresh tokens: long-lived (e.g. 30–90 days, sliding). **Rotate** them: issue a new one on every
  refresh and invalidate the old one. The app always stores the latest. (If you don't rotate, omit
  `refresh_token` from refresh responses and the app keeps the old one.)
- Store only hashes of tokens in the database.

Errors (the app treats `400`/`401`/`403` as "must sign in again", and anything else, or no
connection, as "Wonuva unreachable"):

```json
{"error": "invalid_grant", "error_description": "Refresh token is invalid or revoked"}
```

Use `invalid_grant` (400) for bad/expired/used codes, failed PKCE, and revoked/expired refresh
tokens; `invalid_client` (401) for an unknown `client_id`. **Don't** return 4xx for temporary
problems (database down, etc.). Use 5xx, so users aren't signed out by an outage.

## `GET /api/me`

`Authorization: Bearer <access_token>`

`200`:

```json
{"id": "u_12345", "email": "jane@example.com", "name": "Jane Doe"}
```

`id` is required and stable; `email` and `name` are shown in the app. `401` if the token is invalid
or expired.

## `POST /oauth/revoke`

Called on **Sign out**. Form fields: `token=<refresh token>`, `client_id=live-caption`.
Revoke that refresh token (and ideally its access tokens). Always answer `200`, even for unknown
tokens ([RFC 7009]).

## `GET /signup`

The page the app's "Create an account" link opens. Any normal sign-up page is fine.

## Account management (recommended)

- A "Connected apps / devices" list on the user's Wonuva account page, with a way to sign out of
  Live Caption (revoke its refresh tokens). The app notices within 6 hours, or at its next launch.
- Disabling an account should revoke its refresh tokens.

## What the app does offline

If Wonuva can't be reached (no internet, 5xx), a session that was verified within the last
**7 days** keeps working (`AUTH_OFFLINE_GRACE_DAYS`). After that, the user must reconnect.

## Security notes

- Rate-limit `/oauth/token` and the login form.
- Don't allow `localhost` or other hosts in `redirect_uri`: only `127.0.0.1`.
- Codes: 60 s, single use. Reject a second use and revoke tokens issued from it.
- Sign-in being required in the app is a client-side check: a determined user can modify any
  desktop app. Anything that must be enforced (paid plans, usage limits) has to be checked on the
  server, for example by routing paid features through a Wonuva API that requires the access token.

[RFC 6749]: https://www.rfc-editor.org/rfc/rfc6749
[RFC 7009]: https://www.rfc-editor.org/rfc/rfc7009
[RFC 7636]: https://www.rfc-editor.org/rfc/rfc7636
[RFC 8252]: https://www.rfc-editor.org/rfc/rfc8252
