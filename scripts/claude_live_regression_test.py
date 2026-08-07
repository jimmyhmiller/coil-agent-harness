#!/usr/bin/env python3
"""Opt-in live regression for Claude through the production TUI worker path."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    binary = root / "harness"
    token = subprocess.run(
        ["python3", "scripts/claude_oauth.py", "token"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if token.returncode != 0 or not token.stdout.strip():
        print("live Claude regression: not authenticated; run harness login claude", file=sys.stderr)
        return 77

    iterations = int(os.environ.get("CLAUDE_LIVE_ITERATIONS", "1"))
    for attempt in range(iterations):
        with tempfile.TemporaryDirectory(prefix="coil-claude-live-") as directory:
            journal = Path(directory) / "events.jsonl"
            interaction = (
                "/model\n"
                "claude\n"
                "claude-sonnet-4-6\n"
                "Reply with exactly OK.\n"
                "/quit\n"
            )
            environment = os.environ.copy()
            environment.update({
                "TERM": "dumb",
                "COIL_TUI_PLAIN": "1",
                "MallocScribble": "1",
                "MallocGuardEdges": "1",
            })
            completed = subprocess.run(
                [str(binary), "tui", str(journal)],
                cwd=root,
                input=interaction,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=60,
            )
            if completed.returncode != 0 or "● OK." not in completed.stdout:
                print(
                    f"live Claude regression attempt {attempt + 1} failed with "
                    f"exit {completed.returncode}",
                    file=sys.stderr,
                )
                print(completed.stdout[-3000:], file=sys.stderr)
                print(completed.stderr[-3000:], file=sys.stderr)
                return 1
    print(f"live Claude regression: ok ({iterations} run(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
