# Agent bus — known gaps

## 1. A dead subscriber kills the harness (SIGPIPE)

**Severity: crash.** `bus-server-drain!` writes to each subscriber's socket. If a
subscriber has gone away, that write raises `SIGPIPE`, whose default action
terminates the process. One client closing its connection takes down the whole
harness, including every run in flight.

This was found by the server test, not by reasoning — the per-layer tests all
pass, because none of them writes to a socket whose peer is gone.

### Repro

Reduced from the test that found it (full source below): connect two
subscribers to the same run topic, close one, emit an event, drain.

```
test a-dead-subscriber-is-retired-and-the-others-keep-receiving ... FAILED (signal 13)
```

Signal 13 is SIGPIPE.

### Why it is not fixed here

There is currently no way to take SIGPIPE off its default action from Coil:

- `coil.signals` declares `signal` as an extern but **does not export it**, and
  its signature takes a `(fnptr c [i32] i64)`, so `SIG_IGN` (the integer 1)
  cannot be passed through it.
- `coil.signals/signal-subscribe` is exported, but `signal-number-valid?`
  permits only SIGHUP (1), SIGINT (2), SIGUSR1 (10), and SIGTERM (15).
  Subscribing to SIGPIPE (13) returns `InvalidSignal`.
- Declaring `signal` as an extern in the harness would collide at link time with
  `coil.signals`, which the harness already links via `shutdown_signal.coil` —
  externs are not deduped across modules.
- `setsockopt` is declared in `coil.socket` but not exported, so `SO_NOSIGPIPE`
  cannot be set from here either, and redeclaring it collides the same way.

### The fix it needs

At the socket layer, in `coil.socket`, so that writing to a socket is safe
without a process-global signal policy:

- **macOS/BSD:** `setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &1, 4)` on each
  accepted and connected socket.
- **Linux:** `send(fd, buf, len, MSG_NOSIGNAL)` instead of `write`, or
  `SO_NOSIGPIPE`'s absence handled by the same flag.

Either way `write`/`send` then returns `EPIPE`, which `unix-write` already maps
to a transport error, which `bus-server-drain!` already handles by retiring the
subscriber. **The server logic is already correct** — it is only the signal
disposition that is missing.

Allowing SIGPIPE in `signal-number-valid?` would also unblock it, but it is the
worse fix: it makes every program that writes to a socket responsible for
installing a process-global handler.

### Restoring the test

Once sockets no longer raise SIGPIPE, append the following to
`tests/bus_server_test.coil` and remove the caveat in that file's header. It
asserts the survivor receives every event and the dead subscriber is retired.

```lisp
;; The case that decides whether one broken client can hurt the others: a
;; subscriber whose socket is gone.
(deftest a-dead-subscriber-is-retired-and-the-others-keep-receiving
         (let [allocator (malloc-allocator)
               listener (alloc/stack socket/UnixListener)
               codec (alloc/stack MessagePackCodec)
               journal (alloc/stack EventJournal)
               observer (alloc/stack BusObserverSink)
               tee (alloc/stack TeeEventSink)
               emitter (alloc/stack EventEmitter)
               router (alloc/stack Router)
               server (alloc/stack BusServer)
               sequence (alloc/stack i64)
               doomed (alloc/stack UnixTransport)
               survivor (alloc/stack UnixTransport)]
           (remove-path SOCKET_PATH)
           (remove-path JOURNAL_PATH)
           (match (socket/unix-listen listener SOCKET_PATH 8)
             (Err [_] (assert false))
             (Ok [_] 0))
           (match (event-journal-open allocator JOURNAL_PATH true)
             (JournalOpenFailed [message] (assert false))
             (JournalOpened [opened] (store! journal opened)))
           (bus-observer-init! observer allocator 64)
           (tee-event-sink-init! tee allocator journal observer)
           (store! sequence 1)
           (event-emitter-init! emitter allocator tee sequence)
           (store! router (router-new allocator))
           (bus-server-init! server allocator router observer codec)

           (assert (subscribe-client! allocator doomed codec (run-topic allocator "chat-1")))
           (assert (= (bus-server-accept! server listener) 1))
           (assert (subscribe-client! allocator survivor codec (run-topic allocator "chat-1")))
           (assert (= (bus-server-accept! server listener) 1))
           (assert (= (bus-server-live-count server) 2))

           ;; The client goes away without telling the server.
           (transport-close! doomed)

           (assert (> (emit-sample emitter (RunStarted)) 0))
           (bus-server-drain! server)
           (assert (> (emit-sample emitter (RunCompleted)) 0))
           (bus-server-drain! server)

           ;; The survivor got everything; the dead one was dropped.
           (assert (str-eq (receive-event-kind survivor codec allocator) "run.started"))
           (assert (str-eq (receive-event-kind survivor codec allocator) "run.completed"))
           (assert (= (bus-server-live-count server) 1))

           (bus-server-close! server)
           (event-journal-close! journal)
           (socket/unix-listener-close! listener)
           (remove-path SOCKET_PATH)
           (remove-path JOURNAL_PATH)))
```

## 2. The bus is not wired into `harness serve`

`src/bus/` is a complete, tested subsystem, but nothing in `main.coil`
constructs it. There is no `harness serve --socket` yet, so the bus is reachable
only from tests. Wiring it means building the observer sink and tee in
`cli-serve`, passing the tee to `event-emitter-init!` instead of the journal,
and calling `bus-server-accept!` / `bus-server-drain!` from the serve loop —
which currently blocks on the HTTP listener, so the two need to share a poll or
run on separate threads.

Gap 1 should be fixed first. Wiring a subsystem into the main server while a
single disconnecting client can kill the process would turn a test-only crash
into a production one.
