#!/usr/bin/env python3
"""Small black-box contract test for Coil's inline terminal lifecycle."""

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
    print(f"tui pty test: {message}", file=sys.stderr)
    if output:
        print(repr(output[-2000:]), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "./harness").resolve()
    if not binary.is_file():
        fail(f"binary not found: {binary}")

    with tempfile.TemporaryDirectory(prefix="coil-tui-pty-") as directory:
        journal = Path(directory) / "events.jsonl"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        original_attributes = termios.tcgetattr(slave)
        environment = os.environ.copy()
        environment["TERM"] = "xterm-256color"
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
        deadline = time.monotonic() + 8.0
        phase = "waiting"
        pasted_at = 0.0
        resized_at = 0.0
        interrupted_at = 0.0
        prompt_bytes = "❯ ".encode()

        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    output.extend(chunk)
                    if phase == "waiting" and prompt_bytes in output:
                        # A pasted newline and slash command must remain editor text;
                        # neither may be interpreted as submission.
                        os.write(master, b"\x1b[200~hello\n/quit\x1b[201~")
                        pasted_at = time.monotonic()
                        phase = "pasted"
            if phase == "pasted" and time.monotonic() - pasted_at >= 0.2:
                if process.poll() is not None:
                    fail("bracketed paste submitted embedded input", bytes(output))
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 12, 0, 0))
                resized_at = time.monotonic()
                phase = "resized"
            if phase == "resized" and time.monotonic() - resized_at >= 0.4:
                if process.poll() is not None:
                    fail("terminal resize terminated input", bytes(output))
                os.write(master, b"\x03")
                phase = "interrupted"
                interrupted_at = time.monotonic()
            if phase == "interrupted" and time.monotonic() - interrupted_at >= 0.2:
                # Exercise cursor movement, scalar-safe backspace, forward delete,
                # and submission while constructing /quit.
                os.write(master, b"/quix\x1b[D\x7fi\x1b[3~t\r")
                phase = "quitting"
            if process.poll() is not None:
                break

        if process.poll() is None:
            process.kill()
            process.wait()
            fail("process did not exit", bytes(output))
        captured = bytes(output)
        if process.returncode != 0:
            fail(f"process exited with {process.returncode}", captured)
        restored_attributes = termios.tcgetattr(master)
        local_mode_mask = termios.ICANON | termios.ECHO | termios.ISIG
        if (restored_attributes[3] & local_mode_mask) != (
            original_attributes[3] & local_mode_mask
        ):
            fail("terminal input modes were not restored", captured)
        if "Coil · auto/auto · /help for commands".encode() not in captured:
            fail("header was not rendered", captured)
        if "❯ ".encode() not in captured:
            fail("input prompt was not rendered", captured)
        if b"\x1b[2m" not in captured or b"\x1b[0m" not in captured:
            fail("semantic styling did not use valid SGR sequences", captured)
        if b"\x1b[?2004h" not in captured or b"\x1b[?2004l" not in captured:
            fail("bracketed paste lifecycle was incomplete", captured)
        forbidden = {
            b"\x1b[?1049h": "entered the alternate screen",
            b"\x1b[?1047h": "entered the alternate screen",
            b"\x1b[2J": "cleared the screen during startup or exit",
        }
        for sequence, message in forbidden.items():
            if sequence in captured:
                fail(message, captured)
        os.close(master)

    print("tui pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
