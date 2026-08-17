# Native GUI notes

Build a genuine native continuous event loop, never a browser, terminal renderer, or
turn-by-turn input loop. Keep game rules in the headless Coil engine; native APIs own
only windows, drawing, timing, and immediate input.

The installed raylib package is a known-good available option, not a requirement:

```toml
[native-dependencies]
raylib = { pkg-config = "raylib" }
```

```lisp
(cimport "/opt/homebrew/include/raylib.h"
  :use [InitWindow CloseWindow WindowShouldClose SetTargetFPS
        BeginDrawing EndDrawing ClearBackground DrawRectangle DrawText Color
        IsKeyPressed GetFrameTime TextFormat])
```

Coil float arithmetic uses `coil.primitive`, including `primitive/fadd`,
`primitive/fsub`, and `primitive/fcmp-ge`. Discover additional symbols with one narrow
search. Build a minimal window first, then add the continuous update, input, and draw
loop. Never leave an artificial frame limit in the release loop.
