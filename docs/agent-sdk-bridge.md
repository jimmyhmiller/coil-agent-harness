# Claude Agent SDK bridge

The Agent SDK is the only official Claude agent harness. This branch runs it as
the loop while the coil harness supplies every tool, so we keep our registry,
effect classification, and journal without reimplementing an agent loop. The
bridge lives in `agent-sdk/` and is TypeScript, on `@anthropic-ai/claude-agent-sdk`.

## Passing JSON Schema through TypeScript

Our `ToolSpec` already carries a JSON Schema. The SDK's `tool()` helper — and
`registerTool` under it — takes a Zod schema (`AnySchema` in the MCP SDK is
`z3.ZodTypeAny | z4.$ZodType`), so building the server that way would mean
translating every harness schema into Zod and letting the MCP server translate
it back to JSON Schema for `tools/list`. That is a lossy layer that has to be
kept in sync with the registry, and anything Zod can't express is lost twice.

MCP is JSON Schema on the wire, so the bridge skips the helper and sets the
low-level `tools/list` and `tools/call` handlers on the server instance itself
(`createHarnessMcpServer` in `src/harness.ts`). The harness's own schema is
what reaches the model, untouched, and there is no second schema to maintain.
The result is still a real `McpServer`, so it drops straight into
`mcpServers: { harness: { type: 'sdk', name, instance } }`.

## How full control is obtained

Four options, all set in `buildOptions`:

| Option | Effect |
|---|---|
| `tools: []` | Removes every built-in Claude Code tool. The model's entire capability surface is the harness registry. |
| `settingSources: []` | Stops `~/.claude` and project settings from being read, so a run is reproducible from the source alone. |
| `systemPrompt: <string>` | A prompt we own, not the `claude_code` preset — none of Claude Code's instructions leak in. |
| `canUseTool` | Every permission decision is forwarded to the harness instead of being decided by the SDK. |

Tools are deliberately left out of `allowedTools`: listing them there would
pre-approve calls and bypass `canUseTool`, which is the hook that keeps the
harness as the single authority.

Effect classification maps onto MCP annotations. `readOnlyHint` is the only one
the SDK acts on — it allows parallel calls — so it tracks `ToolEffect::ReadOnly`
exactly. `destructiveHint` and `idempotentHint` carry the harness's own
classification through for display.

## Transport

The bridge talks to `harness serve` over its existing localhost HTTP service
with `fetch`, so the SDK and its MCP peer dependency are the only dependencies.
The service accepts one connection at a time, so concurrent read-only calls are
serialized at the harness boundary — `readOnlyHint` does not buy real
parallelism until the listener does.

Three endpoints carry it, all on the run service:

- `GET  /v1/tools` — `{version, tools: [{name, description, input_schema, effect, idempotent, timeout_ms}]}`.
  Requires the observe capability.
- `POST /v1/tools/authorize` — `{name, arguments}` in, `{authorized, reason, effect}` out.
- `POST /v1/tools/call` — `{name, arguments, session_id?, call_id?}` in,
  `{status, output, error, call_id, session_id, started_at_ms, finished_at_ms}` out.
  `status` is the harness's own `succeeded` / `errored` / `denied` / `unknown`.

The registry belongs to the runtime controller, so the service reaches all three
through the `RunController` trait rather than aliasing the registry pointer. A
controller without a registry answers 501, which is why a service backed by a
test double reports "no tool plane" instead of an empty catalog.

Every executed call is a 200 — including an unknown tool and a schema denial.
The caller is a model loop: it has to read a refusal as a tool result it can act
on, not as a transport failure. Only a malformed request (no tool name, invalid
JSON) is a 4xx.

Nothing in these endpoints is specific to the SDK or to TypeScript; any external
loop can drive them.

## Resolved decisions

**Bridged calls are journaled, but the harness does not manufacture a run.**
Calls run through `execute-tools-parallel`, the same path an in-harness run
uses, so each one is schema-validated, bounded by its tool's own `timeout_ms`,
and emits `tool.call.proposed` / `started` / `completed` / `failed` with
`provider: "agent-sdk"`. The bridge sends a `session_id` and the harness uses it
as the run ID on those events, so a session reads back through the existing
`GET /v1/runs/<session_id>/events`.

What the harness deliberately does not do is open a run around the session. The
SDK owns that lifecycle and never tells us when it ends; a synthesized run would
sit in `running` forever and lie about a state we cannot observe. The session ID
is an operation grouping in the journal, nothing more.

Cancellation and the run clock stay with the loop that owns the task for the
same reason. The caller's HTTP timeout bounds a request; each tool still carries
its own deadline from its spec.

**Authorization is registry membership plus schema validation.** A registered
tool whose arguments satisfy its own schema is authorized, and nothing else is.
There is no effect-based policy layer in the harness to delegate to, so the
endpoint does not pretend to consult one — it reports `effect` alongside the
decision and a caller that wants to refuse everything destructive can do so on
what it reads there. `canUseTool` remains the correct hook for the day a policy
layer lands: the decision moves behind this endpoint and the bridge does not
change.

## Setup

The SDK drives the `claude` CLI, which must be installed and authenticated
separately (`claude --version`). Node 22.18 or newer runs the bridge's
TypeScript directly, so there is no build step.

    npm install --prefix agent-sdk

## Running

    ./harness serve 8080 events.jsonl            # in one terminal
    export HARNESS_TOKEN=...                     # same token harness serve was given
    node agent-sdk/src/main.ts "summarize the src tree"
    node agent-sdk/src/main.ts                   # interactive

`--session-id` pins the run ID the calls are journaled under; otherwise a fresh
one is generated and printed at startup. `--url`, `--model`, `--cwd`, and
`--max-turns` are the other flags.

## Tests

    python3 scripts/tool_plane_e2e_test.py ./harness   # harness side, stdlib only
    npm --prefix agent-sdk test                        # bridge side, no model
    npm --prefix agent-sdk run test:live               # one real model turn
    sh scripts/e2e.sh --live-agent-sdk                  # full sweep, SDK instead of Codex

`scripts/tool_plane_e2e_test.py` covers the HTTP contract with nothing but the
standard library, so it runs in the ordinary `scripts/e2e.sh` sweep.
`agent-sdk/test/bridge-test.ts` starts a real `harness serve` and drives the
bridge the way the CLI does — over an in-memory MCP transport, asserting the
schema arrives untouched, plus the permission handler and the journal. It joins
the sweep whenever `agent-sdk/node_modules` exists.
`agent-sdk/test/live-test.ts` spends one model turn to prove the last link: that
the CLI reaches the in-process server, that `canUseTool` is consulted, and that
the call lands in the journal. It exits 77 when the `claude` CLI is missing.

Coil-side coverage: `tool-plane-describes-authorizes-and-invokes-registered-tools`
in `tests/runtime_controller_test.coil` for the registry and journal behaviour,
`tool-plane-routes-are-capability-gated` in `tests/run_service_test.coil` for
routing, capabilities, and the 501.
