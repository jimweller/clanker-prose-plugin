'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { majority, aggregateFindings, aggregateVerdicts, judgeError } = require('../graders/judge/aggregate');

const f = (rule, span = 'span', why = 'why') => ({ rule, span, why });
const ids = ['CR-a', 'CR-b', 'CR-c'];

test('majority is floor(P/2)+1', () => {
  assert.equal(majority(1), 1);
  assert.equal(majority(2), 2);
  assert.equal(majority(3), 2);
  assert.equal(majority(4), 3);
  assert.equal(majority(5), 3);
});

test('three clean passes are clean on every definition', () => {
  const r = aggregateFindings({ prefix: 'reg', passes: [{ findings: [] }, { findings: [] }, { findings: [] }], ids, perRule: true });
  assert.equal(r.pass, true);
  assert.equal(r.score, 1);
  assert.deepEqual(r.namedScores, {
    reg_judged: 1, reg_judge_error: 0, reg_passes: 3, reg_pass_clean: 3,
    reg_clean_maj: 1, reg_clean_union: 1, reg_pass_agree: 1,
    'R:CR-a': 0, 'R:CR-b': 0, 'R:CR-c': 0,
  });
  assert.deepEqual(r.componentResults, []);
});

test('a rule seen by two of three passes reaches majority and the row is dirty', () => {
  const passes = [{ findings: [f('CR-a', 'I think')] }, { findings: [f('CR-a', 'I'), f('CR-b', 'you')] }, { findings: [] }];
  const r = aggregateFindings({ prefix: 'reg', passes, ids, perRule: true });
  assert.equal(r.pass, false);
  assert.equal(r.namedScores.reg_pass_clean, 1);
  assert.equal(r.namedScores.reg_clean_maj, 0);
  assert.equal(r.namedScores.reg_clean_union, 0);
  assert.equal(r.namedScores.reg_pass_agree, 0);
  assert.equal(r.namedScores['R:CR-a'], 1);
  assert.equal(r.namedScores['R:CR-b'], 0);
  const a = r.componentResults.find((c) => c.metadata.key === 'CR-a');
  assert.equal(a.metadata.role, 'finding');
  assert.equal(a.metadata.votes, 2);
  assert.equal(a.metadata.majority, true);
  assert.deepEqual(a.metadata.passes.map((p) => p.span), ['I think', 'I']);
  assert.deepEqual(a.metadata.passes.map((p) => p.pass_index), [0, 1]);
  const b = r.componentResults.find((c) => c.metadata.key === 'CR-b');
  assert.equal(b.metadata.votes, 1);
  assert.equal(b.metadata.majority, false);
  assert.equal(r.componentResults[0].metadata.key, 'CR-a');
});

test('a single dissenting pass leaves the row clean by majority but dirty by union', () => {
  const r = aggregateFindings({ prefix: 'reg', passes: [{ findings: [f('CR-a')] }, { findings: [] }, { findings: [] }], ids, perRule: true });
  assert.equal(r.pass, true);
  assert.equal(r.namedScores.reg_clean_maj, 1);
  assert.equal(r.namedScores.reg_clean_union, 0);
  assert.equal(r.namedScores['R:CR-a'], 0);
});

test('a rule reported twice in one pass counts one vote', () => {
  const r = aggregateFindings({ prefix: 'reg', passes: [{ findings: [f('CR-a', 'x'), f('CR-a', 'y')] }, { findings: [] }, { findings: [] }], ids, perRule: true });
  assert.equal(r.componentResults[0].metadata.votes, 1);
  assert.equal(r.componentResults[0].metadata.passes.length, 2);
});

test('all passes dirty agree even when they cite different rules', () => {
  const r = aggregateFindings({ prefix: 'reg', passes: [{ findings: [f('CR-a')] }, { findings: [f('CR-b')] }, { findings: [f('CR-c')] }], ids, perRule: true });
  assert.equal(r.namedScores.reg_pass_agree, 1);
  assert.equal(r.namedScores.reg_clean_maj, 0);
  assert.deepEqual(ids.map((i) => r.namedScores[`R:${i}`]), [0, 0, 0]);
});

