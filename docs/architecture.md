# Core architecture

The core dependency direction is intentionally narrow:

```text
CLI / future server / future UIs
              |
        runtime/agent_runner
         /              \
provider capability   tool executor
         \              /
 model + tool + event contracts
              |
        JSON / hosted Coil libraries
```

The runtime does not know URLs, headers, provider response shapes, or Codex
protocol method names. Providers do not execute harness tools. Tool implementations
do not choose policy. Monitoring observes semantic events and is not coupled to
terminal output.

Every provider advertises streaming, native-tool, parallel-tool, reasoning,
subscription-authentication, and relative-cost capabilities through the model
boundary. Create commands may pin provider/model or select a named routing profile.
Routing happens before `run.created`; its requirements, selection, explanation, and
capability snapshot are persisted in the command payload. Recovery therefore executes
the original durable choice even if policy changes later.

Every event names an `agent_id`. A root agent uses its run ID; delegated children use
their child run ID. Delegation is represented as a normal durable child create command
with a validated `parent_run_id`, a server-owned parent identity, and a versioned typed
message whose content becomes the child prompt. The service emits `agent.delegated`
and `agent.created`, then schedules the child through the existing run controller.
Children therefore inherit ordinary capacity limits, tool policy, cancellation,
queries, journaling, and crash recovery.

Version 1 workflows compose those same durable runs into incrementally admitted DAGs.
Each node names already-created predecessors in the same workflow, which makes cycle
prevention an admission invariant. The scheduler starts a node only after every
predecessor succeeds and terminalizes downstream nodes whose dependencies fail or are
cancelled. Workflow queries are journal projections, not a separate source of truth.

Supervisors consume that same public journal. Assessments append structured semantic
events; cancellation interventions are durable, idempotent commands that pass through
the existing run controller and cancellation lifecycle. This keeps observation,
judgment, and action auditable without granting a supervisor a hidden execution path.

## Model turns and continuations

`ModelRequest` is stable across providers. After a model returns tool calls, the
runner executes one bounded batch and writes a `ModelContinuation` for the next
turn. The continuation carries:

- a provider response identifier where one exists;
- opaque previous output, which the runtime never rewrites;
- all tool results from the batch.

Keeping prior output opaque is essential. DeepSeek's OpenAI-compatible endpoint
requires the prior `reasoning_content` to be replayed, while its Anthropic endpoint
uses signed thinking blocks. Projecting either into a lowest-common-denominator
chat message would silently corrupt a valid continuation.

Forced or required tool choice applies to the first model turn. After a tool
batch, the runner switches to automatic selection so the model can consume the
results and finish instead of being forced into an infinite tool loop.

## Tool execution

Each tool contains a serializable specification and a `dyn ToolImplementation`.
Execution follows this order:

1. emit `tool.call.proposed`;
2. resolve the tool name;
3. validate arguments against the common JSON Schema subset;
4. emit `tool.call.rejected` when the name or the arguments do not resolve;
5. run the remaining calls in bounded waves of worker threads;
6. place results in original call order while emitting completion events in
   actual completion order.

There is no permission step. Registering a tool is what grants it, so a schema-valid
call to a registered tool always executes. A policy layer, if one is ever wanted,
belongs outside this loop and outside the runtime contract.

No provider adapter owns this loop. Adding another provider means implementing the
`ModelProvider` trait, not copying orchestration logic. Runtime selection erases the
concrete adapter behind a `dyn ModelProvider` object.

## Observability

Every event has a schema version, atomic sequence number, timestamp, run and
operation identifiers, provider/model identity, semantic kind, and JSON payload.
Sinks implement the `EventSink` trait and must be thread-safe. The CLI demonstrates a
JSONL sink; a persistent journal, websocket fan-out, metrics projection, or meta
agent can subscribe through the same contract.

Credentials are resolved only inside provider adapters. Request-start events do
not contain headers or API keys. Raw provider payloads are retained in model
responses for correct continuation, but are not emitted automatically.

The journal takes no locks across processes. It is opened `O_APPEND`, and each
record is written by a single `write`, so the kernel places whole records at the end
of the file and two writers cannot interleave one record inside another. A crashed
process leaves nothing to release and a replacement recovers immediately.

What that buys is record integrity, not a total order. Sequence numbers are assigned
from an in-memory counter seeded at recovery, so two harness processes writing one
journal concurrently will assign the same sequence to different events. Recovery
reads the file in file order and is unharmed, but any consumer treating `sequence`
as unique across the file would be wrong to. Making that correct means deriving the
sequence from the file rather than from process memory — which is a correctness fix,
not a lock, and is the shape any future work here should take. Running two harnesses
on one journal is not a supported configuration in the meantime.

Foreground and background entry points call the same runner. A background handle
owns only thread/job state and exposes completion polling plus an idempotent join;
it does not fork orchestration behavior.

## Hosted system boundary

COIL owns orchestration, data modeling, HTTP, time, process environment access,
current-directory lookup, fd I/O, sleep, readiness polling, and bidirectional Codex
App Server pipes. The harness uses Coil's supported hosted libraries directly and
contains no application-owned native shim.

## Ownership and presentation boundaries

Storage lifetime is part of the architecture, not an allocator parameter chosen by
each helper. Process, service, run, turn, tool-call, TUI-session, and TUI-cycle data
live in explicitly owned Coil regions. Background runs use the synchronized
`AllocationDomain` region owner. Data moves from a child lifetime to an ancestor only
through an explicit promotion/copy boundary; a pointer or slice derived from a stack
temporary never crosses a function or thread boundary. The complete rules are in
`docs/decisions/0008-lifetime-owned-arenas.md`.

Terminal presentation follows one pipeline: semantic state produces a declarative
layout tree, the pure layout engine resolves it into a frame and semantic anchors,
the renderer plans a frame transition, and the terminal driver executes typed
operations. Input, conversation blocks, and service responses do not own
separate formatting/cursor protocols. Application code does not emit presentation
bytes. See `docs/decisions/0009-declarative-terminal-layout.md`.

## Deliberate next boundaries

The Codex App Server can initiate approval RPCs while a turn is running. The harness
has no permission model to answer them with, so the adapter runs with
`approvalPolicy: "never"` and declines unexpected server requests rather than letting
a provider define its own policy.
