# Software factory efficiency audit

## Conclusion

The Snake factory reached a correct artifact, but it was drastically less efficient
than a normal focused coding-agent workflow. The product contains roughly 340 lines of
Coil across the engine, GUI, and tests, yet the complete effort used 87 completed model
turns, 109 tool completions, about 20 minutes of agent-run wall time, and 1.54 million
cumulative input tokens.

Normal conversation replay and prompt caching are not the problem. A tool-using model
must see the preceding tool calls and results. The problem is that the factory put too
much low-value material into that history, allowed it to grow for too many turns, and
split a small implementation into too many serial workers.

## Measured evidence

| Stage | Completed turns | Tools | Run time | Input tokens | Cached input |
|---|---:|---:|---:|---:|---:|
| Builder | 8 | 10 | 60.5 s | 60,576 | 8,704 |
| Engine | 14 | 15 | 281.7 s | 165,501 | 34,304 |
| Engine tests, including retries | 33 | 41 | 449.7 s | 349,725 | 101,376 |
| GUI integrator | 25 | 28 | 320.7 s | 895,630 | 368,128 |
| Cleanup | 6 | 14 | 80.6 s | 64,398 | 7,680 |
| Verifier | 1 | 1 | 6.7 s | 3,089 | 2,560 |

The GUI integrator alone consumed 58% of all reported input tokens. Its request body
grew beyond 225 KB as it accumulated repeated searches, file replacements, compiler
feedback, and tool schemas.

Each worker began with approximately 9.5–10.5 KB of factory prompt before tool schemas
or workspace content. Across the measured runs, workers made 66 Bash calls, 23 whole-
file writes, and 16 file reads. Bash results contributed about 265 KB of unique JSON
payload, including one result of roughly 27 KB. Whole-file write arguments contributed
about 70 KB of unique payload. Conversation replay then caused those unique bytes to
be counted again on subsequent turns.

## Problems

### P0: no patch/edit tool

`write_text_file` can only create or replace a file. A one-line correction therefore
sends the complete file as tool arguments. The provider must retain that function call
in later history so its corresponding result remains intelligible.

This is not how an efficient coding agent should make routine edits. The harness needs
an `apply_patch`-style tool with contextual hunks, explicit failure on stale context,
and a bounded result. Whole-file replacement should remain available for genuinely new
or very small files.

### P0: unbounded low-value discovery enters durable model history

Workers ran broad `coil guide`, `rg`, `sed`, and namespace searches. A Bash result can
contain thousands of lines or tens of kilobytes, all of which then remains in the
conversation. The instructions asked workers not to repeat discovery, but the tool
layer did not enforce narrow output or detect repeated searches.

The harness needs:

- strict default output limits with an explicit continuation mechanism;
- a focused Coil documentation tool keyed by topic or symbol;
- duplicate-command detection;
- warnings when a read/search has no workspace-changing follow-up;
- result digests that retain the command, exit status, relevant excerpts, and a path to
  full logs without putting the full log into model context.

### P0: too many serial roles for a small coherent product

The factory used separate builder, engine, test, integrator, cleanup, and verifier
workers. Every boundary paid a fresh base-prompt and tool-schema cost, and later workers
had to rediscover the workspace. Engine implementation and engine tests are one tight
feedback loop and should have been assigned to one worker. GUI integration and final
verification could reasonably be a second worker.

Worker decomposition should be based on independent ownership or parallelism, not on a
fixed ceremony. For this product, two implementation workers plus one cheap verifier
would have been enough.

### P0: workers do not receive the executable gate contract up front

The test worker was told the behavior in prose, but it did not receive the exact gate
commands that would judge it. It declared completion with only a movement test, after
which the supervisor discovered the missing growth test.

Every worker prompt should include its exact gates. The worker should run those same
commands before returning. The supervisor should still rerun them independently, but
gate failure should be exceptional rather than the ordinary feedback mechanism.

### P1: oversized static factory context

Every worker received a long Coil cheatsheet containing syntax, arrays, FFI examples,
native-library examples, testing instructions, and product invariants. Most workers
needed only a fraction of it. Static instructions are cacheable, but they still consume
context and attention.

