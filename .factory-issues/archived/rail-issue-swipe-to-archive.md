---
project: gui
---

# Two-finger horizontal swipe on issue rows in the rail should reveal an Archive action

There is currently no way to dismiss or remove an issue from the rail without going to the filesystem. A two-finger swipe left on an issue row should slide the row left to expose an "Archive" button on the right edge, and tapping that button should move the issue file out of active circulation.

## Current behaviour

Event type 22 (scroll wheel / trackpad) in `src/main.coil` around line 1341 already reads `scrollingDeltaY` and routes it to `scroll-by!` when the pointer is over the conversation pane. The `scrollingDeltaX` component is read from the same event but is entirely ignored. Nothing in `draw-rail!` (`src/view.coil` line 66) renders a swipe-in button, and no app state tracks per-row swipe offset.

## What should happen

1. **State** – Add a field to `App` (in `src/model.coil`) that records which rail index, if any, is currently swiped open and by how many points (a partial `f64` offset clamped to `[0, ARCHIVE_BTN_W]`).

2. **Input** – In the event-type-22 handler in `src/main.coil`, when the pointer is inside the rail (`px < .rail geom`) and `scrollingDeltaX` is non-zero, update the swipe state for the rail row under the pointer rather than scrolling the conversation. Only issue rows (those where `item-issue?` is true) should respond; project headings, workflow rows, and run rows should not.

3. **Drawing** – In `draw-rail!` (`src/view.coil`), when a row's swipe offset is > 0, clip-translate the row content left by that amount and draw a red "Archive" button of width `ARCHIVE_BTN_W` revealed from the right edge of the rail. The button label can be the single word "Archive" in `ink1` on a red fill.

4. **Commit** – When the swipe offset reaches `ARCHIVE_BTN_W` (fully open) and the user lifts their fingers, or when they click inside the revealed button region, move the issue's `.file` path (stored on the `Issue` struct, which is the full path under `.factory-issues/`) into a sibling directory `.factory-issues/archived/`. Create that directory if it does not exist. Then rebuild the rail with `rail-build!` and clear the swipe state.

5. **Cancel** – If the user swipes back right, or clicks anywhere outside the open button, close the swipe (reset offset to 0) without archiving.

## Concrete references

- Swipe state: new fields on `App` in `src/model.coil` near line 165 (existing view-state fields)
- Input routing: `src/main.coil` ~line 1343, where `scrollingDeltaY` is already extracted — add a branch on `scrollingDeltaX` when `px < .rail geom`
- Drawing: `src/view.coil` `draw-rail!`, in the `:else` branch that renders issue/run rows (~line 133), offset the row by the swipe state and draw the button behind it
- Archive destination: `.factory-issues/archived/<filename>` (same filename, different directory); `issues-dir` is defined in `src/harness.coil` line 972
