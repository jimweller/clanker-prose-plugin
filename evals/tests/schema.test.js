'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { registerSchema, correctnessSchema, proseSchema, validate } = require('../graders/judge/schema');

test('register schema enumerates exactly the ids in scope', () => {
  const s = registerSchema(['CR-b', 'CR-a']);
  assert.deepEqual(s.properties.findings.items.properties.rule.enum, ['CR-a', 'CR-b']);
  assert.equal(s.additionalProperties, false);
  assert.equal(s.properties.findings.items.additionalProperties, false);
  assert.equal(s.properties.findings.items.properties.span.minLength, 1);
});

test('register schema refuses an empty id list', () => {
  assert.throws(() => registerSchema([]), /no ids/);
});

test('a clean register answer validates', () => {
  assert.deepEqual(validate(registerSchema(['CR-a']), { findings: [] }), []);
});

test('a register finding validates', () => {
  const v = { findings: [{ rule: 'CR-a', span: 'I think', why: 'first person' }] };
  assert.deepEqual(validate(registerSchema(['CR-a']), v), []);
});

test('an invented id fails validation', () => {
  const v = { findings: [{ rule: 'CR-made-up', span: 'x', why: 'y' }] };
  assert.ok(validate(registerSchema(['CR-a']), v).length > 0);
});

test('an extra property fails validation', () => {
  assert.ok(validate(registerSchema(['CR-a']), { findings: [], verdict: 'clean' }).length > 0);
  const v = { findings: [{ rule: 'CR-a', span: 'x', why: 'y', severity: 'high' }] };
  assert.ok(validate(registerSchema(['CR-a']), v).length > 0);
});

test('an empty span or a missing field fails validation', () => {
  assert.ok(validate(registerSchema(['CR-a']), { findings: [{ rule: 'CR-a', span: '', why: 'y' }] }).length > 0);
  assert.ok(validate(registerSchema(['CR-a']), { findings: [{ rule: 'CR-a', why: 'y' }] }).length > 0);
  assert.ok(validate(registerSchema(['CR-a']), {}).length > 0);
  assert.ok(validate(registerSchema(['CR-a']), { findings: 'none' }).length > 0);
  assert.ok(validate(registerSchema(['CR-a']), null).length > 0);
});

test('correctness schema accepts pass and fail only', () => {
  const s = correctnessSchema();
  assert.deepEqual(validate(s, { verdict: 'pass', reason: 'accurate' }), []);
  assert.deepEqual(validate(s, { verdict: 'fail', reason: 'wrong flag' }), []);
  assert.ok(validate(s, { verdict: 'maybe', reason: 'x' }).length > 0);
  assert.ok(validate(s, { verdict: 'pass', reason: '' }).length > 0);
});

test('prose schema carries kind and rule enums', () => {
  const s = proseSchema(['PC-b', 'PC-a']);
  const item = s.properties.findings.items;
  assert.deepEqual(item.properties.kind.enum, ['violation', 'over-applied']);
  assert.deepEqual(item.properties.rule.enum, ['PC-a', 'PC-b']);
  assert.deepEqual(validate(s, { findings: [{ kind: 'violation', rule: 'PC-a', span: 's', why: 'w' }] }), []);
  assert.ok(validate(s, { findings: [{ kind: 'style', rule: 'PC-a', span: 's', why: 'w' }] }).length > 0);
});
