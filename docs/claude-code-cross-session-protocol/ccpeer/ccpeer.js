#!/usr/bin/env node
'use strict';
// ccpeer -- a hand-rolled harness that speaks Claude Code's cross-session
// messaging protocol. It registers as a peer, receives SendMessage traffic, and
// sends messages that land in a real Claude session's queue.
//
//   ccpeer list                        show live peers
//   ccpeer serve --name X [--auto-reply] [--log F]
//   ccpeer send <peer> <text>          deliver a user message
//   ccpeer rename <peer> <new-name>    control frame
//   ccpeer status <peer> <status> [--orig-msg-id ID]

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const P = require('./protocol');
const R = require('./roster');
const T = require('./transport');

const VERSION = '0.1.0-ccpeer';

function parseArgs(argv) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq !== -1) flags[a.slice(2, eq)] = a.slice(eq + 1);
      else if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) flags[a.slice(2)] = argv[++i];
      else flags[a.slice(2)] = true;
    } else positional.push(a);
  }
  return { positional, flags };
}

function die(msg) {
  console.error(`ccpeer: ${msg}`);
  process.exit(1);
}

function ts() {
  return new Date().toISOString().slice(11, 19);
}

// ---------------------------------------------------------------------------

async function cmdList() {
  const peers = await R.livePeers({ excludeSocket: process.env.CLAUDE_CODE_MESSAGING_SOCKET });
  if (peers.length === 0) {
    console.log('no live peers');
    return;
  }
  const width = Math.max(...peers.map((p) => (p.name || String(p.pid)).length));
  for (const p of peers) {
    const label = (p.name || String(p.pid)).padEnd(width);
    console.log(`${label}  pid=${String(p.pid).padEnd(6)} ${(p.status || '?').padEnd(7)} ${p.cwd}`);
  }
}

// A small verb responder, so --auto-reply is an actual interlocutor rather than
// an echo. Everything it reports is read back out of live protocol state.
async function respond(body, { frame, env, name, socketPath, sessionId, startedAt }) {
  const [verb, ...rest] = body.trim().split(/\s+/);
  const arg = rest.join(' ');
  switch (verb.toLowerCase().replace(/[?.!,]+$/, '')) {
    case 'help':
      return 'verbs: help, whoami, peers, uptime, frame, envelope, echo <text>. anything else gets an ack.';

    case 'whoami':
      return [
        `name=${name}`,
        `pid=${process.pid}`,
        `socket=${socketPath}`,
        `sessionId=${sessionId}`,
        `runtime=node ${process.version} (not Claude Code)`,
        `impl=${path.dirname(__filename)}`,
      ].join('\n');

    case 'peers': {
      const peers = await R.livePeers({ excludeSocket: socketPath });
      return [
        `${peers.length} live peers (socket-probed, same set your ListAgents sees):`,
        ...peers.map((p) => `  ${p.name ?? p.pid}  pid=${p.pid}  ${p.status ?? '?'}  ${p.cwd}`),
      ].join('\n');
    }

    case 'uptime': {
      const secs = Math.round((Date.now() - startedAt) / 1000);
      return `up ${secs}s, ${received} message(s) received`;
    }

    case 'frame':
      return `your frame verbatim:\n${JSON.stringify(lastFrame, null, 2)}`;

    case 'envelope':
      return [
        'decoded from your message.content:',
        `  from      = ${env.from ?? '(none)'}`,
        `  from-name = ${env.fromName ?? '(none)'}`,
        `  from-mode = ${env.fromMode ?? '(none)'}`,
        `  hop-chain = ${env.hopChain ? env.hopChain.join(',') : '(none)'}`,
        `  body      = ${env.body.length} chars`,
      ].join('\n');

    case 'echo':
      return arg || '(nothing to echo)';

    // Silence, not an ack. Two auto-replying peers that acknowledge everything
    // ping-pong forever, and against a real session each round trip costs the
    // user an approval dialog. Only recognized verbs get an answer.
    default:
      return null;
  }
}

let lastFrame = null;
let received = 0;

