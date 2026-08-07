#!/usr/bin/env python3

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import codex_credentials as broker


def token(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


class FakeServer:
    timeout = None

    def handle_request(self):
        broker.OAuthCallback.result = ("authorization-code", "")

    def server_close(self):
        pass


class CodexCredentialsTest(unittest.TestCase):
    def test_login_stores_private_refreshable_credentials_and_credentials_reads_them(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_file = Path(directory) / "codex-auth.json"
            access = token({"exp": int(time.time()) + 3600, "chatgpt_account_id": "account-1"})
            issued = {
                "access_token": access,
                "refresh_token": "refresh-1",
                "id_token": token({"chatgpt_account_id": "account-1"}),
                "expires_in": 3600,
            }
            with (
                mock.patch.object(broker, "HARNESS_AUTH_FILE", auth_file),
                mock.patch.object(broker.http.server, "HTTPServer", return_value=FakeServer()),
                mock.patch.object(broker.webbrowser, "open", return_value=True),
                mock.patch.object(broker, "token_request", return_value=issued),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                broker.login()
                self.assertEqual(auth_file.stat().st_mode & 0o777, 0o600)
                stored = json.loads(auth_file.read_text())
                self.assertEqual(stored["tokens"]["account_id"], "account-1")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    broker.credentials()
                exposed = json.loads(output.getvalue())
                self.assertEqual(exposed["access_token"], access)
                self.assertEqual(exposed["account_id"], "account-1")


if __name__ == "__main__":
    unittest.main()
