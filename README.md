> This is experimental software. It probably doesn't work.

# COIL Agent Harness

The `agent-sdk` provider uses the official Claude Agent SDK for the agent loop
while Coil retains tool discovery, validation, execution, and journaling. It is
invoked like every other provider; no separate server or bridge command is needed.
See [the provider guide](docs/agent-sdk-bridge.md).

This repository contains the first vertical slice of a headless, observable agent
runtime written in COIL. The durable architectural rules live in [agent.md](agent.md).
The current product milestone is the narrowly scoped distributed software-factory
MVP described in [docs/software-factory-mvp.md](docs/software-factory-mvp.md). The TUI
is a client and development workbench, not the product boundary.

The runtime is also consumable as a Coil library. Downstream packages can implement
tool bundles, compose caller-owned registries, and inject them into either a direct
agent run or the durable service runtime. See
[the reusable-library guide](docs/reusable-library.md) and the standalone
[`examples/composable-harness`](examples/composable-harness) consumer.
Trusted native tool libraries can also be loaded dynamically through the stable,
versioned [C-compatible tool-plugin ABI implemented in Coil](docs/c-tool-plugins.md).

The current slice can:

- call OpenAI through the Responses API;
- call DeepSeek through its OpenAI-compatible and Anthropic-compatible APIs;
- use Codex as an external agent through the Codex App Server JSONL protocol;
- use Claude subscriptions through native Anthropic Messages and OAuth authentication;
- run CLI, service, and factory work through the first-class `agent-sdk` provider;
- deliver a message into a run that is already going, which the agent acts on at its
  next turn and then keeps as a standing instruction (`harness say <run-id> "..."`);
- send a worker that reports "not ready" back in with its own account of what remains,
  up to five attempts, instead of ending the run;
- refuse to start a workflow that declares it needs an issue without one;
- run any workflow in a named project -- a checkout declared once in `projects.json` --
  and hand an issue filed in that project to a workflow;
- reach an operator-declared OpenAI-compatible server -- including one behind SSH,
  whose tunnel the harness opens, supervises, and tears down itself;
- advertise provider capabilities and durably resolve explicit `balanced`, `low-cost`,
  `quality`, `subscription`, and `external-agent` routing profiles;
- assign every event a stable `agent_id` and execute delegated child agents as durable,
  independently cancellable child runs with typed delegation messages;
- expose one provider-neutral model, continuation, tool, result, and event contract;
- validate tool arguments against their declared schema before execution;
- execute independent tool calls concurrently with an explicit concurrency bound;
- continue the model with ordered tool results while preserving opaque provider state;
- run the entire model/tool loop on a background worker and join it later;
- emit structured JSON event records suitable for a terminal, server, or future UI;
- append those versioned events to an fsync-backed journal and recover ordered history
  while safely ignoring a torn final record;
- accept versioned create, cancel, run-query, and cursor-based event-query commands
  through a loopback HTTP service boundary;
- rebuild durable run state on restart, relaunch work that was only queued, and
  terminalize work whose in-process outcome can no longer be known;
- expose bounded `read_text_file`, `write_text_file`, `create_directory`, `delete_file`,
  and empty-only `remove_directory` tools to service runs, with traversal checks,
  effect metadata, deadlines, and cancellation.


## Projects

A workflow needs somewhere to work, and until now the only thing a caller could say
was a path. A project is a name for a checkout, declared once in
`~/.coil-agent-harness/projects.json`:

```json
{
  "projects": [
    {"name": "snake", "path": "~/Documents/Code/projects/coil-snake"}
  ]
}
```

```sh
./harness projects
./harness factory run factories/snake-feature --project snake
./harness factory issue factories/issues --issue .factory-issues/wrapping.md --project snake
```

A workflow belongs to no project — it is a reusable definition, and the project is
chosen when you run it. An issue can name its project in front matter. An unknown
project stops the run instead of falling back to a scratch directory. See
[the guide](docs/projects.md).

## Talking to a run

```sh
./harness say factory-issues-1787199382644 "stop rewriting the tests, just fix the arity"
```

