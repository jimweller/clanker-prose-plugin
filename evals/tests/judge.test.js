'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const judgeModule = require('../graders/judge');
const { grade, resolveSettings } = judgeModule;

const CATALOG = { text: '- `PC-a` one\n- `PC-b` two\n- `PC-c` three\n', sha256: 'catsha', ids: ['PC-a', 'PC-b', 'PC-c'], source: 'pinned', path: '/p.md' };
const GROUPS = { g1: ['PC-a'], g2: ['PC-b'] };

function fakeJudge(fn) {
  const calls = [];
  const judge = async (req) => {
    calls.push(req);
    return fn(req, calls.length - 1);
  };
  judge.calls = calls;
  return judge;
}

const okv = (value) => ({ ok: true, value, cost: 0.01, attempts: 1, models: ['claude-opus-5-5[1m]'] });
const v = (rule) => ({ kind: 'violation', rule, span: 'span', why: 'why' });

function ctx(config, vars = { passage: 'the original', expect: 'mixed' }) {
  return { config: { kind: 'comply', prompt: 'prompts/comply-json.txt', source_var: 'passage', ...config }, vars, providerResponse: { output: 'the edit' } };
}

const deps = (callJudge, extra = {}) => ({ callJudge, loadCatalog: async () => CATALOG, loadGroups: () => GROUPS, env: {}, peakInflight: () => 3, ...extra });

test('the module exports a function for promptfoo and grade for injection', () => {
  assert.equal(typeof judgeModule, 'function');
  assert.equal(typeof grade, 'function');
});

test('JUDGE_MODE beats config.mode', () => {
  assert.deepEqual(resolveSettings({ mode: 'whole' }, { JUDGE_MODE: 'groups' }).mode, { value: 'groups', source: 'env' });
});

test('whole mode runs one call per pass over every id, source, and edit', async () => {
  const callJudge = fakeJudge(() => okv({ findings: [] }));
  const r = await grade('the edit', ctx({ passes: 3, class_var: 'expect' }), deps(callJudge));
  assert.equal(callJudge.calls.length, 3);
  for (const c of callJudge.calls) {
    assert.ok(c.prompt.includes(CATALOG.text));
    assert.ok(c.prompt.includes('the original'));
    assert.ok(c.prompt.includes('the edit'));
    assert.ok(c.prompt.includes('Grade against every rule in the contract.'));
    assert.deepEqual(c.schema.properties.findings.items.properties.rule.enum, ['PC-a', 'PC-b', 'PC-c']);
  }
  assert.equal(r.pass, true);
  assert.equal(r.namedScores.cmp_clean_maj, 1);
  assert.equal(r.namedScores.cmp_judged_mixed, 1);
  assert.equal(r.namedScores.cmp_clean_maj_mixed, 1);
  assert.equal(r.namedScores.cmp_judged_good, 0);
  assert.equal(r.namedScores.cmp_viol_maj, 0);
  const meta = r.componentResults[0].metadata;
  assert.equal(meta.mode, 'whole');
  assert.deepEqual(meta.units, [{ name: 'whole', ids: 3 }]);
  assert.equal(meta.calls, 3);
});

test('group mode splits every pass into one call per unit and merges the findings', async () => {
  const callJudge = fakeJudge((req) => {
    const ids = req.schema.properties.findings.items.properties.rule.enum;
    return okv({ findings: ids.includes('PC-b') ? [v('PC-b')] : [] });
  });
  const r = await grade('the edit', ctx({ passes: 3, mode: 'groups', class_var: 'expect' }), deps(callJudge));
  assert.equal(callJudge.calls.length, 9);
  const enums = callJudge.calls.slice(0, 3).map((c) => c.schema.properties.findings.items.properties.rule.enum);
  assert.deepEqual(enums, [['PC-a'], ['PC-b'], ['PC-c']]);
  assert.match(callJudge.calls[0].prompt, /Grade against these rules only, and report no other rule: PC-a\./);
  assert.equal(r.pass, false);
  assert.equal(r.namedScores.cmp_viol_maj, 1);
  const finding = r.componentResults.find((c) => c.metadata.role === 'finding');
  assert.equal(finding.metadata.key, 'violation:PC-b');
  assert.equal(finding.metadata.votes, 3);
  assert.deepEqual(r.componentResults[0].metadata.units, [{ name: 'g1', ids: 1 }, { name: 'g2', ids: 1 }, { name: 'remainder', ids: 1 }]);
});

test('one failed unit makes the row a judge error naming the pass and unit', async () => {
  const callJudge = fakeJudge((req, i) => (i === 4 ? { ok: false, error: 'exit 1: boom', attempts: 1, cost: 0 } : okv({ findings: [] })));
  const r = await grade('the edit', ctx({ passes: 3, mode: 'groups' }), deps(callJudge));
  assert.match(r.reason, /^JUDGE_ERROR: pass 1 unit g2: exit 1: boom/);
  assert.equal(r.namedScores.cmp_judge_error, 1);
});

test('a missing source var is a judge error', async () => {
  const callJudge = fakeJudge(() => okv({ findings: [] }));
  const r = await grade('the edit', ctx({ passes: 1 }, { expect: 'good' }), deps(callJudge));
  assert.match(r.reason, /^JUDGE_ERROR: .*passage/);
  assert.equal(callJudge.calls.length, 0);
});

test('without class_var no per-class keys are emitted', async () => {
  const callJudge = fakeJudge(() => okv({ findings: [] }));
  const r = await grade('the edit', ctx({ passes: 1 }, { passage: 'facts', expect: 'generation' }), deps(callJudge));
  assert.equal(Object.keys(r.namedScores).some((k) => k.startsWith('cmp_judged_')), false);
});

test('an unknown class is a judge error rather than a silent zero', async () => {
  const callJudge = fakeJudge(() => okv({ findings: [] }));
  const r = await grade('the edit', ctx({ passes: 1, class_var: 'expect' }, { passage: 'x', expect: 'generation' }), deps(callJudge));
  assert.match(r.reason, /^JUDGE_ERROR: .*class/);
});

test('every component result names the comply judge', async () => {
  const callJudge = fakeJudge(() => okv({ findings: [v('PC-a')] }));
  const r = await grade('the edit', ctx({ passes: 3 }), deps(callJudge));
  for (const c of r.componentResults) assert.equal(c.metadata.judge_kind, 'comply');
});

test('the judge defaults to opus at high effort', () => {
  const s = resolveSettings({}, {});
  assert.deepEqual(s.model, { value: 'opus', source: 'default' });
  assert.deepEqual(s.effort, { value: 'high', source: 'default' });
});
