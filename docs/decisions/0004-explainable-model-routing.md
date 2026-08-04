# 0004: Model routing is explicit, explainable, and durable

## Status

Accepted.

## Context

The harness required every caller to know provider names and choose a model. The
project charter also requires opinionated selection by capabilities, cost, and task
needs, while preserving caller pinning and making every decision observable.

Inferring a provider from a model-name prefix would be brittle and unexplained.
Rerunning policy during recovery could also change a durable run after configuration
or catalog updates.

## Decision

`ModelProvider` exposes a provider-neutral capability record: streaming, harness-native
tools, parallel tools, reasoning, subscription authentication, and a relative cost
tier. Relative cost is a policy ordering, not a billing estimate.

Create commands either pin both `provider` and `model`, or request automatic selection
with `provider: "auto"`, `model: "auto"`, and a named `routing_profile`. The first
profiles are `balanced`, `low-cost`, `quality`, `subscription`, and `external-agent`.
Boolean `requires_harness_tools` and `requires_subscription` constraints are enforced
against the selected capabilities.

Routing mutates the accepted command before `run.created` is appended. The durable
payload records the original request, selected provider/model, profile, explanation,
and capability snapshot. Recovery consumes that resolved command and does not invoke
the router again.

Explicit custom provider pins remain supported. Constraints on a custom provider are
rejected until that provider's capabilities are registered; automatic policy never
selects an unknown provider.

## Consequences

Callers retain deterministic pinning, while higher-level clients can choose a stable,
inspectable policy. Routing decisions survive restart unchanged and can be rendered by
UIs or evaluated by supervisors. Availability, measured performance, quotas, and live
pricing are not yet route inputs; adding them must preserve the durable explanation
and must not turn recovery into a fresh selection.
