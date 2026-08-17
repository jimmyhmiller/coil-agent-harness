# Product invariants: Coil Snake

These are release requirements, not suggestions.

- The game rules and state transitions belong in Coil. Native code may provide only
  the graphical window, drawing, timing, and immediate input boundary.
- The headless engine is a non-entry Coil module with no native imports or `main`. The
  GUI entry imports it, and tests import the engine directly; tests never import or
  launch the GUI application entry.
- There is exactly one authoritative implementation of each concern. Staging copies,
  abandoned rewrites, and duplicate source trees are release failures.
- Every source file is either referenced by `Coil.toml`, imported by the Coil module
  graph, used by a documented test, or deliberately documented as a standalone asset.
  Otherwise remove it before release.
- `Coil.toml` must build the same implementation that workers reviewed and tested.
- Every Coil import resolves. Remove prior compiler outputs before the release build;
  the current entry module must compile from that clean state and launch the native
  application. A binary left by an earlier source revision is not evidence.
- Browsers, HTML, web views, terminal rendering, line input, and turn-by-turn movement
  are prohibited.
- Before declaring success, inventory the non-generated files, explain each one's
  purpose, run a clean build and tests, launch the application, and record concise
  verification evidence.
