'use strict';
// promptfoo javascript assertion for the compliance and generation loops. promptfoo
// does not catch a throw from a file:// assertion, so grade() returns a JUDGE_ERROR
// GradingResult for every failure.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const claude = require('./judge/claude');
const { proseSchema } = require('./judge/schema');
const { aggregateFindings, judgeError } = require('./judge/aggregate');
const { render } = require('./judge/render');
const { loadCatalog, extractWith } = require('./judge/catalog');
const { loadGroups, buildUnits } = require('./judge/groups');

const SUITE_ROOT = path.resolve(__dirname, '..');
const GROUPS_FILE = path.join(SUITE_ROOT, 'tools', 'bullet-groups.json');
const EXTRACT = path.join(SUITE_ROOT, 'tools', 'extract-catalog.py');
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');

const PREFIX = 'cmp';
const DEFAULT_CLASSES = ['good', 'mixed', 'slop'];

const SETTINGS = {
  model: { env: 'JUDGE_MODEL', fallback: 'opus', parse: String },
  effort: { env: 'JUDGE_EFFORT', fallback: 'high', parse: String },
  passes: { env: 'JUDGE_PASSES', fallback: 3, parse: positiveInt },
  max_procs: { env: 'JUDGE_MAX_PROCS', fallback: 96, parse: positiveInt },
  retries: { env: 'JUDGE_RETRIES', fallback: 0, parse: nonNegativeInt },
  timeout_ms: { env: 'JUDGE_TIMEOUT_MS', fallback: 600000, parse: positiveInt },
  catalog: { env: 'JUDGE_CATALOG', fallback: null, parse: String },
  mode: { env: 'JUDGE_MODE', fallback: 'whole', parse: String },
};

function positiveInt(v) {
  const n = Number(v);
  if (!Number.isInteger(n) || n < 1) throw new Error(`expected a positive integer, got ${JSON.stringify(v)}`);
  return n;
}

function nonNegativeInt(v) {
  const n = Number(v);
  if (!Number.isInteger(n) || n < 0) throw new Error(`expected a non-negative integer, got ${JSON.stringify(v)}`);
  return n;
}

function resolveSettings(config, env) {
  const out = {};
  for (const [name, spec] of Object.entries(SETTINGS)) {
    if (env[spec.env] !== undefined && env[spec.env] !== '') out[name] = { value: spec.parse(env[spec.env]), source: 'env' };
    else if (config[name] !== undefined && config[name] !== null) out[name] = { value: spec.parse(config[name]), source: 'config' };
    else out[name] = { value: spec.fallback, source: 'default' };
  }
  return out;
}

const catalogs = new Map();
function defaultLoadCatalog(settings) {
  const pinned = settings.catalog.value;
  const key = pinned || '';
  if (!catalogs.has(key)) {
    const promise = loadCatalog({ pinned, extract: extractWith(EXTRACT), cachePath: path.join(SUITE_ROOT, 'corpus', 'catalog.md'), prefix: 'PC' });
    promise.catch(() => catalogs.delete(key));
    catalogs.set(key, promise);
  }
  return catalogs.get(key);
}

function defaultCallJudge(settings, env) {
  return claude.makeJudge({
    semaphore: claude.sharedSemaphore(settings.max_procs.value),
    retries: settings.retries.value,
    timeoutMs: settings.timeout_ms.value,
    env: claude.childEnv({ parent: env, settingsEnv: claude.readSettingsEnv(path.join(os.homedir(), '.claude', 'settings.json')) }),
  });
}

// promptfoo flattens every assertion's componentResults into one list per row, so each
// entry carries the judge kind that produced it.
function withMeta(result, meta) {
  const tag = (c) => ({ ...c, metadata: { ...c.metadata, judge_kind: meta.kind } });
  return { ...result, componentResults: [{ pass: true, score: 1, reason: 'judge run metadata', metadata: meta }, ...result.componentResults].map(tag) };
}

