'use strict';
// Wire protocol for Claude Code's cross-session peer messaging ("SendMessage").
//
// Transport: newline-delimited JSON over a unix domain socket.
//   - Each session binds  $XDG_RUNTIME_DIR|$TMPDIR /cc-socks/<pid>.sock  (dir 0700, sock 0600)
//   - Each session advertises itself in ~/.claude/sessions/<pid>.json
//   - A sender just connects, writes one JSON line, and closes.
//   - Receiver drops a connection if >1 MiB accumulates without a newline.
//
// Peer identity is self-declared in the `from` field. The receiver additionally
// looks up the connecting process's pid via SO_PEERPID, but only to detect
// self-sends -- it is not an authorization check.

const crypto = require('crypto');
const os = require('os');
const path = require('path');

const MSG_V = 1;
const PEER_PROTOCOL = 1;
const MAX_SOCKET_PATH = 103;
const MAX_LINE_BYTES = 1024 * 1024;
const TAG = 'cross-session-message';

// ---------------------------------------------------------------------------
// Addresses
// ---------------------------------------------------------------------------

// Percent-encode anything outside the address-safe set, so the result satisfies
// the receiver's /^[A-Za-z0-9%:_/.\\-]{1,300}$/ address check.
function encodeAddr(str) {
  return str.replace(/[^A-Za-z0-9:_/.\\-]/gu, (ch) =>
    Array.from(Buffer.from(ch, 'utf8'), (b) => `%${b.toString(16).toUpperCase().padStart(2, '0')}`).join(''),
  );
}

function udsAddress(socketPath) {
  return `uds:${encodeAddr(socketPath)}`;
}

function parseAddress(addr) {
  if (addr.startsWith('uds:')) return { scheme: 'uds', target: safeDecode(addr.slice(4)) };
  if (addr.startsWith('bridge:')) return { scheme: 'bridge', target: safeDecode(addr.slice(7)) };
  if (addr.startsWith('did:')) return { scheme: 'did', target: addr };
  if (addr.startsWith('/')) return { scheme: 'uds', target: addr };
  return { scheme: 'other', target: addr };
}

