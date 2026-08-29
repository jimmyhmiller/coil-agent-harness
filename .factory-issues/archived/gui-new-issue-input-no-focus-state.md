---
project: gui
---

# Clicking the new-issue input gives no visual focus indication

## Current behaviour

When the window is in "new issue" mode (`issue-composer? app` is true) the centred input box rendered by `draw-new!` (`src/view.coil`) looks identical before and after you click it. There is no border highlight, background wash, or any other change to signal that the field is active and keystrokes will land there.

The bottom composer strip (`draw-composer!`) does have a focused state: when `composer-lit > 0` it fills the strip with `(amber-wash)` and draws a heavier amber rule above it. The centred input has no equivalent path at all — it never reads `composer-lit` and has no active-state branch.

The click handler in `click!` (`src/main.coil`) immediately resets `composer-lit` to `0.0` at the top of every click and only restores it to `1.0` for clicks that land inside the bottom composer strip (the `(> py (- h (composer-height ...)))` branch). Clicks in the centred `draw-new!` area don't match that branch, so `composer-lit` stays `0.0` after the click.

## What should happen

Clicking the centred new-issue/new-workflow input should produce the same kind of focused feedback the bottom composer strip gives: an amber underline, background wash, or equivalent signal that the field received the click and is ready for input. The `draw-new!` rendering should check `composer-lit` (or a similar flag) and show the active state, and the click handler should set `composer-lit = 1.0` when the click lands in the `draw-new!` area.
