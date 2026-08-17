/**
 * Acceptance test for the bridge, with no model in the loop.
 *
 * It starts a real `harness serve`, then drives the bridge the way the CLI
 * would: list the tools over MCP, call them, and put decisions through the
 * permission handler. The harness's tool plane itself is covered separately by
 * scripts/tool_plane_e2e_test.py, which needs nothing but the standard library.
 *
 *     node test/bridge-test.ts [path/to/harness]
 */

import { strict as assert } from 'node:assert'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import {
  HarnessClient,
  buildOptions,
  createHarnessMcpServer,
  permissionHandler,
} from '../src/harness.ts'

const TOKEN = 'coil-agent-sdk-bridge-token'
const SESSION = 'agent-sdk-bridge-session'
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

async function freePort(): Promise<number> {
  const server = createServer()
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as { port: number }
  await new Promise<void>(resolve => server.close(() => resolve()))
  return port
}

async function startServer(
  harness: string,
  port: number,
  journal: string,
  workspace: string,
): Promise<ChildProcess> {
  const server = spawn(harness, ['serve', String(port), journal], {
    cwd: workspace,
    env: { ...process.env, HARNESS_AUTH_TOKEN: TOKEN },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let stdout = ''
  let stderr = ''
  server.stdout!.on('data', chunk => {
    stdout += String(chunk)
  })
  server.stderr!.on('data', chunk => {
    stderr += String(chunk)
  })
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(
        `server exited with code ${server.exitCode}, signal ${server.signalCode}: ${stderr || stdout}`,
      )
    }
    try {
      const probe = await fetch(`http://127.0.0.1:${port}/v1/runs/readiness-probe`, {
        headers: { Authorization: `Bearer ${TOKEN}` },
      })
      if (probe.status === 404) {
        return server
      }
    } catch {
      // not listening yet
    }
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  server.kill('SIGTERM')
  throw new Error('server did not become ready')
}

async function stopServer(server: ChildProcess): Promise<void> {
  if (server.exitCode === null) {
    server.kill('SIGTERM')
    await new Promise(resolve => server.once('exit', resolve))
  }
}

/** Connect an MCP client to the bridge's server over an in-memory transport. */
async function connect(instance: McpServer): Promise<Client> {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  await instance.server.connect(serverTransport)
  const client = new Client({ name: 'bridge-test', version: '1.0.0' })
  await client.connect(clientTransport)
  return client
}

async function main(): Promise<void> {
  const harness = path.resolve(process.argv[2] ?? path.join(ROOT, 'harness'))
  const workspace = await mkdtemp(path.join(tmpdir(), 'coil-agent-sdk-bridge-'))
  const port = await freePort()
  const baseUrl = `http://127.0.0.1:${port}`
  const server = await startServer(harness, port, path.join(workspace, 'events.jsonl'), workspace)

  try {
    const harnessClient = new HarnessClient(baseUrl, TOKEN, { sessionId: SESSION })

    const specs = await harnessClient.listTools()
    const byName = new Map(specs.map(spec => [spec.name, spec]))
    assert.equal(byName.get('echo')!.effect, 'read_only')
    assert.equal(byName.get('write_text_file')!.effect, 'destructive')

    const config = createHarnessMcpServer(harnessClient, specs)
    assert.equal(config.type, 'sdk')
    const mcp = await connect((config as { instance: McpServer }).instance)

    // The registry's own JSON Schema reaches the model untouched -- the whole
    // reason this server is built from the low-level handlers.
    const listed = await mcp.listTools()
    const echo = listed.tools.find(tool => tool.name === 'echo')!
    assert.deepEqual(echo.inputSchema, byName.get('echo')!.inputSchema)
    assert.equal(echo.annotations?.readOnlyHint, true)
    assert.equal(
      listed.tools.find(tool => tool.name === 'write_text_file')!.annotations?.destructiveHint,
      true,
    )

    const called = await mcp.callTool({ name: 'echo', arguments: { text: 'through the bridge' } })
    assert.equal(called.isError, undefined)
    assert.deepEqual(JSON.parse((called.content as { text: string }[])[0]!.text), {
      text: 'through the bridge',
    })

    // A tool that fails is a readable result, not a thrown transport error.
    const failed = await mcp.callTool({
      name: 'read_text_file',
      arguments: { path: 'does-not-exist.txt', start_line: 1, line_count: 1 },
    })
    assert.equal(failed.isError, true)

    // Real side effects land in the harness's workspace, not the bridge's.
    await mcp.callTool({
      name: 'write_text_file',
      arguments: { path: 'bridge.txt', content: 'written by the bridge\n' },
    })
    assert.equal(
      await readFile(path.join(workspace, 'bridge.txt'), 'utf8'),
      'written by the bridge\n',
    )

    const handler = permissionHandler(harnessClient)
    const decide = async (tool: string, input: Record<string, unknown>) => {
      const result = await handler(tool, input, {
        signal: new AbortController().signal,
        toolUseID: 'tool-use-1',
        requestId: 'request-1',
      })
      assert.ok(result, `${tool} produced no decision`)
      return result
    }
    assert.equal((await decide('mcp__harness__echo', { text: 'ok' })).behavior, 'allow')
    assert.equal((await decide('mcp__harness__echo', {})).behavior, 'deny')
    assert.equal((await decide('mcp__harness__nope', {})).behavior, 'deny')
    // Nothing outside the harness server is ours to allow.
    assert.equal((await decide('Bash', { command: 'ls' })).behavior, 'deny')

    const options = await buildOptions(harnessClient, { systemPrompt: 'test' })
    assert.deepEqual(options.tools, [])
    assert.deepEqual(options.settingSources, [])
    assert.equal(options.allowedTools, undefined)
    assert.ok(options.mcpServers!.harness)
    assert.ok(options.canUseTool)

    // Every bridged call is journaled under the session, tool name and all.
    const events = (await (
      await fetch(`${baseUrl}/v1/runs/${SESSION}/events?after=0`, {
        headers: { Authorization: `Bearer ${TOKEN}` },
      })
    ).json()) as { events: { event: string; provider: string; operation_id: string }[] }
    const kinds = new Set(events.events.map(event => event.event))
    assert.ok(kinds.has('tool.call.completed'), [...kinds].join(','))
    assert.ok(kinds.has('tool.call.failed'), [...kinds].join(','))
    assert.deepEqual(new Set(events.events.map(event => event.provider)), new Set(['agent-sdk']))
    assert.ok(events.events.some(event => event.operation_id === 'write_text_file'))

    await mcp.close()
  } finally {
    await stopServer(server)
    await rm(workspace, { recursive: true, force: true })
  }

  process.stdout.write('agent sdk bridge test: ok\n')
}

await main()
