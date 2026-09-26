'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { checkAlias, checkEffort, buildArgv, childEnv, readSettingsEnv, classify, Semaphore, makeJudge } = require('../graders/judge/claude');
const { registerSchema } = require('../graders/judge/schema');

const schema = registerSchema(['CR-a']);
const ok = (value, extra = {}) => ({
  code: 0,
  stdout: JSON.stringify({ type: 'result', subtype: 'success', is_error: false, structured_output: value, total_cost_usd: 0.05, modelUsage: { 'claude-opus-5-5[1m]': {} }, duration_ms: 900, ...extra }),
  stderr: '',
  timedOut: false,
});

test('aliases are the only accepted model names', () => {
  for (const a of ['haiku', 'sonnet', 'opus', 'fable']) assert.equal(checkAlias(a), a);
  assert.throws(() => checkAlias('claude-opus-5-5'), /alias/);
  assert.throws(() => checkAlias(''), /alias/);
});

test('effort accepts the CLI levels only', () => {
  for (const e of ['low', 'medium', 'high', 'xhigh', 'max']) assert.equal(checkEffort(e), e);
  assert.throws(() => checkEffort('extreme'), /effort/);
});

test('the judge argv is bare, tool-less, schema-bound, and prompt-free', () => {
  assert.deepEqual(buildArgv({ schema, model: 'opus', effort: 'medium' }), [
    '-p', '--bare', '--output-format', 'json', '--json-schema', JSON.stringify(schema),
    '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', '',
    '--no-session-persistence', '--model', 'opus', '--effort', 'medium',
  ]);
});

test('the child env is an allowlist with routing from settings', () => {
  const parent = {
    PATH: '/bin', HOME: '/h', USER: 'u', LANG: 'en', TMPDIR: '/t', SHELL: '/bin/zsh',
    SECRET_TOKEN: 's', ANTHROPIC_FOUNDRY_API_KEY: 'k', ANTHROPIC_FOUNDRY_RESOURCE: 'r',
    ENABLE_PROMPT_CACHING_1H: '1', CLAUDE_CODE_USE_FOUNDRY: '0', GITHUB_TOKEN: 'g',
  };
  const settingsEnv = { CLAUDE_CODE_USE_FOUNDRY: '1', ANTHROPIC_DEFAULT_OPUS_MODEL: 'claude-opus-5-5[1m]', DISABLE_TELEMETRY: '1', ENABLE_PROMPT_CACHING_1H: '1' };
  const env = childEnv({ parent, settingsEnv });
  for (const k of ['PATH', 'HOME', 'USER', 'LANG', 'TMPDIR', 'SHELL', 'ANTHROPIC_FOUNDRY_API_KEY', 'ANTHROPIC_FOUNDRY_RESOURCE']) assert.equal(env[k], parent[k]);
  assert.equal(env.CLAUDE_CODE_USE_FOUNDRY, '1');
  assert.equal(env.ANTHROPIC_DEFAULT_OPUS_MODEL, 'claude-opus-5-5[1m]');
  assert.equal(env.CLAUDE_CODE_PROMPT_CACHE_TTL, '5m');
  for (const k of ['SECRET_TOKEN', 'ENABLE_PROMPT_CACHING_1H', 'DISABLE_TELEMETRY', 'GITHUB_TOKEN']) assert.equal(k in env, false, k);
});

test('a routing key absent from settings falls back to the parent', () => {
  const env = childEnv({ parent: { ANTHROPIC_DEFAULT_HAIKU_MODEL: 'claude-haiku-4-5' }, settingsEnv: {} });
  assert.equal(env.ANTHROPIC_DEFAULT_HAIKU_MODEL, 'claude-haiku-4-5');
});

test('a missing settings file reads as an empty env', () => {
  assert.deepEqual(readSettingsEnv(path.join(os.tmpdir(), 'no-such-settings.json')), {});
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'settings-'));
  const f = path.join(dir, 's.json');
  fs.writeFileSync(f, JSON.stringify({ env: { CLAUDE_CODE_USE_FOUNDRY: '1' } }));
  assert.deepEqual(readSettingsEnv(f), { CLAUDE_CODE_USE_FOUNDRY: '1' });
});

