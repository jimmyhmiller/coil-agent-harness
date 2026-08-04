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
protocol method names. Providers do not authorize or execute harness tools. Tool
implementations do not choose policy. Monitoring observes semantic events and is
not coupled to terminal output.

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
4. ask the independent authorizer;
5. emit authorization or rejection;
6. run authorized calls in bounded waves of worker threads;
7. place results in original call order while emitting completion events in
   actual completion order.

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

Each durable journal has exactly one live writer process. `event-journal-open`
acquires a non-blocking kernel file lease and retains it for the journal lifetime.
A competing harness fails before recovery, scheduling, or listening, preventing
duplicate restart decisions, event sequence collisions, and repeated side effects.
The lease is released by close or process exit, so a replacement process can recover
the durable queue after a crash.

Foreground and background entry points call the same runner. A background handle
owns only thread/job state and exposes completion polling plus an idempotent join;
it does not fork orchestration behavior.

## Hosted system boundary

COIL owns orchestration, data modeling, HTTP, time, process environment access,
current-directory lookup, fd I/O, sleep, readiness polling, and bidirectional Codex
App Server pipes. The harness uses Coil's supported hosted libraries directly and
contains no application-owned native shim.

## Deliberate next boundaries

- Approval round-trips for interactive Codex App Server requests.
- Additional production tools and sandboxed execution capabilities.
- Versioned workflow graphs and composable node transitions.
- Supervisor assessments and interventions over the public event model.

These extend current contracts; they must not introduce alternate model/tool
loops or UI-specific behavior into the core.
