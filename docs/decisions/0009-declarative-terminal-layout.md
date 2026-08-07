# 0009: Declarative terminal layout

Status: accepted

## Context

The TUI currently formats semantic content directly into frames through specialized
procedures. Input, approvals, service responses, and conversation blocks use related
but separate layout paths. Application code also writes lines and invokes terminal
operations. This makes spacing, grouping, wrapping, truncation, cursor ownership, and
commit behavior properties of call order instead of data.

## Decision

Every TUI surface first produces a terminal-independent declarative layout tree:

```text
TerminalView
  Stack(gap, children)
  Flow(role, prefix, hangingIndent, text)
  DecoratedFlow(prefixSpan, bodySpan, statusSpan)
  Spacer(rows)
  Tail(rows, child)
  Input(prompt, text, cursorOffset, rowBudget)
```

Presenters convert semantic models into this tree. They do not measure cells, wrap
text, allocate terminal rows, emit ANSI, or call services. The pure layout engine
accepts a tree plus terminal width (and the input node's row budget) and produces a
`ViewLayout`: a complete `Frame` plus semantic anchors such as the input cursor.

The pipeline is:

```text
durable events -> presentation model -> presenter -> layout tree
layout tree + constraints -> frame + anchors
previous/desired frame -> render plan
render plan + terminal profile -> terminal driver
```

Only the layout engine owns Unicode cell measurement, wrapping, hanging indentation,
width constraints, height budgets, truncation, and sanitization. Only the renderer
owns frame history and diff policy. Only the terminal driver emits control bytes.

Committed transcript, live footer, prompt, and approval are sibling regions in one
declarative `TerminalView`. The application submits semantic intent and receives
interaction intent; it never repairs cursor positions or writes presentation lines.

Frames own copied text in a `TuiCycleArena`; they never retain slices into a presenter
temporary. Render plans are valid only until that cycle arena closes.

## Required invariants

- The same layout tree renders through plain and interactive strategies.
- Layout is deterministic for a given tree, constraint set, and capability profile.
- Every produced line fits its cell width constraint.
- Content control bytes are sanitized before reaching a frame.
- Renderer operations cannot change semantic spacing or wrapping.
- Terminal operations cannot contain domain events, JSON, or layout decisions.
- Application and service modules do not execute terminal operations or emit
  presentation bytes; terminal capability/lifecycle queries remain available to
  the interaction controller.
- A prompt anchor explicitly names its row and column; cursor position is never
  inferred from the last bytes written.

## Migration

Introduce the layout tree and engine beside the current presenter, migrate all static
conversation blocks, then input/approval views, then service/slash-command views.
Once every surface produces `TerminalView`, delete direct application output and the
specialized input layout path. Finally reduce the inline renderer to frame planning
and the terminal module to operation execution.
