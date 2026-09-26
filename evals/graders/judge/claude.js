'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { validate } = require('./schema');

const ALIASES = ['haiku', 'sonnet', 'opus', 'fable'];
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];

const BASE_KEYS = ['PATH', 'HOME', 'USER', 'LANG', 'TMPDIR', 'SHELL'];
const AUTH_KEYS = [
  'ANTHROPIC_FOUNDRY_API_KEY', 'ANTHROPIC_FOUNDRY_RESOURCE', 'ANTHROPIC_FOUNDRY_BASE_URL', 'ANTHROPIC_API_KEY',
  'AWS_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION', 'AWS_BEARER_TOKEN_BEDROCK',
];
const ROUTING_KEYS = [
  'CLAUDE_CODE_USE_FOUNDRY', 'CLAUDE_CODE_USE_BEDROCK',
  'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL',
];

function checkAlias(model) {
  if (!ALIASES.includes(model)) throw new Error(`model must be an alias (${ALIASES.join(', ')}), got ${JSON.stringify(model)}`);
  return model;
}

function checkEffort(effort) {
  if (!EFFORTS.includes(effort)) throw new Error(`effort must be one of ${EFFORTS.join(', ')}, got ${JSON.stringify(effort)}`);
  return effort;
}

function buildArgv({ schema, model, effort }) {
  return [
    '-p', '--bare', '--output-format', 'json', '--json-schema', JSON.stringify(schema),
    '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', '',
    '--no-session-persistence', '--model', checkAlias(model), '--effort', checkEffort(effort),
  ];
}

function readSettingsEnv(file) {
  if (!fs.existsSync(file)) return {};
  return JSON.parse(fs.readFileSync(file, 'utf8')).env || {};
}

// Auth comes from the parent shell. Routing comes from the settings file, because a
// plain terminal has no CLAUDE_CODE_USE_FOUNDRY until Claude Code exports it. The
// 5-minute cache TTL halves cache-write cost against the 1-hour default.
function childEnv({ parent, settingsEnv }) {
  const env = {};
  for (const k of [...BASE_KEYS, ...AUTH_KEYS]) if (parent[k] !== undefined) env[k] = parent[k];
  for (const k of ROUTING_KEYS) {
    const v = settingsEnv[k] !== undefined ? settingsEnv[k] : parent[k];
    if (v !== undefined) env[k] = v;
  }
  env.CLAUDE_CODE_PROMPT_CACHE_TTL = '5m';
  return env;
}

function classify({ code, stdout, stderr, timedOut }, schema) {
  if (timedOut) return { ok: false, error: 'timeout' };
  if (code !== 0) return { ok: false, error: `exit ${code}: ${(stderr || stdout || '').trim().slice(0, 300)}` };
  let r;
  try {
    r = JSON.parse(stdout);
  } catch (e) {
    return { ok: false, error: `parse: ${e.message}` };
  }
  const cost = typeof r.total_cost_usd === 'number' ? r.total_cost_usd : 0;
  const models = Object.keys(r.modelUsage || {});
  if (r.is_error) return { ok: false, error: `is_error: ${String(r.result || '').slice(0, 300)}`, cost, models };
  if (r.subtype !== 'success') return { ok: false, error: `subtype ${r.subtype}`, cost, models };
  if (r.structured_output === undefined || r.structured_output === null) return { ok: false, error: 'missing structured_output', cost, models };
  const errors = validate(schema, r.structured_output);
  if (errors.length > 0) return { ok: false, error: `schema: ${errors.slice(0, 5).join('; ')}`, cost, models };
  return { ok: true, value: r.structured_output, cost, models, durationMs: r.duration_ms };
}

class Semaphore {
  constructor(n) {
    this.n = n;
    this.inflight = 0;
    this.peak = 0;
    this.waiting = [];
  }

  acquire() {
    if (this.inflight < this.n) {
      this.inflight += 1;
      this.peak = Math.max(this.peak, this.inflight);
      return Promise.resolve();
    }
    return new Promise((resolve) => this.waiting.push(resolve));
  }

  release() {
    const next = this.waiting.shift();
    if (next) {
      this.peak = Math.max(this.peak, this.inflight);
      next();
    } else {
      this.inflight -= 1;
    }
  }
}

function spawnRun(argv, { input, env, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'judge-'));
    const child = spawn('claude', argv, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });
    child.on('error', (e) => {
      clearTimeout(timer);
      fs.rmSync(cwd, { recursive: true, force: true });
      reject(e);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      fs.rmSync(cwd, { recursive: true, force: true });
      resolve({ code, stdout, stderr, timedOut });
    });
    child.stdin.end(input);
  });
}

function makeJudge({ run = spawnRun, semaphore, retries, timeoutMs, env }) {
  return async ({ prompt, schema, model, effort }) => {
    let argv;
    try {
      argv = buildArgv({ schema, model, effort });
    } catch (e) {
      return { ok: false, error: e.message, attempts: 0, cost: 0, models: [] };
    }
    let last;
    let cost = 0;
    for (let attempt = 1; attempt <= retries + 1; attempt += 1) {
      await semaphore.acquire();
      try {
        last = classify(await run(argv, { input: prompt, env, timeoutMs }), schema);
      } catch (e) {
        last = { ok: false, error: e.message };
      } finally {
        semaphore.release();
      }
      cost += last.cost || 0;
      if (last.ok) return { ...last, cost, attempts: attempt };
    }
    return { ...last, cost, attempts: retries + 1, models: last.models || [] };
  };
}

// One semaphore per promptfoo process, so every assertion and every pass shares the
// JUDGE_MAX_PROCS cap. The first caller sizes it.
let shared = null;
function sharedSemaphore(n) {
  if (!shared) shared = new Semaphore(n);
  return shared;
}

function peakInflight() {
  return shared ? shared.peak : 0;
}

module.exports = {
  ALIASES, checkAlias, checkEffort, buildArgv, readSettingsEnv, childEnv, classify,
  Semaphore, spawnRun, makeJudge, sharedSemaphore, peakInflight,
};
