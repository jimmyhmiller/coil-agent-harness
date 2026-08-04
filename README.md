> This is experimental software. It probably doesn't work.

# COIL Agent Harness

This repository contains the first vertical slice of a headless, observable agent
runtime written in COIL. The durable architectural rules live in [agent.md](agent.md).

The current slice can:

- call OpenAI through the Responses API;
- call DeepSeek through its OpenAI-compatible and Anthropic-compatible APIs;
- use Codex as an external agent through the Codex App Server JSONL protocol;
- use Claude subscriptions through native Anthropic Messages and OAuth authentication;
- advertise provider capabilities and durably resolve explicit `balanced`, `low-cost`,
  `quality`, `subscription`, and `external-agent` routing profiles;
- assign every event a stable `agent_id` and execute delegated child agents as durable,
  independently cancellable child runs with typed delegation messages;
- expose one provider-neutral model, continuation, tool, authorization, result, and
  event contract;
- validate tool arguments before authorization;
- execute independent tool calls concurrently with an explicit concurrency bound;
- continue the model with ordered tool results while preserving opaque provider state;
- run the entire model/tool loop on a background worker and join it later;
- emit structured JSON event records suitable for a terminal, server, or future UI;
- append those versioned events to an fsync-backed journal and recover ordered history
  while safely ignoring a torn final record;
- accept versioned create, cancel, run-query, and cursor-based event-query commands
  through a loopback HTTP service boundary;
- pause tool execution for durable interactive authorization decisions, with
  idempotent allow/reject commands and fail-closed cancellation or expiry;
- rebuild durable run state on restart, relaunch work that was only queued, and
  terminalize work whose in-process outcome can no longer be known;
- hold a kernel-backed exclusive writer lease for each journal, rejecting a second
  harness process before it can duplicate recovery or side effects;
- expose bounded `read_text_file`, `write_text_file`, `create_directory`, `delete_file`,
  and empty-only `remove_directory` tools to service runs, with traversal checks,
  effect metadata, deadlines, cancellation, and interactive approval.

The HTTP listener binds to IPv4 loopback and the CLI exposes a long-running `serve`
command protected by capability-bearing credentials. Operator credentials can create,
cancel, inspect, and authorize runs; observer credentials can only inspect runs and
events. Remote/non-loopback deployment still needs TLS termination and transport
hardening.

The version 1 service routes are `POST /v1/runs`,
`POST /v1/runs/{run_id}/cancel`, `GET /v1/runs/{run_id}`,
`GET /v1/runs/{run_id}/events?after={sequence}`, and
`POST /v1/runs/{run_id}/authorizations/{authorization_id}`. Mutation bodies carry a
stable `command_id`; replaying the same command does not repeat its effect.

A create command can pin `provider` and `model`, or set both to `auto` and provide a
`routing_profile`. Optional `requires_harness_tools` and `requires_subscription`
constraints are checked against provider metadata. The resolved command persists a
`routing` object containing the request, selection, policy, reason, and capability
snapshot; restart recovery never silently reruns routing policy. Current profiles are:

- `balanced` (default): Claude native tools via subscription OAuth;
- `low-cost`: DeepSeek, or Claude when subscription authentication is required;
- `quality`: OpenAI, or Claude when subscription authentication is required;
- `subscription`: Claude native tools;
- `external-agent`: Codex App Server.

A normal run's root `agent_id` equals its `run_id`. To delegate work, submit another
create command with a unique child `run_id` plus `parent_run_id`; the parent must
already exist. The service owns `agent_id` and `parent_agent_id` attribution and
replaces spoofed values. It persists `agent.delegated` and `agent.created` events plus
a versioned `message` of kind `delegation`; the child prompt is that message's content.
The child uses the ordinary durable scheduler, budgets, tools, authorization,
cancellation, queries, and recovery behavior rather than a second agent mechanism.

## Build and verify

Requirements are COIL with its bundled HTTP dependency installed and the `codex` CLI
installed and authenticated for Codex. Claude subscription use requires an OAuth token.

```sh
coil build -O1
coil test --list
coil test --jobs 4
coil verify
sh scripts/check_file_size.sh
sh scripts/e2e.sh
```

The test suites are declared in `Coil.toml`. `coil verify` validates the manifest,
formatting, lint, every entry/test target graph, and all tests. The standalone
size-check script enforces the repository's 4,000-line guard. Neither command spends
model credits.

