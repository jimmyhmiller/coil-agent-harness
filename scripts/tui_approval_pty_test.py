#!/usr/bin/env python3
"""Black-box PTY checks for transient inline approval input."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time


def fail(message: str, output: bytes = b"") -> None:
    print(f"tui approval pty test: {message}", file=sys.stderr)
    if output:
        print(repr(output[-2000:]), file=sys.stderr)
    raise SystemExit(1)


def build_fixture(root: Path, output: Path) -> None:
    completed = subprocess.run(
        [
            "coil",
            "build",
            "integration/tui_approval_fixture.coil",
            "-o",
            str(output),
            "-O1",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        fail(f"could not build approval fixture:\n{completed.stdout}")


def run_case(binary: Path, input_bytes: bytes, expected: bytes) -> None:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    original = termios.tcgetattr(slave)
    environment = os.environ.copy()
    environment["TERM"] = "xterm-256color"
    process = subprocess.Popen(
        [str(binary)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=environment,
        close_fds=True,
    )
    os.close(slave)
    output = bytearray()
    sent = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and process.poll() is None:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            output.extend(chunk)
            if not sent and b"Allow once? [y/N]" in output:
                os.write(master, input_bytes)
                sent = True
    if process.poll() is None:
        process.kill()
        process.wait()
        fail("approval fixture did not exit", bytes(output))
    captured = bytes(output)
    if process.returncode != 0:
        fail(f"approval fixture exited with {process.returncode}", captured)
    if expected not in captured:
        fail(f"approval result did not contain {expected!r}", captured)
    if b"\x1b[?2004h" not in captured or b"\x1b[?2004l" not in captured:
        fail("bracketed-paste mode was not restored", captured)
    if b"\r\x1b[2K" not in captured:
        fail("transient approval prompt was not erased", captured)
    restored = termios.tcgetattr(master)
    mask = termios.ICANON | termios.ECHO | termios.ISIG
    if (restored[3] & mask) != (original[3] & mask):
        fail("terminal input modes were not restored", captured)
    os.close(master)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="coil-tui-approval-") as directory:
        binary = Path(directory) / "approval-fixture"
        build_fixture(root, binary)
        run_case(binary, b"y", b"ALLOW")
        run_case(binary, b"\x1b", b"REJECT")
        run_case(binary, b"\x1b[200~yes\x1b[201~", b"ALLOW")
    print("tui approval pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
