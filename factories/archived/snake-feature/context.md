# Feature request

Crossing the left, right, top, or bottom board edge wraps the snake head to the
opposite edge and does not end the game. Self-collision remains terminal. Add
explicit `wrap-left`, `wrap-right`, `wrap-up`, and `wrap-down` engine tests,
update the README, and leave `coil check`, `coil test`, and a clean build passing.
