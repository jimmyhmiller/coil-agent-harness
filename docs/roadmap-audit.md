# Roadmap audit

## Implemented

- Native Claude subscription OAuth, refresh, durable credential storage, and native
  Anthropic tool continuations.
- Capability-aware service principals and authenticated observe/control boundaries.
- Single-writer durable journals, restart projection, cancellation, deadlines, and
  bounded background scheduling.
- Production filesystem read/write/create/remove tools with rooted paths, effect
  metadata, authorization, cancellation, and deadlines.
- Explainable capability-based model routing with the selected policy persisted in
  each create command.
- Durable agent identities, typed delegation, and parent/child relationships.
- Version 1 workflow DAG admission, dependency scheduling, lifecycle events, and
  workflow graph projection.
- Durable supervisor assessments and cancellation interventions over the public event
  model.

## Remaining product boundary

Codex App Server can initiate approval RPCs while a turn is running. The current
`ModelProvider.execute-model` contract receives a model request and event emitter but
not a tool-authorizer or generic approval capability. The Codex adapter therefore
runs with `approvalPolicy: "never"` and rejects unexpected server requests rather than
silently granting authority.

A correct implementation must extend the provider/runtime boundary with a scoped,
cancellable approval capability; translate Codex command/file-change approval params
into versioned authorization events; wait through the existing durable mailbox; and
return the protocol-specific accept/decline result. It must also preserve CLI
fail-closed behavior when no interactive service is present. This is intentionally a
separate product slice because automatic approval or provider-owned policy would
violate the harness authorization model.

## Next operational work

Future work should be driven by measured production needs: journal indexing and
compaction, multi-tenant storage isolation, metrics and tracing sinks, retry policy,
workflow budgets, and sandbox hardening. None requires a second model/tool execution
loop.
