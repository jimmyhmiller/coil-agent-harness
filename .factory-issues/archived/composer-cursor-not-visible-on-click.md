---
project: gui
---

# Clicking the composer strip does not show a visible cursor

Clicking the composer text area does not produce a clear visual indication that it is ready to accept input. The user sees no cursor appear at the click point.

**Current behaviour:** `click!` in `src/main.coil` (around line 1092–1093) handles a composer click by calling `sel-clear!` and setting `composer-lit` to the current time. That triggers a brief amber glow animation that fades after ~0.45 s. The amber block cursor drawn in `draw-composer!` (`src/view.coil`, line 696 for non-empty, line 664 for empty) is always rendered at the end of the text regardless of whether a click has occurred. There is no persistent focus indicator and no OS-level first-responder / text-focus event raised, so no system I-beam cursor appears.

**What it should do:** Clicking the composer should produce an unmistakable, lasting signal that keyboard input will go there — at minimum a steady visible cursor. The amber glow fading away leaves the user unsure whether the field is active. A focus state (separate from the timed `composer-lit` animation) should be tracked in the model, and `draw-composer!` should use it to decide whether to draw the cursor block, rather than drawing it unconditionally without any relation to whether the strip was actually clicked.

**Relevant code:**
- `src/main.coil` ~line 1089–1093 — composer click handler inside `click!`
- `src/view.coil` ~line 636–696 — `draw-composer!`, cursor drawing
- `src/model.coil` — `App` struct fields; no `composer-focused` or equivalent field exists today
