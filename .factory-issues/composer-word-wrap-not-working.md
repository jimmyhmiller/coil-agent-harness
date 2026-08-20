---
project: gui
---

# Composer text does not visually wrap and the box does not grow

When enough text is typed into the composer strip to exceed one line, it should
wrap at the last word boundary before the edge and the strip should grow upward
to show all rows, up to `COMPOSER_MAX_ROWS` (8) lines. The user reports this
does not happen: text appears to run without wrapping.

The wrap infrastructure exists in `src/view.coil`:
- `composer-columns` computes how many monospaced characters fit in the current
  pane width.
- `composer-row-end` finds the byte offset where each row ends (hard-break on
  `\n`, soft-break at the last space before the column limit).
- `composer-rows` counts rows.
- `composer-height` returns `34.0 + LINE_H * rows`, which is used by
  `draw-composer!` and also by `clip-push!` / the convo-area layout to shrink
  the scroll region as the composer grows.

If wrapping is not working, likely candidates are:

1. `composer-columns` returns a value so large that soft-break never triggers
   (e.g. if `w` passed to it is 0.0 or the full window width rather than the
   conversation pane width).
2. The height change from `composer-height` is not causing a redraw, so the
   newly computed rows are never painted.
3. `composer-row-end` has an off-by-one that makes it always return `n`
   (past-the-end), collapsing everything into one row.

Related: inserting a hard newline requires `⇧⏎` rather than `⏎` (which sends).
This is shown in the hint text (`"⏎ send · ⇧⏎ newline"`, `src/view.coil:955`)
but is easy to miss. If soft-wrap is broken, users are more likely to reach for
`⇧⏎` and discover it only by accident. Fixing soft-wrap is the priority;
confirm the hint is visible at typical window widths as a follow-up.

To reproduce: open the conversation pane, type a message longer than the pane
width without pressing any key except letter/space, and observe whether the
strip grows and text reflows onto a second line.
