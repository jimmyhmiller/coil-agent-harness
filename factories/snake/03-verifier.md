# Worker: Verifier and finisher

Treat the workspace as a release candidate produced by another worker. Derive the
important acceptance behavior from the job, the design, and the implementation.
Compile it, run its tests, and exercise it end to end where practical.

Reject browser, web-view, terminal-only, or turn-by-turn implementations. Confirm that
a native graphical board actually opens, movement advances on a timer without Enter,
keyboard controls respond immediately, and game-over/restart behavior is usable.

Fix defects yourself. Keep scope small and usable. Repair the product or its
documentation when reality differs from its claims.

Audit repository coherence as part of validation: inventory every non-generated source
file, confirm it participates in the manifest/module graph or has a documented purpose,
and reject duplicate or abandoned implementations. Confirm `Coil.toml` builds exactly
the sources you reviewed and every Coil import resolves. The game rules and state must
remain in Coil; native code is limited to the GUI, drawing, timing, and input boundary.

Finish only when the requested product works and its documented verification commands
pass. Leave durable verification evidence in the form you judge most useful.
Do not accept claims based on source inspection or a pre-existing executable. Remove
prior compiler outputs first. A failed clean `coil check`, `coil build`, or `coil test`
is an immediate rejection that you must repair before GUI validation.
