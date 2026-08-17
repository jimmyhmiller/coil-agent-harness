# Inline TUI version-one verification

This record maps the deliverables in `docs/tui-roadmap.md` to source and automated
evidence. Version one uses the normal terminal screen, append-only committed output,
and one bounded mutable footer. It does not implement the optional retained mutable
horizon.

## Architecture

| Responsibility | Implementation | Evidence |
|---|---|---|
| Durable wire-schema adaptation | `src/tui/event_adapter.coil` | `tests/tui_model_test.coil`, recorded JSONL fixtures |
| Terminal-independent session state | `src/tui/model.coil` | replay, duplicate, unknown-event, child-agent, and burst tests |
| Stable-prefix commitment | `src/tui/transcript.coil` | transcript-policy model tests |
| Cell measurement and sanitization | `src/tui/cells.coil`, generated `unicode_width.coil` | strict UTF-8 and Unicode-width tests |
| Width-aware semantic layout | `src/tui/layout.coil`, `frame.coil` | width matrix, wrapping, control-byte, and styled-span tests |
| Tool summaries | `src/tui/tool_presenter.coil` | Bash, generic, orchestration, compact, and verbose layout tests |
| Sequential fallback | `src/tui/render_plain.coil` | golden fixtures and non-TTY e2e checks |
| Mutable footer | `src/tui/render_inline.coil` | symbolic terminal-operation tests and PTY tests |
| Terminal capabilities and modes | `src/tui/terminal.coil` | profile tests, signal/suspend PTYs, compatibility matrix |
| Composer | editor, decoder, layout, reader, and input renderer modules under `src/tui/` | editor/decoder/layout unit tests and input PTY |
| Application coordination | `src/tui/app.coil` | compiled binary and end-to-end suite |
| Assembly | `src/main.coil` | imports only the TUI application facade and terminal profile |

Only `src/tui/terminal.coil` constructs terminal control sequences. Domain events,
presentation state, layout, and frames contain no ANSI bytes or terminal coordinates.

## Behavioral coverage

Recorded event fixtures cover:

- a submitted user turn and multi-delta assistant response;
- one tool call;
- parallel tools completing out of order;
- delegation, workflow progress, and cancellation;
- provider/run failure with a human-readable message.

Model tests add duplicate replay, unknown future events, child-agent completion,
terminalization of open children, 2,000 text deltas, and 256 parallel tool records.
The adapter never retrieves tool arguments from neighboring events.

The renderer tests prove that committed blocks write once, only the owned live rows
are erased, semantic span boundaries survive planning, and clearing leaves no owned
rows. The layout tests cover narrow, normal, and wide widths; ASCII, combining marks,
CJK, emoji, malformed UTF-8, tabs, newlines, and terminal controls.

## Interaction and lifecycle coverage

The native TUI tests exercise editing, bracketed paste, resize, interruption,
submission, ANSI styling, and final termios restoration. Separate PTYs cover SIGTERM
and Ctrl-Z suspend/resume.

During a run, the composer is unavailable. Escape and Ctrl-C request idempotent
cancellation, Ctrl-Z restores modes before suspension, terminal closure exits the
watch, and other input is ignored.

## Capability and accessibility coverage

The plain renderer activates for redirected stdout, `TERM=dumb`, screen-reader mode,
the environment override, or `harness tui --plain`. Plain and screen-reader e2e checks
reject ANSI bytes. `NO_COLOR`, explicit color, compact, verbose, reduced-motion,
width, and locale-derived Unicode policy have unit coverage. Screen-reader mode uses
ASCII labels and forces motion and interactive redraw off.

The compatibility coverage runs the same bounded inline protocol with
`xterm-256color`, `xterm-kitty`, `alacritty`, `wezterm`, `ghostty`,
`screen-256color`, `tmux-256color`, and `vt100`. It verifies normal-buffer operation,
paste-mode pairing, and termios restoration. SSH uses the remote terminal's `TERM`
profile and the same POSIX TTY protocol. Native Windows terminals are outside the
version-one POSIX baseline and receive sequential output unless hosted through a
compatible POSIX TTY.

## Resource bounds

- Assistant text retained by the presentation model: 1 MiB per block, truncated at a
  valid UTF-8 boundary.
- Expanded structured arguments and results: 512 bytes per value.
- Mutable live footer: 3 to 12 rows based on terminal height.
- Multiline composer: bounded to the available input-row budget.
- Committed layout: batches of 128 blocks.
- Streaming redraw cadence: one recovery/render cycle per 40 ms, with all available
  journal deltas reduced before rendering.

## Release commands

Run these as separate gates:

```sh
coil verify
coil build
coil fmt --check
git diff --check
sh scripts/check_file_size.sh
```

## Deferred work

The retained mutable-horizon renderer in phase 6 remains deferred. Version one does
not address arbitrary rows in terminal scrollback. It mutates only the contiguous live
footer it owns.

The harness temporarily implements provider response streaming through a direct curl
adapter behind `StreamingHttpTransport`. `docs/feature-request-http-streaming.md`
specifies the Coil standard-library API needed to remove that adapter without losing
live model deltas.
