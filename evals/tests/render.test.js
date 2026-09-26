'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { render } = require('../graders/judge/render');

const PY = path.join(__dirname, '..', 'tools', 'render-template.py');

function pyRender(template, values) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'render-'));
  const tpl = path.join(dir, 'tpl.txt');
  fs.writeFileSync(tpl, template);
  const args = [PY, tpl];
  for (const [k, v] of Object.entries(values)) {
    const p = path.join(dir, `${k}.txt`);
    fs.writeFileSync(p, v);
    args.push(k, p);
  }
  try {
    return execFileSync('python3', args, { encoding: 'utf8' });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('substitutes every placeholder', () => {
  assert.equal(render('a {{x}} b {{y}}', { x: '1', y: '2' }), 'a 1 b 2');
});

test('leaves an unknown placeholder in place', () => {
  assert.equal(render('a {{x}} {{z}}', { x: '1' }), 'a 1 {{z}}');
});

test('never substitutes into already-substituted text', () => {
  assert.equal(render('{{reply}} {{catalog}}', { reply: '{{catalog}}', catalog: 'RULES' }), '{{catalog}} RULES');
});

test('refuses a value with no placeholder in the template', () => {
  assert.throws(() => render('a {{x}}', { x: '1', y: '2' }), /no placeholder for y/);
});

test('matches tools/render-template.py byte for byte', () => {
  const template = 'grade\n<<<C>>>\n{{catalog}}\n<<<R>>>\n{{reply}}\n{{unknown}}\n';
  const values = { catalog: '- `CR-a` rule\n', reply: 'I think {{catalog}} — ok\n' };
  assert.equal(render(template, values), pyRender(template, values));
});

test('matches the python renderer on the real comply prompt', () => {
  const tpl = fs.readFileSync(path.join(__dirname, '..', 'prompts', 'comply-json.txt'), 'utf8');
  const values = { catalog: '- `PC-a` x\n', source: 'the original', rewrite: 'the edit', scope: 'against every rule in the contract' };
  assert.equal(render(tpl, values), pyRender(tpl, values));
});
