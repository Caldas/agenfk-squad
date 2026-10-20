import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = process.env.PI_COMPAT_PI_ROOT || join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), '@earendil-works/pi-coding-agent');
const require = createRequire(join(root, 'package.json'));
const { createJiti } = require('jiti');
const tuiPath = join(root, 'node_modules/@earendil-works/pi-tui/dist/index.js');
const jiti = createJiti(import.meta.url, { alias: { '@earendil-works/pi-tui': tuiPath } });
const extensionPath = fileURLToPath(new URL('./usage-dashboard.ts', import.meta.url));
const base = fileURLToPath(new URL('./usage-dashboard', import.meta.url));
const { cacheMetrics, monitorConfig, handoffLevel, DEFAULT_MONITOR } = await jiti.import(join(base, 'metrics.ts'));
const { openRouterCosts, parseOpenRouterKey, parseOpenRouterCredits, usd } = await jiti.import(join(base, 'openrouter.ts'));
const { default: dashboard, gauge, parseQuotaHeaders, parseSubscriptionUsage, fiveHourSummary } = await jiti.import(extensionPath);
const { visibleWidth } = await import(tuiPath);

let id = 0;
function assistant(input, cacheRead = 0, options = {}) {
  return { type: 'message', id: String(++id), message: {
    role: 'assistant', provider: 'openrouter', model: 'model', api: 'openai-completions',
    stopReason: 'stop', content: [], ...options,
    usage: { input, cacheRead, cacheWrite: 0, output: 10,
      cost: { input: input / 1e6, cacheRead: cacheRead / 1e7, total: (input + cacheRead / 10) / 1e6 },
      ...options.usage,
    },
  } };
}
const user = () => ({ type: 'message', id: String(++id), message: { role: 'user', content: 'task' } });

