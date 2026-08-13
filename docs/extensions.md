# Extensions

This document specifies the harness's extension system. It is a design record,
not a description of shipped code: nothing below is implemented yet.

The reference point is [pi](https://github.com/earendil-works/pi), whose extension
API is the most complete one in this class of tool. Section 1 records what pi
supports, because "our own flavor of all the things it supports" needs an explicit
list of what those things are. Section 2 states the one decision that makes our
version different in kind. Sections 3–5 specify our surface, the loading model, and
the gaps between the two.

## 1. What pi supports

pi extensions are TypeScript modules loaded through `jiti`, so a file dropped in
`~/.pi/agent/extensions/` is compiled and run in-process at startup. A module
default-exports a factory that receives an `ExtensionAPI`:

```typescript
export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => { ... });
  pi.registerTool({ ... });
}
```

An async factory is awaited before `session_start`, so an extension can fetch remote
configuration or discover models before the session exists.

**Registration surface.** `registerTool`, `registerCommand`, `registerProvider`,
`registerShortcut`, `registerFlag`, `registerMessageRenderer`, `registerEntryRenderer`,
`registerMarkdownTransformer`.

**Events.** Roughly forty, in five families:

| Family | Events |
|---|---|
| session | `project_trust`, `session_start`, `session_shutdown`, `session_before_switch`, `session_before_fork`, `session_before_compact`, `session_compact`, `session_before_tree`, `session_tree`, `session_info_changed`, `resources_discover` |
| agent | `before_agent_start`, `agent_start`, `agent_end`, `agent_settled`, `turn_start`, `turn_end`, `message_start`, `message_update`, `message_end`, `context` |
| provider | `before_provider_headers`, `before_provider_request`, `after_provider_response` |
| tool | `tool_execution_start`, `tool_execution_update`, `tool_execution_end`, `tool_call`, `tool_result`, `user_bash` |
| input | `model_select`, `thinking_level_select`, `input` |

The important distinction inside that table is not the family, it is whether a
handler's **return value changes what happens next**. Most are notifications.
Eight are interception points: `project_trust` decides trust, `tool_call` can block
a call, `tool_result` can rewrite a result, `context` can rewrite the message list,
`before_agent_start` can rewrite the prompt and system prompt, `input` can transform
or swallow user input, `before_provider_request` can rewrite the wire payload, and
the `session_before_*` family can cancel the transition. Everything else could be a
log tail; those eight are why an extension system is more than an event feed.

**Context.** Handlers get `ctx`: `ui` (confirm/select/input/editor/notify/setStatus/
setWidget/setTitle/custom), `mode`, `cwd`, `signal`, `sessionManager`, `model`,
`modelRegistry`, `thinkingLevel`, plus `isIdle()`, `abort()`, `shutdown()`,
`compact()`, `getSystemPrompt()`, `getContextUsage()`. Command handlers additionally
get session control: `newSession`, `fork`, `navigateTree`, `switchSession`,
`waitForIdle`, `reload`.

**State.** `pi.appendEntry(customType, data)` persists extension data in the session
without putting it in LLM context; extensions rebuild their state by iterating
entries on `session_start`.

## 2. The decision: extensions are peers, not plugins

pi can load extensions in-process because it is TypeScript. We are ahead-of-time
compiled native code, so "dynamically loaded" has to be given an actual meaning.
Three are available:

1. **`dlopen` a compiled Coil module.** Fast, no serialization, full access.
2. **Out-of-process peers over the agent bus.** Serialized, isolated, language-neutral.
3. **Embed an interpreter.** A whole language runtime we would then own.

**We choose (2).** Not as a fallback — as the design.

The reason is that we already built it. `src/bus/` has an `Envelope` with
`from`/`to`/`kind`/`correlation`, an `Address` sum (`Agent`, `Topic`, `Broadcast`,
`Service`), a router with topic subscriptions, unix-socket and TCP carriers, length-
prefixed framing, and MessagePack/JSON codecs. `correlation` already makes
request/response work over an otherwise fire-and-forget bus, which is exactly the
primitive the eight interception points need. An extension is a process that
attaches to the bus, subscribes to some topics, and answers some requests. There is
no new transport, no new addressing, and no new discovery to invent.

What (2) buys over (1), beyond the code already existing:

- **A bad extension cannot take the harness down.** Given `docs/tui-failure-postmortem.md`
  — a wrong-platform ioctl corrupting a worker thread's stack, misdiagnosed twice —
  handing third-party native code the same address space is not a trade we should make.
- **Extensions are language-neutral.** Anything that can write a length-prefixed
  MessagePack frame qualifies. That includes TypeScript, so pi's own extensions
  become portable to us with an adapter rather than a rewrite.
- **A hung extension is a deadline, not a hang.** Every interception point carries
  a timeout and a documented default. In-process, a blocking extension is a
  wedged agent.
- **No Coil ABI commitment.** `dyn` trait objects across a shared-library boundary
  would pin us to an LLVM ABI detail the postmortem already shows we do not fully
  control.

The cost is real and should be stated: a serialization round-trip on every hook an
extension subscribes to. This is why the design distinguishes *notification* topics
(fire-and-forget, no reply awaited, zero cost when nobody subscribes) from
*interception* requests (correlated request/reply with a deadline). Only the second
kind can slow a turn down, there are eight of them, and each is opt-in.

A `dlopen` tier for trusted first-party extensions stays possible later. It is not
in this design, and nothing here should be shaped to accommodate it.

## 3. Our surface

### 3.1 Manifest

An extension is a directory with a `harness-extension.json` and an executable:

```json
{
  "version": 1,
  "name": "permissions",
  "description": "Prompts before destructive tool calls.",
  "exec": ["./permissions"],
  "subscribes": ["run.*", "tool.*"],
  "intercepts": ["tool.call", "input"],
  "registers": {
    "tools": ["ask_user"],
    "commands": ["/permissions"],
    "providers": [],
    "shortcuts": ["ctrl+p"]
  },
  "timeout_ms": 5000
}
```

`subscribes` and `intercepts` are declared, not discovered. The harness must know
before starting a turn whether any extension can block it, and a declaration that
is checked at load time beats a registration race during the first tool call.

### 3.2 Discovery and loading

Search order, first match wins per extension name:

| Location | Scope |
|---|---|
| `--extension <path>` | invocation |
| `$HARNESS_HOME/extensions/*/harness-extension.json` | user |
| `./.harness/extensions/*/harness-extension.json` | project |

Loading is: read manifest → spawn `exec` with the bus socket path and a realm in the
environment → wait for the extension to attach and send `extension.ready` → flush its
registrations → proceed. An extension that does not become ready inside `timeout_ms`
is reported and skipped; startup continues without it.

This reuses `HARNESS_BUS_REALM` from `docs/agent-bus-dialects.md`. Extensions attach
in a private realm by default, so they are invisible to Claude Code peers and to each
other unless deliberately placed in a shared one.

**Project trust.** Project-local extensions do not load until the project is trusted,
matching pi. Trust is asked once per project root and remembered in
`$HARNESS_HOME/trust.json`. User and `--extension` extensions load first and may
answer the trust question themselves, which is what makes a trust-prompt extension
possible at all.

**Reload.** `/reload` tears down extension processes and repeats discovery. Because
extensions are processes, reload is `kill` + respawn, with none of the module-cache
invalidation that makes in-process reload leaky.

### 3.3 Notifications

Our durable event journal already emits most of what pi's notification events carry.
`run.created`, `run.started`, `run.completed`, `run.failed`, `run.cancelled`,
`agent.created`, `agent.delegated`, `model.request.started`, `model.response.delta`,
`model.request.completed`, `model.request.failed`, `tool.call.proposed`,
`tool.call.started`, `tool.call.completed`, `tool.call.failed`, `tool.call.rejected`,
`workflow.node.*`, and `supervisor.*` are published on bus topics today by
`src/bus/publisher.coil`.

So notifications need no new event model. An extension subscribes to a topic pattern
and receives the same versioned envelope the journal stores. This is a genuine
advantage over pi: our events are *durable*, so an extension can replay history on
attach rather than reconstructing state from custom entries.

Missing notifications that pi has and we do not emit: `session_start`/`shutdown`
(we have conversations, not sessions — see 5.1), `turn_start`/`turn_end` (derivable
from `model.request.*` but should be explicit), `agent_settled`, and the provider
wire events (`before_provider_headers`, `after_provider_response`).

### 3.4 Interceptions

Eight request/reply exchanges, each with a deadline and a documented default when an
extension is slow, absent, or crashes:

| Interception | Request body | Reply | Default on timeout |
|---|---|---|---|
| `tool.call` | tool name, call id, arguments | `{allow}` / `{block, reason}` / `{arguments}` | allow |
| `tool.result` | name, call id, arguments, result | `{result}` / `{is_error}` | unmodified |
| `context` | ordered messages | `{messages}` | unmodified |
| `agent.before_start` | prompt, system prompt | `{prompt, system_prompt}` | unmodified |
| `input` | text, source | `{continue}` / `{transform, text}` / `{handled}` | continue |
| `provider.before_request` | provider, payload | `{payload}` | unmodified |
| `project.trust` | cwd | `{trusted, remember}` | undecided |
| `session.before_change` | reason, target | `{cancel}` | proceed |

Two rules keep this from becoming a way to make the harness mysteriously slow or
mysteriously permissive:

**Fail-open, loudly.** Every default above is the behavior you would get with no
extension installed. A timeout emits a `extension.timeout` event into the durable
journal naming the extension and the interception. The harness never silently waits.

**Declared order, no implicit priority.** Interceptors run in manifest load order.
For `tool.call`, the first `block` wins and the rest are not consulted. For
transforming interceptions, each sees the previous one's output. There is no
priority field; if order matters, it is the load order, which is inspectable.

### 3.5 Registration

**Tools.** An extension registers a tool spec (name, description, JSON Schema, effect,
timeout). Calls arrive as a correlated request; the reply is a `ToolResult`. The
in-process `ToolRegistry` gains a bus-backed `ToolImplementation` whose `execute-tool`
is a request/reply with the declaring extension. Nothing else in the tool loop changes:
schema validation, deadlines, cancellation, parallel execution, and the event lifecycle
are identical to native tools.

**Commands.** Slash commands are a hardcoded `cond` in `src/tui/app.coil` today. They
become a registry keyed by name, with entries for description, handler address, and an
optional argument-completion address. This is a prerequisite for the completion menu
work, not a consequence of it — a menu over a hardcoded `cond` would have to be
rewritten the moment an extension adds a command.

**Providers.** `resolve-runtime-provider` in `src/service/runtime_controller.coil` is
likewise a `cond` over provider names. It becomes a registry so an extension can add
a provider. Note that a bus-backed provider serializes every streamed delta, so this
is the one registration where the out-of-process cost is per-token rather than per-call.
An extension provider that streams should be understood as slower than a native one,
and the manifest should say so.

**Renderers.** This is where our architecture beats pi's rather than copying it.
pi renderers return `Component` objects, which only works in-process. Our renderer
already consumes a **declarative view tree** (`ViewNode`, `view-flow`,
`view-decorated-flow`, `view-stack` — see `docs/decisions/0009-declarative-terminal-layout.md`),
and a view tree is data. An extension returns a serialized view tree; the harness lays
it out and renders it with the same engine, at the same widths, under the same
capability profile. An extension cannot emit ANSI, cannot move the cursor, and cannot
corrupt the live region, because it never gets to.

**Shortcuts and flags.** A key-binding registry consulted by `src/tui/input_reader.coil`
before its built-in bindings, and a CLI flag table merged at argument parse time. Both
are small; both are blocked on the same registry pattern as commands.

### 3.6 UI

pi's `ctx.ui` is a synchronous dialog API. Ours is request/reply in the other
direction: the extension sends a `ui.*` request to `Service`, the TUI presents it, the
reply carries the answer.

`ui.select`, `ui.confirm`, `ui.input`, `ui.notify`, `ui.set_status`, `ui.set_widget`.
Each takes a view tree for its body where a body is needed. `ui.editor` and `ui.custom`
are deferred: the first needs an external editor handshake, the second is a licence to
draw arbitrary components and is exactly what the view-tree rule exists to prevent.

In non-interactive modes (`--plain`, non-TTY, `serve`), `ui.confirm` and `ui.select`
fail immediately with `no_interactive_ui` rather than blocking. An extension that needs
a human must handle not having one.

### 3.7 State

`extension.append_entry` writes a custom record to the durable journal under a
namespaced event kind (`extension.<name>.<type>`). These records are journal citizens:
they replay on recovery, they are visible to `GET /v1/runs/{id}/events`, and they never
enter LLM context. On attach, an extension replays its own entries from the journal.

This is strictly better than pi's session entries for our purposes, because the journal
is already fsync-backed, sequence-ordered, and recoverable, and because it means
extension state survives a harness restart without the extension implementing anything.

## 4. Worked example: permissions

We deliberately removed the permission layer from the runtime — see `agent.md`. The
design above is what it comes back as, and it is a useful test of whether the surface
is sufficient.

```json
{
  "version": 1,
  "name": "permissions",
  "exec": ["./permissions"],
  "intercepts": ["tool.call"],
  "registers": { "commands": ["/permissions"] },
  "timeout_ms": 30000
}
```

On `tool.call`, the extension reads the tool's declared effect from the request. For
`ReadOnly` it replies `{allow}` immediately. For `Reversible` or `Destructive` it
consults its own rule list; on a miss it sends `ui.confirm` with a view tree describing
the call, and replies according to the answer. `/permissions` lists and edits rules.
Rules persist through `extension.append_entry`, so they survive restart.

This works with no new runtime concepts, which is the point. Note also what it makes
explicit: with no permissions extension installed, `tool.call` times out to `allow`,
which is exactly the current documented behavior rather than a new hazard.

## 5. Gaps

Honest list of what does not exist yet, roughly in dependency order.

**5.1 Sessions.** pi has sessions with fork, tree navigation, compaction, and switching.
We have durable conversations (`conversation_id`) and durable runs, with no fork, no
tree, and no compaction. The `session_*` events and `ctx.fork`/`navigateTree`/
`switchSession` have nothing to bind to. Either we build session trees or we drop that
family; this document does not decide which, but the extension surface cannot be
finished until it is decided.

**5.2 Registries.** Commands, providers, shortcuts, and flags are all hardcoded `cond`
forms. Each needs to become a registry before anything can register into it. This is
the single largest prerequisite and it is mechanical.

**5.3 Interception points.** None of the eight exist. The tool loop runs
`propose → resolve → validate → execute` with no hook between validate and execute;
that hook is the one that matters most and is the smallest to add.

**5.4 Bus service addressing.** The bus routes to `Agent`, `Topic`, `Broadcast`, and
`Service`, but `Service` has no request handler. Extensions calling in (`ui.*`,
`extension.append_entry`, registration) all need one.

**5.5 Process supervision.** Spawning, health, restart policy, stderr capture, and
shutdown ordering for extension processes. None of it exists. An extension that
crashes mid-turn must degrade to its documented defaults rather than stalling the run.

**5.6 Trust.** No project trust model exists. Loading a project-local executable is
the highest-risk thing in this document and it should not ship before 5.6 does.

**5.7 Skills, prompts, themes.** pi's `resources_discover` returns paths for these.
We have none of the three. They are additive and can wait.

## 6. Non-goals

- No in-process extensions in this design. See section 2.
- No extension may emit terminal control sequences. Renderers return view trees.
- No extension may write the event journal directly; `extension.append_entry` goes
  through the single-writer emitter like everything else.
- No priority or ordering field. Load order is the order.
- No implicit registration. Everything an extension can do is declared in its manifest
  and checked at load.
