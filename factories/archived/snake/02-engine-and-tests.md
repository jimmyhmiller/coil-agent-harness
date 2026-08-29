# Worker: Snake engine and behavioral tests

Create the Coil project, headless `snake.engine` module, and its complete behavioral
test suite together as one feedback loop. Model the body, direction and queued
direction, food, growth, score, self-collision game over, and restart in Coil.

The board is 32 by 24 cells. Crossing every edge wraps to the opposite edge and never
sets game over. Add explicitly named tests for movement, forbidden reverse direction,
growth, wrap-left, wrap-right, wrap-up, wrap-down, self collision, game-over stability,
and restart. Each wrap test must assert the destination coordinate and active state.

Create only the smallest temporary native entry needed for `coil check`/`coil build`;
the next worker owns the finished GUI. Report ready only after completing and validating
this assignment.
