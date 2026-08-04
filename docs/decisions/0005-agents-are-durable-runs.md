# 0005: Executing agents are durable runs

## Status

Accepted.

## Context

The platform needs stable agent identities, traceable delegation, bounded concurrency,
cancellation, and recovery. Creating a separate in-memory agent executor would bypass
the run scheduler and duplicate lifecycle semantics just as the system begins to rely
on them.

## Decision

Every executing agent is represented by a durable run. Its `agent_id` equals its
`run_id`. Every event includes that identity; existing run-scoped events belong to the
root agent automatically.

A delegated agent is created through the versioned create-run command with a unique
child `run_id` and an existing `parent_run_id`. The service, not the client, sets the
child `agent_id` and current parent `parent_agent_id`. It records:

1. the child `run.created` fact;
2. an `agent.delegated` fact on the parent stream;
3. an `agent.created` fact on the child stream.

The accepted command also contains a versioned typed message with message ID, kind,
sender, recipient, and content. For a delegation its content is the child prompt, so
the recorded message is the work actually executed rather than informational metadata.

Unknown parents are rejected before any child event or side effect is recorded.
Command idempotency applies to delegation exactly as it does to ordinary run creation.

## Consequences

Delegated work receives the existing scheduler's concurrency bound, provider routing,
tool authorization, timeout, cancellation, event query, and restart behavior. Parent
and child can be inspected and cancelled independently. Recursive delegation depth and
aggregate parent budgets are not yet enforced; workflow graphs will add those explicit
policies instead of hiding recursion in prompts.
