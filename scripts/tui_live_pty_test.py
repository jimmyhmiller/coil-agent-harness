#!/usr/bin/env python3
"""Real-provider acceptance test driven through an interactive pseudo-terminal."""

from __future__ import annotations

import fcntl
import json
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

from vt_oracle import VTOracle


def type_text(master: int, value: str, delay: float | None = None) -> None:
    if delay is None:
        delay = float(os.environ.get("TUI_LIVE_TYPE_DELAY", "0.025"))
    for byte in value.encode():
        os.write(master, bytes([byte]))
        time.sleep(delay)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else root / "harness").resolve()
    prompts = [
        os.environ.get("TUI_LIVE_PROMPT", "Reply with exactly FIRST."),
        os.environ.get("TUI_LIVE_SECOND_PROMPT", "Reply with exactly SECOND."),
    ]
    timeout = float(os.environ.get("TUI_LIVE_TIMEOUT", "60"))
    if not binary.is_file():
        print(f"live TUI PTY test: binary not found: {binary}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="coil-live-tui-pty-") as directory:
        artifact_dir = Path(os.environ.get("TUI_TEST_ARTIFACTS", directory))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        journal = Path(directory) / "events.jsonl"
        master, slave = pty.openpty()
        rows, columns = 24, 80
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        environment = os.environ.copy()
        environment.update({"TERM": "xterm-256color", "COIL_TUI_UNICODE": "always"})
        environment.pop("COIL_TUI_PLAIN", None)
        process = subprocess.Popen(
            [str(binary), "tui", str(journal)],
            cwd=root,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=environment,
            close_fds=True,
        )
        os.close(slave)
        oracle = VTOracle(rows, columns)
        raw = bytearray()

        def pump() -> None:
            readable, _, _ = select.select([master], [], [], 0.05)
            if not readable:
                return
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if chunk:
                raw.extend(chunk)
                oracle.feed(chunk)

        def wait_for(predicate, description: str, seconds: float) -> None:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                pump()
                if predicate(oracle.transcript()):
                    return
                if process.poll() is not None:
                    raise AssertionError(
                        f"process exited with {process.returncode} while {description}"
                    )
            raise AssertionError(f"timed out while {description}")

        def journal_events() -> list[dict]:
            if not journal.exists():
                return []
            events = []
            for line in journal.read_text(errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(event)
            return events

        def terminal_events() -> list[dict]:
            return [
                event
                for event in journal_events()
                if event.get("event") in {"run.completed", "run.failed", "run.cancelled"}
            ]

        def editor_active(screen: str) -> bool:
            return screen.rstrip().endswith("❯")

        try:
            wait_for(lambda screen: "❯" in screen, "waiting for initial prompt", 10)
            for turn, prompt in enumerate(prompts, start=1):
                terminal_count = len(terminal_events())
                created_count = sum(
                    event.get("event") == "run.created" for event in journal_events()
                )
                type_text(master, prompt)
                os.write(master, b"\r")
                wait_for(
                    lambda _screen: sum(
                        event.get("event") == "run.created" for event in journal_events()
                    ) > created_count,
                    f"waiting for turn {turn} submission",
                    10,
                )
                wait_for(
                    lambda _screen: len(terminal_events()) > terminal_count,
                    f"waiting for real provider turn {turn} to terminate",
                    timeout,
                )
                terminal = terminal_events()[-1]
                if terminal.get("event") != "run.completed":
                    raise AssertionError(
                        f"turn {turn} ended with {terminal.get('event')}: "
                        f"{terminal.get('payload', '')}"
                    )
                wait_for(
                    editor_active,
                    f"waiting for editor reactivation after turn {turn}",
                    10,
                )
            type_text(master, "/quit")
            os.write(master, b"\r")
            exit_deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < exit_deadline:
                pump()
            if process.poll() is None:
                raise AssertionError("interactive /quit did not exit")
            if process.returncode != 0:
                raise AssertionError(f"interactive TUI exited with {process.returncode}")
            if os.environ.get("TUI_TEST_ARTIFACTS"):
                (artifact_dir / "raw.ansi").write_bytes(raw)
                (artifact_dir / "screen.txt").write_text(oracle.transcript())
                if journal.exists():
                    (artifact_dir / "events.jsonl").write_bytes(journal.read_bytes())
        except Exception as error:
            (artifact_dir / "raw.ansi").write_bytes(raw)
            (artifact_dir / "screen.txt").write_text(oracle.transcript())
            if journal.exists():
                (artifact_dir / "events.jsonl").write_bytes(journal.read_bytes())
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            print(f"live TUI PTY test failed: {error}", file=sys.stderr)
            print(f"artifacts: {artifact_dir}", file=sys.stderr)
            return 1
        finally:
            os.close(master)

    print(f"live TUI PTY test: ok ({binary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
