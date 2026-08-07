# Inline terminal UI architecture and roadmap

## Product direction

Coil's interactive interface is a conversational CLI, not a full-screen terminal
application. It preserves the user's normal terminal scrollback and keeps the shell's
native selection, copying, search, and history useful.

The first version has two visual areas:

```text
committed transcript       append-only terminal output
live region                a small redrawable block at the bottom
```

Only unfinished work belongs in the live region. Once a message, tool call, approval,
or run reaches a stable presentation, it is committed to the transcript and is no
longer mutated.

The architecture must nevertheless leave room for a later retained viewport that can
revise completed-looking blocks above the bottom line while they remain on screen.
That later feature is an enhancement to the renderer, not a reason to couple terminal
coordinates to runtime events or domain state.

## Non-goals

- Do not enter the alternate screen buffer for the normal chat experience.
- Do not model the interface as a dashboard with permanent panels.
- Do not expose event JSON, operation IDs, or provider protocol details by default.
- Do not make terminal escape sequences part of the service or runtime layers.
- Do not promise mutation of arbitrary terminal scrollback. A terminal application can
  safely redraw only rows it currently owns and can still address.
- Do not make color or animation necessary to understand state.

## UX principles

1. The transcript is calm, compact, and useful after Coil exits.
2. Stable content does not move merely because new events arrive.
3. Tool activity is subordinate to the conversation, not a peer message stream.
4. Human-readable summaries are the default; raw details are explicitly expanded.
5. Every transient state has an equivalent sequential-text representation.
6. Resize, interruption, suspension, output redirection, and terminal failure degrade
   safely rather than corrupting the terminal.
7. Input remains predictable while output streams. Enter submits, Escape interrupts,
   and pasted text is never mistaken for a sequence of commands.

## Dependency direction

```text
service journal / runtime events
              |
        event adapter
              |
   semantic presentation model
       /              \
 transcript policy   interaction controller
       |              /        \
     layout       input editor  approvals
       |
 virtual terminal frame
       |
 renderer strategy
   /          |          \
plain     inline footer   retained viewport
       |
terminal driver + capability profile
```

Dependencies point downward. In particular:

- Domain events never contain colors, indentation, terminal rows, or animation frames.
- Presentation state never writes to file descriptors.
- Layout never performs service calls or authorization decisions.
- The renderer receives complete desired frames and does not interpret event payloads.
- The terminal driver is the only layer that emits control sequences or changes
  terminal modes.

## Separation of concerns

### 1. Event adapter

The adapter consumes durable public events and translates them into semantic UI
actions. Each event family must be self-describing: a tool proposal carries the
authoritative tool name and structured arguments, an authorization event carries the
authorization decision data, and a completion carries the structured outcome. The
adapter may reduce successive lifecycle events for the same entity by stable identity;
it must never recover missing facts from another event family, event adjacency, or
previously formatted text.

Example actions include:

```text
AssistantTextAppended(run, text)
ToolStarted(operation, tool, arguments)
ToolFinished(operation, outcome)
ApprovalRequested(authorization, effect)
AgentStateChanged(agent, state)
RunFinished(run, outcome)
```

This is the only presentation layer that knows the journal's wire schema. Unknown
events are ignored or represented as diagnostics in verbose mode. Duplicate events
must be harmless, since recovery may replay history.

Contract tests use recorded durable events and assert both sides of this boundary:
producers emit complete authoritative payloads, and the adapter produces the same
semantic actions during live delivery and journal replay. A missing required field is
a contract error or explicit degraded presentation, not an invitation to infer it.

### 2. Semantic presentation model

The model is a retained, terminal-independent tree of conversational blocks:

```text
Session
  Turn
    UserMessage
    AssistantMessage
    ToolGroup
      ToolCall
    Approval
    Delegation
    Error
```

Each block has a stable presentation ID, semantic state, visibility policy, and detail
level. It does not have a terminal row. It supports incremental streaming while still
being renderable from scratch.

Tool-specific presenters turn arguments and results into concise descriptions. For
example, the Bash presenter shows the command and a bounded result summary; a file
presenter shows a path and change counts. A generic presenter exists for unknown
tools, but raw JSON is restricted to expanded or verbose output.

### 3. Transcript policy

This policy decides when a block becomes immutable history in the first renderer.
It owns neither terminal output nor domain truth.

Initial rules:

- A submitted user message commits immediately.
- Assistant text remains live while streaming and commits at a stable boundary.
- A running tool remains live; its final compact summary commits on completion.
- An approval remains live until decided, then commits as a one-line result.
- Multiple parallel tools may form one live group and commit in deterministic visual
  order even when execution completes out of order.
