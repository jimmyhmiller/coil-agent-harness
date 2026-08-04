# ADR 0006: Workflow nodes are durable runs

## Status

Accepted.

## Decision

A workflow is an incrementally admitted, versioned directed acyclic graph whose nodes
are ordinary durable runs. A create command joins a workflow by supplying
`workflow_id`, `workflow_version: 1`, a non-empty `node_id`, and a `depends_on` array
of run IDs.

Dependencies must already exist in the same workflow. This topological admission rule
rejects forward references, cross-workflow edges, self-edges, and cycles without a
second graph store. An empty dependency array creates a root node. Multiple
dependencies form an AND-join.

The runtime leaves a node queued until every predecessor succeeds. A failed or
cancelled predecessor causes `workflow.node.skipped` followed by terminal
`run.failed`; the provider is not invoked. A ready node emits `workflow.node.ready`
and enters the existing run scheduler, so capacity limits, cancellation, tools,
provider routing, and recovery remain unchanged.

`workflow.node.created`, `workflow.node.ready`, and `workflow.node.skipped` expose the
graph lifecycle in the journal. `GET /v1/workflows/{workflow_id}` projects node
definitions and current durable run status from those immutable records.

## Consequences

Workflow creation is incremental rather than an atomic whole-graph transaction.
Callers submit nodes in topological order and can safely retry each create command by
command ID. Independent roots and branches can run concurrently within ordinary
runtime capacity; a queued join preserves admission order until its dependencies are
terminal.

Nodes do not introduce a second execution mechanism or status model. Future workflow
features such as retries, conditional edges, aggregate budgets, and supervisor
interventions must extend the event contract while retaining durable runs as the unit
of execution.