Every run has an inbox; the agent drains it at its next turn, acts on what it finds, and
keeps it as a standing instruction for the rest of the run. See
[the guide](docs/talking-to-a-run.md).

## Declared providers

A model server the harness does not know about is described in
`~/.coil-agent-harness/providers.json` rather than compiled in. Naming a machine
is the whole setup -- for one behind SSH the harness reserves a local port, opens
`ssh -N -L`, proves the forward accepts before sending anything, reconnects it when
it drops, and releases it on shutdown. Nothing has to be started beforehand.

```json
{
  "providers": [
    {
      "name": "metaphysics",
      "default_model": "qwen3.8-27b",
      "reasoning": { "dialect": "qwen-jinja" },
      "transport": { "ssh": { "host": "computer.jimmyhmiller.com", "remote_port": 8080 } }
    }
  ]
}
```

```sh
./harness run metaphysics qwen3.8-27b "explain this repository"
```

The name then works anywhere a provider name works, including a `factory.json`
step. See [the guide](docs/declared-providers.md).

## OpenRouter

OpenRouter is a built-in OpenAI-compatible provider. Set an API key, then choose
`OpenRouter · Ox Alpha` from the TUI `/model` picker or pin it from the CLI:

```sh
export OPENROUTER_API_KEY=sk-or-v1-...
coil run -- run openrouter stealth/ox-alpha "Inspect this codebase"
```

Ox Alpha uses the OpenRouter model slug `stealth/ox-alpha`; it is the built-in
OpenRouter default and currently advertises zero-dollar input and output pricing.
OpenRouter availability, pricing, and free-tier rate limits can change independently
of the harness.

The HTTP listener binds to IPv4 loopback and the CLI exposes a long-running `serve`
command protected by capability-bearing credentials. Operator credentials can create,
cancel, and inspect runs; observer credentials can only inspect runs and
events. Remote/non-loopback deployment still needs TLS termination and transport
hardening.

### Running inside Gatekeeper

Gatekeeper can own the complete HTTP boundary—listener, TLS, path normalization,
authentication, and request delivery—while loading the harness as a pinned
in-process service function:

```sh
scripts/build_gatekeeper_function.sh
export HARNESS_JOURNAL_PATH="$HOME/.coil-agent-harness/gatekeeper.jsonl"
```

```toml
[[route]]
path = "/agents"
function = {
  library = "/absolute/path/to/coil-agent-harness/build/libcoil_agent_harness.dylib",
  lifecycle = "service"
}
# private by default
```

Requests such as `/agents/v1/runs/<id>` reach `RunService` as `/v1/runs/<id>`.
An authenticated `GET /agents` returns a plain-text, zero-context guide intended
to be handed directly to an agent. Request `GET /agents?format=json` or send
`Accept: application/json` for the same API as structured discovery metadata.
Gatekeeper authenticates the route and the adapter assigns the non-client-spoofable
`gatekeeper` actor with observe/control capability. No harness port or bearer token
is involved. `HARNESS_JOURNAL_PATH` selects the durable journal; when absent it
defaults to `gatekeeper-harness.jsonl` in Gatekeeper's working directory.
`HARNESS_WORKSPACE_PATH` selects the root used by the filesystem, search, and Bash
tool bundles; set it to a dedicated service-owned directory in deployments rather
than inheriting Gatekeeper's process directory.

The `service` lifecycle is mandatory: runs continue on background threads after
`gk_handle` returns. Gatekeeper therefore pins the dylib until process exit and a
new build is deployed by restarting Gatekeeper, never by hot-unmapping live code.

The version 1 service routes are `POST /v1/runs`,
`POST /v1/runs/{run_id}/cancel`, `GET /v1/runs/{run_id}`, and
`GET /v1/runs/{run_id}/events?after={sequence}`. Mutation bodies carry a
stable `command_id`; replaying the same command does not repeat its effect.

