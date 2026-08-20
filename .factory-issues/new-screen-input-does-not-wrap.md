---
project: gui
---

# Initial prompt box elides long input instead of wrapping it

## Current behaviour

On the "new" screen — the centred single-prompt view shown before any conversation exists — the text the user has typed is rendered by `text-elided!` in `draw-new!` (`src/view.coil`, around line 942):

```
(text-elided! cv
              (field cv f13)
              (+ left 20.0)
              (+ top 50.0)
              24.0
              (- box-w 40.0)   ; 580 px hard limit
              …
              text)
```

`text-elided!` (`src/draw.coil`, line 344) renders a single row and appends `…` when the text exceeds the pixel budget. Once the prompt fills the box width the user can no longer see what they are typing; everything beyond the clip point is invisible.

## What it should do instead

The input should wrap onto additional rows exactly as it does in the bottom-of-pane composer that appears after the first send. That composer uses `composer-rows`, `composer-row-end`, and `composer-height` to break the text at word boundaries, expand the strip upward row by row (up to `COMPOSER_MAX_ROWS`), and place the cursor after the last character. The new-screen box should use the same approach, expanding downward (or upward) from the baseline line rather than clipping.

The fix is in `draw-new!`: replace the single `text-elided!` call for the live input text with the multi-row loop already present in `draw-composer!`, sized to the 620 px centred box (`box-w`). The placeholder text (shown when the input is empty) can stay as a single elided/row call since it is short and fixed.