Keep a short universal Coil preamble. Put detailed material behind focused retrieval or
attach only the sections relevant to the worker. Builder/GUI workers need native FFI;
engine/test workers do not.

### P1: inappropriate reasoning level

Every worker ran Luna with `max` reasoning. Routine file creation, test addition, and
cleanup do not need maximum reasoning. The run emitted 26,796 reasoning tokens and also
spent many turns investigating elementary syntax.

Default routine workers to Luna medium or high. Escalate reasoning only after concrete
compiler/test failures that the ordinary loop cannot resolve.

### P1: context grows without a progress-based reset

Correct client-managed history is append-only within a tool conversation, but one
worker does not need to remain in the same conversation indefinitely. The integrator
continued for 25 completed turns while its history grew past 50K input tokens per turn.

When context becomes dominated by old tool traffic, start a fresh corrective worker
with the same workspace, assignment, current failing command, and a compact factual
handoff. This is not lossy truncation inside an active tool-call chain; it is an explicit
new run at a safe boundary.

Trigger this from progress signals, not a fixed model-turn budget: context size,
repeated commands, repeated compiler errors, time since workspace change, and ratio of
tool-result bytes to source changes.

### P1: validation is too lexical

Several gates use `rg` to prove that names or strings exist. This permitted placeholder
or shallow implementations to get close to acceptance. Behavioral tests should be the
primary contract. GUI gates need a launch/smoke harness that verifies the window stays
alive for multiple frames and the update loop is not artificially bounded.

### P1: redundant builds and tests

Workers repeatedly ran `coil check`, `coil build`, and `coil test`, and the supervisor
then ran them again. Independent verification is valuable, but repeated unchanged
commands are not.

Record the workspace fingerprint with each successful command. The supervisor can
reuse a result only when the command, environment, toolchain, and fingerprint match;
otherwise rerun it. A final clean build and full test must always remain mandatory.

### P2: tool surface is larger than most workers need

Every request carried schemas for ordinary file/Bash tools plus orchestration tools such
as subagent spawning, workflows, asynchronous tools, and notifications. Snake workers
did not need most of that surface. Tool schemas are part of the repeated prompt prefix
and also increase model decision complexity.

Assign tools per worker role. A simple implementation worker needs read, patch, focused
search, and command execution. Orchestration tools belong only to coordinator workers.

### P2: full-file and full-log events are useful for auditing but not for inference

The durable journal should retain complete evidence. The model context does not need
the same representation. Storage/audit payloads and inference payloads should be
separate: preserve full arguments and outputs in the journal, while feeding the model a
bounded semantic projection with a retrievable artifact reference.

### P2: statistics did not distinguish unique from replayed tokens

The headline 1.54 million input tokens is cumulative provider usage, not unique text.
About 523K input tokens were reported as cached. The current report can make an
efficient cached conversation look as though every byte was newly processed.

Report at least:

- total input tokens;
- cached input tokens;
- uncached input tokens;
- unique tool-result bytes introduced;
- request-context high-water mark;
- output and reasoning tokens;
- source lines changed and accepted tests added.

## Recommended minimal factory

For a product of this size:

1. One engine-and-tests worker receives the exact behavioral gates and implements until
   they pass.
2. One native-GUI worker integrates the tested engine and receives exact build, launch,
   and interaction gates.
3. One low-reasoning verifier runs a clean inventory, build, test, and launch check;
   defects automatically return to the owning stage.

Use Luna medium/high initially, a patch tool for edits, focused Coil documentation, and
bounded tool projections. Escalate to a fresh high/max corrective run only when measured
progress stalls.

An appropriate target for this Snake implementation is approximately 10–20 completed
model turns, not 87. That target is an operational expectation, not a hard turn budget:
the factory continues while it is making measurable progress and retries within its
configured stage-attempt or wall-clock policy.

## Implementation order

1. Add `apply_patch` and prefer it for existing files.
2. Put exact gates in every worker prompt and keep automatic corrective retries.
3. Bound/project Bash and documentation results before adding them to model history.
4. Collapse the default Snake workflow to engine+tests, GUI, verifier.
5. Select tools and reference context per worker.
6. Add progress/context telemetry and safe fresh-run handoffs.
7. Add fingerprinted validation reuse and richer efficiency statistics.
