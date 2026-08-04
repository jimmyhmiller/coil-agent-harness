# ADR 0007: Supervision is a public event consumer

## Status

Accepted.

## Decision

Supervisors observe the same versioned journal exposed to every other client. They do
not receive provider credentials, private runtime state, or a separate model/tool
execution loop.

An operator-capable principal can record a structured assessment with
`POST /v1/runs/{run_id}/assessments`. The versioned command includes a unique
`command_id`, a `verdict`, and optional score, rationale, or evidence fields. The
service emits `supervisor.assessment.recorded`; retries are idempotent by command ID.

An operator can request a cancellation intervention with
`POST /v1/runs/{run_id}/interventions` and `action: "cancel"`. The service validates
the durable run state, emits `supervisor.intervention.requested`, invokes the existing
run-controller cancellation path, and emits either `supervisor.intervention.applied`
or `supervisor.intervention.rejected`. The ordinary cancellation lifecycle remains
authoritative for run state.

## Consequences

Assessments are durable observations, not hidden mutations. Interventions are
auditable commands and cannot bypass authorization, terminal-state rules, or runtime
cancellation semantics. Observer credentials may read the resulting events but may
not create assessments or interventions.

Additional intervention types must define their state transition and failure behavior
before being added. Arbitrary supervisor-side tool execution is intentionally outside
this boundary.
