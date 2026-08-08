"""Run a Claude Agent SDK session whose only tools come from the harness.

    export HARNESS_TOKEN=...                     # same token `harness serve` prints
    python -m agent_sdk "summarize the src tree"
    python -m agent_sdk                          # interactive

The harness must already be serving:  ./harness serve
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, ToolUseBlock

from .harness import HarnessClient, HarnessError, build_options

DEFAULT_SYSTEM_PROMPT = (
    "You are an operator for the coil agent harness. Every tool you have is "
    "provided by the harness itself; you have no built-in file, shell, or web "
    "tools. Use the harness tools to inspect and act on the system, and say "
    "plainly when a task needs a capability the harness does not expose."
)


def _render_message(message: object) -> None:
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                print(f"\n  ⏺ {block.name} {block.input}", file=sys.stderr)
            else:
                text = getattr(block, "text", None)
                if text:
                    print(text, end="", flush=True)
    elif isinstance(message, ResultMessage):
        if message.subtype != "success":
            print(f"\n[run ended: {message.subtype}]", file=sys.stderr)
        print()


async def run(prompt: str | None, args: argparse.Namespace) -> int:
    token = os.environ.get("HARNESS_TOKEN")
    if not token:
        print("HARNESS_TOKEN is not set", file=sys.stderr)
        return 2

    client = HarnessClient(args.url, token)
    try:
        options = await build_options(
            client,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            model=args.model,
            cwd=args.cwd,
            max_turns=args.max_turns,
        )
    except HarnessError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    async with ClaudeSDKClient(options=options) as session:
        if prompt is not None:
            await session.query(prompt)
            async for message in session.receive_response():
                _render_message(message)
            return 0

        # Interactive: one turn per line, conversation state kept by the SDK.
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            await session.query(line)
            async for message in session.receive_response():
                _render_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent_sdk", description=__doc__)
    parser.add_argument("prompt", nargs="?", help="one-shot prompt; omit for interactive")
    parser.add_argument(
        "--url",
        default=os.environ.get("HARNESS_URL", "http://127.0.0.1:8080"),
        help="harness service base URL",
    )
    parser.add_argument("--model", default=None, help="model id (default: SDK default)")
    parser.add_argument("--cwd", default=None, help="working directory for the session")
    parser.add_argument("--max-turns", type=int, default=None, help="cap agent turns")
    args = parser.parse_args()

    try:
        return asyncio.run(run(args.prompt, args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
