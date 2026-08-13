#!/usr/bin/env python3
"""Inspect and follow harness event journals without owning the running process."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TERMINAL_RUN_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
START_EVENTS = {"model.request.started", "tool.call.started"}
FINISH_FOR = {
    "model.request.completed": "model.request.started",
    "model.request.failed": "model.request.started",
    "tool.call.completed": "tool.call.started",
    "tool.call.failed": "tool.call.started",
    "tool.call.rejected": "tool.call.proposed",
}


@dataclass(frozen=True)
class Filters:
    run_id: str | None = None
    agent_id: str | None = None
    operation_id: str | None = None
    parent_operation_id: str | None = None
    event: str | None = None

    def matches(self, item: dict[str, Any]) -> bool:
        return all(
            wanted is None or item.get(field) == wanted
            for field, wanted in (
                ("run_id", self.run_id),
                ("agent_id", self.agent_id),
                ("operation_id", self.operation_id),
                ("parent_operation_id", self.parent_operation_id),
                ("event", self.event),
            )
        )


def read_journal(path: Path, *, tolerate_torn_tail: bool = True) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    lines = raw.splitlines()
    torn = bool(raw) and not raw.endswith(b"\n")
    if torn and tolerate_torn_tail:
        lines = lines[:-1]
    events: list[dict[str, Any]] = []
    last_sequence = 0
    for number, line in enumerate(lines, 1):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: invalid JSON: {error.msg}") from error
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or sequence <= last_sequence:
            raise ValueError(f"{path}:{number}: sequence is missing or out of order")
        last_sequence = sequence
        events.append(event)
    return events


def filtered(events: Iterable[dict[str, Any]], filters: Filters) -> list[dict[str, Any]]:
    return [event for event in events if filters.matches(event)]


def inspection_scope(events: list[dict[str, Any]], filters: Filters) -> list[dict[str, Any]]:
    """Select runs by any action filter, then retain their full lifecycle."""
    matches = filtered(events, filters)
    selected_runs = {event.get("run_id") for event in matches if event.get("run_id")}
    return [event for event in events if event.get("run_id") in selected_runs]


def duration_text(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def run_projection(events: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        run_id = event.get("run_id")
        if run_id:
            grouped.setdefault(run_id, []).append(event)

    result = []
    for run_id, run_events in grouped.items():
        first = run_events[0]
        last = run_events[-1]
        kinds = [event.get("event", "") for event in run_events]
        terminal = next((event for event in reversed(run_events) if event.get("event") in TERMINAL_RUN_EVENTS), None)
        started = next((event for event in run_events if event.get("event") == "run.started"), first)
        status = {
            "run.completed": "succeeded",
            "run.failed": "failed",
            "run.cancelled": "cancelled",
        }.get(terminal.get("event") if terminal else None, "running" if "run.started" in kinds else "queued")
        end_ms = terminal.get("timestamp_ms", now_ms) if terminal else now_ms
        start_ms = started.get("timestamp_ms", first.get("timestamp_ms", end_ms))

        open_operations: dict[tuple[str, str], dict[str, Any]] = {}
        for event in run_events:
            kind = event.get("event", "")
            key = (event.get("operation_id", ""), kind)
            if kind in START_EVENTS:
                open_operations[key] = event
            elif kind in FINISH_FOR:
                open_operations.pop((event.get("operation_id", ""), FINISH_FOR[kind]), None)

        inflight = []
        for (_, kind), event in open_operations.items():
            timestamp = event.get("timestamp_ms", now_ms)
            inflight.append({
                "kind": kind.removesuffix(".started"),
                "operation_id": event.get("operation_id", ""),
                "parent_operation_id": event.get("parent_operation_id", ""),
                "agent_id": event.get("agent_id", ""),
                "elapsed_ms": max(0, now_ms - timestamp),
            })

        result.append({
            "run_id": run_id,
            "status": status,
            "provider": last.get("provider") or first.get("provider", ""),
            "model": last.get("model") or first.get("model", ""),
            "started_at_ms": start_ms,
            "elapsed_ms": max(0, end_ms - start_ms),
            "last_event_at_ms": last.get("timestamp_ms", 0),
            "last_sequence": last.get("sequence", 0),
            "event_count": len(run_events),
            "event_counts": dict(Counter(kinds)),
            "in_flight": inflight,
        })
    return sorted(result, key=lambda item: (item["last_sequence"], item["run_id"]))


def compact_event(event: dict[str, Any], now_ms: int) -> str:
    elapsed = duration_text(now_ms - event.get("timestamp_ms", now_ms))
    identity = event.get("operation_id") or event.get("run_id") or "-"
    parent = event.get("parent_operation_id")
    relation = f" <- {parent}" if parent else ""
    return f"#{event.get('sequence', '?'):>4} {elapsed:>10} ago  {event.get('event', '?'):<28} {identity}{relation}"


def print_inspection(events: list[dict[str, Any]], args: argparse.Namespace) -> None:
    now_ms = int(time.time() * 1000)
    projections = run_projection(events, now_ms)
    if args.json:
        print(json.dumps(projections, indent=2, sort_keys=True))
        return
    if not projections:
        print("no matching runs")
        return
    for run in projections:
        print(f"{run['run_id']}  {run['status']}  {run['provider']}/{run['model']}")
        print(f"  elapsed {duration_text(run['elapsed_ms'])}  events {run['event_count']}  last sequence {run['last_sequence']}")
        if run["in_flight"]:
            print("  in flight:")
            for operation in run["in_flight"]:
                print(f"    {operation['kind']} {operation['operation_id']}  {duration_text(operation['elapsed_ms'])}")
        elif run["status"] == "running":
            print("  in flight: model/runtime work with no open model or tool event")


def print_events(events: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if args.json:
        for event in events:
            print(json.dumps(event, separators=(",", ":"), sort_keys=True))
        return
    now_ms = int(time.time() * 1000)
    for event in events:
        print(compact_event(event, now_ms))


def watch(path: Path, filters: Filters, args: argparse.Namespace) -> None:
    seen = 0
    next_summary = 0.0
    while True:
        events = read_journal(path)
        if len(events) < seen:
            print("journal was replaced or truncated; replaying", file=sys.stderr)
            seen = 0
        new_events = filtered(events[seen:], filters)
        print_events(new_events, args)
        seen = len(events)
        now = time.monotonic()
        if args.summary_every and now >= next_summary:
            print_inspection(inspection_scope(events, filters), args)
            next_summary = now + args.summary_every
        if args.until_terminal:
            selected = filtered(events, filters)
            if any(event.get("event") in TERMINAL_RUN_EVENTS for event in selected):
                return
        time.sleep(args.interval)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("inspect", "project current run state and in-flight work"),
        ("events", "print a filtered event timeline"),
        ("watch", "follow new events and periodically show elapsed work"),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("journal", type=Path)
        command.add_argument("--run-id")
        command.add_argument("--agent-id")
        command.add_argument("--operation-id")
        command.add_argument("--parent-operation-id")
        command.add_argument("--event")
        command.add_argument("--json", action="store_true")
        if name == "watch":
            command.add_argument("--interval", type=float, default=0.25)
            command.add_argument("--summary-every", type=float, default=5.0)
            command.add_argument("--until-terminal", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    filters = Filters(args.run_id, args.agent_id, args.operation_id, args.parent_operation_id, args.event)
    try:
        if args.command == "watch":
            watch(args.journal, filters, args)
        else:
            events = read_journal(args.journal)
            if args.command == "inspect":
                print_inspection(inspection_scope(events, filters), args)
            else:
                print_events(filtered(events, filters), args)
        return 0
    except (OSError, ValueError) as error:
        print(f"observer: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
