# Bus dialects

The harness has to talk to peers that were not designed for it. Claude Code
sessions already speak a shipped local protocol; other harnesses on other
machines will speak ours; a browser will eventually want a WebSocket. None of
these can be made to converge on one wire format, so the harness carries several
and keeps the difference in one place per dialect.

## What a dialect is, and what it is not

The existing `src/bus/` abstractions — `Transport`, `Codec`, `Address` — split
one protocol into replaceable parts. They are the right decomposition *inside* a
protocol we control, and the wrong one for a protocol we do not: Claude Code's
framing, envelope, addressing, discovery, and connection lifetime are a single
package. Its envelope cannot be swapped for MessagePack, and its `uds:` address
is not our `Address`.

So a dialect is a layer *above* `Transport`, not another implementation of it:

| | native bus (`src/bus/`) | Claude Code (`src/bus/cc/`) |
|---|---|---|
| framing | 4-byte length prefix | newline-delimited JSON |
| codec | MessagePack or JSON, negotiable | JSON only, fixed shape |
| identity | `Address` sum in the envelope | text envelope inside `message.content` |
| connection | persistent, subscribe handshake | one message per connection |
| discovery | none yet | socket directory + probe + registry |
| ordering | per-connection | none beyond the receiver's queue |

Trying to express the second row-set as `Codec` impls of the first would mean an
`Address` that can round-trip through a `<cross-session-message>` attribute and
a `Transport` that reconnects per frame. That is not reuse, it is a shared name
over two different things.

## What generalizes anyway

Three things did transfer, and they are the parts worth keeping when a third
dialect arrives.

**Discovery by liveness probe, not declaration.** A registry entry is a hint;
opening the socket is the truth. This needs no heartbeat, no lease, and no
expiry: a stale entry is discovered by whoever next tries to use it, and self-
heals. `cc-probe-alive?` is nine lines and replaces an entire presence protocol.

**The directory is the graph; the registry is a cache of names over it.** This
is the one that is easy to get backwards. `readdir` on the socket directory
already enumerates everything reachable. Registration adds names, cwd, and
status — metadata, not reachability. Building it registry-first would make
unregistered peers invisible and stale entries authoritative. Our `harness
peers` finds peers that Claude Code's own `ListAgents` cannot see, purely
because it reads the directory rather than the roster.

**Structured metadata surviving an unstructured channel.** Claude Code's peer
identity rides as a text envelope inside a prompt string, guarded by close-tag
scrubbing and a round-trip re-render check. The technique — re-render what you
parsed and compare byte-for-byte — is worth stealing anywhere structure has to
travel through a channel that cannot guarantee it, and it is what makes
`src/bus/cc/envelope.coil` a renderer with a parser attached rather than two
codecs that can drift.

## Why the CC envelope is tested the way it is

The receiver validates by re-rendering. A renderer that is merely self-
consistent passes every round-trip test we could write and still has every
message it sends silently demoted to anonymous text — the message arrives, the
sender does not. Self-consistency cannot detect this; only a differential test
against the reference can.

Hence `tests/bus_cc_conformance_test.coil` is generated, not authored:
The checked-in conformance corpus was captured from the reference client and records the
expected strings mechanically. Its 30 vectors were confirmed to fail under three
deliberate mutations (clamp at 63, truncated ellipsis, reordered attributes)
before being trusted. The suite also anchors on a frame captured verbatim from a
live Claude Code 2.1.225 session.

Verified end to end: the reference receiver attributes our messages to
`coil-harness` rather than showing raw envelope text, which is only possible if
its round-trip check passed; and a live Claude Code session moved `idle` →
`busy` on receiving one, which is only possible if the frame cleared its inbound
gate and reached the prompt queue.

## Realms: keeping the scheme without the interop

Everything above describes a mechanism, not a relationship with Claude Code.
The two are separable, and `src/bus/cc/realm.coil` is where they separate.

A **realm** is a pair of directories. `claude-code` resolves to Claude Code's
own — we appear to its sessions and they appear to us. Any other name resolves
to a private pair, and the same protocol then runs with no contact in either
direction.

