---
project: gui
---

# Clicking inside the composer does not move the cursor to the click position

The amber block cursor in the composer is always pinned to the end of the typed
text. Clicking anywhere in the composer strip — whether mid-text or to the left
of existing characters — has no effect on cursor position. The click handler in
`src/main.coil` (`click!`, around line 1089–1093) only calls `sel-clear!` and
sets `composer-lit` to trigger the brief amber wash; it does not do any
hit-testing against character positions or move an insertion point.

As a result:
- A user who clicks partway through a long draft cannot correct a word without
  backspacing all the way from the end.
- Clicking gives only a 0.45-second amber fade as feedback, then the strip looks
  exactly as it did before. There is no persistent visual indicator that the
  composer is now the active target for keystrokes (it always is, but nothing
  says so after the fade).

What should happen: clicking inside the composer at minimum confirms focus with a
steady visible state (the amber block cursor is already there, but the strip
returns to its dim appearance after the fade). Ideally the click also repositions
the cursor to the nearest character boundary in the clicked row, which requires
hit-testing the row geometry already computed by `composer-row-end` /
`composer-rows` in `src/view.coil`.

A minimum fix is a persistent "lit" state while the composer is the active
input target. Full click-to-position requires mapping the click x-coordinate to
a column using `Face.adv` and the row boundaries already available in
`draw-composer!`.
