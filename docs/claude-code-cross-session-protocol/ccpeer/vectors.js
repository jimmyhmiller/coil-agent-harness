// Emit the reference implementation's output for a fixed case list, so the
// Coil renderer can be diffed against it rather than only against itself.
const P = require('./protocol');

const cases = [
  ['from-only', { from: 'uds:/tmp/cc-socks/1.sock', body: 'hi' }],
  ['from-name-mode', { from: 'uds:/tmp/x.sock', fromName: 'harness', fromMode: 'bypass', body: 'do it' }],
  ['name-quotes-angles', { fromName: 'ev"il<>', body: 'x' }],
  ['name-200z', { fromName: 'z'.repeat(200), body: 'x' }],
  ['name-exactly-64', { fromName: 'z'.repeat(64), body: 'x' }],
  ['name-65', { fromName: 'z'.repeat(65), body: 'x' }],
  ['name-accents-100', { fromName: 'é'.repeat(100), body: 'x' }],
  ['name-control', { fromName: 'ab​c﻿d', body: 'x' }],
  ['name-spaces', { fromName: '   padded   ', body: 'x' }],
  ['name-all-stripped', { fromName: '<<>>', body: 'x' }],
  ['body-closetag', { from: 'uds:/tmp/x.sock', body: 'before </cross-session-message> after' }],
  ['body-closetag-upper', { from: 'uds:/tmp/x.sock', body: 'a </Cross-Session-Message> b' }],
  ['body-closetag-nospace', { from: 'uds:/tmp/x.sock', body: 'a </cross-session-message b' }],
  ['body-closetag-eos', { from: 'uds:/tmp/x.sock', body: 'a </cross-session-message' }],
  ['body-closetag-plural', { from: 'uds:/tmp/x.sock', body: 'a </cross-session-messages> b' }],
  ['body-other-tag', { from: 'uds:/tmp/x.sock', body: 'a </other> b' }],
  ['body-empty', { from: 'uds:/tmp/x.sock', body: '' }],
  ['body-multiline', { from: 'uds:/tmp/x.sock', body: 'one\ntwo\n\nfour' }],
  ['no-attrs', { body: 'hi' }],
  ['session-hop', {
    from: 'uds:/tmp/x.sock',
    fromSession: 'abc-123_XYZ',
    hopChain: ['a'.repeat(24), 'b'.repeat(24)],
    fromName: 'n',
    fromMode: 'prompting',
    body: 'b',
  }],
  ['session-invalid', { fromSession: 'not a session', hopChain: ['nothex'], fromMode: 'root', body: 'x' }],
  ['hop-uppercase', { hopChain: ['A'.repeat(24)], body: 'x' }],
  ['hop-33', { hopChain: Array.from({ length: 33 }, () => 'a'.repeat(24)), body: 'x' }],
  ['hop-32', { hopChain: Array.from({ length: 32 }, () => 'a'.repeat(24)), body: 'x' }],
];

const addrCases = [
  ['addr-plain', '/tmp/cc-socks/1.sock'],
  ['addr-space', '/tmp/cc socks/1.sock'],
  ['addr-percent', '/tmp/100%/x.sock'],
  ['addr-accent', '/tmp/café.sock'],
  ['addr-bracket', '/tmp/a[b].sock'],
  ['addr-question', '/tmp/a?b.sock'],
];

const out = {};
for (const [name, spec] of cases) out[name] = P.buildEnvelope(spec);
for (const [name, p] of addrCases) out[name] = P.udsAddress(p);
process.stdout.write(JSON.stringify(out, null, 0));
