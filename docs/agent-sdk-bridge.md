# Claude Agent SDK bridge

The Agent SDK is the only official Claude agent harness. This branch runs it as
the loop while the coil harness supplies every tool, so we keep our registry,
effect classification, and journal without reimplementing an agent loop.

## Why Python, not TypeScript

Our `ToolSpec` already carries a JSON Schema. The Python `@tool` decorator
accepts a full JSON Schema dict directly; the TypeScript `tool()` helper accepts
only Zod. A TypeScript host would need a JSON-Schema-to-Zod translation layer
that must stay in sync with the harness and loses anything Zod can't express.
Python passes the schema through untouched. That is the whole reason for the
language choice.

## How full control is obtained

Four options, all set in `build_options`:

| Option | Effect |
|---|---|
| `tools=[]` | Removes every built-in Claude Code tool. The model's entire capability surface is the harness registry. |
| `setting_sources=[]` | Stops `~/.claude` and project settings from being read, so a run is reproducible from the source alone. |
| `system_prompt=<string>` | A prompt we own, not the `claude_code` preset — none of Claude Code's instructions leak in. |
| `can_use_tool` | Every permission decision is forwarded to the harness instead of being decided by the SDK. |

Tools are deliberately left out of `allowed_tools`: listing them there would
pre-approve calls and bypass `can_use_tool`, which is the hook that keeps the
harness as the single authority.

Effect classification maps onto MCP annotations. `readOnlyHint` is the only one
the SDK acts on — it allows parallel calls — so it tracks `ToolEffect::ReadOnly`
exactly. `destructiveHint` and `idempotentHint` carry the harness's own
classification through for display.

## Transport

The host talks to `harness serve` over its existing localhost HTTP service using
only the standard library, so the SDK is the sole dependency. Blocking requests
run on worker threads via `asyncio.to_thread`, so parallel read-only tool calls
do not stall the SDK event loop.

Three endpoints are required on the harness side:

- `GET  /v1/tools` — project each `ToolSpec` as `{name, description, input_schema, effect, idempotent}`
- `POST /v1/tools/call` — execute one tool, returning `{status, output, error}`
- `POST /v1/tools/authorize` — the decision point behind `can_use_tool`

## Open decisions

**1. Should bridge tool calls be journaled as a harness run?** The harness's
value is the durable journal, cancellation, and deadlines. If the SDK calls
tools out-of-band, none of that applies and the bridge is a thin RPC shim. If
each SDK session opens a harness run and every call is journaled under it, we
keep the audit trail and cancellation while the SDK drives the model. The second
is the better architecture and changes the endpoint shape (calls carry a session
id), so it is worth deciding before the endpoints are written.

**2. Authorization is currently allow-all.** `runtime-authorizer` in
`src/service/runtime_controller.coil` returns `AllowAllAuthorizer`, with a
comment that policy is still to come. `can_use_tool` is therefore the correct
hook but currently delegates to a permissive authority. Either the authorize
endpoint implements effect-based policy at the boundary now, or the bridge
inherits allow-all until the policy layer lands.

## Status

`agent_sdk/` is complete and compiles. The three harness endpoints are not yet
implemented — they depend on decision 1 above.
