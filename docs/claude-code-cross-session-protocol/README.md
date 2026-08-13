# Claude Code cross-session messaging

Reverse-engineering notes and a working independent client for the protocol behind Claude
Code's `SendMessage` / `ListAgents` tools. Filed here as prior art for the agent bus work:
it is a shipped, in-use local agent-to-agent transport, and its design choices — and the
places they are load-bearing — are worth having written down.

- [`wire-format.md`](wire-format.md) — the protocol: discovery, framing, envelope,
  addresses, the inbound gate, what state a client has to touch, and
  [§8](wire-format.md#8-the-bridge-transport-peers-on-other-machines), the `bridge:`
  transport that carries the *same* envelope to sessions on other machines.
- [`wire-format.md` §10](wire-format.md#10-projecting-non-local-agents-as-local-peers) — the
  plan for the bus: don't join the bridge, project our agents as local uds peers so they can
  run anywhere and still be first-class in `ListAgents` and `SendMessage`.
- [`ccpeer/`](ccpeer/) — a dependency-free Node client that registers as a peer, receives
  real `SendMessage` traffic, and sends messages into a live session's prompt queue.

Everything here was derived from the `2.1.225` binary and then confirmed against a running
session. Nothing in it is a public API; it can change without notice.

## Running it

```sh
cd ccpeer
node ccpeer.js list                       # live peers (the set ListAgents shows)
node ccpeer.js serve --name handrolled --auto-reply
node ccpeer.js send <peer> "text"         # deliver into a session's prompt queue
node ccpeer.js rename <peer> <new-name>
node ccpeer.js status <peer> held --orig-msg-id <id>
node conformance.test.js                  # checks against a captured real frame
```

`<peer>` matches on name, pid, session id, or name prefix — or a raw `uds:` address /
absolute socket path, which skips the roster entirely. `send` and `serve` also take
`--from-mode bypass|prompting` (the permission-mode attestation; omitting it makes a
bypass-mode receiver hold the message for user approval). `serve` takes `--auto-reply`,
`--log F` (frames land in `F.jsonl`), `--console`, `--socket P`, and `--no-register`
(bind the socket but publish nothing — see the reachability/discoverability split in
[`wire-format.md` §7](wire-format.md#7-what-state-a-client-actually-touches)).

When sending from a separate process, pass `--socket` pointing at your listening socket so
the message carries a usable reply address.

## Verification

`serve` registered itself and Claude Code's own `ListAgents` reported it alongside real
sessions, indistinguishable from them:

```
handrolled [55439e]  ·  interactive  ·  idle  ·  started 6s ago
```

A real `SendMessage` to it arrived as:

```json
{"msgV":1,"msg_id":"7985a1f4-308d-43fd-861a-5a10490f9c38","type":"user",
 "message":{"role":"user","content":"<cross-session-message from=\"uds:/tmp/cc-socks/39194.sock\" from-name=\"…\" from-mode=\"bypass\">\nframe\n</cross-session-message>"},
 "priority":"next","from":"uds:/tmp/cc-socks/39194.sock"}
```

with `msg_id` matching what the tool returned. Replies sent back to the address in the
envelope appeared in the real session as ordinary peer messages, including an autonomous
`--auto-reply` round trip. `conformance.test.js` checks the encoder against a frame
captured verbatim from that exchange — byte-identical re-encoding, attribute ordering, the
round-trip guard, and close-tag scrubbing (9/9).

## Observations that transfer

- **Discovery by liveness probe, not by declaration.** A registry entry is a *hint*; the
  socket connect is the truth. Stale entries are self-healing because any reader that
  fails a probe unlinks the file. No heartbeat protocol, no lease.
- **The registry is a name directory, not a routing layer — and it is optional in both
  directions.** An unregistered process can hold a full two-way conversation, and it can
  also *find* peers without the registry, because `readdir` on the socket directory is
  already the reachability graph. Registration adds names, cwd, and status; it adds
  nothing to who can talk to whom. The design temptation is to treat such a registry as
  the source of truth when it is really a cache of names over a directory that never
  needed one.
- **Structured metadata inside an unstructured field.** Peer identity rides as a text
  envelope inside `message.content` rather than as sibling JSON keys, because the payload
  ultimately has to survive as prompt text. The round-trip re-render check is what keeps a
  body from forging that metadata — a cheap and effective trick when structure has to
  travel through a channel that can't guarantee it.
- **One envelope, two transports — and the reply address is just an attribute.** The
  cross-machine path (§8) reuses the local envelope and the local inbound gate verbatim; a
  unix socket is swapped for an HTTP POST and an SSE stream. Because the reply address
  rides *inside* the message rather than being implied by the connection, a sender that
  cannot be addressed back does not fail — it writes `from="unknown"` and the send is
  simply one-way. Worth stealing: make the return path data, not a property of the pipe.
- **Visibility is gated on the observer, which reads as absence.** A remote peer is listed
  only if *your* session is itself connected to the bridge. A healthy, addressable peer is
  therefore indistinguishable from a dead one until you connect — and the roster has no way
  to say "there may be more." Any registry whose completeness depends on the reader's own
  state needs to admit that in its output; this one only does so in the tool description.
- **The trust boundary is not where it looks.** `SO_PEERPID` is read but used only for
  self-send detection. Authorization lives entirely in the receiver's inbound gate
  (`crossSessionInbound`), which fails closed to `hold` on anything unrecognized. Identity
  on the wire is self-asserted.
- **Failure modes are chosen deliberately.** A `session_id` mismatch drops silently; a
  >1 MiB unterminated line drops the connection; an unknown permission mode holds rather
  than accepts.

## Caveats

- Node exposes no `SO_PEERPID`, so this client cannot populate `verifiedPeerPid` and
  cannot distinguish a self-send. Treat every `from` as a self-declared hint.
- The client is local only. `bridge:` is documented in
  [§8](wire-format.md#8-the-bridge-transport-peers-on-other-machines) but not implemented
  here: it needs an OAuth credential and a worker registration, so a handrolled peer cannot
  join it the way it can bind a socket in `/tmp`. `did:` is inert in the shipped binary.
- Kill `serve` with SIGINT/SIGTERM so it unregisters. A `SIGKILL` leaves a stale entry
  that other sessions will probe and eventually reap, but until then it is a phantom peer.
