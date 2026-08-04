#!/usr/bin/env python3
"""Claude subscription OAuth broker for the COIL harness."""

import base64
import fcntl
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

CLIENT_ID = base64.b64decode("OWQxYzI1MGEtZTYxYi00NGQ5LTg4ZWQtNTk0NGQxOTYyZjVl").decode()
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI = "http://localhost:53692/callback"
SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
AUTH_DIR = Path(os.environ.get("HARNESS_AUTH_DIR", Path.home() / ".coil-agent-harness"))
AUTH_FILE = AUTH_DIR / "auth.json"
LOCK_FILE = AUTH_DIR / "auth.lock"


def request_token(payload):
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare rejects urllib's default Python-urllib signature with
            # error 1010 before Anthropic can evaluate the OAuth request.
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


def credential(data):
    return {
        "access": data["access_token"],
        "refresh": data["refresh_token"],
        "expires": int(time.time() * 1000) + int(data["expires_in"]) * 1000,
    }


def write_auth(value):
    AUTH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(AUTH_DIR, 0o700)
    temporary = AUTH_FILE.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"anthropic": value}, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, AUTH_FILE)
    os.chmod(AUTH_FILE, 0o600)


def read_auth():
    with AUTH_FILE.open() as source:
        return json.load(source)["anthropic"]


class Callback(http.server.BaseHTTPRequestHandler):
    result = None
    expected_state = None
    ready = threading.Event()

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        if self.path.startswith("/callback") and code and secrets.compare_digest(state, self.expected_state):
            Callback.result = (code, state)
            status, message = 200, b"Claude authentication complete. You may close this window."
            Callback.ready.set()
        else:
            status, message = 400, b"Invalid OAuth callback."
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(message)))
        self.end_headers()
        self.wfile.write(message)

    def log_message(self, *_args):
        pass


def parse_manual(value, expected_state):
    value = value.strip()
    if "://" in value:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        code, state = query.get("code", [""])[0], query.get("state", [expected_state])[0]
    elif "#" in value:
        code, state = value.split("#", 1)
    else:
        code, state = value, expected_state
    if not secrets.compare_digest(state, expected_state):
        raise RuntimeError("OAuth state mismatch")
    if not code:
        raise RuntimeError("Missing authorization code")
    return code, state


def login():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    Callback.expected_state = verifier
    Callback.result = None
    Callback.ready.clear()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 53692), Callback)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    params = urllib.parse.urlencode({
        "code": "true", "client_id": CLIENT_ID, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "scope": SCOPES,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": verifier,
    })
    url = f"{AUTHORIZE_URL}?{params}"
    print(f"Open this URL to authenticate:\n{url}", file=sys.stderr)
    webbrowser.open(url)
    if not Callback.ready.wait(120):
        print("Paste the final redirect URL or authorization code:", file=sys.stderr)
        result = parse_manual(input(), verifier)
    else:
        result = Callback.result
    server.shutdown()
    server.server_close()
    code, state = result
    data = request_token({
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": code, "state": state, "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    })
    write_auth(credential(data))
    print("Claude authentication saved.", file=sys.stderr)
    print("ok")


def token():
    environment = os.environ.get("ANTHROPIC_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if environment:
        print(environment)
        return
    AUTH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(AUTH_DIR, 0o700)
    descriptor = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    os.chmod(LOCK_FILE, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = read_auth()
        if int(value["expires"]) <= int(time.time() * 1000) + 300_000:
            value = credential(request_token({
                "grant_type": "refresh_token", "client_id": CLIENT_ID,
                "refresh_token": value["refresh"],
            }))
            write_auth(value)
        print(value["access"])


def logout():
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()
    print("Claude authentication removed.", file=sys.stderr)
    print("ok")


if __name__ == "__main__":
    try:
        {"login": login, "token": token, "logout": logout}[sys.argv[1]]()
    except (KeyError, IndexError):
        print("usage: claude_oauth.py <login|token|logout>", file=sys.stderr)
        raise SystemExit(64)
    except Exception as error:
        print(f"Claude authentication failed: {error}", file=sys.stderr)
        raise SystemExit(1)
