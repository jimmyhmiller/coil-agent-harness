/**
 * Bridge between the coil harness tool registry and the Claude Agent SDK.
 *
 * The Agent SDK owns the agent loop; the harness owns every tool.
 *
 * Three options give us full control over what the model can reach:
 *
 *   * `tools: []` removes every built-in Claude Code tool, so the model's
 *     entire capability surface is whatever the harness registry exposes.
 *   * `settingSources: []` stops ~/.claude and project settings from being
 *     read, so a run is reproducible from this file alone.
 *   * `systemPrompt` is a plain string we own rather than the `claude_code`
 *     preset, so none of Claude Code's own instructions leak in.
 *
 * Authorization stays in one place: `canUseTool` forwards the decision to the
 * harness, which already owns the effect classification. The SDK never makes a
 * policy decision of its own.
 *
 * Only the SDK and its MCP peer dependency are dependencies; the harness is
 * reached over its existing HTTP service with `fetch`.
 */

import type { CanUseTool, McpServerConfig, Options } from '@anthropic-ai/claude-agent-sdk'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type ToolAnnotations,
} from '@modelcontextprotocol/sdk/types.js'

export const SERVER_NAME = 'harness'

/**
 * The harness classifies every tool by effect. These are the only three values
 * it emits; anything else means the harness and this bridge are out of sync.
 */
const READ_ONLY = 'read_only'
const REVERSIBLE = 'reversible'
const DESTRUCTIVE = 'destructive'

const EFFECTS = new Set([READ_ONLY, REVERSIBLE, DESTRUCTIVE])

/** The harness was reachable but rejected or failed the request. */
export class HarnessError extends Error {}

/** One tool as the harness describes it. */
export type ToolSpec = {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  effect: string
  idempotent: boolean
}

function toolSpecFrom(raw: Record<string, unknown>): ToolSpec {
  const effect = raw.effect
  if (typeof effect !== 'string' || !EFFECTS.has(effect)) {
    throw new HarnessError(
      `tool ${JSON.stringify(raw.name)} has unknown effect ${JSON.stringify(effect)}; ` +
        'the harness registry and this bridge disagree',
    )
  }
  return {
    name: raw.name as string,
    description: raw.description as string,
    inputSchema: raw.input_schema as Record<string, unknown>,
    effect,
    idempotent: Boolean(raw.idempotent),
  }
}

/**
 * Translate the harness effect classification into MCP annotations.
 *
 * `readOnlyHint` is the only one the SDK acts on -- it lets read-only tools run
 * in parallel -- so it must stay accurate. The rest are informational and
 * simply carry the harness's classification through.
 */
export function annotationsFor(spec: ToolSpec): ToolAnnotations {
  return {
    readOnlyHint: spec.effect === READ_ONLY,
    destructiveHint: spec.effect === DESTRUCTIVE,
    idempotentHint: spec.idempotent,
    openWorldHint: true,
  }
}

export type ToolCallResult = {
  status: string
  output?: unknown
  error?: string
}

/**
 * Talks to the harness HTTP service.
 *
 * Every call carries a session id. The harness journals tool events under it,
 * so one bridged session's calls are readable afterwards through
 * `GET /v1/runs/<sessionId>/events` the same way a harness-driven run is.
 */
export class HarnessClient {
  readonly sessionId: string
  readonly #baseUrl: string
  readonly #token: string
  readonly #timeoutMs: number

  constructor(
    baseUrl: string,
    token: string,
    { timeoutMs = 120_000, sessionId }: { timeoutMs?: number; sessionId?: string } = {},
  ) {
    this.#baseUrl = baseUrl.replace(/\/+$/, '')
    this.#token = token
    this.#timeoutMs = timeoutMs
    this.sessionId = sessionId ?? `agent-sdk-${crypto.randomUUID()}`
  }

  async #request(
    method: string,
    path: string,
    body?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    let response: Response
    try {
      response = await fetch(`${this.#baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.#token}`,
          'Content-Type': 'application/json',
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.#timeoutMs),
      })
    } catch (cause) {
      throw new HarnessError(
        `cannot reach the harness at ${this.#baseUrl}: ${(cause as Error).message}. ` +
          'Is `harness serve` running?',
        { cause },
      )
    }
    if (!response.ok) {
      const detail = await response.text()
      throw new HarnessError(`${method} ${path} failed: ${response.status} ${detail}`)
    }
    return (await response.json()) as Record<string, unknown>
  }

  async listTools(): Promise<ToolSpec[]> {
    const payload = await this.#request('GET', '/v1/tools')
    return (payload.tools as Record<string, unknown>[]).map(toolSpecFrom)
  }

  async callTool(
    name: string,
    args: Record<string, unknown>,
    callId?: string,
  ): Promise<ToolCallResult> {
    const body: Record<string, unknown> = {
      name,
      arguments: args,
      session_id: this.sessionId,
    }
    if (callId !== undefined) {
      body.call_id = callId
    }
    return (await this.#request('POST', '/v1/tools/call', body)) as ToolCallResult
  }

  /**
   * Ask the harness whether this call is allowed. The reason is only meaningful
   * when the call was rejected.
   */
  async authorize(
    name: string,
    args: Record<string, unknown>,
  ): Promise<{ authorized: boolean; reason: string }> {
    const payload = await this.#request('POST', '/v1/tools/authorize', {
      name,
      arguments: args,
      session_id: this.sessionId,
    })
    return {
      authorized: Boolean(payload.authorized),
      reason: typeof payload.reason === 'string' ? payload.reason : '',
    }
  }
}

