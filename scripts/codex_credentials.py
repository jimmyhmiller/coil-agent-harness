#!/usr/bin/env python3
"""OAuth and credential broker for direct ChatGPT Codex transport."""

import base64
import datetime
import fcntl
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
TOKEN_URL = f"{ISSUER}/oauth/token"
OAUTH_PORT = 1455
REDIRECT_URI = f"http://localhost:{OAUTH_PORT}/auth/callback"
CODEX_AUTH_FILE = Path(os.environ.get("CODEX_AUTH_FILE", Path.home() / ".codex" / "auth.json"))
HARNESS_AUTH_DIR = Path(os.environ.get("HARNESS_AUTH_DIR", Path.home() / ".coil-agent-harness"))
HARNESS_AUTH_FILE = HARNESS_AUTH_DIR / "codex-auth.json"


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, IndexError, json.JSONDecodeError):
        return {}


def account_id(tokens):
    if tokens.get("account_id"):
        return tokens["account_id"]
    for name in ("id_token", "access_token"):
        claims = jwt_claims(tokens.get(name, ""))
        auth = claims.get("https://api.openai.com/auth", {})
        value = claims.get("chatgpt_account_id") or auth.get("chatgpt_account_id")
        if value:
            return value
    return ""


def token_request(fields):
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "coil-agent-harness/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"token endpoint returned HTTP {error.code}: {detail}") from error


def write_auth(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(data, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


class OAuthCallback(http.server.BaseHTTPRequestHandler):
    expected_state = ""
    result = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
        error = query.get("error_description", query.get("error", [""]))[0]
        valid = (
            parsed.path == "/auth/callback"
            and code
            and secrets.compare_digest(state, self.expected_state)
        )
        if valid:
            OAuthCallback.result = (code, "")
            status = 200
            message = b"ChatGPT authentication complete. You may close this window."
        else:
            OAuthCallback.result = ("", error or "Invalid OAuth callback")
            status = 400
            message = b"ChatGPT authentication failed. Return to the terminal."
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.end_headers()
        self.wfile.write(message)

    def log_message(self, *_args):
        pass


def login():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    OAuthCallback.expected_state = state
    OAuthCallback.result = None
    server = http.server.HTTPServer(("127.0.0.1", OAUTH_PORT), OAuthCallback)
    parameters = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email offline_access",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "coil-agent-harness",
    })
    url = f"{ISSUER}/oauth/authorize?{parameters}"
    print(f"Open this URL to authenticate:\n{url}", file=sys.stderr)
    webbrowser.open(url)
    server.timeout = 180
    server.handle_request()
    server.server_close()
    code, error = OAuthCallback.result or ("", "OAuth callback timed out")
    if not code:
        raise RuntimeError(error)
    tokens = token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    })
    tokens["account_id"] = account_id(tokens)
    write_auth(HARNESS_AUTH_FILE, {"tokens": tokens})
    print("ChatGPT authentication saved.", file=sys.stderr)
    print("ok")


def credentials():
    environment = os.environ.get("HARNESS_CODEX_ACCESS_TOKEN")
    if environment:
        print(json.dumps({
            "access_token": environment,
            "account_id": os.environ.get("HARNESS_CODEX_ACCOUNT_ID", ""),
        }))
        return

    source = HARNESS_AUTH_FILE if HARNESS_AUTH_FILE.exists() else CODEX_AUTH_FILE
    source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = source.with_suffix(".harness.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with source.open() as auth_input:
            data = json.load(auth_input)
        tokens = data.get("tokens") or {}
        access = tokens.get("access_token", "")
        expiry = int(jwt_claims(access).get("exp", 0))
        if expiry <= int(time.time()) + 300:
            refreshed = token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.get("refresh_token", ""),
                "client_id": CLIENT_ID,
            })
            refreshed.setdefault("refresh_token", tokens.get("refresh_token", ""))
            refreshed["account_id"] = account_id(refreshed) or account_id(tokens)
            data["tokens"] = refreshed
            data["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            write_auth(source, data)
            tokens = refreshed
        print(json.dumps({
            "access_token": tokens.get("access_token", ""),
            "account_id": account_id(tokens),
        }))


def logout():
    if HARNESS_AUTH_FILE.exists():
        HARNESS_AUTH_FILE.unlink()
    print("Harness ChatGPT authentication removed.", file=sys.stderr)
    print("ok")


if __name__ == "__main__":
    try:
        {"login": login, "credentials": credentials, "logout": logout}[sys.argv[1]]()
    except (KeyError, IndexError):
        print("usage: codex_credentials.py <login|credentials|logout>", file=sys.stderr)
        raise SystemExit(64)
    except Exception as error:
        print(f"Codex authentication failed: {error}", file=sys.stderr)
        raise SystemExit(1)
