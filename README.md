> This is experimental software. It probably doesn't work.

# COIL Agent Harness

This repository contains the first vertical slice of a headless, observable agent
runtime written in COIL. The durable architectural rules live in [agent.md](agent.md).

The current slice can:

- call OpenAI through the Responses API;
- call DeepSeek through its OpenAI-compatible and Anthropic-compatible APIs;
- use Codex as an external agent through the Codex App Server JSONL protocol;
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
- expose bounded `read_text_file` and `write_text_file` tools to service runs, with
  traversal checks, effect metadata, deadlines, cancellation, and interactive approval.

The HTTP listener binds to IPv4 loopback and the CLI exposes a long-running `serve`
command protected by a required bearer token. Remote/non-loopback deployment still
needs TLS termination, identity-aware authorization, and transport hardening.

The version 1 service routes are `POST /v1/runs`,
`POST /v1/runs/{run_id}/cancel`, `GET /v1/runs/{run_id}`,
`GET /v1/runs/{run_id}/events?after={sequence}`, and
`POST /v1/runs/{run_id}/authorizations/{authorization_id}`. Mutation bodies carry a
stable `command_id`; replaying the same command does not repeat its effect.

## Build and verify

Requirements are COIL with its bundled HTTP dependency installed and (for Codex) the
`codex` CLI installed and authenticated.

```sh
coil build -O1
coil test --list
coil test --jobs 4
coil verify
sh scripts/check_file_size.sh
```

The test suites are declared in `Coil.toml`. `coil verify` validates the manifest,
formatting, lint, every entry/test target graph, and all tests. The standalone
size-check script enforces the repository's 4,000-line guard. Neither command spends
model credits.

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

Credentials are used to construct request headers and are never included in emitted
events. Do not pass a credential as a CLI argument.

## Run a smoke request

```sh
./harness run openai gpt-5.6 "Answer with one short sentence."
./harness tool deepseek-openai deepseek-v4-flash "Call echo with the text hello."
./harness tool deepseek-anthropic deepseek-v4-flash "Call echo with the text hello."
./harness run codex gpt-5.6-terra "Briefly describe this repository."
HARNESS_AUTH_TOKEN='replace-me' ./harness serve 8080 ./harness-events.jsonl
```

Use `run` for automatic tool selection and `tool` to force the built-in strict `echo`
tool. The final model answer is written to stdout. Versioned lifecycle events are
written as one JSON object per line to stderr, so a controller can consume the two
streams independently.

The model name is always explicit. Current sensible defaults are shown above, but the
runtime does not hard-code a provider's model catalogue.

Service requests use `Authorization: Bearer $HARNESS_AUTH_TOKEN`. The filesystem tools
accept lexically root-relative paths, reject parent traversal, and cap reads and writes
at one MiB. They are host capabilities, not a sandbox: filesystem symlinks are followed,
so deployments that need isolation must place the harness in an OS sandbox or container.

## Module map

```text
src/core/       Provider-neutral JSON, events, models, tools, schema validation
src/runtime/    Bounded model/tool loop, background handle, parallel tool executor
src/providers/  OpenAI Responses, two DeepSeek dialects, Codex App Server
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

## Next architectural slice

The next slice should add identity-aware capabilities beyond the shared bearer token
and durable admission control across multiple harness processes. Additional production
tools can then grow behind the same provider-neutral validation, authorization,
timeout, cancellation, output bound, and event contracts. All current provider
adapters emit incremental text deltas with bounded synchronous backpressure.