test('cache metrics: unknown and first request are not false waste', () => {
  assert.equal(cacheMetrics([]).hitPercent, undefined);
  const stats = cacheMetrics([assistant(1000)]);
  assert.equal(stats.hitPercent, 0);
  assert.equal(stats.reprocessedPercent, undefined);
});
test('cache hit denominator includes input + read + write, not output', () => {
  const stats = cacheMetrics([assistant(100, 800, { usage: { cacheWrite: 100 } })]);
  assert.equal(stats.hitPercent, 80);
  assert.equal(stats.promptTokens, 1000);
});
test('reprocessed size excludes new input and cached prefix', () => {
  const stats = cacheMetrics([assistant(1000), assistant(400, 800)]);
  assert.equal(stats.reprocessedEstimate, 200);
  assert.equal(stats.comparableRequests, 1);
  assert.equal(stats.reprocessedPercent, 200 / 1200 * 100);
});
test('cache reuse is not waste; saturated cache never makes negative values', () => {
  const stats = cacheMetrics([assistant(1000), assistant(100, 1100)]);
  assert.equal(stats.reprocessedEstimate, 0);
  assert.equal(stats.cacheRead, 1100);
});
test('model changes, compaction, branch summaries and failed calls break comparisons', () => {
  for (const reset of [{ type: 'compaction' }, { type: 'branch_summary' }, { type: 'model_change' }]) {
    assert.equal(cacheMetrics([assistant(1000), reset, assistant(2000)]).comparableRequests, 0);
  }
  assert.equal(cacheMetrics([assistant(1000), assistant(2000, 0, { model: 'other' })]).comparableRequests, 0);
  assert.equal(cacheMetrics([assistant(1000, 0, { stopReason: 'error' }), assistant(2000)]).comparableRequests, 0);
  assert.equal(cacheMetrics([assistant(1000), assistant(2000, 0, { stopReason: 'aborted' })]).comparableRequests, 0);
});
test('non-finite usage cannot poison gauges', () => {
  assert.equal(cacheMetrics([assistant(NaN, Infinity)]).requests, 0);
  assert.equal(cacheMetrics([assistant(-2)]).requests, 0);
});
test('handoff boundaries, unknown context and small context reserve', () => {
  const level = (n) => handoffLevel(n, n * 1000, 100000, DEFAULT_MONITOR);
  assert.equal(level(59.9), 'ok');
  assert.equal(level(60), 'prepare');
  assert.equal(level(70), 'handoff');
  assert.equal(level(85), 'critical');
  assert.equal(handoffLevel(null, null, 100000, DEFAULT_MONITOR), 'unknown');
  assert.equal(handoffLevel(0, 0, 8000, DEFAULT_MONITOR), 'ok');
  const late = { ...DEFAULT_MONITOR, handoffPercent: 90, criticalPercent: 95 };
  assert.equal(handoffLevel(75, 6000, 8000, late), 'handoff');
});
test('invalid config falls back without disabling valid blink preference', () => {
  assert.deepEqual(monitorConfig({ warningPercent: 90, handoffPercent: 40, blink: false }), { ...DEFAULT_MONITOR, blink: false });
  assert.equal(monitorConfig({ reserveTokens: -1 }).reserveTokens, 20000);
  assert.equal(monitorConfig({ warningPercent: '10' }).warningPercent, 60);
});
test('OpenRouter costs include all session branches, task uses active branch last user', () => {
  const first = assistant(1000, 1000);
  const otherProvider = assistant(900000, 0, { provider: 'anthropic' });
  const second = assistant(2000, 2000);
  const abandoned = assistant(3000, 3000);
  const active = [user(), first, otherProvider, user(), second];
  const stats = openRouterCosts([...active, abandoned], active);
  assert.equal(stats.requests, 3);
  assert.equal(stats.session, 0.0066);
  assert.equal(stats.task, 0.0022);
  assert.ok(Math.abs(stats.cacheRead - 0.0006) < 1e-10);
  assert.equal(stats.taskCacheRead, 0.0002);
});
test('OpenRouter current key is a cap, not account balance', () => {
  const info = parseOpenRouterKey({ data: { limit: 100, limit_remaining: 75, usage: 25 } });
  assert.deepEqual(info.balance, { total: 100, remaining: 75, usedPercent: 25 });
  assert.equal(info.management, false);
  assert.equal(parseOpenRouterKey({ data: { limit: null, limit_remaining: null } }).balance, undefined);
  assert.equal(parseOpenRouterKey({ data: { limit: null } }).unlimited, true);
  assert.equal(parseOpenRouterKey({ data: { limit: 10, usage: 12 } }).balance.remaining, 0);
});
test('OpenRouter credits validate data, distinguish zero from missing and clamp overdraft', () => {
  assert.equal(parseOpenRouterCredits({}), undefined);
  assert.equal(parseOpenRouterCredits({ data: { total_credits: null, total_usage: null } }), undefined);
  assert.deepEqual(parseOpenRouterCredits({ data: { total_credits: 100, total_usage: 25 } }), { total: 100, remaining: 75, usedPercent: 25 });
  assert.equal(parseOpenRouterCredits({ data: { total_credits: 0, total_usage: 1 } }).remaining, 0);
});
test('cost display does not round tiny paid usage to zero', () => {
  assert.equal(usd(0.000001), '<$0.0001');
  assert.equal(usd(0.1234), '$0.1234');
});
test('existing quota parsing and gauge still work', () => {
  assert.equal(gauge(100), '██████████');
  assert.equal(gauge(-1), '░░░░░░░░░░');
  assert.equal(parseQuotaHeaders({ 'x-codex-primary-used-percent': '20', 'x-codex-primary-window-minutes': '300' }).fiveHour.percent, 20);
});