async function cmdServe(flags) {
  const startedAt = Date.now();
  const fromMode = parseFromMode(flags);
  const name = typeof flags.name === 'string' ? flags.name : 'ccpeer';
  const socketPath = typeof flags.socket === 'string' ? flags.socket : P.defaultSocketPath();
  const sessionId = crypto.randomUUID();
  const myAddress = P.udsAddress(socketPath);
  const logPath = typeof flags.log === 'string' ? flags.log : null;
  const autoReply = Boolean(flags['auto-reply']);

  const log = (line) => {
    console.log(line);
    if (logPath) fs.appendFileSync(logPath, `${line}\n`);
  };
  const record = (obj) => {
    if (logPath) fs.appendFileSync(`${logPath}.jsonl`, `${JSON.stringify(obj)}\n`);
  };

  const handleFrame = async (frame) => {
    record({ at: new Date().toISOString(), frame });

    if (typeof frame?.type !== 'string') {
      log(`${ts()} !! frame without a valid type field`);
      return;
    }

    if (frame.type === 'user') {
      const content = frame.message?.content;
      if (typeof content !== 'string' || content.length === 0) {
        log(`${ts()} !! user frame with missing or non-string content`);
        return;
      }
      const env = P.parseEnvelope(content);
      const who = env?.fromName || frame.from || 'unknown';
      const body = env ? env.body : content;
      log(`${ts()} <- ${who} [${frame.priority ?? 'next'}] ${body}`);

      lastFrame = frame;
      received++;

      if (autoReply && env?.from) {
        const target = P.parseAddress(env.from);
        if (target.scheme === 'uds') {
          // reg.record.name, not the startup name: a rename control frame may
          // have changed it since.
          const reply = await respond(body, {
            frame,
            env,
            name: reg.record.name,
            socketPath,
            sessionId,
            startedAt,
          });
          if (reply === null) {
            log(`${ts()} .. no verb matched; staying silent (no reply sent)`);
          } else {
            await send(target.target, reply, { name, from: myAddress, fromMode }).catch((e) =>
              log(`${ts()} !! auto-reply failed: ${e.message}`),
            );
            log(`${ts()} -> ${who} ${reply}`);
          }
        }
      }
      return;
    }

    if (frame.type === 'control') {
      if (frame.action === 'rename' && typeof frame.name === 'string') {
        reg.update({ name: frame.name });
        log(`${ts()} ** renamed to "${frame.name}"`);
      } else if (frame.action === 'peer_message_status') {
        const reason = P.STATUS_REASONS[frame.status] ?? '(unknown status)';
        log(`${ts()} ** status ${frame.status} for ${frame.orig_msg_id ?? '(none)'}: ${reason}`);
      } else {
        log(`${ts()} ?? unhandled control action: ${frame.action}`);
      }
      return;
    }

    log(`${ts()} ?? unhandled message type: ${frame.type}`);
  };

  const inbox = await T.bindInbox(socketPath, {
    onFrame: (frame) => {
      handleFrame(frame).catch((e) => log(`${ts()} !! handler error: ${e.message}`));
    },
    onError: (err) => log(`${ts()} !! ${err.message}`),
  });

  // --no-register: bind the socket but publish nothing. Demonstrates the split
  // between reachability (the socket) and discoverability (the roster entry).
  const registered = !flags['no-register'];
  const reg = new R.Registration({
    name,
    socketPath,
    cwd: process.cwd(),
    sessionId,
    kind: 'interactive',
    version: VERSION,
    enabled: registered,
  });
  reg.write();

  log(`${ts()} ** ccpeer "${name}" listening on ${socketPath}`);
  log(`${ts()} ** address ${myAddress}  (session ${sessionId}, pid ${process.pid})`);
  log(`${ts()} ** ${registered ? `registered at ${reg.file}` : 'NOT registered (invisible to ListAgents)'}`);

  // A registration that outlives its process would leave a phantom peer in
  // everyone's roster, so tear both down on any exit path.
  let closing = false;
  const shutdown = async (signal) => {
    if (closing) return;
    closing = true;
    log(`${ts()} ** shutting down (${signal})`);
    // Unconditional: unlinking a file we never wrote is a no-op, and if
    // anything did leak one, exit is the last chance to reap it.
    reg.remove();
    await inbox.close();
    process.exit(0);
  };
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => shutdown(sig));

  // Keep updatedAt fresh so watchers can tell a live peer from a wedged one.
  const heartbeat = setInterval(() => reg.update({}), 30_000);
  heartbeat.unref();

  // Optional stdin console: "<peer> <text>" sends, "/quit" exits.
  if (flags.console) {
    const rl = readline.createInterface({ input: process.stdin, terminal: false });
    rl.on('line', async (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      if (trimmed === '/quit') return shutdown('console');
      const sp = trimmed.indexOf(' ');
      if (sp === -1) return log(`${ts()} !! usage: <peer> <text>`);
      const peers = await R.livePeers({ excludeSocket: socketPath });
      const peer = R.resolvePeer(peers, trimmed.slice(0, sp));
      if (!peer) return log(`${ts()} !! no such peer: ${trimmed.slice(0, sp)}`);
      const text = trimmed.slice(sp + 1);
      await send(peer.sock, text, { name, from: myAddress, fromMode });
      log(`${ts()} -> ${peer.name ?? peer.pid} ${text}`);
    });
  }
}