`GET /v1/runs/{run_id}/events/stream` is the incremental SSE form. It emits
durable event envelopes as `data:` records, uses the durable sequence cursor as
the SSE `id`, accepts either `?after=<sequence>` or `Last-Event-ID` for resume,
sends a keep-alive comment during idle periods, and closes after the run reaches
a terminal state. Model token deltas appear as `model.response.delta` events.
Gatekeeper performs authentication before opening the stream and owns HTTP
chunking, backpressure, and disconnect cleanup.

Runs with `"execution_target":"worker"` remain durably queued for an
out-of-process worker instead of launching inside the server. Worker control is part
of the native harness protocol; this repository no longer ships a separate script
client.

The repository also includes a working Markdown-defined software factory. Its
manifest contains a goal and reusable worker-role files, not a list of expected output
files. The harness itself loads the folder, creates the workspace, and runs each agent.
Every worker reports whether it considers its Markdown assignment complete and validated:

```sh
./harness factory run factories/snake
```

Scaffold a new generic Markdown-defined factory with one worker:

```sh
./harness factory new factories/my-factory
```

Provide ordered step names to create a multi-worker factory:

```sh
./harness factory new factories/my-factory architect implement verify
```

This creates `factory.json`, `context.md`, and `01-worker.md`. Edit those files to
describe the goal, shared context, tools, and worker behavior. The command refuses to
overwrite an existing path.

At run start, `context.md` is copied to the implementation workspace root. The rest of
the factory definition is copied under the hidden `.factory/definitions/` directory,
and its manifest points back to the root context. Workers receive the private hidden
snapshot's path and may edit any part of it. Before each phase, the coordinator reloads
`factory.json`, root `context.md`, worker ordering, worker Markdown, and tool groups.
This lets one phase revise what later phases receive without changing the reusable
source factory.

`factory.json` may also define shell commands around the whole flow and around each
worker invocation. A worker can remain a filename string, or use an object when it
needs its own commands:

```json
{
  "commands": {
    "before": ["git status --short"],
    "after": ["git add -A && git commit -m 'factory result'"],
    "before_each": ["git status --short"],
    "after_each": ["git status --short"]
  },
  "workers": [
    {
      "file": "01-implement.md",
      "provider": "codex",
      "model": "gpt-5.6-luna",
      "reasoning": "medium",
      "before": ["printf 'starting implementation\\n'"],
      "after": ["coil check"]
    },
    "02-verify.md"
  ]
}
```

`provider`, `model`, and `reasoning` are independently optional on every worker.
An omitted value inherits the run-level selection (`reasoning` currently defaults to
`medium`). Reasoning is an opaque provider-facing string: the factory runtime passes it
through unchanged and does not maintain an allowlist of provider-specific values.

Commands run in the implementation workspace in this order: flow `before`, global
`before_each`, worker `before`, the worker, worker `after`, global `after_each`, and
finally flow `after`. The per-worker sequence repeats for every invocation, including
workflow jumps. Commands in each list run in order and stop at the first nonzero exit
or timeout; that failure fails the run, and success-only later hooks do not run. Every
command emits `factory.command.started` followed by `factory.command.completed` or
`factory.command.failed`. Bash output uses the normal bounded-output and artifact
spooling behavior, so large command results are retained without flooding the journal.

With no workspace argument, the runner creates a fresh directory under
`.factory-workspaces/` and prints its path. Pass a workspace only when the factory is
intentionally modifying an existing codebase:

```sh
./harness factory run factories/snake /path/to/existing/codebase gpt-5.6-luna codex
```

Any additional arguments are readable context files appended to every worker's
Markdown prompt. This is the generic mechanism for supplying an issue, specification,
or other run-specific material.

For the common case of applying one issue to an existing codebase, use the named issue
form. It defaults to `gpt-5.6-luna` through the `codex` provider:

```sh
./harness factory issue factories/issues \
  --workspace /path/to/existing/codebase \
  --issue /path/to/issue.md
```

Use `--model` or `--provider` to override those defaults. The issue file is supplied as
run-specific context; the issue command does not add a separate issue model or hard-code
an issue tracker into the coordinator.

Factory workers have no arbitrary turn budget. Product-specific Markdown invariants
and cleanup workers enforce repository shape and release requirements without
hard-coding those policies into the generic coordinator. Factory, stage, worker-status,
model, and tool events are written to the printed Coil journal.

