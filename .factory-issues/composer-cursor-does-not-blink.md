---
project: gui
---

# Composer cursor does not blink, leaving no persistent focus indicator after a click

## Current behaviour

Clicking the composer strip sets `composer-lit` to the current timestamp, which
triggers a ~0.45 s amber-wash animation in `draw-composer!` (`src/view.coil`).
Once the animation completes, `lit` reaches `1.0`, `recent` becomes `false`, and
the strip returns to its default appearance. The only remaining indicator that the
composer is ready to accept input is a static 8 × 16 amber rectangle (the text
cursor) and a small amber chevron (`caret!`) to its left — both drawn
unconditionally, regardless of whether the user has ever clicked.

Because the cursor block is always on and never blinks, users who click the strip
get a flash of amber and then silence. The static block is easy to read as a
decorative UI element rather than an insertion point. The composer does in fact
accept keystrokes at all times (no click required — the README notes "typing has
always gone to this line"), but there is nothing after the animation that says so.

## What it should do

The cursor block should blink on a regular interval (e.g. 530 ms on / 530 ms off
is the macOS default) while the composer strip is the active input destination.
The `now` field on `App` is already threaded into draw calls, so the on/off phase
can be derived from `fmod(now - composer-lit, period)` without any new state.

If a full blink is out of scope, at minimum the lit animation should not
completely fade — leaving the strip at, say, 20 % amber-wash indefinitely would
give a persistent signal that is absent today.

Relevant code: `draw-composer!` in `src/view.coil` (the `lit` / `recent` block
and the two `fill!` calls that draw the cursor rectangle).