- Errors commit immediately and use explicit text in addition to color.

The policy produces two projections: newly committed blocks and the current live
block set.

### 4. Layout engine

The layout engine converts semantic blocks to terminal cell lines for a supplied
width and rendering profile. It owns:

- wrapping and continuation indentation;
- display-cell measurement rather than byte length;
- wide characters, combining marks, emoji, and tab policy;
- truncation and bounded previews;
- spacing and visual hierarchy;
- compact, expanded, plain, and reduced-motion variants;
- sanitization or visible escaping of untrusted control characters.

Its output is a virtual frame made of styled spans. Styles are semantic roles such as
`primary`, `muted`, `success`, `warning`, and `failure`, not hard-coded colors.

Layout is deterministic and pure enough for snapshot tests. It must not emit ANSI.

### 5. Interaction controller

The controller coordinates input focus, submission, interruption, approvals,
expansion, command completion, and resize notifications. It turns key events into
intent; it does not mutate service state directly. Service-facing commands pass
through a narrow application boundary so interactions can be tested without a real
terminal or provider.

Approval views expose explicit actions such as allow once, allow by rule, and reject.
The controller chooses no authorization policy on the user's behalf.

### 6. Input editor

The editor is an independent component supporting:

- cursor movement and selection-safe redraws;
- character, word, and line deletion;
- history navigation;
- multiline input;
- bracketed paste;
- slash-command completion;
- terminal-width-aware wrapping;
- an explicit busy/steering policy.

The editor returns text and editing intents. It does not render transcript blocks or
consume journal events.

### 7. Renderer strategies

All renderers consume the same laid-out frames.

#### Plain renderer

Writes sequential labeled text without cursor movement, animation, or color. It is
used for non-TTY output, `TERM=dumb`, screen-reader mode, tests, and `--plain`.

#### Inline-footer renderer (version one)

Writes committed blocks once. It owns only a contiguous live region immediately above
the input cursor. On update it erases and redraws that region using relative cursor
movement and erase-line operations.

State includes:

```text
previous live frame
previous live height
terminal width
cursor visibility
redraw pending
```

It coalesces streaming updates and redraws at a bounded cadence. Committing a block
means clearing the live region, writing the block as ordinary output, and then
rendering the new live region.

#### Retained-viewport renderer (future)

This renderer may revise blocks above the bottom live region, but only inside a
contiguous screen area that Coil explicitly owns. It retains the previous and desired
screen frames, computes row-level differences, and uses relative or absolute cursor
addressing to update changed rows.

Its contract must acknowledge terminal reality:

- Once owned rows scroll into inaccessible scrollback, they become committed.
- A resize invalidates wrapping and row coordinates; the owned viewport must be fully
  reflowed and repainted.
- User scrolling is generally not observable or controllable across terminals.
- Concurrent output from another process invalidates the retained frame.
- Very tall turns may exceed the visible viewport and must progressively commit.

A practical policy is a **mutable horizon**: retain and permit updates to the most
recent N visible blocks, subject to a row budget. Older blocks cross a commit boundary
and become permanent scrollback. This supports changing a tool from running to done,
collapsing parallel-agent progress, or revising token usage without pretending the
entire terminal history is a canvas.

### 8. Terminal driver and capability profile

The driver owns raw mode, cursor movement, erase operations, SGR, cursor visibility,
bracketed paste, terminal size, and signal-safe restoration. It exposes typed
operations instead of accepting arbitrary escape strings.

The capability profile is derived from TTY detection, terminal metadata, environment,
configuration, and optional probing. It records support for color depth, Unicode,
cursor addressing, bracketed paste, hyperlinks, and interactive redraws.

Policy must respect at least `NO_COLOR`, `TERM=dumb`, explicit `--plain`, explicit
color overrides, and per-stream TTY status. Capability detection does not live in the
layout engine.

### 9. Lifecycle guard

Terminal modes are process-global resources and require structured ownership. A guard
installs cleanup for normal exit, errors, interruption, suspend/resume, and panic-like
unwinding where Coil permits it. Cleanup restores styling, cursor visibility, paste
mode, and input mode. The application must never leave the user's shell unusable.

## Version-one visual grammar

```text
Coil · auto/auto · /help for commands

❯ List the files in this project

● I’ll inspect the project root.

  ⏺ Bash  ls
    Found 6 files and 8 directories

● The project contains `README.md`, `src/`, `tests/`, and supporting directories.

❯ _
```

Conventions:

- `❯` is user input; do not print an additional `you` label.
- `●` begins assistant prose but is not repeated for every streamed fragment.
- `⏺` denotes a tool record. Status is also written in words when ambiguity matters.
- Metadata is indented and visually muted.
- Operation IDs are hidden outside verbose diagnostics.
- One blank line separates major conversational blocks.
- Tables are used only for genuinely tabular comparisons, not ordinary file lists.