async function grade(output, context, deps = {}) {
  const env = deps.env || process.env;
  const config = (context && context.config) || {};
  const vars = (context && context.vars) || {};
  const meta = { role: 'judge', kind: config.kind === undefined ? null : config.kind };
  try {
    if (config.kind !== 'comply') throw new Error(`unknown judge kind ${JSON.stringify(config.kind)}`);
    if (typeof output !== 'string') throw new Error(`output is ${output === null ? 'null' : typeof output}, not a string`);
    const settings = resolveSettings(config, env);
    meta.settings = settings;
    claude.checkAlias(settings.model.value);
    claude.checkEffort(settings.effort.value);
    const sourceVar = config.source_var || 'passage';
    if (typeof vars[sourceVar] !== 'string' || vars[sourceVar] === '') throw new Error(`test has no ${sourceVar} var to grade the edit against`);
    let rowClass;
    if (config.class_var) {
      rowClass = vars[config.class_var];
      const classes = config.classes || DEFAULT_CLASSES;
      if (!classes.includes(rowClass)) throw new Error(`row class ${JSON.stringify(rowClass)} is not one of ${JSON.stringify(classes)}`);
    }
    if (typeof config.prompt !== 'string') throw new Error('config.prompt is required');
    const promptPath = path.resolve(SUITE_ROOT, config.prompt);
    const template = fs.readFileSync(promptPath, 'utf8');
    meta.prompt_path = path.relative(SUITE_ROOT, promptPath);
    meta.prompt_sha256 = sha(template);

    const catalog = await (deps.loadCatalog || defaultLoadCatalog)(settings);
    meta.catalog_sha256 = catalog.sha256;
    meta.catalog_source = catalog.source;
    meta.catalog_path = catalog.path;

    const units = buildUnits({ mode: settings.mode.value, catalogIds: catalog.ids, groups: (deps.loadGroups || (() => loadGroups(GROUPS_FILE)))() });
    meta.mode = settings.mode.value;
    meta.units = units.map((u) => ({ name: u.name, ids: u.ids.length }));
    const requests = units.map((u) => {
      const schema = proseSchema(u.ids);
      return { unit: u.name, schema, prompt: render(template, { catalog: catalog.text, source: vars[sourceVar], rewrite: output, scope: u.scope }) };
    });
    meta.schema_sha256 = requests.map((r) => sha(JSON.stringify(r.schema)));

    const callJudge = deps.callJudge || defaultCallJudge(settings, env);
    const p = settings.passes.value;
    const judged = await Promise.all(Array.from({ length: p }, () => Promise.all(requests.map((r) => callJudge({
      prompt: r.prompt, schema: r.schema, model: settings.model.value, effort: settings.effort.value,
    })))));
    const flat = judged.flat();
    meta.calls = flat.length;
    meta.costs = judged.map((pass) => pass.reduce((a, r) => a + (r.cost || 0), 0));
    meta.cost_total = meta.costs.reduce((a, b) => a + b, 0);
    meta.attempts = flat.map((r) => r.attempts);
    meta.models = [...new Set(flat.flatMap((r) => r.models || []))].sort();
    meta.peak_inflight = deps.peakInflight ? deps.peakInflight() : claude.peakInflight();

    for (let i = 0; i < p; i += 1) {
      const bad = judged[i].findIndex((r) => !r.ok);
      if (bad >= 0) return withMeta(judgeError({ prefix: PREFIX, message: `pass ${i} unit ${requests[bad].unit}: ${judged[i][bad].error}` }), meta);
    }
    const passes = judged.map((pass) => ({ findings: pass.flatMap((r) => r.value.findings) }));
    return withMeta(aggregateFindings({
      prefix: PREFIX, passes, ids: catalog.ids, kinds: true,
      ...(config.class_var ? { rowClass, classes: config.classes || DEFAULT_CLASSES } : {}),
    }), meta);
  } catch (e) {
    return withMeta(judgeError({ prefix: PREFIX, message: e.message }), meta);
  }
}

module.exports = async (output, context) => grade(output, context);
module.exports.grade = grade;
module.exports.resolveSettings = resolveSettings;
