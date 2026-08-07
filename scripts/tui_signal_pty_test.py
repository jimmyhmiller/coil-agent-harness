#!/usr/bin/env python3
"""Verify that SIGTERM restores a Coil raw-input terminal session."""

from __future__ import annotations

import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time


def fail(message: str, output: bytes) -> None:
    print(f"tui signal pty test: {message}", file=sys.stderr)
    print(repr(output[-2000:]), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "./harness").resolve()
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    environment = os.environ.copy()
    environment["TERM"] = "xterm-256color"
    environment["COIL_TUI_UNICODE"] = "always"
    environment.pop("NO_COLOR", None)

    with tempfile.TemporaryDirectory(prefix="coil-tui-signal-") as directory:
        process = subprocess.Popen(
            [str(binary), "tui", str(Path(directory) / "events.jsonl")],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=environment,
            close_fds=True,
        )
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 5.0
        prompt = "❯ ".encode()
        while time.monotonic() < deadline and prompt not in output:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                output.extend(os.read(master, 65536))
        if prompt not in output:
            process.kill()
            process.wait()
            fail("did not reach raw input", bytes(output))

        time.sleep(0.1)
        os.kill(process.pid, signal.SIGTERM)
        termination_deadline = time.monotonic() + 5.0
        while process.poll() is None and time.monotonic() < termination_deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    pass
        if process.poll() is None:
            process.kill()
            process.wait()
            fail("SIGTERM did not wake the reader", bytes(output))

        while True:
            readable, _, _ = select.select([master], [], [], 0)
            if not readable:
                break
            try:
                chunk = os.read(master, 65536)
                if not chunk:
                    break
                output.extend(chunk)
            except OSError:
                break
        restored = termios.tcgetattr(master)
        mask = termios.ICANON | termios.ECHO | termios.ISIG
        if (restored[3] & mask) != (original[3] & mask):
            fail("terminal input modes were not restored", bytes(output))
        if b"\x1b[?2004l" not in output or b"\x1b[?25h" not in output:
            fail("terminal restoration sequences were incomplete", bytes(output))
        if process.returncode != 0:
            fail(f"process exited with {process.returncode}", bytes(output))
        os.close(master)

    print("tui signal pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