## Roadmap

### Blocking correctness TODO: conversation continuity and prompt caching

The current TUI submits each user message as an independent model request. The next
message therefore does not reliably include the preceding user messages, assistant
responses, tool calls, or tool results, and the agent cannot resolve ordinary
cross-turn references such as “that,” “continue,” or “change the previous answer.”
This is a correctness failure, not a presentation enhancement.

Before adding broader TUI capabilities:

- Define one stable conversation/session identity distinct from per-turn run IDs.
- Build every new model request from the authoritative ordered conversation history.
- Preserve user, assistant, tool-call, tool-result, and relevant system/developer
  content without reconstructing prompts from rendered terminal text.
- Define provider-specific continuation behavior explicitly: opaque response/thread
  IDs may optimize continuation, but durable semantic history remains authoritative.
- Define prompt-cache keys from the exact stable prefix plus provider, model,
  instructions, tool schema, and all provider options that affect interpretation.
- Invalidate or bypass cached prefixes when any keyed input changes; never reuse
  state across projects, conversations, providers, models, or incompatible tool
  schemas.
- Avoid duplicating cached prefix content when a provider continuation identifier is
  also supplied.
- Make restart/replay reconstruct the same next request as the original live session.

Required acceptance tests:

- Turn two can answer references to facts introduced by turn one.
- Turn two can continue from the preceding assistant response.
- Tool results from turn one remain available to a later turn without re-running the
  tool or scraping the transcript.
- Two simultaneous TUI sessions in one project never share conversation state.
- Changing model, provider, instructions, or tool schema produces a cache miss.
- Restarting from durable history preserves continuity and produces the same cache
  key as the equivalent uninterrupted session.
- Captured provider-wire fixtures prove the exact ordered messages and cache metadata
  sent on every turn.

Exit criterion: multi-turn references work deterministically in live, replayed, and
restarted sessions, and cache reuse is both observable and scoped by tested keys.

### Phase 0: behavioral fixtures and terminal contract

Deliverables:

- Capture representative event streams for plain answers, streamed answers, one tool,
  parallel tools, approvals, delegation, cancellation, failure, and replay.
- Define expected human transcripts and live frames as golden fixtures.
- Add a fake terminal that records typed terminal operations and configurable width.
- Document the supported baseline terminals and fallback behavior.
- Add invariants: no raw control bytes from content, styling always resets, cursor is
  restored, replay is idempotent, and non-TTY output contains no cursor movement.

Exit criterion: current and proposed behavior can be compared without running a real
model, and terminal output is testable without timing-sensitive integration tests.

### Phase 1: semantic presentation model

Deliverables:

- Introduce the event adapter and correlated presentation model.
- Add tool presenter interfaces plus Bash and generic implementations.
- Separate compact summaries from expanded diagnostic detail.
- Move JSON serialization out of the default interactive rendering path.
- Unit-test replay, duplicate events, out-of-order parallel completion, and unknown
  events.

Exit criterion: an event history deterministically produces a terminal-independent
session model.

### Phase 2: pure layout and plain renderer

Deliverables:

- Add styled spans, display-cell measurement, wrapping, sanitization, and truncation.
- Implement compact and plain layouts.
- Implement sequential rendering for non-TTY and explicit plain mode.
- Respect terminal width, `NO_COLOR`, and `TERM=dumb`.
- Add width matrix tests at narrow, normal, and wide sizes, including Unicode cases.

Exit criterion: Coil emits a clean, stable transcript with no cursor addressing and no
raw JSON in the default view.

### Phase 3: inline live-region renderer

Deliverables:

- Add typed terminal operations and a lifecycle guard.
- Implement append-only commits plus the bounded mutable footer.
- Coalesce model deltas and progress events to avoid flicker.
- Render running tools, thinking state, parallel activity, and failures in place.
- Handle resize by repainting only the owned live region.
- Add pseudo-terminal integration tests that assert final screen and scrollback.

Exit criterion: streaming produces a calm interface, completed history never moves,
and interruption or abnormal exit restores the shell.

### Phase 4: input editor and inline approvals

Deliverables:

- Replace line-only reads with the independent input editor.
- Add bracketed paste, multiline editing, history, and slash completion.
- Define whether submitted steering is queued or sent during active runs.
- Present approvals in the live region with keyboard and textual choices.
- Collapse decided approvals into concise transcript records.
- Make Escape semantics consistent for menus, approval rejection, and run interruption.