The end-to-end script exercises the compiled binary over real sockets, including
authentication, command replay, failure projection, journal recovery, and graceful
shutdown. Its default mode makes no model calls. Run `sh scripts/e2e.sh --live-codex`
to add two minimal live Codex App Server checks using the lower-cost
`gpt-5.6-luna` model.

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
both a minimal streaming completion and a forced `echo` tool roundtrip; Codex App
Server owns its own tool registry, so its suite covers the full RPC streaming lifecycle
without claiming to test the harness tool executor.

The configured nesting metaprogram prints authored expression depth by function,
module, and program. Run `coil lint src/main.coil --use harness.nesting-depth` for
one application-graph report (file-mode lint requires the explicit `--use`).
It runs before macro expansion and measures the surface syntax exactly as written;
see `tools/nesting_depth.coil` for the metric.

## Credentials

Provider credentials are read only inside provider adapters:

- OpenAI: `OPENAI_API_KEY`, with `OPENAI_KEY` as a fallback;
- DeepSeek: `DEEPSEEK_API_KEY`, with `DEEPSEEK_KEY` as a fallback;
- Codex: the existing Codex CLI login/session.
- Claude subscription: run `./harness login claude`. OAuth credentials are stored at
  `~/.coil-agent-harness/auth.json` with mode `0600` and refreshed automatically under
  a cross-process lock. `ANTHROPIC_OAUTH_TOKEN` and `ANTHROPIC_AUTH_TOKEN` remain
  environment overrides; never pass credentials as CLI arguments.

Claude login requires Python 3, opens the authorization page in your browser, and
falls back to accepting the final redirect URL in the terminal. Run
`./harness logout claude` to remove the stored credentials. Installed or relocated
builds can set `HARNESS_CLAUDE_OAUTH_HELPER` to the absolute path of
`scripts/claude_oauth.py`.

Credentials are used to construct request headers and are never included in emitted
events. Do not pass a credential as a CLI argument.

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
src/infra/      HTTP/time adapters plus a narrow POSIX lifecycle and allocator shim
src/persistence/ Append-only event journal and recovery
src/service/     Durable run projection, versioned API routing, and HTTP serving
schemas/codex/  Generated schemas for the locally installed Codex App Server protocol
tests/          Deterministic unit, contract, concurrency, and runtime tests
```

COIL places build products under `.coil/build/`; source directories remain free of
generated build products.

Provider adapters own URLs, authentication, request/response formats, and preservation
of provider-specific continuation state. Runtime code never switches on a provider
name. Tool proposal, schema validation, authorization, and execution are separate
steps, each represented by lifecycle events.

OpenAI and both DeepSeek dialects share an injectable streaming HTTP transport. The
production implementation uses libcurl with bounded synchronous chunk delivery;
provider contract tests replace it with an in-memory byte stream while exercising the
same SSE decoders and provider execution paths. Codex retains its separate JSONL
subprocess transport because its bidirectional RPC lifecycle is not HTTP streaming.
Claude uses native Anthropic Messages with OAuth identity headers. Structured
`tool_use` and `tool_result` blocks flow through the harness's normal validation,
authorization, execution, continuation, and event lifecycle.

## Important current behavior

- OpenAI uses strict Responses API function definitions and `function_call_output`
  continuation items keyed by `call_id`. Responses are decoded incrementally from
  SSE and text deltas are emitted as they arrive.
- DeepSeek OpenAI-compatible strict tools use its beta endpoint. On a continuation,
  the full previous assistant message is replayed so `reasoning_content` is retained.
  Streaming reconstructs reasoning, indexed tool-call fragments, and final usage.
- DeepSeek Anthropic compatibility uses `tool_use` and `tool_result` content blocks.
  Its stream reconstructs text, signed thinking blocks, fragmented tool inputs, and
  usage without losing the opaque continuation content.
- Codex is launched as `codex app-server --listen stdio://`. The adapter initializes a
  session, starts a thread and turn, converts notifications to harness events, and has
  pure builders for steering and interrupt requests. Its current one-shot CLI adapter
  rejects interactive server requests rather than silently approving them.
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

See [the roadmap audit](docs/roadmap-audit.md) for the completed slices and the one
remaining product boundary: interactive Codex App Server approval RPCs need a scoped
authorization capability added to the provider/runtime contract.
