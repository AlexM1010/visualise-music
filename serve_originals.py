#!/usr/bin/env python3
"""serve_originals.py - the page, plus the uploader's original files behind it.

Every download this project has made so far has been a **preview**: a ~128 kbps
mp3 that Freesound generates for streaming. The uploader's actual file - the
24-bit wav, the flac - sits behind `GET /apiv2/sounds/<id>/download/`, and that
endpoint requires OAuth2. A static page cannot hold an OAuth2 session, which is
why the zips have always shipped a `manifest.csv` of ids and urls instead: the
record that lets the originals be fetched later by something that can.

This is that something. It is a static file server with three extra routes, so
the page it serves is the same page, and the only thing that changes is where
`downloadOne` and the zip get their bytes.

    python serve_originals.py --dir . --port 8973

Then open http://127.0.0.1:8973/ and click **originals** in the header.

Setup, once:

  1. Register an application at <https://freesound.org/apiv2/apply/>.
  2. Set its redirect URI to exactly
     `http://127.0.0.1:8973/api/auth/callback` (match the port you run on).
  3. Put the credentials in `freesound-oauth.key` beside this file:

         {"client_id": "...", "client_secret": "..."}

`freesound-oauth.key` and the token file it writes are both gitignored. The
access token lasts 24 hours and is refreshed automatically from the refresh
token, so the browser dance happens roughly once.

**Downloads count against the API quota** - 2,000 a day, the same pool the
builder's similarity seeding draws from. A 250-sample zip of originals is 250
requests. That is the real limit on this, not the code.

This is also the one part of the project that could not be pointed at a local
folder instead: it exists specifically to talk to Freesound.
"""
from __future__ import annotations

import argparse
import http.server
import json
import secrets
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
CREDS = HERE / "freesound-oauth.key"
TOKENS = HERE / "freesound-oauth-token.json"
AUTHORIZE = "https://freesound.org/apiv2/oauth2/authorize/"
ACCESS_TOKEN = "https://freesound.org/apiv2/oauth2/access_token/"
DOWNLOAD = "https://freesound.org/apiv2/sounds/{id}/download/"

# A shared lock around the token file: a zip of 250 originals hits /api/original
# 250 times, and without this an expiry mid-zip would start a refresh per
# in-flight request and race them all into the same file.
_lock = threading.Lock()

# --- the `state` parameter, and why it is not optional -------------------------
# /api/auth/callback listens on loopback, and loopback is reachable from any page
# the browser happens to be on. Without a state check, a web page you visit can
# point your own browser at
#
#     http://127.0.0.1:8973/api/auth/callback?code=<the attacker's code>
#
# and this server would exchange that code and store the resulting token - after
# which every "original" download runs through a stranger's Freesound account,
# under their quota, with their history. Nothing on the page would look wrong.
#
# So a state is minted when the flow starts, sent to Freesound, echoed back, and
# has to match. It is single-use, because a code that has already been redeemed
# should not be redeemable twice, and it expires with the ten-minute life of the
# authorization code it is protecting. A state that has aged out or was never
# issued here is rejected rather than trusted.
STATE_TTL = 600.0
_pending: dict[str, float] = {}
_state_lock = threading.Lock()


def issue_state() -> str:
    s = secrets.token_urlsafe(24)
    now = time.time()
    with _state_lock:
        for k, t in list(_pending.items()):     # sweep, so a browser that never
            if now - t > STATE_TTL:             # came back cannot pile up here
                del _pending[k]
        _pending[s] = now
    return s


def claim_state(s: str | None) -> bool:
    """True once, for a state this process issued and has not aged out."""
    if not s:
        return False
    with _state_lock:
        t = _pending.pop(s, None)
    return t is not None and time.time() - t <= STATE_TTL


def creds() -> dict | None:
    if not CREDS.exists():
        return None
    try:
        d = json.loads(CREDS.read_text(encoding="utf-8"))
        if d.get("client_id") and d.get("client_secret"):
            return d
    except Exception:  # noqa: BLE001
        pass
    return None


def load_tokens() -> dict:
    if not TOKENS.exists():
        return {}
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_tokens(d: dict) -> None:
    TOKENS.write_text(json.dumps(d, indent=2), encoding="utf-8")


def post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def store(tok: dict) -> dict:
    """Stamp an absolute expiry on a token response. `expires_in` is only
    meaningful at the moment it arrives, and this file outlives that moment."""
    tok = dict(tok)
    tok["expires_at"] = time.time() + float(tok.get("expires_in") or 86400) - 120
    save_tokens(tok)
    return tok


def access_token() -> str | None:
    """A live access token, refreshing if the stored one has aged out. Returns
    None when nobody has authorised yet, which the caller reports as 401 rather
    than treating as an error."""
    with _lock:
        tok = load_tokens()
        if not tok.get("access_token"):
            return None
        if time.time() < (tok.get("expires_at") or 0):
            return tok["access_token"]
        c = creds()
        if not c or not tok.get("refresh_token"):
            return None
        try:
            tok = store(post_form(ACCESS_TOKEN, {
                "client_id": c["client_id"], "client_secret": c["client_secret"],
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}))
            print("  refreshed the access token")
            return tok["access_token"]
        except Exception as exc:  # noqa: BLE001
            print(f"  refresh failed ({exc}) - re-authorisation needed")
            return None