Exit criterion: input and approval interactions never race with output redraws, pasted
content is safe, and every action has a plain-mode equivalent.

### Phase 5: information architecture and orchestration views

Deliverables:

- Add compact subagent and workflow progress groups.
- Provide expansion for details without making the default transcript noisy.
- Add `/status` and `/graph` human presenters instead of JSON dumps.
- Define completion summaries for parallel tools and child agents.
- Add user-configurable compact, normal, verbose, reduced-motion, and plain profiles.

Exit criterion: orchestration is understandable at a glance while detailed state
remains inspectable on demand.

### Phase 6: retained mutable horizon (optional)

Deliverables:

- Generalize the virtual frame to stable block and row identities.
- Implement owned-region anchoring and a row-diff renderer.
- Define row and block budgets for the mutable horizon.
- Progressively commit blocks before they leave the owned viewport.
- Reflow and repaint the full owned region on resize.
- Detect or conservatively recover from frame invalidation.
- Test tool-state replacement, collapsing groups, user input wrapping, resize, narrow
  terminals, tall output, suspend/resume, and injected foreign output.

Exit criterion: recent visible blocks can change without full-screen mode or scrollback
corruption, and the renderer automatically falls back to footer-only behavior when it
cannot prove ownership.

### Phase 7: polish, compatibility, and performance

Deliverables:

- Test macOS Terminal, iTerm2, Ghostty, Kitty, Alacritty, WezTerm, common Linux
  terminals, tmux, SSH, and supported Windows terminals if applicable.
- Add reduced-motion and screen-reader documentation.
- Benchmark high-rate token streams and large parallel event bursts.
- Cap retained text, frame size, update frequency, and expanded tool output.
- Add terminal transcript recordings to release verification.
- Audit every error path for terminal restoration.

Exit criterion: the interface remains correct under slow terminals, high event rates,
resizes, reconnect/replay, and accessibility fallbacks.

## Suggested source boundaries

Exact filenames may change to fit Coil module conventions, but ownership should remain
recognizable:

```text
src/tui/app.coil                 interaction controller and application loop
src/tui/event_adapter.coil       journal event translation and correlation
src/tui/model.coil               terminal-independent presentation state
src/tui/transcript.coil          commit and mutable-horizon policies
src/tui/layout.coil              wrapping and block layout
src/tui/cells.coil               display-cell width and sanitization
src/tui/style.coil               semantic roles and theme resolution
src/tui/input.coil               editable prompt model
src/tui/approval.coil            approval interaction presentation
src/tui/tool_presenter.coil      generic presenter contract
src/tui/tools/bash.coil          Bash-specific summaries
src/tui/frame.coil               virtual lines, spans, and stable identities
src/tui/render_plain.coil        sequential fallback
src/tui/render_inline.coil       append-only transcript plus mutable footer
src/tui/render_viewport.coil     future retained mutable horizon
src/tui/terminal.coil            typed terminal operations and capabilities
src/tui/lifecycle.coil           mode and signal restoration
```

`src/main.coil` should assemble these pieces and select a renderer, not contain event
formatting, terminal escape construction, approval policy, and the conversation loop
in one module.

## Testing strategy

Use four complementary layers:

1. Model tests replay events and assert semantic state.
2. Layout snapshots assert cell lines at several widths and capability profiles.
3. Renderer tests compare typed terminal operations and reconstructed virtual screens.
4. Pseudo-terminal tests exercise real input, resize, signals, and final scrollback.

Property tests should cover arbitrary Unicode, embedded control bytes, repeated events,
all resize sequences, and terminal widths smaller than any preferred component width.
No test should require a live provider unless it verifies an end-to-end contract that
cannot be represented by recorded events.

## Open decisions

Version-one decisions already made:

- Assistant prose streams in the bounded footer and commits only at a stable model
  boundary.
- While a run is active, the composer is intentionally unavailable: Escape or Ctrl-C
  requests idempotent cancellation, Ctrl-Z suspends safely, and all other typed or
  pasted input is ignored. Version one does not silently queue steering text.
- Parallel tools retain proposal order in the semantic model and transcript even when
  completion order differs.
- Expanded diagnostic details print as bounded rows in verbose mode; they do not
  replace the input area.
- Unicode is capability-controlled, with labeled ASCII presentation in screen-reader
  mode.

Still open after version one:

- Whether later versions should accept explicitly queued or immediate steering while a
  run is active.
- Whether parallel tool and subagent records should gain collapsible visual groups.
- Whether the retained viewport is valuable enough to justify its resize, ownership,
  and compatibility complexity after the footer renderer is proven.

These are presentation and interaction decisions. None should require changing the
durable journal, provider contracts, tool executor, or authorization policy.
