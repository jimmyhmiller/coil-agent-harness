# Worker: Real-time game integrator

Connect the passing Coil Snake engine to the existing native window. The event loop
must advance the engine continuously on a timer, accept immediate WASD and arrow-key
input, draw every active body segment and food, display the numeric score, show a clear
game-over message, restart on Space or Enter, and exit on Escape or window close.

Keep all rules and state transitions in Coil. The selected native API supplies only
windowing, drawing, timing, and key state. Compile after each integration slice and
exercise the actual executable; do not infer GUI behavior from source inspection.

Finish only when the complete game is playable in a real native window and the engine
tests still pass. Add concise build, test, launch, and control instructions.