function harness({ mode = 'tui', configured = false, percent = 72 } = {}) {
  const handlers = new Map();
  const commands = new Map();
  const notifications = [];
  const widgets = new Map();
  const messages = [];
  const executables = [];
  const theme = { fg: (_, text) => text, bold: (text) => text };
  let component;
  let renders = 0;
  const entries = [user(), assistant(1000), assistant(400, 800)];
  let pct = percent;
  const ctx = {
    mode, cwd: '/tmp', model: { provider: 'openrouter', id: 'model', contextWindow: 100000 },
    isIdle: () => true, hasPendingMessages: () => false,
    modelRegistry: {
      hasConfiguredAuth: () => configured,
      getProviderAuthStatus: () => ({ configured }),
      getProviderAuth: async () => ({ auth: { apiKey: 'TEST-NOT-A-REAL-KEY' } }),
      getProviderDisplayName: () => 'OpenRouter',
    },
    sessionManager: { getBranch: () => entries, getEntries: () => entries, getLeafId: () => entries.at(-1).id, getSessionId: () => 'test' },
    getContextUsage: () => ({ percent: pct, tokens: pct == null ? null : pct * 1000, contextWindow: 100000 }),
    ui: {
      notify: (text, kind) => notifications.push({ text, kind }),
      setWidget: (name, factory) => factory === undefined ? widgets.delete(name) : widgets.set(name, typeof factory === 'function' ? factory({ requestRender: () => renders++ }, theme) : factory),
      setFooter: (factory) => {
        const theme = { fg: (_, text) => text, bold: (text) => text };
        component = factory({ requestRender: () => renders++ }, theme,
          { onBranchChange: () => () => {}, getGitBranch: () => 'main' });
      },
    },
  };
  dashboard({
    on: (name, fn) => { const list = handlers.get(name) ?? []; list.push(fn); handlers.set(name, list); },
    registerCommand: (name, command) => commands.set(name, command),
    sendMessage: message => messages.push(message),
    events: { on: (name, fn) => { const list = handlers.get(name) ?? []; list.push(fn); handlers.set(name, list); } },
    exec: async command => { executables.push(command); return { stdout: '', stderr: '', code: 0 }; },
  });
  return {
    ctx, commands, notifications, widgets, messages, executables, get component() { return component; }, get renders() { return renders; },
    setPercent: (value) => { pct = value; },
    emit: async (name, event = {}) => { for (const fn of handlers.get(name) ?? []) await fn(event, ctx); },
  };
}

test('TUI gauges reflow at narrow widths, blink while idle, and stop after shutdown', async () => {
  const h = harness();
  await h.emit('session_start');
  try {
    for (const width of [20, 40, 80, 120, 240]) {
      const lines = h.component.render(width);
      assert.ok(lines.every(line => visibleWidth(line) <= width), `width ${width}`);
      assert.ok(lines.some(line => line.includes('HANDOFF')));
      assert.ok(lines.some(line => line.includes('Cache hit')));
      assert.ok(lines.some(line => line.includes('OR sessão~')));
    }
    const first = h.component.render(120)[0];
    await new Promise(resolve => setTimeout(resolve, 1100));
    assert.notEqual(h.component.render(120)[0], first, 'blink changes without input');
    assert.equal(h.notifications.filter(n => n.text.startsWith('Hora do handoff')).length, 1);
    h.setPercent(null);
    assert.ok(h.component.render(120).some(line => line.includes('Ctx N/A')));
    h.setPercent(5);
    await h.emit('session_compact');
    assert.ok(h.component.render(120)[0].includes('Handoff OK'));
  } finally { await h.emit('session_shutdown'); h.component.dispose(); }
  const after = h.renders;
  await new Promise(resolve => setTimeout(resolve, 1100));
  assert.equal(h.renders, after, 'no leaked interval');
});
test('headless start/model selection creates no footer or network work', async () => {
  for (const mode of ['print', 'json', 'rpc']) {
    const h = harness({ mode });
    await h.emit('session_start');
    await h.emit('model_select');
    assert.equal(h.component, undefined);
    await h.emit('session_shutdown');
  }
});
test('OpenRouter balance uses /key; no credits request without management key; HTTP failure visible', async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.OPENROUTER_MANAGEMENT_KEY;
  delete process.env.OPENROUTER_MANAGEMENT_KEY;
  const urls = [];
  let fail = false;
  globalThis.fetch = async (url) => {
    urls.push(url);
    return { ok: !fail, status: fail ? 401 : 200, json: async () => ({ data: { limit: 10, limit_remaining: 8 } }) };
  };
  const h = harness({ configured: true, mode: 'print' });
  try {
    await h.commands.get('dashboard-costs').handler('', h.ctx);
    assert.deepEqual(urls, ['https://openrouter.ai/api/v1/key']);
    assert.match(h.notifications.at(-1).text, /Limite restante da chave: \$8\.00/);
    assert.match(h.notifications.at(-1).text, /Saldo da conta: N\/A/);
    fail = true;
    await h.commands.get('dashboard-costs').handler('', h.ctx);
    assert.match(h.notifications.at(-1).text, /HTTP 401/);
    assert.doesNotMatch(h.notifications.at(-1).text, /Limite restante da chave: \$8/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.OPENROUTER_MANAGEMENT_KEY;
    else process.env.OPENROUTER_MANAGEMENT_KEY = originalKey;
  }
});
function codex(h) {
  h.ctx.model = { provider: 'openai-codex', id: 'fixture-model', contextWindow: 100000 };
  const token = `header.${Buffer.from(JSON.stringify({ 'https://api.openai.com/auth': { chatgpt_account_id: 'fixture-account' } })).toString('base64url')}.signature`;
  h.ctx.modelRegistry.getProviderAuth = async () => ({ auth: { apiKey: token } });
}
const quotaResponse = (percent = 37) => ({ ok: true, status: 200, json: async () => ({ rate_limit: { primary_window: { used_percent: percent, reset_after_seconds: 3600 }, secondary_window: { used_percent: 12 } } }) });

