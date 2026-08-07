#!/usr/bin/env python3
"""Oracle-backed black-box test of the optimized production TUI."""

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

ANSWER = "It looks like that may have been accidental—what would you like to work on?"


def wait_for(master: int, oracle: VTOracle, raw: bytearray, needle: str,
             snapshots: list[dict], timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            chunk = os.read(master, 65536)
            if not chunk:
                break
            raw.extend(chunk)
            oracle.feed(chunk)
            snapshots.append(oracle.snapshot())
        if needle in oracle.transcript():
            return
    raise AssertionError(f"timed out waiting for {needle!r}\n{oracle.transcript()}")


def wait_for_event_count(master: int, oracle: VTOracle, raw: bytearray,
                         journal: Path, event_kind: str, count: int,
                         snapshots: list[dict], timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            chunk = os.read(master, 65536)
            if not chunk:
                break
            raw.extend(chunk)
            oracle.feed(chunk)
            snapshots.append(oracle.snapshot())
        if journal.exists():
            events = [
                json.loads(line) for line in journal.read_text().splitlines()
                if line.strip()
            ]
            if sum(event.get("event") == event_kind for event in events) >= count:
                return
    raise AssertionError(
        f"timed out waiting for {count} {event_kind!r} events\n"
        f"{oracle.transcript()}"
    )


def send_text(master: int, text: str, delay: float = 0.012) -> None:
    for byte in text.encode():
        os.write(master, bytes([byte]))
        time.sleep(delay)


def drain(master: int, oracle: VTOracle, raw: bytearray,
          snapshots: list[dict], quiet: float = 0.2) -> None:
    deadline = time.monotonic() + quiet
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.03)
        if not readable:
            continue
        chunk = os.read(master, 65536)
        if not chunk:
            return
        raw.extend(chunk)
        oracle.feed(chunk)
        snapshots.append(oracle.snapshot())
        deadline = time.monotonic() + quiet


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    binary = Path(os.environ.get("TUI_TEST_BINARY", root / "harness")).resolve()
    if not binary.exists():
        print("tui product test: ./harness is missing; build the optimized binary first",
              file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="coil-tui-product-") as directory:
        artifact_dir = Path(os.environ.get("TUI_TEST_ARTIFACTS", directory))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        journal = Path(directory) / "events.jsonl"
        rows, columns = 12, 50
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, columns, 0, 0))
        environment = os.environ.copy()
        environment.update({
            "TERM": "xterm-256color",
            "COIL_TUI_COLOR": "never",
            "COIL_TUI_UNICODE": "always",
            "COIL_TUI_WIDTH": str(columns - 1),
            "HARNESS_TUI_TEST_PROVIDER": "1",
        })
        process = subprocess.Popen(
            [str(binary), "tui", str(journal)], cwd=root, stdin=slave,
            stdout=slave, stderr=slave, env=environment, close_fds=True,
        )
        os.close(slave)
        oracle = VTOracle(rows, columns)
        raw = bytearray()
        snapshots: list[dict] = []
        try:
            wait_for(master, oracle, raw, "❯", snapshots)
            prompt_lines = [line for line in oracle.visible_lines() if "❯" in line]
            assert prompt_lines and prompt_lines[-1].find("❯") == 0, \
                "initial prompt did not begin at the left margin"
            baseline_scrollback = len(oracle.scrollback)
            typed = "x" * 50
            send_text(master, typed)
            wait_for(master, oracle, raw, typed[-12:], snapshots)
            drain(master, oracle, raw, snapshots)
            assert len(oracle.scrollback) == baseline_scrollback, \
                "typing grew terminal scrollback"
            send_text(master, "\x7f" * len(typed), delay=0.004)
            drain(master, oracle, raw, snapshots)
            send_text(master, "reproduce codex streaming duplication\r")
            wait_for(master, oracle, raw, "t would you like to work on?",
                     snapshots, timeout=12.0)
            drain(master, oracle, raw, snapshots, quiet=0.5)

            transcript = oracle.transcript()
            joined_transcript = transcript.replace("\n  ", "")
            assert joined_transcript.count(ANSWER) == 1, \
                "completed answer was not committed exactly once"
            for prefix in (
                "It looks like",
                "It looks like that may have been",
                "It looks like that may have been accidental—what would",
            ):
                occurrences = sum(
                    line.startswith("  " + prefix) or line.startswith("● " + prefix)
                    for line in transcript.splitlines()
                )
                assert occurrences <= 1, \
                    f"stale streamed prefix remained visible: {prefix!r}"
            send_text(master, "second sequential prompt\r")
            wait_for_event_count(master, oracle, raw, journal, "run.completed", 2,
                                 snapshots, timeout=12.0)
            drain(master, oracle, raw, snapshots, quiet=0.5)
            send_text(master, "cancel this response\r")
            wait_for(master, oracle, raw, "Thinking…", snapshots, timeout=4.0)
            send_text(master, "\x1b", delay=0)
            wait_for_event_count(master, oracle, raw, journal, "run.cancelled", 1,
                                 snapshots, timeout=6.0)
            wait_for(master, oracle, raw, "❯", snapshots, timeout=4.0)
            drain(master, oracle, raw, snapshots, quiet=0.8)
            send_text(master, "/quit\r")
            drain(master, oracle, raw, snapshots, quiet=0.3)
            process.wait(timeout=5)
            assert process.returncode == 0, \
                f"production TUI exited with {process.returncode}"
            events = [
                json.loads(line) for line in journal.read_text().splitlines()
                if line.strip()
            ]
            created = [event for event in events if event.get("event") == "run.created"]
            assert len(created) == 3, "three submitted turns were not durably created"
            second_messages = created[1]["payload"]["messages"]
            assert created[0]["payload"]["conversation_id"] == created[1]["payload"]["conversation_id"], \
                "sequential turns did not retain durable conversation identity"
            assert "previous_response_id" not in created[1]["payload"], \
                "non-native fixture continuation was incorrectly reused"
            assert {"role": "user", "content": "reproduce codex streaming duplication"} in second_messages, \
                "turn two omitted the preceding user message"
            assert {"role": "assistant", "content": ANSWER} in second_messages, \
                "turn two omitted the preceding assistant response"
            assert {"role": "user", "content": "second sequential prompt"} in second_messages, \
                "turn two omitted its current user message"
            assert sum(event.get("event") == "run.completed" for event in events) == 2, \
                "two sequential prompts did not durably complete"
            assert sum(event.get("event") == "run.cancelled" for event in events) == 1, \
                "Escape did not durably cancel the active run"
            restart_environment = environment.copy()
            restart_environment["HARNESS_CONVERSATION_ID"] = created[0]["payload"]["conversation_id"]
            restarted = subprocess.run(
                [str(binary), "tui", "--plain", str(journal)],
                cwd=root,
                input="after process restart\n/quit\n",
                text=True,
                capture_output=True,
                env=restart_environment,
                timeout=15,
            )
            assert restarted.returncode == 0, \
                f"restarted TUI exited with {restarted.returncode}: {restarted.stderr}"
            restarted_events = [
                json.loads(line) for line in journal.read_text().splitlines()
                if line.strip()
            ]
            restarted_created = [
                event for event in restarted_events if event.get("event") == "run.created"
            ]
            assert len(restarted_created) == 4, "restart did not append a fourth durable turn"
            restart_messages = restarted_created[-1]["payload"]["messages"]
            assert {"role": "user", "content": "reproduce codex streaming duplication"} in restart_messages, \
                "restart lost the original user turn"
            assert {"role": "assistant", "content": ANSWER} in restart_messages, \
                "restart lost the original assistant turn"
            assert restart_messages[-1] == {"role": "user", "content": "after process restart"}, \
                "restart did not append the new user turn"
        except Exception:
            (artifact_dir / "raw.ansi").write_bytes(raw)
            (artifact_dir / "snapshots.json").write_text(
                json.dumps(snapshots, ensure_ascii=False, indent=2)
            )
            (artifact_dir / "screen.txt").write_text(oracle.transcript())
            if journal.exists():
                (artifact_dir / "events.jsonl").write_bytes(journal.read_bytes())
            (artifact_dir / "process.txt").write_text(
                f"returncode-before-termination={process.poll()}\n"
            )
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            print(f"tui product test artifacts: {artifact_dir}", file=sys.stderr)
            raise
        finally:
            os.close(master)
    print("tui product test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
