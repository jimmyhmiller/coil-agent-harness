/**
 * Run a Claude Agent SDK session whose only tools come from the harness.
 *
 *     export HARNESS_TOKEN=...            # same token `harness serve` was given
 *     node src/main.ts "summarize the src tree"
 *     node src/main.ts                    # interactive
 *
 * The harness must already be serving:  ./harness serve
 */

import { parseArgs } from 'node:util'
import { createInterface } from 'node:readline/promises'
import { query, type SDKMessage, type SDKUserMessage } from '@anthropic-ai/claude-agent-sdk'

import { HarnessClient, HarnessError, buildOptions } from './harness.ts'

const DEFAULT_SYSTEM_PROMPT =
  'You are an operator for the coil agent harness. Every tool you have is ' +
  'provided by the harness itself; you have no built-in file, shell, or web ' +
  'tools. Use the harness tools to inspect and act on the system, and say ' +
  'plainly when a task needs a capability the harness does not expose.'

function render(message: SDKMessage): void {
  if (message.type === 'assistant') {
    for (const block of message.message.content) {
      if (block.type === 'tool_use') {
        process.stderr.write(`\n  ⏺ ${block.name} ${JSON.stringify(block.input)}\n`)
      } else if (block.type === 'text') {
        process.stdout.write(block.text)
      }
    }
  } else if (message.type === 'result') {
    if (message.subtype !== 'success') {
      process.stderr.write(`\n[run ended: ${message.subtype}]\n`)
    }
    process.stdout.write('\n')
  }
}

function userMessage(text: string): SDKUserMessage {
  return { type: 'user', message: { role: 'user', content: text }, parent_tool_use_id: null }
}

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      url: { type: 'string', default: process.env.HARNESS_URL ?? 'http://127.0.0.1:8080' },
      model: { type: 'string' },
      cwd: { type: 'string' },
      'max-turns': { type: 'string' },
      'session-id': { type: 'string' },
    },
  })

  const token = process.env.HARNESS_TOKEN
  if (!token) {
    process.stderr.write('HARNESS_TOKEN is not set\n')
    return 2
  }

  const client = new HarnessClient(values.url!, token, { sessionId: values['session-id'] })
  process.stderr.write(`[session ${client.sessionId}]\n`)

  let options
  try {
    options = await buildOptions(client, {
      systemPrompt: DEFAULT_SYSTEM_PROMPT,
      model: values.model,
      cwd: values.cwd,
      maxTurns: values['max-turns'] === undefined ? undefined : Number(values['max-turns']),
    })
  } catch (error) {
    if (error instanceof HarnessError) {
      process.stderr.write(`error: ${error.message}\n`)
      return 1
    }
    throw error
  }

  const prompt = positionals.join(' ')
  if (prompt) {
    for await (const message of query({ prompt, options })) {
      render(message)
    }
    return 0
  }

  // Interactive: one turn per line, conversation state kept by the SDK. The
  // prompt is a stream rather than a string so the session stays open across
  // turns instead of ending with the first reply. Closing stdin ends the
  // stream, which ends the session.
  const lines = createInterface({ input: process.stdin, output: process.stdout, prompt: '> ' })
  // Piped input reaches EOF while the last turn is still streaming back, so
  // every later prompt has to check that there is still someone to prompt.
  let reading = true
  lines.on('close', () => {
    reading = false
  })
  async function* turns(): AsyncGenerator<SDKUserMessage> {
    lines.prompt()
    for await (const line of lines) {
      const text = line.trim()
      if (text) {
        yield userMessage(text)
      } else {
        lines.prompt()
      }
    }
  }
  try {
    for await (const message of query({ prompt: turns(), options })) {
      render(message)
      if (message.type === 'result' && reading) {
        lines.prompt()
      }
    }
  } finally {
    lines.close()
  }
  return 0
}

process.exitCode = await main()