Every factory worker also receives generic workflow-control tools. `inspect_workflow`
reloads the private definition and returns its ordered worker files, the current worker
and index, and the completed execution history. Traversal continues to the following
worker by default. A worker can call `set_workflow_state` with `continue`, `complete`,
or `goto`; `goto` names any worker file in the live definition and may move forward or
backward. Each invocation still gets a new run identity even when a workflow loops back.

A create command can pin `provider` and `model`, or set both to `auto` and provide a
`routing_profile`. Optional `requires_harness_tools` and `requires_subscription`
constraints are checked against provider metadata. The resolved command persists a
`routing` object containing the request, selection, policy, reason, and capability
snapshot; restart recovery never silently reruns routing policy. Current profiles are:

- `balanced` (default): direct Codex HTTP via the local ChatGPT subscription;
- `low-cost`: DeepSeek, or Claude when subscription authentication is required;
- `quality`: OpenAI, or Claude when subscription authentication is required;
- `subscription`: Claude native tools;
- `external-agent`: Codex using the selected execution strategy.

A normal run's root `agent_id` equals its `run_id`. To delegate work, submit another
create command with a unique child `run_id` plus `parent_run_id`; the parent must
already exist. The service owns `agent_id` and `parent_agent_id` attribution and
replaces spoofed values. It persists `agent.delegated` and `agent.created` events plus
a versioned `message` of kind `delegation`; the child prompt is that message's content.
The child uses the ordinary durable scheduler, budgets, tools, cancellation,
queries, and recovery behavior rather than a second agent mechanism.
Delegated runs inherit the parent run's resolved provider and model by default, so
subscription authentication follows the same provider strategy automatically. In the
strict `spawn_subagent` tool schema, pass `provider: null` and `model: null` to inherit;
string values remain explicit per-child overrides.

## Build and verify

Requirements are COIL with its bundled HTTP dependency. Subscription OAuth, PKCE,
credential storage, and token refresh are implemented natively in the harness. The
Codex CLI is needed only when using the optional App Server strategy.

```sh
coil build
coil test --list
coil test --jobs 4
coil verify
sh scripts/check_file_size.sh
```

Launch the local interactive workbench with a durable journal:

```sh
./harness tui                 # creates a journal under ~/.coil-harness/runs/
./harness tui ./work.jsonl    # reopen a specific workspace
```

Set `HARNESS_STATE_DIR` to override the default `~/.coil-harness` state root.

Every submitted turn has a durable `conversation_id` distinct from its `run_id`.
Use `/conversation` to display it and `/new` to start another conversation. To
resume the same conversation after restarting the process, reopen its journal with
`HARNESS_CONVERSATION_ID=<id>`. The service reconstructs ordered user, assistant,
and harness-tool context from journal events; the TUI does not own or serialize a
private transcript.

Provider continuation is scoped by a canonical key containing provider, model,
instructions, reasoning settings, and the complete tool schema. OpenAI Responses
reuses `previous_response_id`; Codex records its thread ID and uses `thread/resume`.
On a key mismatch the runtime sends durable semantic history without the stale
provider continuation. Each structured `model.request.completed` payload records
`response_id`, `provider_session_id`, `cache_key`, and usage including
`cached_input_tokens`, so cache reuse is auditable in the journal.

Inspecting and monitoring do not require attaching to the process that owns a run.
The journal observer can project current state, print a filtered action trace, or
follow a live run. Filtering by run, agent, operation, parent operation, and event is
being moved into the native harness command surface.

`inspect` reports wall-clock elapsed time and open model/tool operations. `watch`
tails new journal events and refreshes that projection every five seconds without
taking the journal's writer lease.

The terminal opens as a conversational coding-agent client: enter a request at the
composer and watch model text, tool activity, delegation, workflow events, and
failures stream into one transcript. Slash commands such as `/agent`,
`/workflow`, `/status`, `/graph`, `/cancel`, and `/model` expose direct controls without
turning the primary experience into an operator menu. The runtime registry exposes
`bash`, `spawn_subagent`, `create_workflow_node`, `query_run`, and `query_workflow`, so
models can construct and coordinate the same durable agent trees and DAGs. A
registered tool runs as soon as its arguments satisfy its schema; the harness has no
permission layer and does not prompt before shell execution or file mutation.

