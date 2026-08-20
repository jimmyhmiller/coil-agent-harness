---
project: gui
---

# Composer text does not wrap automatically as you type

Typing a long message into the composer strip produces a single line that runs off the edge rather than wrapping to additional rows.

**Current behaviour:** The user reports that text does not wrap. The wrapping logic exists — `composer-columns`, `composer-row-end`, and `composer-rows` in `src/view.coil` (lines 582–630) compute soft-wrap break points by character-cell count, and `draw-composer!` (lines 636–696) iterates over rows using those functions. However the user observes no wrapping in practice, suggesting either the column count is computed incorrectly (e.g. `composer-columns` divides the available room by `.adv` of the monospace face but the face's advance might not be initialised at the point it is first called), or the strip height is not being recomputed and the conversation above is not moved up, so the wrapped rows are drawn behind the conversation and clipped.

**What it should do:** As the user types past the end of a row the text should soft-wrap to a new line and the strip should grow upward, pushing the conversation scroll region up to make room, up to `COMPOSER_MAX_ROWS` (currently 8) rows. Shift-Return should also insert a hard newline and move to the next row.

**Relevant code:**
- `src/view.coil` lines 582–634 — `composer-columns`, `composer-row-end`, `composer-rows`, `composer-height`
- `src/view.coil` lines 636–696 — `draw-composer!`, row-drawing loop
- `src/view.coil` ~line 723 and 764 — places that call `composer-height` to position the conversation area; if these use a stale or zero width the height will always be one row
