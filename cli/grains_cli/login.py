"""`grains login` -- browser sign-in via the Grains OAuth 2.1 server.

Same PKCE + dynamic-client-registration flow Claude Code uses against
mcp.grains.run, with a loopback redirect: register a public client, open the
browser to the consent page, catch the code on 127.0.0.1, exchange it for a
deploy token, and store it in ~/.grains/credentials.json (0600). After this,
every CLI command works with no token pasting; GRAINS_DEPLOY_TOKEN still
wins when set (CI, scripts).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import stat
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .apiclient import resolve_api

CRED_PATH = Path.home() / ".grains" / "credentials.json"
LOGIN_TIMEOUT_S = 300


def stored_token(api: str) -> str | None:
    try:
        data = json.loads(CRED_PATH.read_text())
    except (OSError, ValueError):
        return None
    return (data.get(api) or {}).get("token")


def store_token(api: str, token: str) -> None:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(CRED_PATH.read_text())
    except (OSError, ValueError):
        data = {}
    data[api] = {"token": token}
    CRED_PATH.write_text(json.dumps(data, indent=2))
    CRED_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class _Callback(BaseHTTPRequestHandler):
    result: dict = {}
    expected_state = ""

    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        ok = q.get("state", [""])[0] == self.expected_state and "code" in q
        if ok:
            _Callback.result = {"code": q["code"][0]}
        else:
            _Callback.result = {"error": q.get("error", ["invalid callback"])[0]}
        body = (
            b"<body style='font-family:system-ui;text-align:center;padding-top:4rem'>"
            + (b"<h2>Signed in to Grains.</h2>You can close this tab." if ok
               else b"<h2>Sign-in failed.</h2>Return to the terminal.")
            + b"</body>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)


def login_flow(api: str, http: httpx.Client | None = None, open_browser=webbrowser.open,
               timeout_s: float = LOGIN_TIMEOUT_S) -> str:
    """Run the full browser PKCE flow; returns the deploy token."""
    client = http or httpx.Client(timeout=30.0)
    meta = client.get(f"{api}/.well-known/oauth-authorization-server").json()

    server = HTTPServer(("127.0.0.1", 0), _Callback)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    reg = client.post(meta["registration_endpoint"], json={
        "client_name": "grains CLI",
        "redirect_uris": [redirect_uri],
    })
    reg.raise_for_status()
    client_id = reg.json()["client_id"]

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    _Callback.expected_state = state
    _Callback.result = {}
    auth_url = meta["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print("Opening your browser to sign in with GitHub…")
    print(f"  {auth_url}")
    open_browser(auth_url)
    thread.join(timeout=timeout_s)
    server.server_close()
    if "code" not in _Callback.result:
        raise RuntimeError(_Callback.result.get("error") or "sign-in timed out")

    resp = client.post(meta["token_endpoint"], data={
        "grant_type": "authorization_code",
        "code": _Callback.result["code"],
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def ensure_token(api: str, *, allow_login: bool = True) -> str:
    token = os.environ.get("GRAINS_DEPLOY_TOKEN") or stored_token(api)
    if token:
        return token
    if not allow_login:
        raise RuntimeError("not signed in (run `grains login`)")
    token = login_flow(api)
    store_token(api, token)
    print("Signed in. Token stored in ~/.grains/credentials.json")
    return token


def cmd_login(args: argparse.Namespace) -> int:
    api = resolve_api(getattr(args, "api", None))
    try:
        token = login_flow(api)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    store_token(api, token)
    print("Signed in. Token stored in ~/.grains/credentials.json")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    api = resolve_api(getattr(args, "api", None))
    try:
        data = json.loads(CRED_PATH.read_text())
        data.pop(api, None)
        CRED_PATH.write_text(json.dumps(data, indent=2))
    except (OSError, ValueError):
        pass
    print("Signed out.")
    return 0