The interface stays in the normal screen buffer, so terminal scrollback, selection,
copying, and search continue to work.

`/model` opens a picker rather than a text prompt: type to filter, then choose a
model and a reasoning-effort level (`low` through `max`). Filtering is fuzzy
subsequence matching over both the name and its description, so `sol` finds
`gpt-5.6-sol` and `op5` finds Claude Opus 5; a query that matches nothing leaves
the previous list up rather than blanking it. Models that reject an effort parameter — Haiku 4.5,
DeepSeek v4 flash — skip the second step and carry no level, so the picker never
offers a control that does nothing. The chosen effort rides on the durable create
command and is part of the provider prompt-cache key, so changing it correctly
misses the cache rather than silently reusing a prefix built at another level.
Pinning a model the picker does not list is still possible through the HTTP API;
the catalog is a shortlist, not an allowlist.

Typing `/` opens a completion menu beneath the composer: it filters as you type,
`↑`/`↓` move the selection, `Tab` extends to the longest shared prefix and then takes
the highlighted command, `Enter` takes the highlighted command unless what you typed
is already that command, and `Esc` dismisses it. Menu rows are transient — they are
erased on submit rather than committed to the transcript. An unrecognised `/command`
is reported instead of being sent to the model.

Line editing follows readline: `Ctrl-A`/`Ctrl-E` for line ends, `Alt-B`/`Alt-F` by
word, `Ctrl-W` and `Alt-Backspace` delete the previous word, `Alt-D` the next one,
`Ctrl-K` and `Ctrl-U` kill to the end and the start of the line, and `Ctrl-R` opens a
reverse history search whose prompt shows the query and the matched line. `Enter`
submits, `Ctrl-J` or `Shift-Enter` inserts a newline, `↑`/`↓` navigate history when no
menu is open, `Ctrl-C` interrupts active work, and `Ctrl-Z` restores the terminal
before suspending. `Esc` dismisses the completion menu or cancels a reverse search; it
cancels a run only while one is active, and does nothing at an idle composer.

Bracketed paste is enabled only while the editor owns the terminal; pasted newlines
and slash commands remain inert text until an explicit submission.

Tool calls render as one record per call with a bounded preview of what they
produced — the first lines of `bash` output, a byte count for a file write — and a
non-zero exit status is reported on the record even though the call itself succeeded.
Fenced code blocks in model output are highlighted per language (keywords, strings,
numbers, and comments) using semantic style roles, so `NO_COLOR` and screen-reader
profiles render the same code as plain text without losing the fence that marks it.

Coil automatically uses sequential, ANSI-free output when stdout is redirected, when
`TERM=dumb`, or when screen-reader mode is enabled. It respects `NO_COLOR`. The
following environment settings provide explicit compatibility overrides:

- `harness tui --plain [journal-path]` forces sequential output for one invocation.
- `COIL_TUI_PLAIN=1` forces the sequential renderer.
- `COIL_TUI_SCREEN_READER=1` selects plain labels and ASCII-safe output.
- `COIL_TUI_REDUCED_MOTION=1` disables optional motion.
- `COIL_TUI_COMPACT=1` removes redundant successful-state labels.
- `COIL_TUI_VERBOSE=1` includes bounded structured tool arguments and outcomes.
- `COIL_TUI_COLOR=always|never` overrides automatic color selection.
- `COIL_TUI_UNICODE=always|never` overrides locale-based Unicode detection.
- `COIL_TUI_WIDTH=<columns>` supplies a width when terminal probing is unavailable.

The supported interactive baseline is a POSIX TTY with relative cursor addressing
and erase-line support, including current macOS and common Linux terminals, tmux, and
SSH sessions. Other terminals degrade to the sequential renderer; Coil never requires
the alternate screen buffer.

