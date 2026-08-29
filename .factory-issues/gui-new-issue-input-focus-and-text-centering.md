---
project: gui
---

# New-issue input: focus ring is visually broken and text is not centred

## Current behaviour

The centred "new issue" prompt is drawn by `draw-new!` in `src/view.coil`.

**Focus styling** – when the composer is active (`active = (.composer-lit app) > 0.0`) the only visual change is a faint amber wash painted as a filled rectangle inside the input box:

```
(fill! cv left input-top box-w input-height (mix (amber-wash) (ground) 0.0))
```

There is no ring, outline, or border around the box. The wash is very subtle and reads poorly against most backgrounds.

**Text alignment** – the placeholder text and every row of typed text are anchored at `(+ left 20.0)`:

```
(text-elided! cv (field cv f13) (+ left 20.0) input-top ...)   ; placeholder
(text-at!     cv (field cv f13) (+ left 20.0) (+ y 15.0) ...)  ; typed rows
```

`left` is already the left edge of the 620 px centred box, so text is left-aligned inside it rather than centred.

## What it should be

- The focused state should draw a clearly visible outline/ring around the input box (e.g. a 1–2 px amber border drawn with `hline!`/`vline!` calls framing the box) so the active element is unambiguous.
- The placeholder and typed text should be horizontally centred within the 620 px box rather than left-justified inside it.

## Location

`src/view.coil`, function `draw-new!` (~line 1089). The hit-test companion `new-input-hit` (line 1379) uses the same geometry and will need matching updates if the box dimensions change.
