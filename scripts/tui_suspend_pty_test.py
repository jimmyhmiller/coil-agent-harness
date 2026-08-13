#!/usr/bin/env python3
"""Verify Ctrl-Z restoration and resume for Coil's raw input session."""

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
    print(f"tui suspend pty test: {message}", file=sys.stderr)
    print(repr(output[-2000:]), file=sys.stderr)
    raise SystemExit(1)


def read_available(master: int, output: bytearray, timeout: float = 0.1) -> None:
    readable, _, _ = select.select([master], [], [], timeout)
    if readable:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            chunk = b""
        output.extend(chunk)


def main() -> int:
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "./harness").resolve()
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    environment = os.environ.copy()
    environment["TERM"] = "xterm-256color"
    environment["COIL_TUI_UNICODE"] = "always"
    environment.pop("NO_COLOR", None)

    with tempfile.TemporaryDirectory(prefix="coil-tui-suspend-") as directory:
        process = subprocess.Popen(
            [str(binary), "tui", str(Path(directory) / "events.jsonl")],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=environment,
            close_fds=True,
            preexec_fn=os.setpgrp,
        )
        os.close(slave)
        output = bytearray()
        prompt = "❯ ".encode()
        deadline = time.monotonic() + 5.0
        while prompt not in output and time.monotonic() < deadline:
            read_available(master, output)
        if prompt not in output:
            process.kill()
            process.wait()
            fail("did not reach raw input", bytes(output))

        os.write(master, b"draft\x1a")
        stopped = False
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            read_available(master, output)
            pid, status = os.waitpid(process.pid, os.WUNTRACED | os.WNOHANG)
            if pid == process.pid and os.WIFSTOPPED(status):
                stopped = True
                break
            time.sleep(0.05)
        if not stopped:
            process.kill()
            process.wait()
            fail("Ctrl-Z did not suspend the process", bytes(output))

        mask = termios.ICANON | termios.ECHO | termios.ISIG
        suspended = termios.tcgetattr(master)
        if (suspended[3] & mask) != (original[3] & mask):
            os.killpg(process.pid, signal.SIGCONT)
            process.kill()
            process.wait()
            fail("terminal modes were not restored before suspension", bytes(output))
        if b"\x1b[?2004l" not in output:
            os.killpg(process.pid, signal.SIGCONT)
            process.kill()
            process.wait()
            fail("bracketed paste remained enabled while suspended", bytes(output))

        os.killpg(process.pid, signal.SIGCONT)
        deadline = time.monotonic() + 5.0
        while output.count(b"\x1b[?2004h") < 2 and time.monotonic() < deadline:
            read_available(master, output)
        if output.count(b"\x1b[?2004h") < 2:
            process.kill()
            process.wait()
            fail("resume did not restore interactive input", bytes(output))
        # Ctrl-C no longer echoes "^C" and no longer ends the read: with text on
        # the line it discards the line, shell-style, and stays in the composer.
        # Assert that contract rather than the old echo, and assert the composer
        # is still live afterwards by typing again.
        os.write(master, b"\x03")
        deadline = time.monotonic() + 5.0
        while b"draft" in output.split(b"\x1b[2K")[-1] and time.monotonic() < deadline:
            read_available(master, output)
        if b"^C" in output:
            process.kill()
            process.wait()
            fail("interrupt echoed a literal ^C into the transcript", bytes(output))
        os.write(master, b"z")
        deadline = time.monotonic() + 5.0
        while b"z" not in output.split(b"\x1b[2K")[-1] and time.monotonic() < deadline:
            read_available(master, output)
        if b"z" not in output.split(b"\x1b[2K")[-1]:
            process.kill()
            process.wait()
            fail("composer stopped accepting input after interrupt", bytes(output))
        # Ctrl-U clears the probe character; without it /quit would be typed
        # onto the end of it and submitted to the model instead.
        os.write(master, b"\x15/quit\r")
        deadline = time.monotonic() + 5.0
        while process.poll() is None and time.monotonic() < deadline:
            read_available(master, output)
        if process.poll() is None:
            process.kill()
            process.wait()
            fail("quit after resume did not exit", bytes(output))
        if process.returncode != 0:
            fail(f"process exited with {process.returncode}", bytes(output))
        restored = termios.tcgetattr(master)
        if (restored[3] & mask) != (original[3] & mask):
            fail("terminal modes were not restored after resume", bytes(output))
        os.close(master)

    print("tui suspend pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