The test suites are declared in `Coil.toml`. `coil verify` validates the manifest,
formatting, lint, every entry/test target graph, and all tests. The standalone
size-check script enforces the repository's 4,000-line guard. Neither command spends
model credits.

## Talking to Claude Code sessions

The harness speaks Claude Code's local cross-session protocol, so it can find
and message live Claude Code sessions on the same machine:

```sh
./harness peers                  # reachable sessions
./harness peers --all            # plus dead sockets and this session, marked
./harness send <peer> "message"  # deliver into a session's prompt queue
```

`<peer>` is a name, pid, session id, name prefix, or a raw `uds:` address or
socket path. A raw address skips the roster entirely, because reachability never
depended on registration.

The same protocol can run in a private namespace that has no contact with Claude
Code in either direction:

```sh
./harness peers --realm lab            # private namespace, same mechanism
./harness send --realm lab <peer> "hi"
HARNESS_BUS_REALM=lab ./harness peers  # or make it the default
```

`claude-code` is the default realm and is the only one that shares directories
with Claude Code. Any other name gets its own socket directory
(`harness-socks-<realm>`) and its own registry under `~/.coil-agent-harness`, so
peers in it are invisible to Claude Code and it cannot see them. Isolation is by
directory, which means a private realm still uses the same conformance-tested
envelope and discovery.

Discovery reads the socket directory and probes each entry by connecting, then
overlays names from `~/.claude/sessions/`. That ordering is deliberate: the
directory is the reachability graph and the registry is a cache of names over
it, so `harness peers` also finds unregistered peers that Claude Code's own
`ListAgents` cannot see.

Sending currently works; receiving does not — the harness binds no socket, so it
cannot be messaged or replied to. See [bus dialects](docs/agent-bus-dialects.md)
for the design and [known gaps](docs/bus-known-gaps.md) for what remains.

The wire format is reverse-engineered and is not a public API; it can change
without notice. The notes and a reference client live in
`docs/claude-code-cross-session-protocol/`. Checked-in conformance vectors are
exercised directly by the Coil test suite.

## Opt-in live provider tests

Real-network provider tests live under `integration/`, outside every configured source
and test root. Consequently, neither plain `coil test` nor `coil verify` can discover
or spend credits on them. Run each file explicitly when you want to exercise live
credentials:

```sh
# ChatGPT subscription through the locally authenticated Codex CLI
coil test integration/codex_live_integration.coil

# Claude subscription; requires ANTHROPIC_OAUTH_TOKEN
coil test integration/claude_live_integration.coil

# OpenAI API billing; requires OPENAI_API_KEY or OPENAI_KEY
coil test integration/openai_live_integration.coil

# DeepSeek API billing; requires DEEPSEEK_API_KEY or DEEPSEEK_KEY
coil test integration/deepseek_live_integration.coil
```

The OpenAI and Codex tests use the efficient `gpt-5.6-luna` model. API suites include
both a minimal streaming completion and a forced `echo` tool roundtrip. The Codex
adapter registers the harness registry as App Server dynamic tools and dispatches
`item/tool/call` requests through the same executor as other providers.

The optional nesting metaprogram warns only when a function body exceeds 24 nested
surface expressions. Run `coil lint src/main.coil --use harness.nesting-depth` to
enable it, or override its threshold with
`--lint-param harness.nesting-depth.maximum=40`. It runs before macro expansion and counts nested s-expressions, including
ordinary nested calls; it does not detect nested function definitions or indicate a
correctness/runtime problem. The advisory is intentionally not part of the default
lint set because expression-tree depth is only a weak maintainability signal. See
`tools/nesting_depth.coil` for the metric.

## Credentials

Provider credentials are read only inside provider adapters:

- OpenAI: `OPENAI_API_KEY`, with `OPENAI_KEY` as a fallback;
- OpenRouter: `OPENROUTER_API_KEY`;
- DeepSeek: `DEEPSEEK_API_KEY`, with `DEEPSEEK_KEY` as a fallback;
- Codex subscription: run `./harness login codex`. Harness credentials are stored
  separately at `~/.coil-agent-harness/codex-auth.json`; an existing Codex CLI login
  remains a migration fallback.
