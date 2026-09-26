'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');

function parseIds(text, prefix) {
  const re = new RegExp(`^- \`(${prefix}-[a-z0-9-]+)\``, 'gm');
  return [...new Set([...text.matchAll(re)].map((m) => m[1]))].sort();
}

function describe(text, source, file, prefix) {
  const ids = parseIds(text, prefix);
  if (ids.length === 0) throw new Error(`catalog at ${file} has no ${prefix}- ids`);
  return { text, sha256: crypto.createHash('sha256').update(text).digest('hex'), ids, source, path: file };
}

// JUDGE_CATALOG pins a copy for an A/B and is never rebuilt. Otherwise the extract
// script runs every time and the cache is replaced on a content difference, because
// an mtime comparison is defeated by a git checkout.
async function loadCatalog({ pinned, extract, cachePath, prefix }) {
  if (pinned) return describe(fs.readFileSync(pinned, 'utf8'), 'pinned', pinned, prefix);
  const text = await extract();
  const current = fs.existsSync(cachePath) ? fs.readFileSync(cachePath, 'utf8') : null;
  if (current === text) return describe(text, 'cached', cachePath, prefix);
  describe(text, 'rebuilt', cachePath, prefix);
  fs.mkdirSync(path.dirname(cachePath), { recursive: true });
  const tmp = `${cachePath}.${process.pid}.${crypto.randomBytes(4).toString('hex')}`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, cachePath);
  return describe(text, 'rebuilt', cachePath, prefix);
}

function extractWith(script) {
  return () => new Promise((resolve, reject) => {
    execFile('python3', [script], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) reject(new Error(`${path.basename(script)} failed: ${stderr || err.message}`));
      else resolve(stdout);
    });
  });
}

module.exports = { parseIds, loadCatalog, extractWith };