class Handler(http.server.SimpleHTTPRequestHandler):
    redirect_uri = "http://127.0.0.1:8973/api/auth/callback"

    def log_message(self, fmt, *args):        # noqa: A003
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    # --- helpers ---------------------------------------------------------
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self, text, code=200):
        b = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # --- routes ----------------------------------------------------------
    def do_GET(self):                          # noqa: N802
        parts = urllib.parse.urlsplit(self.path)
        route = parts.path
        if route == "/api/auth/status":
            return self.status()
        if route == "/api/auth/start":
            return self.start()
        if route == "/api/auth/callback":
            return self.callback(urllib.parse.parse_qs(parts.query))
        if route.startswith("/api/original/"):
            return self.original(route.rsplit("/", 1)[-1])
        return super().do_GET()

    def status(self):
        c = creds()
        tok = load_tokens()
        self._json({
            "configured": bool(c),
            "authed": bool(c) and bool(tok.get("access_token")),
            # Reported so the page can say "expires in 3h" rather than
            # discovering it is stale on the first download of a 250-file zip.
            "expires_in": max(0, int((tok.get("expires_at") or 0) - time.time())),
            "redirect_uri": self.redirect_uri,
        })

    def start(self):
        c = creds()
        if not c:
            return self._html(
                "<h1>No credentials</h1><p>Register an app at "
                "<a href='https://freesound.org/apiv2/apply/'>freesound.org/apiv2/apply/</a>, "
                f"set its redirect URI to <code>{self.redirect_uri}</code>, and write "
                f"<code>{CREDS.name}</code> as "
                '<code>{"client_id": "...", "client_secret": "..."}</code>.', 400)
        q = urllib.parse.urlencode({"client_id": c["client_id"], "response_type": "code",
                                    "state": issue_state()})
        self.send_response(302)
        self.send_header("Location", f"{AUTHORIZE}?{q}")
        self.end_headers()

    def callback(self, q):
        if "error" in q:
            return self._html(f"<h1>Denied</h1><p>{q['error'][0]}</p>", 400)
        # Before the code is worth anything: prove this callback belongs to a
        # flow this process started. See the note on STATE_TTL.
        if not claim_state((q.get("state") or [None])[0]):
            print("  callback rejected - state did not match a flow started here")
            return self._html(
                "<h1>Rejected</h1><p>This callback did not carry a valid "
                "<code>state</code>, so it was not from a sign-in this server "
                "started. Nothing was stored.</p><p>If you were signing in, the "
                "server was probably restarted mid-flow, or the attempt sat for "
                "more than ten minutes - start again from the "
                "<b>originals</b> chip.</p>", 400)
        code = (q.get("code") or [None])[0]
        c = creds()
        if not code or not c:
            return self._html("<h1>No code</h1>", 400)
        try:
            store(post_form(ACCESS_TOKEN, {
                "client_id": c["client_id"], "client_secret": c["client_secret"],
                "grant_type": "authorization_code", "code": code}))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            return self._html(f"<h1>Token exchange failed</h1><pre>{body}</pre>", 400)
        print("  authorised - originals are available")
        self._html("<h1>Authorised</h1><p>Close this tab and go back to the map. "
                   "Downloads now serve the uploader's original file.</p>"
                   "<script>setTimeout(()=>window.close(),1500)</script>")

    def original(self, sid: str):
        if not sid.isdigit():
            return self._json({"error": "bad id"}, 400)
        tok = access_token()
        if not tok:
            # 401 is the whole contract with the page: it falls back to the
            # preview rather than failing the download.
            return self._json({"error": "not authorised"}, 401)
        req = urllib.request.Request(DOWNLOAD.format(id=sid))
        req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                self.send_response(200)
                for h in ("Content-Type", "Content-Length", "Content-Disposition"):
                    v = r.headers.get(h)
                    if v:
                        self.send_header(h, v)
                # The page fetches this from the same origin it was served from,
                # so no CORS header is needed and none is given.
                self.end_headers()
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:200]
            self._json({"error": f"freesound {e.code}", "detail": msg}, e.code)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 502)


class Server(socketserver.ThreadingTCPServer):
    # Threaded because a download streams for as long as it streams, and a
    # single-threaded server would block the page - including its audio - behind
    # one 40MB wav.
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8973)
    ap.add_argument("--dir", type=Path, default=Path("."))
    ap.add_argument("--open", action="store_true", help="open a browser at the page")
    a = ap.parse_args()

    root = a.dir.resolve()
    Handler.redirect_uri = f"http://127.0.0.1:{a.port}/api/auth/callback"

    def factory(*args, **kw):
        return Handler(*args, directory=str(root), **kw)

    c, tok = creds(), load_tokens()
    print(f"=== serving {root} on http://127.0.0.1:{a.port}/ ===")
    if not c:
        print(f"  no {CREDS.name} - originals are off, previews still work")
        print("  register at https://freesound.org/apiv2/apply/ and set the redirect URI to")
        print(f"    {Handler.redirect_uri}")
    elif tok.get("access_token"):
        left = int((tok.get("expires_at") or 0) - time.time())
        print(f"  authorised, token good for {max(0, left) // 3600}h - originals are on")
    else:
        print(f"  credentials found, not authorised yet - open "
              f"http://127.0.0.1:{a.port}/api/auth/start")

    with Server(("127.0.0.1", a.port), factory) as srv:
        if a.open:
            webbrowser.open(f"http://127.0.0.1:{a.port}/")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
