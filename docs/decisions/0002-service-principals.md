# 0002: Service principals carry explicit capabilities

## Status

Accepted.

## Context

The first remote slice authenticated every request with one shared bearer token. That
proved the HTTP boundary but gave every authenticated client full control and trusted
the optional `actor` supplied in mutation bodies. A read-only UI could therefore not
be given least-privilege access, and durable event attribution was spoofable.

## Decision

Authentication resolves a bearer credential to a server-owned principal and explicit
capabilities before constructing the transport-neutral service request.

- `operator` has `observe` and `control` capabilities.
- `observer` has only `observe`.
- create, cancel, and authorization-decision routes require `control`.
- run and event queries require `observe`.
- missing or unknown credentials return 401; an authenticated principal without the
  required capability returns 403.
- mutation commands are stamped with the authenticated principal. Any client-provided
  `actor` is replaced before the command is persisted or executed.

`HARNESS_OPERATOR_TOKEN` configures the operator credential and
`HARNESS_OBSERVER_TOKEN` optionally configures the observer credential.
`HARNESS_AUTH_TOKEN` remains a compatibility fallback for the operator.

Token comparison is performed without content-dependent early exit. The listener
continues to bind only to loopback; bearer credentials are not a replacement for TLS
on a remotely exposed transport.

## Consequences

Read-only clients can inspect execution without receiving mutation authority. Durable
mutation events have trustworthy coarse-grained actor attribution. Additional
principals and capabilities can replace the two environment-backed credentials later
without changing `RunService` routing semantics.
