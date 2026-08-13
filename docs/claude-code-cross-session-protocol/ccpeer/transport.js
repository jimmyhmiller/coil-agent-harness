'use strict';
// Socket plumbing: bind an inbox, and send single-frame connections.

const fs = require('fs');
const fsp = require('fs/promises');
const net = require('net');
const path = require('path');

const { MAX_LINE_BYTES } = require('./protocol');

// Reject anything that isn't a plain local path -- the receiver applies the
// same rule, and it keeps a crafted roster entry from pointing us elsewhere.
function isLocalPath(p) {
  return typeof p === 'string' && p.length > 0 && !p.includes('\0') && (p.startsWith('/') || p.startsWith('\\\\.\\pipe\\'));
}

// Split a stream into newline-delimited JSON values, dropping the connection if
// a single line grows past 1 MiB.
function lineReader(socket, onValue, onError) {
  let buf = '';
  socket.setEncoding('utf8');
  socket.on('data', (chunk) => {
    buf += chunk;
    if (Buffer.byteLength(buf) > MAX_LINE_BYTES) {
      onError?.(new Error('buffer exceeded 1 MiB without newline; dropping connection'));
      socket.destroy();
      buf = '';
      return;
    }
    let nl;
    while ((nl = buf.indexOf('\n')) !== -1) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (!line.trim()) continue;
      try {
        onValue(JSON.parse(line));
      } catch (err) {
        onError?.(new Error(`failed to parse JSON line: ${line.slice(0, 200)}`));
      }
    }
  });
  socket.on('end', () => {
    if (buf.trim()) {
      try {
        onValue(JSON.parse(buf));
      } catch (err) {
        onError?.(new Error(`failed to parse final buffer: ${buf.slice(0, 200)}`));
      }
    }
    socket.end();
  });
  socket.on('error', (err) => onError?.(err));
}

async function bindInbox(socketPath, { onFrame, onError }) {
  if (!isLocalPath(socketPath)) throw new Error(`refusing to bind non-local socket path: ${socketPath}`);

  await fsp.mkdir(path.dirname(socketPath), { recursive: true, mode: 0o700 });
  await fsp.chmod(path.dirname(socketPath), 0o700).catch(() => {});
  await fsp.unlink(socketPath).catch(() => {});

  const conns = new Set();
  // allowHalfOpen lets a sender shut down its write side and still read the
  // reply we may write back on the same connection.
  const server = net.createServer({ allowHalfOpen: true }, (sock) => {
    conns.add(sock);
    // SO_PEERCRED-style attribution. Node exposes no getsockopt for this, so
    // unlike the real implementation we have no verified peer pid; the `from`
    // field on each frame is self-declared and must be treated as a hint.
    lineReader(
      sock,
      (frame) => onFrame(frame, sock),
      onError,
    );
    sock.on('close', () => conns.delete(sock));
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(socketPath, () => {
      server.removeListener('error', reject);
      resolve();
    });
  });
  await fsp.chmod(socketPath, 0o600);

  return {
    server,
    async close() {
      for (const c of conns) c.destroy();
      conns.clear();
      await new Promise((r) => server.close(r));
      await fsp.unlink(socketPath).catch(() => {});
    },
  };
}

// One frame, one connection. On macOS the close is deferred briefly: ending
// immediately after write can deliver an RST that costs the peer the payload.
const MACOS_LINGER_MS = 150;

function sendFrame(socketPath, frame, { timeoutMs = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    if (!isLocalPath(socketPath)) {
      reject(new Error(`refusing to connect to non-local IPC path: ${socketPath}`));
      return;
    }
    const sock = net.connect({ path: socketPath });
    let failed = false;
    sock.setTimeout(timeoutMs, () => {
      failed = true;
      sock.destroy();
      reject(new Error(`timed out sending to ${socketPath}`));
    });
    sock.on('error', (err) => {
      failed = true;
      reject(err);
    });
    sock.on('connect', () => {
      sock.write(`${JSON.stringify(frame)}\n`);
      if (process.platform === 'darwin') {
        setTimeout(() => {
          if (!sock.destroyed) sock.end();
        }, MACOS_LINGER_MS);
      } else {
        sock.end();
      }
    });
    sock.on('close', () => {
      if (!failed) resolve();
    });
  });
}

module.exports = { isLocalPath, lineReader, bindInbox, sendFrame };