function safeDecode(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

// Deliberately not os.tmpdir(): Claude uses CLAUDE_CODE_TMPDIR or a literal
// /tmp, and peers must land in the same directory or hold-receipts addressed
// back to us get rejected as "outside our socket namespace".
function defaultSocketPath(pid = process.pid) {
  const base = process.env.XDG_RUNTIME_DIR || process.env.CLAUDE_CODE_TMPDIR || '/tmp';
  const p = path.join(base, 'cc-socks', `${pid}.sock`);
  if (Buffer.byteLength(p) <= MAX_SOCKET_PATH) return p;
  return path.join('/tmp', `cc-socks-${process.getuid?.() ?? 0}`, `${pid}.sock`);
}

// ---------------------------------------------------------------------------
// The <cross-session-message> envelope
// ---------------------------------------------------------------------------
//
//   <cross-session-message from="uds:/tmp/cc-socks/123.sock" from-name="worker">
//   body text
//   </cross-session-message>
//
// Attribute order is significant: from, from-session, hop-chain, from-name,
// from-mode. The receiver re-renders what it parsed and compares it against the
// original string, so any deviation (extra spaces, reordered attrs, a stray
// attribute) makes it fall back to treating the whole thing as opaque text.

const RE_SESSION = /^[A-Za-z0-9_-]{1,80}$/;
const RE_HOP_CHAIN = /^[0-9a-f]{24}(?:,[0-9a-f]{24}){0,31}$/;
const MODES = ['bypass', 'prompting'];

// Strip format/control chars and clamp to 64 code points, matching the
// receiver's own normalization of from-name.
function sanitizeName(name) {
  const clean = name.replace(/[\p{Cf}\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/gu, '').trim();
  const chars = [...clean];
  return chars.length > 64 ? `${chars.slice(0, 64).join('')}…` : clean;
}

// Neutralize a closing tag hidden in the body so it can't terminate the
// envelope early. The receiver expects exactly this substitution.
function scrubCloseTag(body) {
  return body.replace(new RegExp(`</(?=${TAG}(?:[>\\s/]|$))`, 'gi'), '<\\/');
}

function buildEnvelope({ from, fromName, body, fromSession, hopChain, fromMode }) {
  const attrs = [];
  if (from) attrs.push(`from="${from}"`);
  if (fromSession && RE_SESSION.test(fromSession)) attrs.push(`from-session="${fromSession}"`);
  if (hopChain && hopChain.length > 0) {
    const joined = hopChain.join(',');
    if (RE_HOP_CHAIN.test(joined)) attrs.push(`hop-chain="${joined}"`);
  }
  const name = fromName === undefined ? undefined : sanitizeName(fromName.replace(/["<>]/g, ''));
  if (name) attrs.push(`from-name="${name}"`);
  if (fromMode && MODES.includes(fromMode)) attrs.push(`from-mode="${fromMode}"`);
  const head = attrs.length > 0 ? ` ${attrs.join(' ')}` : '';
  return `<${TAG}${head}>\n${scrubCloseTag(body)}\n</${TAG}>`;
}

const ENVELOPE_RE = new RegExp(
  `^<${TAG}` +
    `(?: from="([A-Za-z0-9%:_/.\\\\-]+)")?` +
    `(?: from-session="([A-Za-z0-9_-]{1,80})")?` +
    `(?: hop-chain="([0-9a-f]{24}(?:,[0-9a-f]{24}){0,31})")?` +
    `(?: from-name="([^"<>\\n\\r]+)")?` +
    `(?: from-mode="(bypass|prompting)")?` +
    `>\\n([\\s\\S]*)\\n</${TAG}>$`,
);

// Returns null when the text is not a well-formed envelope -- including the
// round-trip check the receiver performs, so a body that merely looks like one
// is not misread as peer metadata.
function parseEnvelope(text) {
  if (typeof text !== 'string') return null;
  const m = text.match(ENVELOPE_RE);
  if (!m) return null;
  const parsed = {
    from: m[1],
    fromSession: m[2],
    hopChain: m[3] !== undefined ? m[3].split(',') : undefined,
    fromName: m[4],
    fromMode: m[5],
    body: m[6] ?? '',
  };
  if (buildEnvelope(parsed) !== text) return null;
  return parsed;
}

// ---------------------------------------------------------------------------
// Frames
// ---------------------------------------------------------------------------

function newMsgId() {
  return crypto.randomUUID();
}

// priority: "next" (front of queue, what SendMessage uses) or "later".
function userFrame({ content, from, priority = 'next', sessionId, fileAttachments }) {
  const frame = {
    msgV: MSG_V,
    msg_id: newMsgId(),
    type: 'user',
    message: { role: 'user', content },
    priority,
  };
  if (from) frame.from = from;
  // Only set session_id when targeting a specific session: the receiver drops
  // any frame whose session_id is present and does not match its own.
  if (sessionId) frame.session_id = sessionId;
  if (fileAttachments && fileAttachments.length > 0) frame.file_attachments = fileAttachments;
  return frame;
}

function controlFrame(action, extra = {}) {
  return { msgV: MSG_V, msg_id: newMsgId(), type: 'control', action, ...extra };
}

const STATUS_REASONS = {
  held: "Your message is held for the recipient user's approval before it reaches their Claude session (permission-mode parity).",
  denied: 'The recipient user declined your message; it was not delivered to their Claude session.',
  expired: "Your held message expired without approval and was not delivered to the recipient's Claude session.",
  delivered: "Your previously-held message was approved and released to the recipient's Claude session.",
};

module.exports = {
  MSG_V,
  PEER_PROTOCOL,
  MAX_LINE_BYTES,
  TAG,
  STATUS_REASONS,
  encodeAddr,
  udsAddress,
  parseAddress,
  defaultSocketPath,
  buildEnvelope,
  parseEnvelope,
  sanitizeName,
  scrubCloseTag,
  newMsgId,
  userFrame,
  controlFrame,
};