test('five-hour subscription parsing distinguishes missing, zero and unsupported providers', () => {
  assert.equal(parseSubscriptionUsage('openai-codex', { rate_limit: { primary_window: { used_percent: null } } }).fiveHour, undefined);
  assert.equal(parseSubscriptionUsage('openai-codex', { rate_limit: { primary_window: { used_percent: '' } } }).fiveHour, undefined);
  assert.equal(parseSubscriptionUsage('openai-codex', { rate_limit: { primary_window: { used_percent: 0 } } }).fiveHour.percent, 0);
  assert.equal(parseSubscriptionUsage('anthropic', { five_hour: { utilization: 43 } }).fiveHour.percent, 43);
  assert.deepEqual(parseSubscriptionUsage('google', { five_hour: { utilization: 43 } }), {});
});
test('weekly-only Codex plans are not mislabeled as five-hour consumption', () => {
  const q = parseSubscriptionUsage('openai-codex', { rate_limit: { primary_window: { used_percent: 6, limit_window_seconds: 604800, reset_after_seconds: 601117 }, secondary_window: null } });
  assert.equal(q.fiveHour, undefined); assert.equal(q.weekly.percent, 6);
  assert.match(fiveHourSummary('openai-codex', 'ready', q.fiveHour, '', 0, q.weekly), /5h N\/A.*Wk 6% used/);
  const reversed = parseSubscriptionUsage('openai-codex', { rate_limit: { primary_window: { used_percent: 8, limit_window_seconds: 604800 }, secondary_window: { used_percent: 25, limit_window_seconds: 18000 } } });
  assert.equal(reversed.fiveHour.percent, 25); assert.equal(reversed.weekly.percent, 8);
  assert.equal(parseQuotaHeaders({ 'x-codex-primary-used-percent': '12', 'x-codex-primary-window-minutes': '120' }).fiveHour, undefined);
});
test('five-hour text includes usage, provider and reset, not session-token estimates', () => {
  const text = fiveHourSummary('openai-codex', 'ready', { percent: 37, resetsAt: 3600000 }, '', 0);
  assert.match(text, /5h 37% used/); assert.match(text, /resets in 1h00/); assert.match(text, /openai-codex/);
  assert.match(fiveHourSummary('google', 'unsupported'), /N\/A/);
  assert.match(fiveHourSummary('anthropic', 'loading'), /loading/);
});
test('five-hour quota remains visible independently of the custom footer at narrow widths', async () => {
  const saved = globalThis.fetch; const urls = []; const h = harness(); codex(h);
  globalThis.fetch = async url => { urls.push(url); return quotaResponse(); };
  try {
    await h.commands.get('cockpit-quota').handler('', h.ctx);
    assert.deepEqual(urls, ['https://chatgpt.com/backend-api/wham/usage']);
    assert.equal(h.component, undefined, 'quota does not depend on owning a footer');
    const widget = h.widgets.get('cockpit-quota'); assert(widget);
    for (const width of [20, 40, 80, 120]) { const lines = widget.render(width); assert(lines.every(l => visibleWidth(l) <= width)); assert(lines[0].includes('5h 37% used')); }
    assert.match(widget.render(120)[0], /resets in/);
    assert.match(h.messages.at(-1).content, /37% used/);
  } finally { globalThis.fetch = saved; await h.emit('session_shutdown'); }
});
test('quota HTTP errors are visible and never become a false zero', async () => {
  const saved = globalThis.fetch; const h = harness(); codex(h);
  globalThis.fetch = async () => ({ ok: false, status: 401 });
  try { await h.commands.get('cockpit-quota').handler('', h.ctx); assert.match(h.messages.at(-1).content, /unavailable.*HTTP 401/); assert.doesNotMatch(h.messages.at(-1).content, /0% used/); }
  finally { globalThis.fetch = saved; await h.emit('session_shutdown'); }
});
test('quota errors do not echo credentials from an auth resolver exception', async () => {
  const h = harness(); codex(h); h.ctx.modelRegistry.getProviderAuth = async () => { throw new Error('Bearer PRIVATE_FIXTURE_SECRET'); };
  try { await h.commands.get('cockpit-quota').handler('', h.ctx); assert.match(h.messages.at(-1).content, /unavailable/); assert.doesNotMatch(h.messages.at(-1).content, /PRIVATE_FIXTURE_SECRET/); }
  finally { await h.emit('session_shutdown'); }
});
test('a late old-provider quota response cannot replace the current model quota state', async () => {
  const saved = globalThis.fetch; const h = harness(); codex(h); let release;
  globalThis.fetch = async () => new Promise(resolve => { release = resolve; });
  try {
    const old = h.commands.get('cockpit-quota').handler('', h.ctx);
    await new Promise(resolve => setImmediate(resolve));
    h.ctx.model = { provider: 'google', id: 'gemini', contextWindow: 100000 };
    await h.commands.get('cockpit-quota').handler('', h.ctx);
    release(quotaResponse(99)); await old;
    const text = h.widgets.get('cockpit-quota').render(120)[0]; assert.match(text, /5h N\/A/); assert.match(text, /google/); assert.doesNotMatch(text, /99%/);
  } finally { globalThis.fetch = saved; await h.emit('session_shutdown'); }
});
test('unattributed provider headers cannot overwrite authoritative five-hour usage', async () => {
  const saved = globalThis.fetch; const h = harness(); codex(h); globalThis.fetch = async () => quotaResponse(37);
  try {
    await h.commands.get('cockpit-quota').handler('', h.ctx);
    await h.emit('after_provider_response', { status: 200, headers: { 'x-codex-primary-used-percent': '0', 'x-codex-primary-window-minutes': '300' } });
    assert.match(h.widgets.get('cockpit-quota').render(120)[0], /5h 37% used/);
  } finally { globalThis.fetch = saved; await h.emit('session_shutdown'); assert(!h.widgets.has('cockpit-quota')); }
});
test('quota gadget requests its own render after a competing footer disposes ours', async () => {
  const h = harness({ percent: 5 }); await h.emit('session_start');
  try { assert(h.widgets.has('cockpit-quota')); h.component.dispose(); const before = h.renders; await h.emit('message_end'); assert(h.renders > before); }
  finally { await h.emit('session_shutdown'); }
});
test('dashboard uses Pi MCP status without invoking the Claude CLI', async () => {
  const h = harness({ percent: 5 }); await h.emit('session_start');
  try {
    await h.emit('pi-mcp-adapter/status/v1', { servers: [{ name: 'first', status: 'connected' }, { name: 'second', status: 'needs-auth' }] });
    assert(h.component.render(240).some(line => line.includes('MCP ✓1')));
    await h.commands.get('dashboard-refresh').handler('', h.ctx);
    assert(!h.executables.includes('claude'));
  } finally { await h.emit('session_shutdown'); }
});
test('unsupported providers perform no subscription fetch and report N/A', async () => {
  const saved = globalThis.fetch; const h = harness(); h.ctx.model.provider = 'google'; let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('unexpected network'); };
  try { await h.commands.get('cockpit-quota').handler('', h.ctx); assert.equal(calls, 0); assert.match(h.messages.at(-1).content, /N\/A/); }
  finally { globalThis.fetch = saved; await h.emit('session_shutdown'); }
});
test('native Pi extension loader accepts updated cockpit', async () => {
  const { loadExtensions } = await import(join(root, 'dist/core/extensions/loader.js'));
  const result = await loadExtensions([extensionPath], '/tmp');
  assert.deepEqual(result.errors, []);
  assert.equal(result.extensions.length, 1);
  assert.ok(result.extensions[0].commands.has('dashboard-costs'));
});
