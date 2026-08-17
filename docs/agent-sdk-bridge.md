# Claude Agent SDK provider

`agent-sdk` is a normal harness `ModelProvider`. The official Claude Agent SDK
owns the model loop; Coil owns the tool registry, schema validation, execution,
deadlines, effects, and journal events.

## Setup

The provider's private host requires Node and the SDK package:

    npm install --prefix agent-sdk
    claude --version

The Claude CLI must already be authenticated. No harness server, URL, port, or
token is involved.

## Use

Use the provider anywhere another provider name is accepted:

    ./harness run agent-sdk '' "Use the echo tool to echo READY"
    ./harness factory run factories/snake-feature examples/snake-gui '' agent-sdk
    ./harness factory issue factories/snake-issue \
      --workspace examples/snake-gui \
      --issue /absolute/path/to/issue.md \
      --model '' \
      --provider agent-sdk

An empty model selects the SDK/Claude default. A supported Claude model name may
be supplied explicitly.

## Boundary

Coil starts `agent-sdk/src/provider.ts` as a private newline-delimited JSON stdio
child. It sends the prompt, system instructions, model, working directory, and
the harness registry's JSON Schemas. The SDK host exposes those schemas through
an in-process MCP server. It has no Claude Code built-in tools and reads no user
or project settings. `strictMcpConfig` is enabled, so account-level or locally
configured MCP connectors are excluded as well; `harness` is the only MCP server.

When the model calls a tool, the host sends a `tool_call` message to Coil. Coil
runs it through `execute-tools-parallel`, which performs the same lookup, schema
validation, cancellation/deadline handling, and event publication used by the
ordinary harness loop. The result returns to the SDK over the same private stdio
channel. The final assistant text becomes the provider's `ModelResponse`.

The implementation still uses Node internally because the official SDK is a
TypeScript package. That is an implementation dependency, not a second user-facing
workflow.

## Verification

    npm --prefix agent-sdk run typecheck
    npm --prefix agent-sdk test
    coil test tests/runtime_controller_test.coil

For a real workflow, run the Snake command above and inspect its journal under
`.factory-runs/snake-wrap-feature/`; model and tool events should report
`"provider":"agent-sdk"` and end with `factory.run.completed`.
