# 0008: Lifetime-owned arenas

Status: accepted

## Context

The harness currently passes an unqualified `Allocator` through process, service,
run, model-turn, tool-call, HTTP-request, and TUI rendering code. That makes storage
mechanism explicit but leaves lifetime implicit. In particular, a pointer or slice
does not reveal whether it refers to process state, a run arena, a temporary request,
or a stack value. Background work can consequently retain shorter-lived values, and
defensive JSON cloning has become a substitute for an ownership contract.

## Decision

The harness has the following ordered lifetime classes:

```text
Process
  Service
    Run
      Turn
        ToolCall
    TuiSession
      TuiCycle
```

Coil's `coil.region/Region` is the lifetime primitive: it owns every allocation made
through its allocator and closes all of them as one unit. `AllocationDomain` is the
harness's synchronized region owner for lifetimes shared with a worker thread; it is
not a competing allocator implementation. A value owned by a shorter-lived region
may borrow immutable data from an ancestor. An ancestor may not retain a pointer,
slice, dynamic trait object, JSON tree, or collection owned by a descendant.

The classes have these responsibilities:

- `ProcessArena`: immutable configuration and tool specifications.
- `ServiceArena`: journal/controller/mailbox state and durable projections.
- `RunArena`: one background job, provider context, request, cancellation state,
  continuations, and final result.
- `TurnArena`: provider wire requests, decoders, and response scratch for one model
  turn. Data needed by the next turn is promoted deliberately into the run arena.
- `ToolCallArena`: validation and execution scratch for one call. A retained result
  is promoted into the run arena before the call arena closes.
- `TuiSessionArena`: semantic presentation state and interaction history.
- `TuiCycleArena`: one declarative layout tree, laid-out frame, and render plan. It
  closes after the terminal update completes.

Durable journal recovery is a projection, not service-owned state. Its API requires
the destination allocator (`service-recover-into`): HTTP requests, TUI sessions, and
runtime operations materialize snapshots in their own lifetime. In particular, the
service arena is never used as scratch while descendant run arenas are live. The
journal owns a dedicated synchronized service-lifetime scratch domain for encoding;
each publication opens and closes a thread-confined child region inside that domain.

Thread entry points receive one owned job allocated in an arena that outlives the
thread. They may borrow immutable process/service data. They never receive pointers
to caller stack storage. Closing a run arena requires joining every thread that can
access it.

Core boundary types follow these rules:

- `Json` is an arena-owned tree. Copying the tagged value is a borrow, not ownership
  transfer. Crossing into a longer lifetime requires explicit promotion.
- `slice u8` is borrowed unless its API name states that it copies into a named
  arena.
- Collections own their buffers in the allocator supplied at construction.
- A `dyn` value may cross a thread boundary only when its concrete object belongs to
  the run arena or an ancestor.
- References derived from by-value temporaries never escape the expression that
  created them. Durable code loads the containing value first.

Generic scratch allocators remain implementation details inside pure algorithms.
Application and runtime constructors accept a named arena/lifetime context rather
than an unexplained allocator wherever the lifetime affects correctness.

## Enforcement

- Region-owning structs store the `Region` (or synchronized `AllocationDomain`) and
  expose its allocator; consumers do not close regions they did not open.
- Thread/job constructors are the only background ownership-transfer boundary.
- Promotion functions are named for their destination, for example
  `json-clone-into-run` rather than an ambiguous `json-clone` at a boundary.
- Tests close and poison child arenas as early as possible, then exercise every
  retained parent value.
- Live-arena counters are asserted at service and process shutdown.

## Consequences

Some values will be copied at explicit promotion boundaries. That cost is preferred
to pervasive defensive cloning and unprovable lifetime assumptions. Turn and render
scratch is reclaimed in bulk, reducing both leaks and allocator contention.
