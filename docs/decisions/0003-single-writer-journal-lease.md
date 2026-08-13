# 0003: A durable journal has one live writer process

## Status

Superseded. The `flock` lease this record describes was removed from
`src/persistence/event_journal.coil` in commit `81f4e62`, and the project has since
decided against process locks of any kind: the journal should be correct by
construction, not by exclusion.

The problem the lease named is still real — see the sequence-collision note in
`docs/architecture.md`. The replacement is to derive a record's sequence from the
file rather than from process memory, which removes the collision instead of
forbidding the second writer. Nothing below is implemented.

## Context

The event journal is the authority for command idempotency, event ordering, recovery,
and whether an external side effect may be restarted. Its original lock protected
threads inside one process only. Two harness processes could open the same path,
allocate overlapping sequence numbers, both recover queued work, and duplicate model
or tool effects.

Supporting concurrent writers would require a transactional global sequence allocator,
cross-process command admission, run ownership leases, and recovery rules that can
distinguish a dead owner from a live process. Implementing only part of that protocol
would make the durability claim false.

## Decision

Opening an `EventJournal` acquires an exclusive, non-blocking `flock` on the journal
file and holds it for the lifetime of the open descriptor. A second writer fails
before it can recover or start work. Closing the journal explicitly unlocks it; the
kernel also releases the lease if the process exits or crashes.

Raw append helpers honor the same lease and fail rather than writing through an active
owner. Read access remains available through the owning service's query API.

## Consequences

- command admission, sequence assignment, recovery, and side-effect ownership remain
  single-writer and therefore retain their existing invariants;
- multiple harness processes may operate concurrently only when they use different
  journals;
- active/passive deployment is possible because a replacement can acquire the lease
  after the owner exits and then run normal recovery;
- horizontal multi-writer execution remains future work and must introduce the full
  transactional ownership protocol rather than weakening this lease.
