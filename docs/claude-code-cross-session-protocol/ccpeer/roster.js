'use strict';
// The peer directory: ~/.claude/sessions/<pid>.json, one file per live session.
//
// Discovery is liveness-probed, not pid-based: a peer shows up in another
// session's ListAgents if and only if something is actually accepting on its
// messagingSocketPath. Stale files are unlinked by whoever notices first.

const fs = require('fs');
const fsp = require('fs/promises');
const net = require('net');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { PEER_PROTOCOL } = require('./protocol');

const SESSIONS_DIR = path.join(os.homedir(), '.claude', 'sessions');
const KINDS = ['interactive', 'bg', 'daemon', 'daemon-worker'];
const STATUSES = ['busy', 'shell', 'idle', 'waiting'];

// Claude validates a session file by re-running this exact command and
// comparing the result, so pid reuse can't resurrect a dead session's identity.
function procStart(pid = process.pid) {
  try {
    const out = execFileSync('/bin/sh', ['-c', `LC_ALL=C TZ=UTC ps -o lstart= -p ${pid}`], {
      timeout: 1000,
      encoding: 'utf8',
    });
    return out.trim() || undefined;
  } catch {
    return undefined;
  }
}

function sessionFile(pid = process.pid) {
  return path.join(SESSIONS_DIR, `${pid}.json`);
}

function readAll() {
  let names;
  try {
    names = fs.readdirSync(SESSIONS_DIR);
  } catch {
    return [];
  }
  const out = [];
  for (const name of names) {
    if (!/^\d+\.json$/.test(name)) continue;
    const pid = parseInt(name.slice(0, -5), 10);
    if (Number.isNaN(pid)) continue;
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(SESSIONS_DIR, name), 'utf8'));
      out.push({
        pid,
        file: path.join(SESSIONS_DIR, name),
        sock: typeof raw.messagingSocketPath === 'string' ? raw.messagingSocketPath : '',
        cwd: typeof raw.cwd === 'string' ? raw.cwd : '?',
        name: typeof raw.name === 'string' ? raw.name : undefined,
        sessionId: raw.sessionId,
        kind: KINDS.includes(raw.kind) ? raw.kind : undefined,
        status: STATUSES.includes(raw.status) ? raw.status : undefined,
        startedAt: typeof raw.startedAt === 'number' ? raw.startedAt : 0,
        procStart: typeof raw.procStart === 'string' ? raw.procStart : undefined,
        peerProtocol: typeof raw.peerProtocol === 'number' ? raw.peerProtocol : undefined,
        version: raw.version,
      });
    } catch {
      // Unreadable or half-written file: skip it, same as Claude does.
    }
  }
  return out;
}

// Connect-and-drop liveness probe. EBUSY means a listener exists but its
// backlog is full, which still counts as alive.
function probe(sockPath, timeoutMs = 250) {
  return new Promise((resolve) => {
    if (!sockPath) return resolve(false);
    const sock = net.connect({ path: sockPath });
    const done = (alive) => {
      sock.destroy();
      resolve(alive);
    };
    sock.on('connect', () => done(true));
    sock.on('error', (err) => done(err.code === 'EBUSY'));
    sock.setTimeout(timeoutMs, () => done(false));
  });
}

async function livePeers({ excludeSocket } = {}) {
  const all = readAll().filter((p) => p.sock && p.sock !== excludeSocket);
  const alive = await Promise.all(all.map((p) => probe(p.sock)));
  return all.filter((_, i) => alive[i]);
}

function resolvePeer(peers, query) {
  const q = String(query);
  return (
    peers.find((p) => p.name === q) ||
    peers.find((p) => String(p.pid) === q) ||
    peers.find((p) => p.sessionId === q) ||
    peers.find((p) => p.name && p.name.startsWith(q)) ||
    null
  );
}

// ---------------------------------------------------------------------------
// Advertising ourselves
// ---------------------------------------------------------------------------

class Registration {
  // `enabled: false` makes every write a no-op, so an unregistered peer stays
  // unregistered no matter which code path (heartbeat, rename, status change)
  // reaches for it. Guarding at the call sites instead is how you end up
  // publishing a phantom entry 30 seconds in.
  constructor({ name, socketPath, cwd, sessionId, kind = 'interactive', version, enabled = true }) {
    this.enabled = enabled;
    this.pid = process.pid;
    this.file = sessionFile(this.pid);
    this.record = {
      pid: this.pid,
      sessionId,
      cwd: cwd || process.cwd(),
      startedAt: Date.now(),
      procStart: procStart(this.pid),
      version,
      peerProtocol: PEER_PROTOCOL,
      kind,
      entrypoint: 'cli',
      messagingSocketPath: socketPath,
      name,
      status: 'idle',
      updatedAt: Date.now(),
      statusUpdatedAt: Date.now(),
    };
  }

  write() {
    if (!this.enabled) return;
    fs.mkdirSync(SESSIONS_DIR, { recursive: true });
    // Atomic replace: a peer scanning the directory never sees a partial file.
    const tmp = `${this.file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.record));
    fs.renameSync(tmp, this.file);
  }

  update(patch) {
    const now = Date.now();
    if (patch.status && patch.status !== this.record.status) this.record.statusUpdatedAt = now;
    Object.assign(this.record, patch, { updatedAt: now });
    this.write();
  }

  remove() {
    try {
      fs.unlinkSync(this.file);
    } catch {
      /* already gone */
    }
  }
}

module.exports = {
  SESSIONS_DIR,
  procStart,
  sessionFile,
  readAll,
  probe,
  livePeers,
  resolvePeer,
  Registration,
  fsp,
};
