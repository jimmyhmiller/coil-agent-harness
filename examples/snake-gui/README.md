# Coil Snake (native GUI)

Snake, with the whole game living in Coil and a small SDL2 file doing nothing but
windows, keys, and pixels.

**The board wraps on all four edges.** Running off the left edge brings the head
back on the right, off the right edge brings it back on the left, off the top
brings it back at the bottom, and off the bottom brings it back at the top. No
edge ends the game. Running into the snake's own body still does.

## Layout

| File | Role |
| --- | --- |
| `src/engine.coil` | **The authoritative engine.** Board size, movement, steering, wraparound, self-collision, eating, scoring, restart. No I/O. |
| `src/main.coil` | The playable loop: reads input codes, ticks the engine, asks the shim to draw what the engine reports. |
| `native/snake_window.c` | Presentation shim: SDL window, keyboard, clock, rectangles. Holds no board, no snake, and no rules. |
| `tests/engine_test.coil` | Behavioral tests against the engine, run headlessly. |

The split is the point: because no rule lives in C, every rule is testable
without a display.

## Rules

- The snake advances one cell per 120 ms tick in its current direction.
- **Wraparound.** The new head position is folded onto the board with
  `wrap-index`, so `x = -1` becomes `x = 29`, `x = 30` becomes `x = 0`,
  `y = -1` becomes `y = 21`, and `y = 22` becomes `y = 0`. Crossing an edge is an
  ordinary move: score, length, and direction are unchanged, and the game
  continues.
- **Self-collision is terminal.** If the new head lands on a live body segment
  the game is over — including when it got there by wrapping across an edge. The
  tail cell is exempt while the snake is not growing, because that same step
  vacates it.
- Eating the food grows the snake by one, scores a point, and respawns food on a
  uniformly chosen free cell.
- Arrows or `WASD` steer; a reversal straight back onto the neck is ignored.
  `Space`/`Enter` restarts after a game over, `Esc` quits.
- The board is 30 × 22 cells; the snake starts three long in the middle heading
  right.

## Build, test, run

    coil check     # typecheck the project and compile the native shim
    coil test      # run the engine test suite (no window needed)
    coil build     # writes builds/snake
    coil run       # build and play

Requires SDL2 (`brew install sdl2`); `Coil.toml` points at the Homebrew include
and library directories.

## Tests

`coil test` runs `tests/engine_test.coil` in-process-per-test with no window:

| Test | What it pins down |
| --- | --- |
| `wrap-left` | Head at `x = 0` moving left reappears at `x = 29`, same row, alive, same length and score. |
| `wrap-right` | Head at `x = 29` moving right reappears at `x = 0`, same row, alive. |
| `wrap-up` | Head at `y = 0` moving up reappears at `y = 21`, same column, alive. |
| `wrap-down` | Head at `y = 21` moving down reappears at `y = 0`, same column, alive. |
| `wrap-index-folds-both-ways` | The fold itself, on both edges of both axes. |
| `wrap-keeps-the-body-following` | The body trails the head correctly across an edge. |
| `wrapping-lap-returns-to-the-start` | A full 30-step lap comes home, still alive. |
| `wrap-eats-food-on-the-far-edge` | Wrapping onto food scores and grows. |
| `self-collision-ends-the-game` | Turning into a body segment is still terminal. |
| `self-collision-across-an-edge-ends-the-game` | Wrapping into your own body is terminal too. |
| `a-finished-game-does-not-move` | A finished game ignores further ticks. |
| `following-the-tail-is-allowed` | Entering the tail cell being vacated is legal. |
| `reset-starts-a-fresh-game` | Fresh length, score, position, and food off the snake. |
| `restart-after-game-over` | Restart clears the game-over state and moves again. |
| `eating-grows-and-scores` | Food grows the snake, scores, and respawns. |
| `steering-cannot-reverse-onto-the-neck` | Reversal is ignored; a legal turn is queued. |

Run one edge on its own with, for example:

    coil test tests/engine_test.coil --filter wrap-left

## Known issue

Project-wide `coil lint` currently fails with
`comptime: code-field-* expects a type symbol or instantiation (Gen …)`. This is
a compiler-side limitation, not a problem with this example: any project whose
struct has a fixed `(array T N)` field reproduces it, and `Game` stores its
segments in an `(array Cell 660)`. Per-file linting (`coil lint src/engine.coil`)
is clean, as are `coil check`, `coil test`, and `coil build`.
