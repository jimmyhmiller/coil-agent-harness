#!/usr/bin/env python3
"""Black-box regression for the prompt scrolling once per typed character."""

from pathlib import Path
import fcntl
import os
import pty
import struct
import subprocess
import sys
import tempfile
import termios


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="coil-tui-typing-") as directory:
        binary = Path(directory) / "typing-fixture"
        built = subprocess.run(
            ["coil", "build", "integration/tui_typing_fixture.coil", "-o", str(binary), "-O1"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if built.returncode != 0:
            print(built.stdout, file=sys.stderr)
            return 1
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 1, 80, 0, 0))
        environment = os.environ.copy()
        environment["TERM"] = "xterm-256color"
        completed = subprocess.Popen(
            [str(binary)], stdin=slave, stdout=slave, stderr=slave, env=environment, close_fds=True
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
        completed.wait(timeout=5)
        os.close(master)
        if completed.returncode != 0:
            return completed.returncode
        if bytes(output).count(b"\n") != 1:
            print("typing redraw advanced scrollback", file=sys.stderr)
            print(repr(bytes(output[-2000:])), file=sys.stderr)
            return 1
    print("tui typing pty test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