```sh
harness peers                      # shared namespace, interoperates
harness peers --realm lab          # private namespace, same protocol
harness send --realm lab <peer> "..."
HARNESS_BUS_REALM=lab harness peers    # or set the default
```

| | `claude-code` | any other name |
|---|---|---|
| sockets | `$XDG_RUNTIME_DIR\|$CLAUDE_CODE_TMPDIR\|/tmp` + `/cc-socks` | `$XDG_RUNTIME_DIR\|$TMPDIR\|/tmp` + `/harness-socks-<realm>` |
| registry | `$CLAUDE_CONFIG_DIR\|~/.claude` + `/sessions` | `$HARNESS_CONFIG_DIR\|~/.coil-agent-harness` + `/bus/<realm>/sessions` |
| self | inherited from `CLAUDE_CODE_MESSAGING_SOCKET` | `HARNESS_BUS_SOCKET`, else none |
| `interop` | true | false |

**Isolation is by directory, not by dialect**, and that is what makes it cheap.
A Claude Code session enumerates its own socket directory and never looks in
ours, so a private realm is invisible to it without a single byte of the wire
format differing. Changing the envelope tag as well would buy nothing — nobody
would be reading it — and would cost the property worth the most here: the
conformance-tested renderer is the *same renderer* in both realms, so a private
realm inherits every guarantee the differential suite establishes.

The private socket directory is named `harness-socks-<realm>`, never
`cc-socks`, so pointing two realms at the same base still keeps them apart.
There is no configuration that silently merges them.

Isolation is tested rather than asserted:
`a-private-realm-and-claude-code-cannot-see-each-other` binds a live registered
peer in each realm *under the same pid* — if isolation came from anything other
than the directory, a colliding pid is where it would show — and checks that
neither listing nor name resolution crosses. `two-private-realms-cannot-see-each-other`
and `self-identification-does-not-leak-across-realms` cover the rest.

The default is `claude-code`. Interop is what the harness was built to do first
and what is verified against a live session; a private realm is one flag away.

## Layout

```text
src/bus/            native bus: protocol, framing, router, carriers, server
src/bus/cc/         the dialect Claude Code introduced
  realm.coil        which peer namespace we are in: shared, or private
  address.coil      uds:/bridge:/did:, percent encoding, socket paths
  envelope.coil     <cross-session-message> render/parse, round-trip validated
  frame.coil        NDJSON user/control frames, v4 message ids
  discovery.coil    socket directory, liveness probe, registry overlay, resolve
  peer.coil         send, rename, status receipts
src/infra/directory.coil   readdir/mkdir/unlink/chmod, platform dirent layout
```

`src/infra/directory.coil` exists because `coil.fs` reaches files, not
directories. It follows `coil.socket`'s `sockaddr_un` pattern: a comptime branch
on the target OS, with the `d_name` offset asserted by a test that writes a long
filename and reads it back — a wrong offset yields plausible garbage rather than
an error, so it has to be caught by data.

## Not done

- **Receiving.** `harness send` works; there is no listener yet, so the harness
  cannot be messaged and cannot reply. This needs binding a socket, reading
  NDJSON, and registering a session file (including `procStart`, which the
  receiver re-runs and compares so a recycled pid cannot inherit a dead
  session's identity).
- **The native bus is still not wired into `harness serve`.** Unchanged from
  `bus-known-gaps.md`: nothing outside `src/bus/` and tests constructs it. The
  shared poll over the HTTP listener and the bus socket is the remaining work.
- **A dialect trait.** Both dialects exist; nothing yet names the thing they
  both are. Worth writing only once receiving exists on both sides, because the
  send-only shape would under-specify it.
- **Non-blocking probe.** `unix-connect` blocks, so `cc-probe-alive?` cannot
  impose the reference's 250 ms timeout. Local connects resolve in the kernel
  with no round trip, so the exposure is narrow: a listener with a full backlog
  on a platform that blocks rather than returning `EBUSY`.
- **Authentication.** Nothing here crosses a machine. Unix socket permissions
  are the whole boundary, which is correct for local peers and is not a plan for
  TCP or WebSocket.
