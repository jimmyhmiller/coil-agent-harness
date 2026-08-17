# Wrap Snake at the board edges

Change wall behavior so crossing any board edge wraps the snake head to the opposite
edge. Crossing a wall must no longer set game-over. Self-collision must still end the
round, and restart behavior must remain intact. Update the engine tests and README to
describe wraparound play.

Acceptance behavior:

- Moving left from x=0 enters x=29.
- Moving right from x=29 enters x=0.
- Moving up from y=0 enters y=19.
- Moving down from y=19 enters y=0.
- None of those transitions sets game-over.
- Self-collision still sets game-over.

```factory-gates
rg -q 'deftest.*wrap-left' tests/engine_test.coil
rg -q 'deftest.*wrap-right' tests/engine_test.coil
rg -q 'deftest.*wrap-up' tests/engine_test.coil
rg -q 'deftest.*wrap-down' tests/engine_test.coil
rg -qi 'wrap' README.md
coil check
coil test
coil build -o {gate_dir}/coil-snake
test ! -e coil-snake && test ! -e coil-snake.o
```
