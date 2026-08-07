#!/usr/bin/env python3
"""Black-box regression for streamed output growing terminal scrollback."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import pty
import struct
import subprocess
import sys
import tempfile
import termios


def fail(message: str, output: bytes = b"") -> None:
    print(f"tui stream pty test: {message}", file=sys.stderr)
    if output:
        print(repr(output[-2000:]), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="coil-tui-stream-") as directory:
        binary = Path(directory) / "stream-fixture"
        built = subprocess.run(
            ["coil", "build", "integration/tui_stream_fixture.coil", "-o", str(binary), "-O1"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if built.returncode != 0:
            fail(f"could not build stream fixture:\n{built.stdout}")

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 1, 80, 0, 0))
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
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
        process.wait(timeout=5)
        os.close(master)

        captured = bytes(output)
        if process.returncode != 0:
            fail(f"stream fixture exited with {process.returncode}", captured)
        if captured.count(b"\n") != 1:
            fail("live redraw emitted a scrolling line break", captured)
        if b"final answer" not in captured:
            fail("stable answer was not committed", captured)

    print("tui stream pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
