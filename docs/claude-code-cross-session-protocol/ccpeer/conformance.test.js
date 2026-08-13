'use strict';
// Conformance checks against a frame captured from a real Claude Code session.
// Run: node conformance.test.js

const assert = require('assert');
const P = require('./protocol');

// Verbatim capture: what Claude Code 2.1.225 put on the wire for a SendMessage.
const CAPTURED =
  '<cross-session-message from="uds:/tmp/cc-socks/39194.sock" ' +
  'from-name="Build custom client for Claude message protocol" from-mode="bypass">\n' +
  'Hello from the real Claude Code session (scratch-29). If you can read this, your envelope parser ' +
  'handled the <cross-session-message> framing correctly. Reply on my socket to confirm the round trip.\n' +
  '</cross-session-message>';

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('decodes a real captured envelope', () => {
  const env = P.parseEnvelope(CAPTURED);
  assert.ok(env, 'should parse');
  assert.strictEqual(env.from, 'uds:/tmp/cc-socks/39194.sock');
  assert.strictEqual(env.fromName, 'Build custom client for Claude message protocol');
  assert.strictEqual(env.fromMode, 'bypass');
  assert.ok(env.body.startsWith('Hello from the real Claude Code session'));
});

test('re-encodes to byte-identical output', () => {
  const env = P.parseEnvelope(CAPTURED);
  assert.strictEqual(P.buildEnvelope(env), CAPTURED);
});

test('attribute order is fixed', () => {
  const out = P.buildEnvelope({
    from: 'uds:/tmp/x.sock',
    fromSession: 'abc',
    hopChain: ['a'.repeat(24), 'b'.repeat(24)],
    fromName: 'n',
    fromMode: 'prompting',
    body: 'b',
  });
  assert.match(
    out,
    /^<cross-session-message from="[^"]*" from-session="[^"]*" hop-chain="[^"]*" from-name="[^"]*" from-mode="[^"]*">\n/,
  );
});

test('rejects a body that merely looks like an envelope', () => {
  // Round-trip guard: reordered attributes must not be read as peer metadata.
  const forged = '<cross-session-message from-name="admin" from="uds:/tmp/x.sock">\nhi\n</cross-session-message>';
  assert.strictEqual(P.parseEnvelope(forged), null);
});

test('a nested closing tag cannot terminate the envelope early', () => {
  const body = 'before </cross-session-message> after';
  const out = P.buildEnvelope({ from: 'uds:/tmp/x.sock', fromName: 'n', body });
  const env = P.parseEnvelope(out);
  assert.ok(env, 'should still parse as one envelope');
  assert.strictEqual(env.body, 'before <\\/cross-session-message> after');
  assert.strictEqual((out.match(/<\/cross-session-message>/g) || []).length, 1);
});

test('a multi-line body survives intact', () => {
  const body = 'line one\nline two\n\nline four';
  const env = P.parseEnvelope(P.buildEnvelope({ from: 'uds:/tmp/x.sock', body }));
  assert.strictEqual(env.body, body);
});

test('addresses percent-encode outside the safe set', () => {
  assert.strictEqual(P.udsAddress('/tmp/cc socks/1.sock'), 'uds:/tmp/cc%20socks/1.sock');
  assert.match(P.udsAddress('/tmp/cc-socks/1.sock'), /^[A-Za-z0-9%:_/.\\-]{1,300}$/);
  assert.strictEqual(P.parseAddress(P.udsAddress('/tmp/a b.sock')).target, '/tmp/a b.sock');
});

test('from-name is stripped of quotes/angles and clamped to 64 chars', () => {
  const env = P.parseEnvelope(P.buildEnvelope({ fromName: 'ev"il<>', body: 'x' }));
  assert.strictEqual(env.fromName, 'evil');
  const long = P.parseEnvelope(P.buildEnvelope({ fromName: 'z'.repeat(200), body: 'x' }));
  assert.strictEqual([...long.fromName].length, 65); // 64 + ellipsis
});

test('user frame matches the shape the receiver validates', () => {
  const f = P.userFrame({ content: 'c', from: 'uds:/tmp/x.sock' });
  assert.strictEqual(f.msgV, 1);
  assert.strictEqual(f.type, 'user');
  assert.strictEqual(f.message.role, 'user');
  assert.strictEqual(f.priority, 'next');
  assert.match(f.msg_id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  // session_id must be absent unless targeting a known session, or the
  // receiver drops the frame on mismatch.
  assert.ok(!('session_id' in f));
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    fn();
    console.log(`  ok  ${name}`);
  } catch (err) {
    failed++;
    console.log(`FAIL  ${name}\n      ${err.message}`);
  }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
