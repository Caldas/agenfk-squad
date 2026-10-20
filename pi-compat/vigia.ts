import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { Type } from "typebox";
import { getAgentDir, SettingsManager, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";

const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const STATE = "squad-vigia-state-v1";
type Ready = { file: string; digest: string; revision: number; session: string; userStamp: string };
type State = { version: 1; dispatches: number; reviews: Record<string, number>; calls: string[]; revision: number; alerted: boolean; reminded: boolean; ready?: Ready };
const fresh = (): State => ({ version: 1, dispatches: 0, reviews: {}, calls: [], revision: 0, alerted: false, reminded: false });
export type VigiaConfig = { enabled: boolean; handoffPercent: number; preparePercent: number; maxDispatches: number; maxChildren: number; maxOrchestrators: number; maxReviews: number; autoPickup: boolean; preCache: { enabled: boolean; minTokens: number; beforeSeconds: number } };
export function vigiaConfig(raw: any): VigiaConfig {
  const number = (key: string, fallback: number, min: number, max: number) => typeof raw?.[key] === "number" && Number.isFinite(raw[key]) && raw[key] >= min && raw[key] <= max ? Math.floor(raw[key]) : fallback;
  const handoffPercent = number("handoffPercent", 80, 70, 95);
  return { enabled: raw?.enabled !== false, handoffPercent, preparePercent: Math.min(number("preparePercent", 70, 50, 90), handoffPercent - 1), maxDispatches: number("maxDispatches", 40, 1, 40), maxChildren: number("maxChildren", 4, 1, 4), maxOrchestrators: number("maxOrchestrators", 3, 1, 3), maxReviews: number("maxReviews", 6, 1, 6), autoPickup: raw?.autoPickup !== false, preCache: {
    enabled: raw?.preCache?.enabled !== false,
    minTokens: Number.isSafeInteger(raw?.preCache?.minTokens) && raw.preCache.minTokens > 0 ? raw.preCache.minTokens : 150000,
    beforeSeconds: typeof raw?.preCache?.beforeSeconds === "number" && Number.isFinite(raw.preCache.beforeSeconds) && raw.preCache.beforeSeconds >= 0.05 && raw.preCache.beforeSeconds <= 600 ? raw.preCache.beforeSeconds : 120,
  } };
}
export function contextLevel(tokens: unknown, window: unknown, config: VigiaConfig, child = false): "unknown" | "ok" | "prepare" | "handoff" {
  if (typeof tokens !== "number" || !Number.isFinite(tokens) || tokens < 0 || typeof window !== "number" || !Number.isFinite(window) || window <= 0) return "unknown";
  if (child && tokens >= Math.min(180000, window * 0.8)) return "handoff";
  const percent = tokens / window * 100;
  return percent >= config.handoffPercent ? "handoff" : percent >= config.preparePercent ? "prepare" : "ok";
}
// TTLs are best-effort request/catalog metadata, never subscription quota estimates.
export function preCacheTtl(model: { promptCache?: { short?: number; long?: number } }, payload: unknown): { ms: number; source: string } | undefined {
  const body = payload as any;
  if (body?.cacheRetention === "none" || body?.prompt_cache_retention === "none") return;
  const ttls: number[] = [], nodes: any[] = [body];
  const add = (values: unknown) => { if (Array.isArray(values)) for (const value of values) { nodes.push(value); if (nodes.length > 10000) return false; } return true; };
  if (!add(body?.system) || !add(body?.tools) || (Array.isArray(body?.messages) && body.messages.length > 10000)) return;
  for (const message of Array.isArray(body?.messages) ? body.messages : []) if (!add(message?.content)) return;
  // Inspect protocol cache markers only, never tool inputs or arbitrary document metadata.
  for (const node of nodes) {
    const control = node?.cache_control;
    if (!control) continue;
    if (control.type !== "ephemeral" || ![undefined, "5m", "1h"].includes(control.ttl)) return;
    ttls.push(control.ttl === "1h" ? 3600000 : 300000);
  }
  if (ttls.length) return { ms: Math.min(...ttls), source: "request cache_control" };
  const requested = body?.prompt_cache_options?.ttl;
  if (requested !== undefined) return requested === "30m" ? { ms: 1800000, source: "request prompt_cache_options.ttl" } : undefined;
  if (body?.prompt_cache_retention === "24h") return { ms: 86400000, source: "request prompt_cache_retention" };
  if (body?.prompt_cache_retention !== undefined && body.prompt_cache_retention !== "in-memory") return;
  const short = model.promptCache?.short;
  if (typeof short !== "number" || !Number.isFinite(short) || short <= 0 || short > 86400) return;
  const tiers = [model.promptCache?.short, model.promptCache?.long].filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0 && v <= 86400);
  // Conservative minimum: per-provider retention overrides can differ from process.env.
  if (tiers.length) return { ms: Math.min(...tiers) * 1000, source: "model.promptCache conservative minimum" };
}
function alive(pid: number) { try { process.kill(pid, 0); return true; } catch { return false; } }
function privateDir(dir: string) { fs.mkdirSync(dir, { recursive: true, mode: 0o700 }); }
function save(file: string, value: unknown) {
  const temp = `${file}.${randomUUID()}.tmp`;
  try { fs.writeFileSync(temp, JSON.stringify(value), { mode: 0o600, flag: "wx" }); fs.renameSync(temp, file); }
  finally { fs.rmSync(temp, { force: true }); }
}
/** Short synchronous critical section: reserve a live child across Pi parents atomically. */
export function reserveDispatch(dir: string, session: string, config: VigiaConfig, reviewCard?: string): () => void {
  privateDir(dir);
  const lock = path.join(dir, "dispatch.lock");
  try { fs.writeFileSync(lock, String(process.pid), { flag: "wx", mode: 0o600 }); }
  catch {
    let pid = 0; try { pid = Number(fs.readFileSync(lock, "utf8")); } catch { /* Busy or removed. */ }
    if (pid && !alive(pid)) { fs.rmSync(lock, { force: true }); throw new Error("Stale reservation removed; retry on another turn."); }
    throw new Error("Another session is reserving a slot; wait for another turn.");
  }
  const file = path.join(dir, `${hash(session)}.json`);
  try {
    const live: any[] = [];
    for (const name of fs.readdirSync(dir).filter(n => n.endsWith(".json"))) {
      try { const entry = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8")); if (alive(entry.pid) && entry.active > 0) live.push(entry); } catch { /* Ignore incomplete/dead leases. */ }
    }
    const own = live.find(e => e.session === session);
    if (own && own.pid !== process.pid) throw new Error("The same session is open in another Pi process; do not dispatch from this copy.");
    if ((own?.active ?? 0) >= config.maxChildren) throw new Error("Concurrent child cap reached in this session; wait for a task to return.");
    if (!own && live.length >= config.maxOrchestrators) throw new Error("No orchestrator slot; implement here if the card is small. Independent review waits for a slot; never approve your own work.");
    if (reviewCard) {
      const reviews = path.join(dir, "reviews"); privateDir(reviews);
      const record = path.join(reviews, `${hash(reviewCard)}.json`);
      let count = 0;
      if (fs.existsSync(record)) {
        count = JSON.parse(fs.readFileSync(record, "utf8")).count;
        if (!Number.isSafeInteger(count) || count < 0) throw new Error("Invalid review counter; check before dispatching.");
      }
      if (count >= config.maxReviews) throw new Error("Cross-session review cap reached for this card; ask the owner, never approve your own work.");
      save(record, { count: count + 1 });
    }
    save(file, { session, pid: process.pid, active: (own?.active ?? 0) + 1 });
  } finally { fs.rmSync(lock, { force: true }); }
  let released = false;
  return () => {
    if (released) return; released = true;
    // All children of a session live in this parent process; JS callbacks serialize releases.
    try { const own = JSON.parse(fs.readFileSync(file, "utf8")); if (own.pid !== process.pid) return; if (own.active > 1) save(file, { ...own, active: own.active - 1 }); else fs.rmSync(file, { force: true }); } catch { /* Already removed at shutdown. */ }
  };
}
export function attachVigia(pi: ExtensionAPI, options: () => unknown) {
  let state = fresh();
  let timer: ReturnType<typeof setInterval> | undefined;
  let current: ExtensionContext | undefined;
  let failed = false;
  let completedHandoff: string | undefined;
  let handoffSignal: AbortSignal | undefined;
  type Request = { id: string; session: string; model: string; at: number; ms: number; source: string };
  type Plan = Request & { due: number; expires: number; leaf: string | null; revision: number; epoch: number };
  let compactTimer: ReturnType<typeof setTimeout> | undefined;
  let preCacheEpoch = 0;
  let pendingRequest: Request | undefined, cachedRequest: Request | undefined, compactPlan: Plan | undefined;
  let ownCompact: { token: string; plan: Plan } | undefined;
  let closed = true, modal = false, otherCompaction = false, settledSuccessfully = false, preCacheFailed = false;
  let preCacheStatus: Record<string, unknown> = { state: "waiting", reason: "waiting for a cache-confirmed request with known TTL" };
  const activeTools = new Set<string>();
  const releases = new Map<string, () => void>();
  const child = () => Number(process.env.PI_CLAUDE_CHILD_DEPTH ?? 0) > 0;
  const config = () => vigiaConfig(options());
  const root = () => path.join(getAgentDir(), "squad");
  const persist = () => pi.appendEntry(STATE, JSON.parse(JSON.stringify(state)));
  const userStamp = (ctx: ExtensionContext) => hash(JSON.stringify(ctx.sessionManager.getBranch().filter(e => e.type === "message" && e.message.role === "user")));
  const invalidateHandoff = () => { if (state.ready) { state.ready = undefined; completedHandoff = undefined; state.revision++; persist(); } };
  const restore = (ctx: ExtensionContext) => {
    state = fresh();
    for (const entry of ctx.sessionManager.getEntries()) {
      if (entry.type !== "custom" || entry.customType !== STATE) continue;
      const s = entry.data as State;
      if (s?.version === 1 && Number.isSafeInteger(s.dispatches) && s.dispatches >= 0 && Array.isArray(s.calls) && Number.isSafeInteger(s.revision)) state = structuredClone(s);
    }
  };
  const level = (ctx: ExtensionContext) => { const u = ctx.getContextUsage(); return contextLevel(u?.tokens, u?.contextWindow ?? ctx.model?.contextWindow, config(), child()); };
  const instruction = (ctx: ExtensionContext) => {
    const u = ctx.getContextUsage();
    return child()
      ? `[squad-vigia · Pi] CHILD HANDOFF: ${u?.tokens}/${u?.contextWindow ?? ctx.model?.contextWindow} tokens. Do not start new work. Return verified state and remaining work to the parent; do not clear or replace this session.`
      : `[squad-vigia · Pi] PROACTIVE HANDOFF: ${u?.tokens}/${u?.contextWindow ?? ctx.model?.contextWindow} tokens. Finish the current step, record the card and call squad_handoff with a faithful summary and executable next step. Start no new front. Replacement requires a saved note and verified Git state; do not use /clear or Claude automation. Do not advance the card or claim completion because of this alert.`;
  };
  const modelKey = (ctx: ExtensionContext) => `${ctx.model?.provider}/${ctx.model?.id}`;
  const cancelPreCache = (reason: string, forget = true) => {
    if (compactTimer) clearTimeout(compactTimer); compactTimer = undefined; compactPlan = undefined;
    if (forget) { preCacheEpoch++; cachedRequest = undefined; pendingRequest = undefined; }
    if (!ownCompact) preCacheStatus = { state: "waiting", reason };
  };
  const auditPreCache = (data: Record<string, unknown>) => {
    preCacheStatus = data;
    try { if (!closed) pi.appendEntry("squad-precache-v1", data); return !closed; }
    catch { preCacheFailed = true; preCacheStatus = { state: "error", reason: "pre-cache audit unavailable; reload required" }; return false; }
  };
  const preCacheGuard = (ctx: ExtensionContext, job?: Plan, starting = false): string | undefined => {
    if (closed || failed || preCacheFailed || !config().enabled || !config().preCache.enabled) return "disabled or unavailable";
    if (child() || !ctx.isProjectTrusted() || !["tui", "rpc"].includes(ctx.mode)) return "requires a trusted persistent parent";
    if ((!starting && !ctx.isIdle()) || modal || otherCompaction || activeTools.size || releases.size || ctx.hasPendingMessages()) return "session has pending activity";
    if (!settledSuccessfully || state.ready || state.alerted || level(ctx) === "handoff") return "handoff, failed run or cancellation takes priority";
    const usage = ctx.getContextUsage();
    if (usage?.tokens == null || usage.tokens < config().preCache.minTokens) return "context below minimum or unknown";
    try {
      const settings = SettingsManager.create(ctx.cwd, getAgentDir(), { projectTrusted: true });
      if (settings.drainErrors().length || !settings.getCompactionEnabled()) return "native auto-compaction disabled or settings unreadable";
    } catch { return "native settings unreadable"; }
    if (job) {
      if (job.epoch !== preCacheEpoch || job.session !== ctx.sessionManager.getSessionId() || job.model !== modelKey(ctx) || job.leaf !== ctx.sessionManager.getLeafId() || job.revision !== state.revision) return "session, model, branch or activity changed";
      if (Date.now() >= job.expires - Math.min(config().preCache.beforeSeconds * 500, 5000)) return "pre-expiry deadline missed";
      if (ctx.sessionManager.getBranch().some(e => e.type === "usage" && e.kind === "cache_warm" && Date.parse(e.timestamp) >= job.at)) return "native cache warmer refreshed the request";
    }
  };
  const armPreCache = (ctx: ExtensionContext) => {
    cancelPreCache("waiting for eligible idle state", false);
    const why = preCacheGuard(ctx);
    if (why || !cachedRequest) { preCacheStatus = { state: "waiting", reason: why ?? "cache TTL or cache usage unknown" }; return; }
    const request = cachedRequest;
    const due = request.at + request.ms - config().preCache.beforeSeconds * 1000;
    if (due <= Date.now()) { preCacheStatus = { state: "skipped", reason: "pre-expiry deadline already passed" }; return; }
    const job: Plan = { ...request, due, expires: request.at + request.ms, leaf: ctx.sessionManager.getLeafId(), revision: state.revision, epoch: preCacheEpoch };
    compactPlan = job;
    preCacheStatus = { state: "scheduled", dueAt: due, expiresAt: job.expires, ttlMs: job.ms, source: job.source };
    compactTimer = setTimeout(() => {
      compactTimer = undefined;
      if (compactPlan !== job) return;
      const denied = preCacheGuard(ctx, job);
      compactPlan = undefined; cachedRequest = undefined;
      if (denied) { auditPreCache({ state: "skipped", reason: denied }); return; }
      const token = `[squad-precache:${randomUUID()}]`;
      ownCompact = { token, plan: job };
      if (!auditPreCache({ state: "started", request: job.id, ttlMs: job.ms, source: job.source })) { ownCompact = undefined; return; }
      // The audit entry is metadata, not new conversation activity.
      job.leaf = ctx.sessionManager.getLeafId();
      const finish = (state: "completed" | "failed") => {
        if (closed || ownCompact?.token !== token) return;
        ownCompact = undefined; cachedRequest = undefined; pendingRequest = undefined;
        auditPreCache({ state, request: job.id, reason: state === "failed" ? "native compaction failed or was cancelled; no automatic retry" : "native compaction completed" });
      };
      try { ctx.compact({ customInstructions: `${token}\nPreserve the owner's latest request verbatim, AgenFK card, branch/worktree/PR, decisions and constraints, evidence and tests actually run, completed/remaining work, next step and live tasks. Do not invent completion, tests or approval. Drop repeated reads/output; keep file and transcript pointers. Do not change files, model, tools or card status.`, onComplete: () => finish("completed"), onError: () => finish("failed") }); }
      catch { finish("failed"); }
    }, Math.min(due - Date.now(), 2147483647)); compactTimer.unref?.();
  };
  pi.on("before_provider_request", (event, ctx) => {
    if (closed || ownCompact || otherCompaction || ctx.isIdle()) return;
    pendingRequest = undefined;
    const payload = event.payload as any;
    if (!ctx.model || (typeof payload?.model === "string" && payload.model !== ctx.model.id)) return;
    const ttl = preCacheTtl(ctx.model, event.payload);
    if (ttl) pendingRequest = { id: randomUUID(), session: ctx.sessionManager.getSessionId(), model: modelKey(ctx), at: Date.now(), ...ttl };
  });
  pi.on("message_end", (event, ctx) => {
    const m = event.message;
    if (m.role !== "assistant" || ownCompact || otherCompaction) return;
    cachedRequest = undefined;
    if (pendingRequest?.model === `${m.provider}/${m.model}` && pendingRequest.model === modelKey(ctx) && (!m.responseModel || m.responseModel === m.model) && !["error", "aborted"].includes(m.stopReason) && (m.usage?.cacheRead > 0 || m.usage?.cacheWrite > 0)) cachedRequest = pendingRequest;
    pendingRequest = undefined;
  });
  pi.on("agent_start", () => { settledSuccessfully = false; cancelPreCache("agent started"); });
  pi.on("agent_settled", (_event, ctx) => { armPreCache(ctx); });
  pi.on("ui_prompt_start", () => { modal = true; cancelPreCache("waiting for user input"); });
  pi.on("ui_prompt_end", () => { modal = false; });
  pi.on("user_bash", () => { cancelPreCache("user shell activity"); });
  pi.on("session_before_switch", () => { cancelPreCache("session switch requested"); });
  pi.on("session_before_fork", () => { cancelPreCache("fork requested"); });
  pi.on("session_before_tree", () => { cancelPreCache("branch navigation requested"); });
  pi.on("session_before_compact", (event, ctx) => {
    if (ownCompact && event.customInstructions?.startsWith(ownCompact.token)) {
      const why = preCacheGuard(ctx, ownCompact.plan, true);
      if (why) { ownCompact = undefined; auditPreCache({ state: "skipped", reason: why }); return { cancel: true }; }
      return;
    }
    otherCompaction = true; cancelPreCache("another compaction started");
  });
  pi.on("session_compact_failed", () => { otherCompaction = false; cancelPreCache("native compaction failed"); });
  pi.on("cache_warming_decision", (event, ctx) => {
    if (ownCompact) return { action: "stop" as const };
    if (ctx.isIdle() && event.action === "warm") cancelPreCache("native cache warming takes priority");
  });
  const tick = (ctx: ExtensionContext, notifyModel: boolean) => {
    if (!config().enabled || failed) return;
    try {
    const l = level(ctx);
    if (l !== "handoff" && state.alerted) { state.alerted = false; state.reminded = false; state.ready = undefined; persist(); }
    if (ctx.hasUI) ctx.ui.setStatus("squad-vigia", `squad · ${l} · ${state.dispatches}/${config().maxDispatches} dispatches`);
    if (l === "handoff" && !state.alerted && !state.ready && notifyModel) {
      state.alerted = true; persist();
      pi.sendMessage({ customType: "squad-vigia", content: instruction(ctx), display: true }, { deliverAs: ctx.isIdle() ? "nextTurn" : "steer" });
    }
    } catch { failed = true; if (ctx.hasUI) ctx.ui.setStatus("squad-vigia", "squad · ERROR: check /squad-status"); }
  };
  pi.on("session_start", (_event, ctx) => {
    current = ctx; failed = false; closed = false; preCacheFailed = false; otherCompaction = false; modal = false; settledSuccessfully = false; cancelPreCache("waiting for a fresh request after startup/reload"); restore(ctx);
    if (!config().enabled) return;
    tick(ctx, false);
    timer = setInterval(() => { if (current) tick(current, !current.isIdle()); }, 60000); timer.unref();
  });
  pi.on("session_shutdown", (_event, ctx) => {
    closed = true; cancelPreCache("session shutdown"); ownCompact = undefined;
    if (timer) clearInterval(timer); timer = undefined; current = undefined;
    completedHandoff = undefined; handoffSignal = undefined;
    for (const release of releases.values()) release(); releases.clear(); activeTools.clear();
    if (ctx.hasUI) ctx.ui.setStatus("squad-vigia", undefined);
  });
  pi.on("before_agent_start", (_event, ctx) => {
    if (!config().enabled) return;
    cancelPreCache("new prompt"); settledSuccessfully = false;
    current = ctx; state.ready = undefined; state.reminded = false; completedHandoff = undefined; handoffSignal = undefined; persist();
    // Pi runtime policy replaces ONLY the Claude-specific control-plane assumptions.
    return { message: { customType: "squad-pi-policy", display: false, content:
      `[squad Pi] Native supervisor active. Pi control-plane policy takes precedence over Claude-hook instructions: actual model window; prepare ${config().preparePercent}%, handoff ${config().handoffPercent}%; ${config().maxDispatches} dispatches/session, ${config().maxChildren} concurrent children, ${config().maxOrchestrators} Pi orchestrators, ${config().maxReviews} reviews/card. Do not wait for squad-watch.py or invoke Claude session-switch/compaction/merge-queue scripts in Pi. Delegate through real subagent; pi -p via Bash is not a supervised dispatch. The Claude merge queue is not ported. Native pre-cache compaction requires eligible idle state and known TTL; see /squad-status. Pi safety compaction stays native. Authors cannot approve their own work. ${level(ctx) === "handoff" ? instruction(ctx) : "Cockpit warnings are informational; only a supervisor order or owner request authorizes handoff."}` } };
  });
  // Steering/follow-up input can be consumed without another before_agent_start.
  pi.on("input", () => { cancelPreCache("new input"); if (config().enabled) invalidateHandoff(); });
  pi.on("message_start", event => { if (event.message.role === "user") { cancelPreCache("new user message"); if (config().enabled) invalidateHandoff(); } });
  pi.on("tool_execution_start", event => { cancelPreCache("tool started", false); activeTools.add(event.toolCallId); });
  pi.on("tool_execution_end", (event, ctx) => {
    activeTools.delete(event.toolCallId); releases.get(event.toolCallId)?.(); releases.delete(event.toolCallId);
    tick(ctx, true);
  });
  pi.on("tool_call", (event, ctx) => {
    if (!config().enabled) return;
    if (failed) return { block: true, reason: "Pi supervisor unavailable; use /squad-status and /reload before continuing." };
    try {
      if (event.toolName !== "squad_handoff") { state.revision++; state.ready = undefined; }
      const signature = hash(JSON.stringify([event.toolName, event.input]));
      state.calls = [...state.calls.slice(-11), signature];
      const repeats = state.calls.filter(s => s === signature).length;
      if (repeats >= 8 && event.toolName !== "squad_handoff") { persist(); return { block: true, terminate: true, reason: "[squad-vigia · Pi] LOOP: the same call occurred 8 times in the last 12. Stop and return the blocker with evidence; do not retry or bypass." }; }
      if (repeats === 5) pi.sendMessage({ customType: "squad-vigia", display: true, content: "[squad-vigia · Pi] LOOP WARNING: the same call occurred 5 times in the last 12; check progress before repeating." }, { deliverAs: "steer" });
      if (event.toolName === "subagent") {
        const input = event.input as { agent: string; task: string };
        const card = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i.exec(input.task)?.[0]?.toLowerCase();
        const review = /verif|review|revis/i.test(input.agent);
        let denial = child() ? "Child sessions cannot delegate." : level(ctx) === "handoff" || state.alerted ? instruction(ctx) : state.dispatches >= config().maxDispatches ? "Dispatch cap reached. Save a handoff with the plan; do not try another channel." : review && !card ? "Pass the card UUID to the reviewer to track independent rounds." : review && state.reviews[card!] >= config().maxReviews ? "Review cap reached for this card; ask the owner. Do not approve your own work." : undefined;
        if (!denial) { try { releases.set(event.toolCallId, reserveDispatch(path.join(root(), "sessions"), ctx.sessionManager.getSessionId(), config(), review ? card : undefined)); } catch (error) { denial = String(error); } }
        if (denial) {
          const dir = path.join(root(), "handoffs", hash(ctx.sessionManager.getSessionId())); privateDir(dir);
          const file = path.join(dir, `denied-${hash(event.toolCallId)}.md`);
          fs.writeFileSync(file, `# Dispatch denied\n\nAgent: ${input.agent}\nReason: ${denial}\n\n## Received plan\n\n${input.task}\n`, { mode: 0o600 });
          persist(); return { block: true, reason: `[squad-vigia · Pi] DISPATCH DENIED: ${denial}\nPreserved brief: ${file}` };
        }
        state.dispatches++; if (review) state.reviews[card!] = (state.reviews[card!] ?? 0) + 1;
      }
      persist();
    } catch {
      failed = true;
      return { block: true, reason: "Pi supervisor persistence/reservation failed; no new work is authorized. /reload or inspect the private Pi directory." };
    }
  });
  pi.on("agent_before_settle", (event, ctx) => {
    settledSuccessfully = event.outcome === "completed" && !ctx.signal?.aborted;
    if (!settledSuccessfully) cancelPreCache("run failed or was cancelled");
    if (config().enabled && state.ready) {
      if (event.outcome !== "completed" || handoffSignal?.aborted) invalidateHandoff();
      else completedHandoff = state.ready.digest;
    }
    if (!config().enabled || failed || child() || event.outcome !== "completed" || level(ctx) !== "handoff" || state.ready || state.reminded || ctx.signal?.aborted) return;
    state.alerted = true; state.reminded = true; persist();
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "squad-vigia", display: true, content: instruction(ctx) }], continue: true };
  });
  pi.on("session_tree", (_event, ctx) => { cancelPreCache("branch changed"); restore(ctx); state.ready = undefined; state.calls = []; persist(); tick(ctx, true); });
  pi.on("session_compact", (_event, ctx) => { otherCompaction = false; cancelPreCache("context compacted"); state.ready = undefined; state.alerted = false; state.reminded = false; persist(); tick(ctx, true); });
  pi.on("model_select", (_event, ctx) => { cancelPreCache("model changed"); current = ctx; tick(ctx, true); });
  const snapshot = async (ctx: ExtensionContext) => {
    let gitCwd = ctx.cwd;
    const run = async (args: string[]) => {
      const r = await pi.exec("git", ["--no-optional-locks", "-c", "core.fsmonitor=false", ...args], { cwd: gitCwd, timeout: 5000, signal: ctx.signal });
      if (r.code !== 0 || r.killed || r.stdout.length > 48000) throw new Error("Git snapshot unavailable; preserve the session and check manually.");
      return r.stdout;
    };
    gitCwd = (await run(["rev-parse", "--show-toplevel"])).trim();
    const branch = await run(["branch", "--show-current"]), head = await run(["rev-parse", "HEAD"]), status = await run(["status", "--porcelain=v1"]);
    // This fingerprint detects tracked changes even when porcelain status is unchanged.
    const diff = await run(["diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD"]);
    const untracked = (await run(["ls-files", "--others", "--exclude-standard", "-z"])).split("\0").filter(Boolean);
    if (untracked.length > 1000) throw new Error("Too many untracked files for a safe snapshot; check manually.");
    const files: string[] = []; let bytes = 0;
    for (const name of untracked) {
      const file = path.resolve(gitCwd, name), stat = fs.lstatSync(file);
      bytes += stat.size;
      if (bytes > 16000000 || (!stat.isFile() && !stat.isSymbolicLink())) throw new Error("Untracked snapshot exceeds the safe limit; session preserved.");
      files.push(hash(name + "\0" + (stat.isSymbolicLink() ? fs.readlinkSync(file) : fs.readFileSync(file).toString("base64"))));
    }
    return { branch, head, status, fingerprint: hash(branch + head + status + diff + files.join("\n")) };
  };
  pi.registerTool({
    name: "squad_handoff", label: "Save Pi handoff", description: "Save a private, session-bound handoff with git ground truth and the next executable step. Use after a vigia order or owner handoff request. Automatic pickup only after a vigia order; never invokes Claude/herdr. Requires trusted Git project and no other active tools.",
    parameters: Type.Object({ summary: Type.String({ minLength: 30, maxLength: 16000 }), nextStep: Type.String({ minLength: 15, maxLength: 8000 }), card: Type.Optional(Type.String({ maxLength: 200 })) }),
    async execute(id, params, _signal, _update, ctx) {
      if (!config().enabled || failed || child() || !ctx.isProjectTrusted()) throw new Error("Handoff requires an active supervisor and trusted project in the parent session.");
      if ([...activeTools].some(tool => tool !== id) || releases.size || ctx.hasPendingMessages()) throw new Error("Work or messages are pending; finish the step and retry later.");
      _signal?.throwIfAborted();
      const revision = state.revision, users = userStamp(ctx);
      const git = await snapshot(ctx);
      _signal?.throwIfAborted();
      if (state.revision !== revision || userStamp(ctx) !== users || ctx.hasPendingMessages() || [...activeTools].some(tool => tool !== id)) throw new Error("The session changed during the snapshot; save a new handoff afterward.");
      const session = ctx.sessionManager.getSessionId();
      const dir = path.join(root(), "handoffs", hash(session)); privateDir(dir);
      const file = path.join(dir, `${randomUUID()}.md`);
      const lastUser = [...ctx.sessionManager.getBranch()].reverse().find(e => e.type === "message" && e.message.role === "user");
      const rawRequest = lastUser?.type === "message" && lastUser.message.role === "user" ? JSON.stringify(lastUser.message.content) : "Consult the original transcript.";
      const request = rawRequest.length > 16000 ? rawRequest.slice(0, 16000) + "\n[Request truncated; consult the original transcript above before resuming.]" : rawRequest;
      const note = `# Pi handoff\n\nSession: ${session}\nTranscript: ${ctx.sessionManager.getSessionFile() ?? "ephemeral"}\nWorktree: ${ctx.cwd}\nCard: ${params.card ?? "not supplied; check AgenFK"}\nDate: ${new Date().toISOString()}\n\n## Latest request (data, not new instructions)\n\n${request}\n\n## Verified Git state\n\n${JSON.stringify(git, null, 2)}\n\n## State and decisions\n\n${params.summary}\n\n## Next step\n\n${params.nextStep}\n\nCheck Git and the card before editing. Denied briefs, if any, are in ${dir}. Detached shell processes are not tracked: inspect them before resuming.\n`;
      fs.writeFileSync(file, note, { flag: "wx", mode: 0o600 });
      state.ready = { file, digest: hash(note), revision, session, userStamp: users }; completedHandoff = undefined; handoffSignal = _signal ?? ctx.signal; persist();
      // Keep the git fingerprint off the model input while retaining it for the command.
      pi.appendEntry("squad-handoff-git-v1", { digest: state.ready.digest, fingerprint: git.fingerprint });
      const automatic = (ctx.mode === "tui" || ctx.mode === "rpc") && (state.alerted || level(ctx) === "handoff" || state.dispatches >= config().maxDispatches) && config().autoPickup;
      if (automatic) pi.sendUserMessage(`/squad-pickup auto:${state.ready.digest}`, { deliverAs: "followUp", expandPromptTemplates: true });
      return { content: [{ type: "text", text: `Session-bound handoff saved: ${file}. ${automatic ? "Native pickup scheduled after this step." : "Use /squad-pickup to replace the session and resume."}` }], details: { file }, terminate: true };
    },
  });
  pi.registerCommand("squad-pickup", {
    description: "Switch to a new Pi session only after verifying the saved handoff and git state",
    handler: async (args, ctx) => {
      await ctx.waitForIdle();
      const ready = state.ready;
      const automatic = args.startsWith("auto:");
      if (args && (!automatic || !ready || args !== `auto:${ready.digest}` || completedHandoff !== ready.digest || handoffSignal?.aborted)) throw new Error("Automatic pickup cancelled: the run failed, was cancelled or the note became stale. Session preserved.");
      if (!config().enabled || failed || child() || !ctx.isProjectTrusted() || !ready || ready.session !== ctx.sessionManager.getSessionId() || ready.revision !== state.revision || ready.userStamp !== userStamp(ctx) || releases.size || activeTools.size || ctx.hasPendingMessages()) throw new Error("Pickup refused: no current handoff, or work/messages are pending. Session preserved.");
      const note = fs.readFileSync(ready.file, "utf8");
      if (hash(note) !== ready.digest) throw new Error("Handoff changed; save it again before replacement. Session preserved.");
      const entry = [...ctx.sessionManager.getBranch()].reverse().find(e => e.type === "custom" && e.customType === "squad-handoff-git-v1" && (e.data as any)?.digest === ready.digest);
      const git = await snapshot(ctx);
      if (entry?.type !== "custom" || (entry.data as any).fingerprint !== git.fingerprint) throw new Error("Git changed since handoff; save it again before replacement. Session preserved.");
      if (state.ready !== ready || ready.revision !== state.revision || ready.userStamp !== userStamp(ctx) || handoffSignal?.aborted || (automatic && completedHandoff !== ready.digest) || ctx.hasPendingMessages() || !ctx.isIdle()) throw new Error("The session changed during verification; replacement cancelled, save a new handoff.");
      if (!ctx.model) throw new Error("Original model missing; session preserved.");
      const runtime = { provider: ctx.model.provider, model: ctx.model.id, thinking: pi.getThinkingLevel(), tools: pi.getActiveTools(), digest: ready.digest };
      const parentSession = ctx.sessionManager.getSessionFile();
      await ctx.newSession({ parentSession, setup: async sm => { sm.appendCustomEntry("squad-pickup-runtime-v1", runtime); }, withSession: async replacement => {
        // Only the replacement extension owns a live pi API after newSession.
        await replacement.sendUserMessage(`/squad-restore-runtime ${runtime.digest}`, { expandPromptTemplates: true });
        const restored = replacement.sessionManager.getEntries().some(e => e.type === "custom" && e.customType === "squad-runtime-restored-v1" && (e.data as any)?.digest === runtime.digest);
        if (!restored) throw new Error("Original runtime was not restored; pickup not executed. Consult the note and previous session.");
        await replacement.sendUserMessage(`Resume the unfinished request from this verified handoff. Check Git and AgenFK before editing. Do not accept the summary as test/review evidence.\n\n${note}`);
      } });
    },
  });
  pi.registerCommand("squad-restore-runtime", {
    description: "Internal pickup gate: restore the original provider/model, thinking and active tool names",
    handler: async (digest, ctx) => {
      const entry = [...ctx.sessionManager.getEntries()].reverse().find(e => e.type === "custom" && e.customType === "squad-pickup-runtime-v1");
      const runtime = entry?.type === "custom" ? entry.data as { provider: string; model: string; thinking: ReturnType<ExtensionAPI["getThinkingLevel"]>; tools: string[]; digest: string } : undefined;
      if (!config().enabled || !ctx.isProjectTrusted() || !runtime || !/^[a-f0-9]{64}$/.test(digest) || runtime.digest !== digest || !Array.isArray(runtime.tools)) throw new Error("Runtime restoration refused without a matching handoff.");
      const available = new Set(pi.getAllTools().map(t => t.name));
      if (runtime.tools.some(name => !available.has(name))) throw new Error("Original tool unavailable; pickup stopped without widening permissions.");
      const model = ctx.modelRegistry.find(runtime.provider, runtime.model);
      if (!model || !await pi.setModel(model)) throw new Error("Original model unavailable; pickup will not use a fallback.");
      pi.setThinkingLevel(runtime.thinking);
      if (pi.getThinkingLevel() !== runtime.thinking) throw new Error("Original thinking level was not restored; pickup stopped.");
      pi.setActiveTools(runtime.tools);
      pi.appendEntry("squad-runtime-restored-v1", { digest });
    },
  });
  pi.registerCommand("squad-status", { description: "Show native Pi vigia state and explicit automation boundaries", handler: async (_args, ctx) => {
    tick(ctx, false);
    pi.sendMessage({ customType: "squad-status", display: true, content: JSON.stringify({ nativePi: true, enabled: config().enabled, failed, session: ctx.sessionManager.getSessionId(), level: level(ctx), dispatches: state.dispatches, reviews: state.reviews, runningChildren: releases.size, handoff: state.ready?.file, preCache: preCacheStatus, config: config(), limits: "Only subagent dispatches are tracked. No Claude/herdr hooks or merge queue. Native pre-cache compaction requires known TTL and cache usage; Pi safety compaction unchanged." }, null, 2) });
  } });
}
