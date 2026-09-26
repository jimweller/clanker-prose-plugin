'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { parseIds, loadCatalog } = require('../graders/judge/catalog');

const TEXT = '### Structure\n\n- `CR-b` two\n- `CR-a` one\n- `CR-a` again\n  - `CR-nested` not a rule line\n';
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
}

test('parses unique sorted ids from rule lines only', () => {
  assert.deepEqual(parseIds(TEXT, 'CR'), ['CR-a', 'CR-b']);
});

test('parses PC ids with the PC prefix', () => {
  assert.deepEqual(parseIds('- `PC-emdashes` x\n- `CR-a` y\n', 'PC'), ['PC-emdashes']);
});

test('a pinned catalog is read as-is and never rebuilt', async () => {
  const dir = tmp();
  const pinned = path.join(dir, 'pinned.md');
  fs.writeFileSync(pinned, TEXT);
  let extracted = 0;
  const c = await loadCatalog({ pinned, extract: async () => { extracted += 1; return 'other'; }, cachePath: path.join(dir, 'cache.md'), prefix: 'CR' });
  assert.equal(c.source, 'pinned');
  assert.equal(c.text, TEXT);
  assert.equal(c.sha256, sha(TEXT));
  assert.deepEqual(c.ids, ['CR-a', 'CR-b']);
  assert.equal(extracted, 0);
});

test('an absent cache is rebuilt from the extract script', async () => {
  const dir = tmp();
  const cachePath = path.join(dir, 'corpus', 'catalog.md');
  const c = await loadCatalog({ extract: async () => TEXT, cachePath, prefix: 'CR' });
  assert.equal(c.source, 'rebuilt');
  assert.equal(fs.readFileSync(cachePath, 'utf8'), TEXT);
});

test('a cache whose content matches is kept', async () => {
  const dir = tmp();
  const cachePath = path.join(dir, 'catalog.md');
  fs.writeFileSync(cachePath, TEXT);
  const c = await loadCatalog({ extract: async () => TEXT, cachePath, prefix: 'CR' });
  assert.equal(c.source, 'cached');
});

test('a stale cache is replaced by content compare, not mtime', async () => {
  const dir = tmp();
  const cachePath = path.join(dir, 'catalog.md');
  fs.writeFileSync(cachePath, 'stale');
  const future = new Date(Date.now() + 3600e3);
  fs.utimesSync(cachePath, future, future);
  const c = await loadCatalog({ extract: async () => TEXT, cachePath, prefix: 'CR' });
  assert.equal(c.source, 'rebuilt');
  assert.equal(fs.readFileSync(cachePath, 'utf8'), TEXT);
});

test('a catalog with no ids is refused', async () => {
  const dir = tmp();
  await assert.rejects(loadCatalog({ extract: async () => 'no rules', cachePath: path.join(dir, 'c.md'), prefix: 'CR' }), /no CR- ids/);
});
