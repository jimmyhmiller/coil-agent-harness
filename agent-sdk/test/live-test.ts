/**
 * Opt-in live check: a real model turn driven by the Agent SDK over harness tools.
 *
 * Everything except the model is covered by test/bridge-test.ts. This one spends
 * a request to prove the last link -- that the CLI reaches the bridge's
 * in-process MCP server, that our permission handler is consulted rather than
 * the SDK's own policy, and that the call lands in the harness journal.
 *
 *     node test/live-test.ts [path/to/harness]
 *
 * Exits 77 when the `claude` CLI is unavailable, so a sweep can treat it as
 * skipped rather than failed.
 */

import { strict as assert } from 'node:assert'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { query } from '@anthropic-ai/claude-agent-sdk'

import { HarnessClient, buildOptions } from '../src/harness.ts'

const TOKEN = 'coil-agent-sdk-live-token'
const SESSION = 'agent-sdk-live-session'
const PROMPT = 'Use the echo tool to echo the exact word READY, then reply with just the word done.'
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
  let stderr = ''
  server.stderr!.on('data', chunk => {
    stderr += String(chunk)
  })
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`server exited: ${stderr}`)
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

function claudeInstalled(): boolean {
  const probe = spawnSync('claude', ['--version'], { stdio: 'ignore' })
  return probe.error === undefined && probe.status === 0
}

async function main(): Promise<number> {
  if (!claudeInstalled()) {
    process.stderr.write('live agent sdk test: the claude CLI is not on PATH\n')
    return 77
  }

  const harness = path.resolve(process.argv[2] ?? path.join(ROOT, 'harness'))
  const workspace = await mkdtemp(path.join(tmpdir(), 'coil-agent-sdk-live-'))
  const port = await freePort()
  const baseUrl = `http://127.0.0.1:${port}`
  const server = await startServer(harness, port, path.join(workspace, 'events.jsonl'), workspace)

  try {
    const client = new HarnessClient(baseUrl, TOKEN, { sessionId: SESSION })
    const options = await buildOptions(client, {
      systemPrompt:
        'You are testing a tool bridge. Every tool you have comes from the harness. ' +
        'Use them when asked and keep replies to a few words.',
      maxTurns: 4,
    })

    // Count decisions to prove the CLI consulted the harness rather than
    // applying a policy of its own.
    const delegate = options.canUseTool!
    let decisions = 0
    options.canUseTool = async (toolName, input, context) => {
      decisions += 1
      return delegate(toolName, input, context)
    }

    const used: string[] = []
    for await (const message of query({ prompt: PROMPT, options })) {
      if (message.type === 'assistant') {
        for (const block of message.message.content) {
          if (block.type === 'tool_use') {
            used.push(block.name)
          }
        }
      }
    }

    assert.ok(used.includes('mcp__harness__echo'), `tools used: ${used.join(', ') || 'none'}`)
    assert.ok(decisions > 0, 'the permission handler was never consulted')

    const events = (await (
      await fetch(`${baseUrl}/v1/runs/${SESSION}/events?after=0`, {
        headers: { Authorization: `Bearer ${TOKEN}` },
      })
    ).json()) as { events: { event: string; provider: string; payload: unknown }[] }
    const completed = events.events.filter(
      event => event.event === 'tool.call.completed' && event.provider === 'agent-sdk',
    )
    assert.ok(completed.length > 0, 'no completed tool call was journaled')
    assert.deepEqual(completed[0]!.payload, { text: 'READY' })
  } finally {
    if (server.exitCode === null) {
      server.kill('SIGTERM')
      await new Promise(resolve => server.once('exit', resolve))
    }
    await rm(workspace, { recursive: true, force: true })
  }

  process.stdout.write('live agent sdk test: ok\n')
  return 0
}

process.exitCode = await main()