/**
 * Turn a harness tool result into an MCP tool result.
 *
 * A failed tool is reported with `isError` rather than thrown, so the model
 * reads the harness's own message and can react to it instead of seeing a bare
 * stack trace.
 */
export function renderResult(result: ToolCallResult): CallToolResult {
  if (result.status !== 'succeeded') {
    const message = result.error || `tool ${result.status}`
    return { content: [{ type: 'text', text: message }], isError: true }
  }
  const output = result.output
  const text = typeof output === 'string' ? output : JSON.stringify(output, null, 2)
  return { content: [{ type: 'text', text }] }
}

/**
 * Build the in-process MCP server whose entire tool surface is the harness
 * registry.
 *
 * This drives the low-level request handlers rather than the `tool()` helper on
 * purpose. That helper -- and `registerTool` beneath it -- takes a Zod schema,
 * so using it would mean translating each harness JSON Schema into Zod and back
 * again, a lossy layer that has to be kept in sync with the registry. MCP is
 * JSON Schema on the wire, so handling `tools/list` ourselves passes the
 * harness's own schema through untouched.
 */
export function createHarnessMcpServer(client: HarnessClient, specs: ToolSpec[]): McpServerConfig {
  const server = new McpServer(
    { name: SERVER_NAME, version: '1.0.0' },
    { capabilities: { tools: {} } },
  )

  server.server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: specs.map(spec => ({
      name: spec.name,
      description: spec.description,
      inputSchema: spec.inputSchema as { type: 'object' },
      annotations: annotationsFor(spec),
    })),
  }))

  server.server.setRequestHandler(CallToolRequestSchema, async request => {
    try {
      return renderResult(
        await client.callTool(request.params.name, request.params.arguments ?? {}),
      )
    } catch (error) {
      // Compose the message rather than letting the exception surface raw, so
      // the model can tell a transport failure from a tool failure.
      return {
        content: [{ type: 'text', text: `harness call failed: ${(error as Error).message}` }],
        isError: true,
      }
    }
  })

  return { type: 'sdk', name: SERVER_NAME, instance: server }
}

/**
 * Delegate every permission decision to the harness.
 *
 * Without this the SDK would apply its own policy on top of the harness's, and
 * the two could disagree. The harness already knows each tool's effect and owns
 * the decision, so it stays the single authority.
 */
export function permissionHandler(client: HarnessClient): CanUseTool {
  const prefix = `mcp__${SERVER_NAME}__`
  return async (toolName, input) => {
    if (!toolName.startsWith(prefix)) {
      // With tools: [] nothing else should exist. Deny rather than guess.
      return { behavior: 'deny', message: `${toolName} is not a harness tool`, interrupt: false }
    }
    let decision: { authorized: boolean; reason: string }
    try {
      decision = await client.authorize(toolName.slice(prefix.length), input)
    } catch (error) {
      return { behavior: 'deny', message: `authorization unavailable: ${(error as Error).message}` }
    }
    if (decision.authorized) {
      return { behavior: 'allow', updatedInput: input }
    }
    return { behavior: 'deny', message: decision.reason || 'the harness rejected this call' }
  }
}

/** Assemble SDK options whose entire tool surface is the harness registry. */
export async function buildOptions(
  client: HarnessClient,
  {
    systemPrompt,
    model,
    cwd,
    maxTurns,
  }: { systemPrompt: string; model?: string; cwd?: string; maxTurns?: number },
): Promise<Options> {
  const specs = await client.listTools()
  if (specs.length === 0) {
    throw new HarnessError('the harness exposed no tools; nothing for the model to use')
  }

  return {
    mcpServers: { [SERVER_NAME]: createHarnessMcpServer(client, specs) },
    // Every harness tool is reachable; canUseTool decides each call. Listing
    // nothing in allowedTools keeps the harness in the loop.
    tools: [], // strip every built-in Claude Code tool
    settingSources: [], // ignore ~/.claude and project settings
    systemPrompt,
    canUseTool: permissionHandler(client),
    model,
    cwd,
    maxTurns,
  }
}
