---
project: harness
---

# Input composer gives no visible signal that it is focused when clicked

## Current behaviour

The TUI input composer renders at the bottom of the screen with `RolePrimary` styling for the prompt text and a terminal cursor, but nothing else distinguishes the input area as the active/focused element. When a user clicks inside the terminal while the composer is on screen there is no visible change in the prompt or surrounding region to confirm that keystrokes will land in the input. The terminal cursor position is the only signal, and on many terminal emulators that cursor is hard to spot.

The relevant code paths are:

- `src/tui/view.coil` — `ViewInput` struct: holds prompt, text, cursor-offset, menu; no focused/unfocused state
- `src/tui/view_layout.coil` — `view-layout-node!` for `ViewInputNode`: unconditionally assigns `(RolePrimary)` to the flow and `"  "` as continuation prefix; no visual treatment for focus state
- `src/tui/input_reader.coil` — `input-reader-redraw-with!`: calls `view-input-with-menu` and then `TerminalShowCursor`; showing the cursor is the only focus cue
- `src/tui/frame.coil` — `StyleRole`: no role for a focused input border or prompt

## What it should do instead

When the input composer is live and accepting input, the prompt line should carry an unambiguous focus indicator that does not rely solely on cursor blink. Options in order of preference:

- Render the prompt with a distinct `StyleRole` (e.g. a new `RoleInputPrompt`) that maps to a contrasting colour in colour profiles and is still legible in plain/no-colour profiles.
- Prefix the prompt with a marker glyph (`▸ ` in unicode mode, `> ` in plain mode) absent from all transcript lines, making the input row structurally distinct from output.
- Draw a separator rule with a role-coloured style immediately above the composer so the boundary between transcript and input is always visible.

Whatever approach is chosen must degrade gracefully in plain/no-colour profiles: a structural or glyph-based distinction is required; a colour-only change is not sufficient.