- Claude subscription: run `./harness login claude`. OAuth credentials are stored at
  `~/.coil-agent-harness/auth.json` with mode `0600` and refreshed automatically under
  a cross-process lock. `ANTHROPIC_OAUTH_TOKEN` and `ANTHROPIC_AUTH_TOKEN` remain
  environment overrides; never pass credentials as CLI arguments.

Both subscription login commands implement OAuth PKCE in Coil, open the authorization
page, validate the loopback callback state, and fall back to accepting the final
redirect URL or authorization code in the terminal. Credential replacement is
create-at-`0600`, fsynced, and atomically renamed while holding the provider lock.

Credentials are used to construct request headers and are never included in emitted
events. Do not pass a credential as a CLI argument.

Codex execution is strategy-based. The default is the fast OpenCode-style direct HTTP
strategy against ChatGPT's private Codex Responses endpoint. That endpoint is not a
documented third-party OpenAI API and may change without notice. Set
`HARNESS_CODEX_STRATEGY=app-server` to use the supported App Server compatibility path.
Direct credentials refresh automatically under a cross-process lock. For isolated
testing, credentials may instead be supplied through `HARNESS_CODEX_ACCESS_TOKEN` and
`HARNESS_CODEX_ACCOUNT_ID`; never put them in command arguments.

The harness has no permission or approval layer. Registration is the only gate: a tool
in the registry runs whenever the model calls it with schema-valid arguments, including
`bash` and the file-mutation tools. Point a run at a workspace you are willing to let it
change. Policy, if it returns, belongs in an out-of-tree plugin rather than in the
runtime contract.

## Run a smoke request

```sh
./harness run openai gpt-5.6 "Answer with one short sentence."
./harness tool deepseek-openai deepseek-v4-flash "Call echo with the text hello."
./harness tool deepseek-anthropic deepseek-v4-flash "Call echo with the text hello."
./harness run codex gpt-5.6-terra "Briefly describe this repository."
./harness run claude claude-sonnet-4-6 "Briefly describe this repository."
./harness tool claude claude-sonnet-4-6 "Call echo with the text hello."
HARNESS_AUTH_TOKEN='replace-me' ./harness serve 8080 ./harness-events.jsonl
```

Use `run` for automatic tool selection and `tool` to force the built-in strict `echo`
tool. The final model answer is written to stdout. Versioned lifecycle events are
written as one JSON object per line to stderr, so a controller can consume the two
streams independently.

The model name is always explicit. Current sensible defaults are shown above, but the
runtime does not hard-code a provider's model catalogue.

Service requests use `Authorization: Bearer ...`. Set `HARNESS_OPERATOR_TOKEN` for a
principal with observe/control capabilities and optionally `HARNESS_OBSERVER_TOKEN`
for a read-only principal. `HARNESS_AUTH_TOKEN` remains a compatibility fallback for
the operator credential. Mutation payloads cannot choose their durable actor identity;
the service overwrites `actor` with the authenticated principal. The filesystem tools
accept lexically root-relative paths, reject parent traversal, and cap reads and writes
at one MiB. They are host capabilities, not a sandbox: filesystem symlinks are followed,
so deployments that need isolation must place the harness in an OS sandbox or container.

## Module map

```text
src/core/       Provider-neutral JSON, events, models, tools, schema validation
src/runtime/    Bounded model/tool loop, background handle, parallel tool executor
src/providers/  OpenAI Responses, Anthropic Messages, DeepSeek dialects, Codex
src/config/     Operator-declared providers and projects, read from ~/.coil-agent-harness
src/factory/    Markdown-defined workflows: manifest, workspace, coordinator, status
src/infra/      HTTP, synchronization, signals, sockets, and allocation adapters over Coil stdlib APIs
src/persistence/ Append-only event journal and recovery
src/service/     Durable run projection, versioned API routing, and HTTP serving
tests/          Deterministic unit, contract, concurrency, and runtime tests
```

COIL places build products under `.coil/build/`; source directories remain free of
generated build products.

