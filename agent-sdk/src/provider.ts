/** Stdio host used internally by the Coil `agent-sdk` ModelProvider. */
import { createInterface } from 'node:readline'
import { query } from '@anthropic-ai/claude-agent-sdk'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'

type WireTool = {
  name: string
  description: string
  input_schema: Record<string, unknown>
  effect: string
  idempotent: boolean
}
type Start = {
  type: 'start'
  prompt: string
  instructions: string
  model?: string
  cwd?: string
  max_turns?: number
  tools: WireTool[]
}
type ToolReply = {
  type: 'tool_result'
  id: string
  status: string
  output?: unknown
  error?: string
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
const waiting = new Map<string, { resolve(value: ToolReply): void; reject(error: Error): void }>()
let startResolve!: (value: Start) => void
const started = new Promise<Start>(resolve => { startResolve = resolve })

lines.on('line', line => {
  try {
    const message = JSON.parse(line) as Start | ToolReply
    if (message.type === 'start') startResolve(message)
    else if (message.type === 'tool_result') {
      const pending = waiting.get(message.id)
      if (pending) {
        waiting.delete(message.id)
        pending.resolve(message)
      }
    }
  } catch (error) {
    process.stderr.write(`agent-sdk provider received invalid JSON: ${(error as Error).message}\n`)
  }
})

function send(message: unknown): void {
  process.stdout.write(`${JSON.stringify(message)}\n`)
}

function callTool(name: string, input: Record<string, unknown>): Promise<ToolReply> {
  const id = crypto.randomUUID()
  send({ type: 'tool_call', id, name, arguments: input })
  return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }))
}

async function main(): Promise<void> {
  const start = await started
  const server = new McpServer({ name: 'harness', version: '1.0.0' }, { capabilities: { tools: {} } })
  server.server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: start.tools.map(tool => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.input_schema,
      annotations: {
        readOnlyHint: tool.effect === 'read_only',
        destructiveHint: tool.effect === 'destructive',
        idempotentHint: tool.idempotent,
        openWorldHint: true,
      },
    })),
  }))
  server.server.setRequestHandler(CallToolRequestSchema, async request => {
    const reply = await callTool(request.params.name, request.params.arguments ?? {})
    const ok = reply.status === 'succeeded'
    const value = ok ? reply.output : reply.error ?? `tool ${reply.status}`
    return {
      content: [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value) }],
      isError: !ok,
    }
  })

  let text = ''
  for await (const message of query({
    prompt: start.prompt,
    options: {
      cwd: start.cwd,
      model: start.model || undefined,
      maxTurns: start.max_turns || undefined,
      systemPrompt: start.instructions,
      tools: [],
      settingSources: [],
      mcpServers: { harness: { type: 'sdk', name: 'harness', instance: server } },
      strictMcpConfig: true,
      canUseTool: async () => ({ behavior: 'allow', updatedInput: {} }),
    },
  })) {
    if (message.type === 'assistant') {
      for (const block of message.message.content) if (block.type === 'text') text += block.text
    } else if (message.type === 'result' && message.subtype !== 'success') {
      throw new Error(`Agent SDK ended with ${message.subtype}`)
    }
  }
  send({ type: 'completed', text })
  lines.close()
}

main().catch(error => {
  send({ type: 'failed', error: error instanceof Error ? error.message : String(error) })
  process.exitCode = 1
})