test('classify accepts a success with valid structured output', () => {
  const r = classify(ok({ findings: [] }), schema);
  assert.equal(r.ok, true);
  assert.deepEqual(r.value, { findings: [] });
  assert.equal(r.cost, 0.05);
  assert.deepEqual(r.models, ['claude-opus-5-5[1m]']);
});

test('classify names every judge error', () => {
  assert.match(classify({ code: 1, stdout: '', stderr: 'boom', timedOut: false }, schema).error, /exit 1/);
  assert.match(classify({ code: null, stdout: '', stderr: '', timedOut: true }, schema).error, /timeout/);
  assert.match(classify({ code: 0, stdout: 'not json', stderr: '', timedOut: false }, schema).error, /parse/);
  assert.match(classify(ok({ findings: [] }, { is_error: true }), schema).error, /is_error/);
  assert.match(classify(ok({ findings: [] }, { subtype: 'error_max_turns' }), schema).error, /subtype/);
  assert.match(classify(ok(undefined), schema).error, /structured_output/);
  assert.match(classify(ok({ findings: [{ rule: 'CR-x', span: 'a', why: 'b' }] }), schema).error, /schema/);
});

test('the semaphore caps inflight work and records the peak', async () => {
  const sem = new Semaphore(2);
  let inflight = 0;
  let seen = 0;
  await Promise.all(Array.from({ length: 6 }, async () => {
    await sem.acquire();
    inflight += 1;
    seen = Math.max(seen, inflight);
    await new Promise((r) => setTimeout(r, 5));
    inflight -= 1;
    sem.release();
  }));
  assert.equal(seen, 2);
  assert.equal(sem.peak, 2);
});

test('makeJudge sends the prompt on stdin and returns the parsed value', async () => {
  const calls = [];
  const judge = makeJudge({ run: async (argv, opts) => { calls.push({ argv, opts }); return ok({ findings: [] }); }, semaphore: new Semaphore(4), retries: 0, timeoutMs: 1000, env: { PATH: '/bin' } });
  const r = await judge({ prompt: 'GRADE THIS', schema, model: 'opus', effort: 'medium' });
  assert.equal(r.ok, true);
  assert.equal(r.attempts, 1);
  assert.equal(calls[0].opts.input, 'GRADE THIS');
  assert.equal(calls[0].opts.timeoutMs, 1000);
  assert.equal(calls[0].argv.includes('GRADE THIS'), false);
});

test('makeJudge does not retry by default', async () => {
  let n = 0;
  const judge = makeJudge({ run: async () => { n += 1; return { code: 1, stdout: '', stderr: '', timedOut: false }; }, semaphore: new Semaphore(1), retries: 0, timeoutMs: 1000, env: {} });
  const r = await judge({ prompt: 'p', schema, model: 'opus', effort: 'medium' });
  assert.equal(r.ok, false);
  assert.equal(n, 1);
  assert.equal(r.attempts, 1);
});

test('makeJudge retries when asked and reports the attempts', async () => {
  let n = 0;
  const judge = makeJudge({ run: async () => { n += 1; return n === 1 ? { code: 1, stdout: '', stderr: '', timedOut: false } : ok({ findings: [] }); }, semaphore: new Semaphore(1), retries: 1, timeoutMs: 1000, env: {} });
  const r = await judge({ prompt: 'p', schema, model: 'opus', effort: 'medium' });
  assert.equal(r.ok, true);
  assert.equal(r.attempts, 2);
});

test('makeJudge turns a bad alias into an error without spawning', async () => {
  let n = 0;
  const judge = makeJudge({ run: async () => { n += 1; return ok({ findings: [] }); }, semaphore: new Semaphore(1), retries: 0, timeoutMs: 1000, env: {} });
  const r = await judge({ prompt: 'p', schema, model: 'claude-opus-5-5', effort: 'medium' });
  assert.equal(r.ok, false);
  assert.match(r.error, /alias/);
  assert.equal(n, 0);
});

test('makeJudge turns a runner throw into an error', async () => {
  const judge = makeJudge({ run: async () => { throw new Error('ENOENT claude'); }, semaphore: new Semaphore(1), retries: 0, timeoutMs: 1000, env: {} });
  const r = await judge({ prompt: 'p', schema, model: 'opus', effort: 'medium' });
  assert.equal(r.ok, false);
  assert.match(r.error, /ENOENT/);
});