Provider adapters own URLs, authentication, request/response formats, and preservation
of provider-specific continuation state. Runtime code never switches on a provider
name. Tool proposal, schema validation, and execution are separate steps, each
represented by lifecycle events.

OpenAI and both DeepSeek dialects share an injectable streaming HTTP transport. The
production implementation uses libcurl with bounded synchronous chunk delivery;
provider contract tests replace it with an in-memory byte stream while exercising the
same SSE decoders and provider execution paths. Codex direct mode uses the same bounded
HTTP streaming boundary; its optional App Server strategy retains the JSONL subprocess
transport for bidirectional RPC.
Claude uses native Anthropic Messages with OAuth identity headers. Structured
`tool_use` and `tool_result` blocks flow through the harness's normal validation,
execution, continuation, and event lifecycle.

## Important current behavior

- A run has no time limit unless the command asks for one. `timeout_ms` on a create
  command sets that run's deadline and is honoured verbatim -- there is no default
  and no ceiling. Omit it, and the run ends only by finishing, failing, or being
  cancelled, which is the normal case for a task. Three separate bounds used to be
  derived from one number; they are now distinct: the transport timeout bounds a
  single HTTP request to the provider, each `ToolSpec` carries its own `timeout_ms`
  (zero for unbounded), and the run deadline is the opt-in one above. Conflating
  them meant an expired run clock rejected later tool calls before running them, so
  a `read_text_file` that never touched the disk reported a deadline error.

- OpenAI uses strict Responses API function definitions and `function_call_output`
  continuation items keyed by `call_id`. Responses are decoded incrementally from
  SSE and text deltas are emitted as they arrive.
- DeepSeek OpenAI-compatible strict tools use its beta endpoint. On a continuation,
  the full previous assistant message is replayed so `reasoning_content` is retained.
  Streaming reconstructs reasoning, indexed tool-call fragments, and final usage.
- DeepSeek Anthropic compatibility uses `tool_use` and `tool_result` content blocks.
  Its stream reconstructs text, signed thinking blocks, fragmented tool inputs, and
  usage without losing the opaque continuation content.
- Codex defaults to direct subscription HTTP with `store=false`, conversation-scoped
  prompt-cache affinity, streamed output-item reconstruction, and encrypted reasoning
  replay for tool continuations. `HARNESS_CODEX_STRATEGY=app-server` selects the
  persistent JSONL App Server fallback.
- A registered tool executes as soon as its arguments validate. There is no
  permission check, and no interactive approval pause in TUI or server runs.
- Parallel tool results retain model call order even when completion order differs.
- Concurrent event publication is serialized across sequence assignment and journal
  append, so durable records are written in ascending `sequence` order.
- Every wire event uses the same versioned envelope. Tool events carry their model
  request as `parent_operation_id`, and every run emits exactly one terminal event.
- Background handles require the request, provider context, emitter, and allocator to
  remain alive until `agent-run-join` returns.
- Runs carry one atomic cancellation token and one absolute monotonic deadline.
  Background callers can request cancellation with `agent-run-cancel!`; a late model
  success cannot override cancellation or timeout. Tool handlers receive a
  `ToolExecutionContext` and overruns are returned as tool failures. In-process tools
  are cooperative and cannot be safely preempted by the hosted thread API.
- Version 1 workflows compose ordinary durable runs into DAGs. Nodes are admitted in
  topological order, wait for all predecessors, emit durable node lifecycle events,
  and remain visible through `GET /v1/workflows/{workflow_id}`. Failed or cancelled
  dependencies skip downstream nodes without invoking a provider.
- Operator-capable supervisors can record idempotent structured assessments and
  request cancellation interventions through public HTTP commands. Assessment,
  request, application, and rejection events remain visible in each run's journal;
  interventions reuse the ordinary cancellation state machine.

## Next architectural slice

The implemented core now spans durable agents, workflow DAGs, explainable routing,
production tools, and auditable supervision. The next roadmap pass should prioritize
operational hardening and measured gaps rather than introducing another execution
mechanism. All current provider adapters emit incremental text deltas with bounded
synchronous backpressure.

See [the roadmap audit](docs/roadmap-audit.md) for the completed slices.
