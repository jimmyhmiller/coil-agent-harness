---
project: gui
---

# Composer text does not appear to wrap as you type

## Current behaviour

A user typing a long message into the composer strip reported that text does not
wrap automatically — it continues on one line instead of flowing onto the next.

The wrapping logic exists in `src/view.coil`: `composer-columns` computes how
many fixed-pitch characters fit across the pane, and `composer-row-end` walks the
buffer to find where each row breaks. Both `draw-composer!` and `composer-rows`
call these functions. However, `composer-columns` derives the column count by
dividing the available width by a character width measured from the canvas font
object at render time. If that measurement is wrong — wrong font, wrong size, or
a stale canvas pointer — the column count could come out far too large, silently
preventing any line break from firing before `COMPOSER_MAX_ROWS` (8) is reached.

The wrapping is also purely visual: there is no scroll, so if rows are not being
created the strip stays single-line and text silently overflows without any
clue that something is wrong.

## What it should do

Typing past the width of the composer pane should cause the text to wrap to a new
row and the strip to grow upward, as documented in the README ("text wraps at the
pane's measure instead of running off the right edge, and the strip grows upward
to hold it").

## To reproduce / investigate

1. Open the app and navigate to any project so the composer is active.
2. Type a sentence long enough to exceed the pane width (roughly 80+ characters
   at the default window size).
3. Observe whether the strip grows and the text reflows, or whether it stays
   single-line.

If it stays single-line, instrument `composer-columns` to print the column count
and compare it against the actual visible character width. The likely culprit is
the font-metrics call inside `composer-columns` in `src/view.coil`.
