# Roadmap audit

## Implemented

- Native Claude subscription OAuth, refresh, durable credential storage, and native
  Anthropic tool continuations.
- Capability-aware service principals and authenticated observe/control boundaries.
- Single-writer durable journals, restart projection, cancellation, deadlines, and
  bounded background scheduling.
- Production filesystem read/write/create/remove tools with rooted paths, effect
  metadata, cancellation, and deadlines.
- Explainable capability-based model routing with the selected policy persisted in
  each create command.
- Durable agent identities, typed delegation, and parent/child relationships.
- Version 1 workflow DAG admission, dependency scheduling, lifecycle events, and
  workflow graph projection.
- Durable supervisor assessments and cancellation interventions over the public event
  model.

## Remaining product boundary

Codex App Server can initiate approval RPCs while a turn is running. The harness has
no permission model, so there is nothing to answer them with: the adapter runs with
`approvalPolicy: "never"` and declines unexpected server requests rather than letting
the provider define its own policy. If a permission plugin is ever added, translating
those RPCs into it is the work.

## Next operational work

Future work should be driven by measured production needs: journal indexing and
compaction, multi-tenant storage isolation, metrics and tracing sinks, retry policy,
workflow budgets, and sandbox hardening. None requires a second model/tool execution
loop.
