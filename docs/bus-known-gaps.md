# Agent bus — known gaps

## Resolved: a dead subscriber killed the harness (SIGPIPE)

`bus-server-drain!` writes to each subscriber's socket. When a subscriber had
gone away, that write raised `SIGPIPE`, whose default action terminated the
process — one client disconnecting took down the whole harness, every run in
flight with it.

Found by `tests/bus_server_test.coil`, not by reasoning: the per-layer tests all
passed, because none of them wrote to a socket whose peer was gone.

Nothing in Coil could take SIGPIPE off its default action — `signal` and
`setsockopt` are both declared privately in the stdlib (so they can neither be
called nor redeclared without an extern collision), and `signal-number-valid?`
rejected 13. Fixed in `coil.socket` instead, which is the right layer: writing
to a socket is now safe without a process-global signal policy.

- Darwin: `SO_NOSIGPIPE` (`0x1022`) via `setsockopt` on every accepted and
  connected fd.
- Linux: `MSG_NOSIGNAL` (`0x4000`), which required moving `tcp-write` and
  `unix-write` from `write()` to `send()` — there is no way to pass the flag
  through `write()`.

A closed peer now surfaces as an ordinary `IoFailed`, which `unix-write` maps to
a transport error and `bus-server-drain!` already handled by retiring the
subscriber. No harness change was needed and no new `SocketError` variant: the
drain retires on *any* write error, so the reason never had to be distinguished.

`a-dead-subscriber-is-retired-and-the-others-keep-receiving` is now a permanent
part of the suite. Both of its claims were falsified before being trusted —
asserting the dead subscriber was still live, and asserting the survivor
received the wrong event, each fail — because the process now survives to reach
a drain path that previously died, and a green result there could otherwise be
vacuous.

## 1. The bus is not wired into `harness serve`

`src/bus/` is a complete, tested subsystem, but nothing in `main.coil`
constructs it. There is no `harness serve --socket` yet, so the bus is reachable
only from tests.

Wiring it means building the observer sink and tee in `cli-serve`, passing the
tee to `event-emitter-init!` instead of the journal, and calling
`bus-server-accept!` / `bus-server-drain!` from the serve loop. The obstacle is
that `serve-run-service-until-shutdown` blocks on the HTTP listener, so the two
listeners need to share a poll (both fds are already watchable — see
`shutdown-signal-wait-listener`, which already selects over the HTTP listener
and the shutdown pipe) or run on separate threads.

This was previously blocked on the SIGPIPE crash above, on the grounds that
wiring a subsystem into the main server while one disconnecting client could
kill the process would turn a test-only crash into a production one. That
objection is now resolved.

Still open. The Claude Code dialect (`src/bus/cc/`, see
[bus dialects](agent-bus-dialects.md)) landed first because it needs no shared
poll — sending is one connection per message and discovery is a directory scan,
so it delivers value without touching the serve loop. That does not make this
gap smaller; it means the native bus is now the only one of the two that cannot
be reached from a running harness.

## 2. The Claude Code dialect can send but not receive

`harness peers` and `harness send` work against live sessions. There is no
listener, so the harness cannot be addressed, cannot reply, and does not appear
in another session's `ListAgents`.

Receiving needs three things, and only the third is interesting: bind a socket
in the agreed directory, read newline-delimited JSON off it, and write a session
file whose `procStart` matches `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` — which
the peer lister re-runs and compares, so a recycled pid cannot inherit a dead
session's identity. Skipping it does not fail loudly; it makes the entry
quietly untrusted.

Note that sending never required registration and receiving does not either: a
peer that binds a socket can be messaged by anything that knows the path.
Registration buys names and visibility, nothing more.
