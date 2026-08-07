#!/usr/bin/env python3
"""Build and stress the optimized Claude native-tool request serializer."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="coil-claude-wire-") as directory:
        binary = Path(directory) / "claude-wire-fixture"
        built = subprocess.run(
            ["coil", "build", "integration/claude_wire_fixture.coil", "-o", str(binary), "-O1"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if built.returncode != 0:
            print(built.stdout, file=sys.stderr)
            return 1
        environment = os.environ.copy()
        environment.update({"MallocScribble": "1", "MallocGuardEdges": "1"})
        completed = subprocess.run([str(binary)], env=environment, timeout=30)
        if completed.returncode != 0:
            return completed.returncode
    print("claude wire regression test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
