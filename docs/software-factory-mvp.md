# Software factory MVP

The first product milestone is a headless service that can dispatch one real unit of
agent work to a worker process that is not the service process. The worker may run on
the same machine for the first end-to-end test; the protocol must use the HTTP service
boundary so the same worker can later run on another machine without changing the
execution model.

## Acceptance test

The MVP is complete when an automated end-to-end test can:

1. start one harness server with a durable journal;
2. start two independent worker processes;
3. submit a run through the versioned HTTP API;
4. observe the run being claimed by exactly one worker;
5. observe model and tool progress through the ordinary run event API;
6. inspect the terminal result from a client other than the worker;
7. stop a worker while it owns work and produce an explicit, inspectable recovery
   outcome rather than silently losing or blindly repeating the operation; and
8. restart the server and recover the terminal run history.

The first worker implementation may support only the tools and providers already in
the harness. A single server and a filesystem journal are acceptable for the MVP.
Distributed control-plane storage and multiple server replicas are later milestones.

## Narrow protocol

Workers make outbound authenticated requests to the control plane. The initial
protocol needs only these operations:

- register a worker and advertise a small capability document;
- claim the next compatible assignment with a bounded lease;
- renew the current lease;
- append progress for the leased operation;
- complete or fail the leased operation.

Every mutating request carries an idempotency key. An assignment names its run,
operation, attempt, required capabilities, and opaque execution payload. A completion
is accepted only from the current lease holder.

For the first implementation, claim may use bounded polling. WebSockets, a broker,
push scheduling, and distributed consensus are explicitly out of scope.

## Correctness rules needed now

- A logical agent or run is not identified with a thread or process.
- A worker must claim an assignment before executing it.
- At most one unexpired lease is authoritative for an assignment.
- Lease expiry means the outcome is uncertain; it does not prove an external effect
  did not happen.
- Read-only or explicitly idempotent work may be reassigned according to recorded
  policy. Other work becomes `recovery_required` in the MVP.
- Worker progress uses the existing structured event stream. There is no second log.
- Large artifacts are referenced rather than embedded, but the first implementation
  may use local paths inside the configured workspace.

## Deliberately deferred

- PostgreSQL and multi-server coordination;
- a general plugin packaging or discovery system;
- arbitrary artifact and vector-store backends;
- tenant billing, quotas, and organization management;
- Kubernetes or VM provisioning;
- mobile and web user interfaces;
- sophisticated placement, cost optimization, and autoscaling.

Those features must be added only when a working vertical slice creates a concrete
need for them.

## Delivery slices

1. Define assignment, worker, lease, and completion records with deterministic unit
   tests.
2. Expose register, claim, renew, progress, and complete through the existing service.
3. Add `harness worker` and execute one assigned run out of process.
4. Add lease-loss behavior and the end-to-end acceptance test.
5. Route workflow nodes through the same assignment mechanism.

Each slice must build and pass its focused tests before the next abstraction is added.

## Markdown factory vertical slice

The first product-producing factory is deliberately generic. A factory manifest names
a job and an ordered list of Markdown worker definitions. It does not declare which
files a worker must produce and does not infer completion from filesystem paths.
Workers inspect the shared workspace, decide which artifacts the job needs, and report
success or failure through ordinary durable harness runs.

Run the bundled Snake factory with the inexpensive Luna model:

```sh
./harness factory run factories/snake
```

Omitting the workspace creates a fresh factory-owned directory under
`.factory-workspaces/`. Supplying a workspace opts into modifying that existing
codebase. Journals always live separately under `.factory-runs/`, so
workers cannot mistake orchestration history for product source.

There is no turn budget or whole-run deadline. An operator can stop a run based on
observed lack of progress and resume at a worker with concrete guidance:

```sh
./harness factory run factories/snake .factory-workspaces/coil-snake-EXAMPLE gpt-5.6-luna codex
```

This manual intervention path is the MVP precursor to a supervisor that assesses
progress evidence—workspace changes, repeated operations, and repeated failures—and
chooses whether to continue, redirect, or cancel. It must not substitute arbitrary
turn counts for progress assessment.

Factories may add Markdown invariant contracts as context and ordered cleanup or
release workers. The Snake factory uses this to require one authoritative
implementation, a coherent manifest/module graph, no orphaned staging sources, and a
Coil-owned game engine before final verification.

Supply arbitrary additional context files when starting a workflow. For example, put
an issue in Markdown and pass it to the standalone issue workflow along with the
existing product workspace:

```sh
./harness factory run factories/snake-issue \
  .factory-workspaces/coil-snake-EXAMPLE \
  gpt-5.6-luna \
  codex \
  examples/issues/snake-wrap-walls.md
```

Runtime context is generic: every additional file after the provider is appended to
the workflow's common context. The factory itself decides through its Markdown what
that context means.
