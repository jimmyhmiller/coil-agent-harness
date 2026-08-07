#!/usr/bin/env python3
"""Exercise the inline protocol under common POSIX terminal identities."""

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


TERMS = (
    "xterm-256color",  # macOS Terminal and iTerm2 defaults
    "xterm-kitty",
    "alacritty",
    "wezterm",
    "ghostty",
    "screen-256color",  # tmux/screen compatibility
    "tmux-256color",
    "vt100",
)


def fail(term: str, message: str, output: bytes = b"") -> None:
    print(f"tui compatibility pty test ({term}): {message}", file=sys.stderr)
    if output:
        print(repr(output[-1200:]), file=sys.stderr)
    raise SystemExit(1)


def run_term(binary: Path, term: str, journal: Path) -> None:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    original = termios.tcgetattr(slave)
    environment = os.environ.copy()
    environment["TERM"] = term
    environment["COIL_TUI_UNICODE"] = "always"
    environment.pop("NO_COLOR", None)
    process = subprocess.Popen(
        [str(binary), "tui", str(journal)],
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
            if not sent and "❯ ".encode() in output:
                os.write(master, b"/quit\r")
                sent = True
    if process.poll() is None:
        process.kill()
        process.wait()
        fail(term, "process did not exit", bytes(output))
    captured = bytes(output)
    if process.returncode != 0:
        fail(term, f"process exited with {process.returncode}", captured)
    if b"\x1b[?1049h" in captured or b"\x1b[?1047h" in captured:
        fail(term, "entered the alternate screen", captured)
    if b"\x1b[?2004h" not in captured or b"\x1b[?2004l" not in captured:
        fail(term, "did not bracket terminal paste mode", captured)
    restored = termios.tcgetattr(master)
    mask = termios.ICANON | termios.ECHO | termios.ISIG
    if (restored[3] & mask) != (original[3] & mask):
        fail(term, "terminal modes were not restored", captured)
    os.close(master)


def main() -> int:
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "./harness").resolve()
    if not binary.is_file():
        fail("setup", f"binary not found: {binary}")
    with tempfile.TemporaryDirectory(prefix="coil-tui-compat-") as directory:
        root = Path(directory)
        for index, term in enumerate(TERMS):
            run_term(binary, term, root / f"events-{index}.jsonl")
    print(f"tui compatibility pty test: ok ({len(TERMS)} profiles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
