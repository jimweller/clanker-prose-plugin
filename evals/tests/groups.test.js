'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { loadGroups, buildUnits } = require('../graders/judge/groups');

const ROOT = path.join(__dirname, '..');
const GROUPS = path.join(ROOT, 'tools', 'bullet-groups.json');
const realIds = execFileSync('python3', [path.join(ROOT, 'tools', 'extract-catalog.py'), '--ids'], { encoding: 'utf8' }).trim().split('\n');

test('bullet-groups.json loads without its note', () => {
  const g = loadGroups(GROUPS);
  assert.deepEqual(Object.keys(g), ['rhythm', 'claim-scope', 'hidden-actor', 'pointers-and-padding']);
});

test('whole mode is one unit holding every id', () => {
  const units = buildUnits({ mode: 'whole', catalogIds: ['PC-a', 'PC-b'], groups: {} });
  assert.equal(units.length, 1);
  assert.deepEqual(units[0].ids, ['PC-a', 'PC-b']);
  assert.equal(units[0].scope, 'against every rule in the contract');
});

test('groups mode judges every contract id exactly once per pass', () => {
  const units = buildUnits({ mode: 'groups', catalogIds: realIds, groups: loadGroups(GROUPS) });
  assert.deepEqual(units.map((u) => u.name), ['rhythm', 'claim-scope', 'hidden-actor', 'pointers-and-padding', 'remainder']);
  assert.deepEqual(units.map((u) => u.ids.length), [4, 6, 5, 7, 54]);
  const all = units.flatMap((u) => u.ids);
  assert.equal(all.length, 76);
  assert.deepEqual([...new Set(all)].sort(), [...realIds].sort());
  assert.match(units[0].scope, /^against these rules only, and report no other rule: PC-/);
});

test('a group id the contract lacks is refused', () => {
  assert.throws(() => buildUnits({ mode: 'groups', catalogIds: ['PC-a'], groups: { g: ['PC-a', 'PC-zz'] } }), /PC-zz/);
});

test('overlapping groups are refused', () => {
  assert.throws(() => buildUnits({ mode: 'groups', catalogIds: ['PC-a', 'PC-b'], groups: { g1: ['PC-a'], g2: ['PC-a', 'PC-b'] } }), /PC-a.*more than one group/);
});

test('an empty remainder is left out', () => {
  const units = buildUnits({ mode: 'groups', catalogIds: ['PC-a'], groups: { g: ['PC-a'] } });
  assert.deepEqual(units.map((u) => u.name), ['g']);
});

test('an unknown mode is refused', () => {
  assert.throws(() => buildUnits({ mode: 'pairs', catalogIds: ['PC-a'], groups: {} }), /mode/);
});

test('the note in bullet-groups.json names the plugin skill file as the contract', () => {
  const note = JSON.parse(fs.readFileSync(GROUPS, 'utf8'))._note;
  assert.match(note, /skills\/prose\/SKILL\.md/);
});