test('one pass has a majority of one', () => {
  const r = aggregateFindings({ prefix: 'reg', passes: [{ findings: [f('CR-a')] }], ids, perRule: true });
  assert.equal(r.namedScores['R:CR-a'], 1);
  assert.equal(r.namedScores.reg_pass_agree, 1);
});

test('without perRule no R: keys are emitted', () => {
  const r = aggregateFindings({ prefix: 'cmp', passes: [{ findings: [] }], ids });
  assert.equal(Object.keys(r.namedScores).some((k) => k.startsWith('R:')), false);
});

test('prose kinds key findings by kind and rule and count violation and over-applied majorities', () => {
  const v = (rule) => ({ kind: 'violation', rule, span: 's', why: 'w' });
  const o = (rule) => ({ kind: 'over-applied', rule, span: 's', why: 'w' });
  const passes = [{ findings: [v('PC-a'), o('PC-b')] }, { findings: [v('PC-a')] }, { findings: [o('PC-a')] }];
  const r = aggregateFindings({ prefix: 'cmp', passes, ids: ['PC-a', 'PC-b'], kinds: true });
  assert.equal(r.namedScores.cmp_viol_maj, 1);
  assert.equal(r.namedScores.cmp_over_maj, 1);
  const keys = r.componentResults.map((c) => c.metadata.key).sort();
  assert.deepEqual(keys, ['over-applied:PC-a', 'over-applied:PC-b', 'violation:PC-a']);
  assert.equal(r.componentResults.find((c) => c.metadata.key === 'violation:PC-a').metadata.votes, 2);
});

test('an over-applied finding alone makes a row dirty', () => {
  const o = { kind: 'over-applied', rule: 'PC-a', span: 's', why: 'w' };
  const r = aggregateFindings({ prefix: 'cmp', passes: [{ findings: [o] }, { findings: [o] }, { findings: [] }], ids: ['PC-a'], kinds: true });
  assert.equal(r.pass, false);
  assert.equal(r.namedScores.cmp_viol_maj, 0);
  assert.equal(r.namedScores.cmp_over_maj, 1);
});

test('per-class keys are dense across the configured classes', () => {
  const r = aggregateFindings({ prefix: 'cmp', passes: [{ findings: [] }], ids: ['PC-a'], kinds: true, rowClass: 'mixed', classes: ['good', 'mixed', 'slop'] });
  assert.equal(r.namedScores.cmp_judged_good, 0);
  assert.equal(r.namedScores.cmp_judged_mixed, 1);
  assert.equal(r.namedScores.cmp_judged_slop, 0);
  assert.equal(r.namedScores.cmp_clean_maj_good, 0);
  assert.equal(r.namedScores.cmp_clean_maj_mixed, 1);
  assert.equal(r.namedScores.cmp_clean_maj_slop, 0);
});

test('an unknown row class is refused', () => {
  assert.throws(() => aggregateFindings({ prefix: 'cmp', passes: [{ findings: [] }], ids: ['PC-a'], rowClass: 'other', classes: ['good'] }), /class/);
});

test('verdict majority counts pass votes', () => {
  const r = aggregateVerdicts({ prefix: 'cor', passes: [{ verdict: 'pass', reason: 'a' }, { verdict: 'fail', reason: 'b' }, { verdict: 'pass', reason: 'c' }] });
  assert.equal(r.pass, true);
  assert.deepEqual(r.namedScores, { cor_judged: 1, cor_judge_error: 0, cor_passes: 3, cor_pass_votes: 2, cor_pass_maj: 1 });
  assert.equal(r.componentResults.length, 3);
  assert.equal(r.componentResults[1].metadata.role, 'verdict');
});

test('verdict minority fails', () => {
  const r = aggregateVerdicts({ prefix: 'cor', passes: [{ verdict: 'fail', reason: 'a' }, { verdict: 'fail', reason: 'b' }, { verdict: 'pass', reason: 'c' }] });
  assert.equal(r.pass, false);
  assert.equal(r.score, 0);
  assert.equal(r.namedScores.cor_pass_maj, 0);
});

test('a judge error carries only the error key', () => {
  const r = judgeError({ prefix: 'reg', message: 'timeout' });
  assert.equal(r.pass, false);
  assert.equal(r.score, 0);
  assert.match(r.reason, /^JUDGE_ERROR: timeout/);
  assert.deepEqual(r.namedScores, { reg_judge_error: 1 });
});