// fromMode is the permission-mode attestation the receiver's inbound gate keys
// on. Omitting it is not neutral: a bypass-mode receiver holds an unattested
// message for user approval ("no-mode-asserted"), while a matching attestation
// is accepted outright. Nothing verifies the claim, so only assert a mode that
// is actually true of this client.
async function send(socketPath, text, { name, from, priority = 'next', sessionId, fromMode } = {}) {
  const content = P.buildEnvelope({ from, fromName: name, body: text, fromMode });
  const frame = P.userFrame({ content, from, priority, sessionId });
  await T.sendFrame(socketPath, frame);
  return frame.msg_id;
}

function parseFromMode(flags) {
  const v = flags['from-mode'];
  if (v === undefined) return undefined;
  if (v !== 'bypass' && v !== 'prompting') {
    die(`--from-mode must be "bypass" or "prompting", got "${v}"`);
  }
  return v;
}

async function cmdSend(positional, flags) {
  const [target, ...rest] = positional;
  if (!target || rest.length === 0) die('usage: ccpeer send <peer> <text>');
  const text = rest.join(' ');

  // A raw address bypasses the roster entirely: the socket path is the only
  // thing delivery actually needs. Names are a convenience layer on top.
  const asAddress = P.parseAddress(target);
  const direct = asAddress.scheme === 'uds' && (target.startsWith('uds:') || target.startsWith('/'));

  let peer;
  if (direct) {
    peer = { sock: asAddress.target, name: asAddress.target };
  } else {
    const peers = await R.livePeers();
    peer = R.resolvePeer(peers, target);
    if (!peer) die(`no live peer matching "${target}" (try: ccpeer list, or pass a uds: address)`);
  }

  const name = typeof flags.name === 'string' ? flags.name : 'ccpeer';
  // Advertise a reply address only if we are actually listening on it.
  const socketPath = typeof flags.socket === 'string' ? flags.socket : P.defaultSocketPath();
  const from = (await R.probe(socketPath)) ? P.udsAddress(socketPath) : undefined;

  const msgId = await send(peer.sock, text, {
    name,
    from,
    priority: flags.priority === 'later' ? 'later' : 'next',
    sessionId: flags['session-id'],
    fromMode: parseFromMode(flags),
  });
  console.log(`sent to ${peer.name ?? peer.pid} (${peer.sock}) msg_id=${msgId}${from ? '' : '  [no reply address: not listening]'}`);
}

async function cmdRename(positional) {
  const [target, newName] = positional;
  if (!target || !newName) die('usage: ccpeer rename <peer> <new-name>');
  const peers = await R.livePeers();
  const peer = R.resolvePeer(peers, target);
  if (!peer) die(`no live peer matching "${target}"`);
  await T.sendFrame(peer.sock, P.controlFrame('rename', { name: newName }));
  console.log(`renamed ${peer.name ?? peer.pid} -> ${newName}`);
}

async function cmdStatus(positional, flags) {
  const [target, status] = positional;
  if (!target || !['held', 'denied', 'expired', 'delivered'].includes(status)) {
    die('usage: ccpeer status <peer> <held|denied|expired|delivered> [--orig-msg-id ID]');
  }
  const peers = await R.livePeers();
  const peer = R.resolvePeer(peers, target);
  if (!peer) die(`no live peer matching "${target}"`);
  const socketPath = typeof flags.socket === 'string' ? flags.socket : P.defaultSocketPath();
  await T.sendFrame(
    peer.sock,
    P.controlFrame('peer_message_status', {
      status,
      reason: P.STATUS_REASONS[status],
      from: P.udsAddress(socketPath),
      ...(flags['orig-msg-id'] ? { orig_msg_id: flags['orig-msg-id'] } : {}),
    }),
  );
  console.log(`sent peer_message_status=${status} to ${peer.name ?? peer.pid}`);
}

async function main() {
  const { positional, flags } = parseArgs(process.argv.slice(2));
  const cmd = positional.shift();
  switch (cmd) {
    case 'list':
      return cmdList();
    case 'serve':
      return cmdServe(flags);
    case 'send':
      return cmdSend(positional, flags);
    case 'rename':
      return cmdRename(positional);
    case 'status':
      return cmdStatus(positional, flags);
    default:
      console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(3, 12).join('\n').replace(/^\/\/ ?/gm, ''));
      process.exit(cmd ? 1 : 0);
  }
}

main().catch((err) => die(err.stack || err.message));
