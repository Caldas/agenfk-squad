import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { cacheMetrics, handoffLevel, monitorConfig, type CacheMetrics, type HandoffLevel } from "./usage-dashboard/metrics.ts";
import { openRouterCosts, parseOpenRouterKey, parseOpenRouterCredits, usd, type Balance, type KeyInfo } from "./usage-dashboard/openrouter.ts";

const MONITOR_CONFIG = join(process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "usage-dashboard.json");

type Quota = { percent: number; resetsAt?: number };
type ProviderHealth = "configured" | "connected" | "error" | "missing";
type McpHealth = { connected: string[]; inactive: string[]; checkedAt?: number; error?: string };
type AwsHealth = {
  state: "inactive" | "loading" | "connected" | "error";
  profile?: string;
  account?: string;
  role?: string;
  production?: boolean;
};
type JsonRecord = Record<string, unknown>;

const CELLS = 10;
const REFRESH_MS = 10 * 60 * 1000;

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function gauge(percent: number): string {
  const pct = clampPercent(percent);
  let filled = Math.round((pct * CELLS) / 100);
  if (pct > 0 && filled === 0) filled = 1;
  return "█".repeat(filled) + "░".repeat(CELLS - filled);
}

function humanTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`;
  return String(value);
}

function shortDuration(seconds: number): string {
  if (seconds <= 0) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes >= 24 * 60) return `${Math.floor(minutes / 1440)}d${Math.floor((minutes % 1440) / 60)}h`;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
  return `${minutes}m`;
}

function parseReset(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    if (numeric > 1_000_000_000_000) return numeric;
    if (numeric > 1_000_000_000) return numeric * 1000;
    // Some providers expose seconds until reset rather than an epoch.
    if (numeric >= 0) return Date.now() + numeric * 1000;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function percentage(value: string | undefined, utilization = false): number | undefined {
  if (value === undefined) return undefined;
  const parsed = Number(value.replace("%", ""));
  if (!Number.isFinite(parsed)) return undefined;
  return clampPercent(utilization && parsed <= 1 ? parsed * 100 : parsed);
}

/** Extract Anthropic unified and OpenAI Codex subscription windows from response headers. */
export function parseQuotaHeaders(headers: Record<string, string>): { fiveHour?: Quota; weekly?: Quota } {
  const h = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  const result: { fiveHour?: Quota; weekly?: Quota } = {};

  const find = (patterns: RegExp[]): [string, string] | undefined =>
    Object.entries(h).find(([key]) => patterns.some((pattern) => pattern.test(key)));

  const readNamed = (kind: "5h" | "7d"): Quota | undefined => {
    const aliases = kind === "5h" ? ["5h", "five-hour", "five_hour"] : ["7d", "seven-day", "seven_day", "weekly"];
    const usage = find(aliases.flatMap((name) => [
      new RegExp(`${name}.*(?:used[-_]?percent|utilization)$`),
      new RegExp(`(?:used[-_]?percent|utilization).*${name}$`),
    ]));
    if (!usage) return undefined;
    const pct = percentage(usage[1], usage[0].includes("utilization"));
    if (pct === undefined) return undefined;
    const reset = find(aliases.flatMap((name) => [
      new RegExp(`${name}.*reset(?:s[-_]?at|-after-seconds)?$`),
      new RegExp(`reset(?:s[-_]?at|-after-seconds)?.*${name}$`),
    ]));
    return { percent: pct, resetsAt: parseReset(reset?.[1]) };
  };

  result.fiveHour = readNamed("5h");
  result.weekly = readNamed("7d");

  // Codex calls the subscription windows primary/secondary and supplies their duration.
  for (const prefix of ["primary", "secondary"] as const) {
    const used = find([new RegExp(`${prefix}.*used[-_]?percent$`)]);
    if (!used) continue;
    const pct = percentage(used[1]);
    if (pct === undefined) continue;
    const minutesEntry = find([new RegExp(`${prefix}.*window[-_]?minutes$`)]);
    const minutes = Number(minutesEntry?.[1]);
    const reset = find([new RegExp(`${prefix}.*reset(?:s[-_]?at|-after-seconds)?$`)]);
    const quota = { percent: pct, resetsAt: parseReset(reset?.[1]) };
    if (minutes === 7 * 24 * 60) result.weekly = quota;
    else if (minutes === 5 * 60) result.fiveHour = quota;
    else if (!minutesEntry && prefix === "primary" && !result.fiveHour) result.fiveHour = quota;
    else if (!minutesEntry && prefix === "secondary" && !result.weekly) result.weekly = quota;
  }

  return result;
}

function asRecord(value: unknown): JsonRecord | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : undefined;
}

function quotaFromWindow(value: unknown, percentField: "used_percent" | "utilization"): Quota | undefined {
  const window = asRecord(value);
  if (!window) return undefined;
  const rawValue = window[percentField];
  if (!["number", "string"].includes(typeof rawValue) || (typeof rawValue === "string" && !rawValue.trim())) return undefined;
  const rawPercent = Number(rawValue);
  if (!Number.isFinite(rawPercent)) return undefined;
  const reset = window.resets_at ?? window.reset_at ?? window.reset_after_seconds;
  return {
    percent: clampPercent(rawPercent),
    resetsAt: parseReset(reset === null || reset === undefined ? undefined : String(reset)),
  };
}

export function parseSubscriptionUsage(provider: string, payload: unknown): { fiveHour?: Quota; weekly?: Quota } {
  const body = asRecord(payload);
  if (!body) return {};
  if (provider === "openai-codex") {
    const limits = asRecord(body.rate_limit);
    const result: { fiveHour?: Quota; weekly?: Quota } = {};
    for (const key of ["primary_window", "secondary_window"] as const) {
      const window = asRecord(limits?.[key]);
      const quota = quotaFromWindow(window, "used_percent");
      if (!quota || !window) continue;
      const seconds = window.limit_window_seconds ?? window.window_seconds ?? (typeof window.window_minutes === "number" ? window.window_minutes * 60 : undefined);
      // Some plans expose only a weekly primary window; it is not a five-hour quota.
      if (seconds === 18000 || (seconds === undefined && key === "primary_window")) result.fiveHour = quota;
      else if (seconds === 604800 || (seconds === undefined && key === "secondary_window")) result.weekly = quota;
    }
    return result;
  }
  if (provider === "anthropic") {
    return {
      fiveHour: quotaFromWindow(body.five_hour, "utilization"),
      weekly: quotaFromWindow(body.seven_day, "utilization"),
    };
  }
  return {};
}

function jwtAccountId(token: string): string | undefined {
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1] ?? "", "base64url").toString("utf8")) as JsonRecord;
    const auth = asRecord(payload["https://api.openai.com/auth"]);
    const accountId = auth?.chatgpt_account_id;
    return typeof accountId === "string" ? accountId : undefined;
  } catch {
    return undefined;
  }
}

export function parseMcpList(output: string): McpHealth {
  const connected: string[] = [];
  const inactive: string[] = [];
  const ansi = /\x1b\[[0-?]*[ -\/]*[@-~]/g;
  for (const raw of output.replace(ansi, "").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("Checking MCP")) continue;
    const name = line.split(": ", 1)[0]?.trim();
    if (!name) continue;
    if (line.includes("✔") || /\bConnected\b/i.test(line)) connected.push(name);
    else if (line.includes("✘") || line.includes("!") || /failed|authentication|inactive|disconnected/i.test(line)) inactive.push(name);
  }
  return { connected, inactive, checkedAt: Date.now() };
}

function isAwsModel(ctx: ExtensionContext): boolean {
  const model = ctx.model;
  return Boolean(model && (model.api === "bedrock-converse-stream" || /bedrock|amazon/i.test(model.provider)));
}

function providerLabel(ctx: ExtensionContext): string {
  const model = ctx.model;
  if (!model) return "no provider";
  const isClaude = /claude/i.test(`${model.id} ${model.name}`);
  if (isAwsModel(ctx)) return "AWS Bedrock";
  if (isClaude && /vertex|google/i.test(model.provider)) return "Vertex→Claude";
  if (isClaude && /openrouter/i.test(model.provider)) return "OpenRouter→Claude";
  if (isClaude && model.provider === "anthropic") return "Anthropic";
  return ctx.modelRegistry.getProviderDisplayName(model.provider) || model.provider;
}

function fitSegments(segments: string[], width: number, separator: string): string {
  const full = segments.filter(Boolean).join(separator);
  return truncateToWidth(full, width, "…");
}

export function fiveHourSummary(provider: string, state: string, quota?: Quota, error = "", now = Date.now(), weekly?: Quota): string {
  if (!quota) return `5h ${state === "loading" ? "loading…" : state === "unsupported" ? "N/A (provider has no subscription window)" : state === "ready" ? "N/A (not reported)" : `unavailable${error ? ` · ${error}` : ""}`}${weekly ? ` · Wk ${weekly.percent.toFixed(0)}% used` : ""} · ${provider}`;
  const reset = quota.resetsAt ? ` · resets in ${shortDuration((quota.resetsAt - now) / 1000)}` : "";
  return `5h ${quota.percent.toFixed(0)}% used ${gauge(quota.percent)}${reset} · ${provider}`;
}

export default function usageDashboard(pi: ExtensionAPI) {
  let fiveHour: Quota | undefined;
  let weekly: Quota | undefined;
  let providerHealth: ProviderHealth = "missing";
  let providerDetail = "";
  let mcp: McpHealth = { connected: [], inactive: [] };
  let aws: AwsHealth = { state: "inactive" };
  let agentActive = false;
  const runningTools = new Set<string>();
  let timer: ReturnType<typeof setInterval> | undefined;
  let requestRender: (() => void) | undefined;
  let currentCtx: ExtensionContext | undefined;
  let refreshing = false;
  let quotaState: "loading" | "ready" | "unsupported" | "error" = "loading";
  let quotaError = "";
  let quotaGeneration = 0;
  let quotaLastCheckedAt = 0;
  let quotaRequestRender: (() => void) | undefined;
  let quotaRenderMinute = -1;

  // A separate cockpit gadget survives another extension replacing the footer.
  function publishQuota(ctx: ExtensionContext): void {
    if (ctx.mode !== "tui" || closed) return;
    ctx.ui.setWidget("cockpit-quota", (tui, theme) => {
      const render = () => tui.requestRender();
      quotaRequestRender = render;
      return {
        render(width: number) {
          const colour = quotaState === "error" ? "warning" : fiveHour && fiveHour.percent >= 80 ? "error" : fiveHour && fiveHour.percent >= 60 ? "warning" : "dim";
          return [truncateToWidth(theme.fg(colour, fiveHourSummary(ctx.model?.provider ?? "no provider", quotaState, fiveHour, quotaError, Date.now(), weekly)), width, "…")];
        },
        invalidate() {},
        dispose() { if (quotaRequestRender === render) quotaRequestRender = undefined; },
      };
    }, { placement: "belowEditor" });
  }

  let monitor = monitorConfig(undefined);
  let monitorTimer: ReturnType<typeof setInterval> | undefined;
  let blinkPhase = true;
  let lastAlert: HandoffLevel = "unknown";
  let metricsLeaf: string | null | undefined;
  let metrics: CacheMetrics = cacheMetrics([]);
  let orCosts = openRouterCosts([], []);
  let orCostsKey = "";
  let orState: "missing" | "loading" | "ready" | "error" = "missing";
  let orKeyInfo: KeyInfo | undefined;
  let orCredits: Balance | undefined;
  let orError = "";
  let orCreditsError = "";
  let orCheckedAt: number | undefined;
  let orRefreshing = false;
  let closed = false;

  const getOrCosts = (ctx: ExtensionContext) => {
    const key = `${ctx.sessionManager.getSessionId()}:${ctx.sessionManager.getLeafId()}`;
    if (orCostsKey !== key) {
      orCosts = openRouterCosts(ctx.sessionManager.getEntries(), ctx.sessionManager.getBranch());
      orCostsKey = key;
    }
    return orCosts;
  };

  async function checkOpenRouter(ctx: ExtensionContext): Promise<void> {
    if (orRefreshing || closed) return;
    if (!ctx.modelRegistry.getProviderAuthStatus("openrouter").configured) {
      orState = "missing";
      return;
    }
    orRefreshing = true;
    orState = "loading";
    orError = "";
    orCreditsError = "";
    orKeyInfo = undefined;
    orCredits = undefined;
    try {
      const resolved = await ctx.modelRegistry.getProviderAuth("openrouter");
      const token = resolved?.auth.apiKey ?? resolved?.auth.headers?.Authorization?.replace(/^Bearer\s+/i, "");
      if (!token) throw new Error("OpenRouter key unavailable");
      const get = async (endpoint: string, apiKey: string) => {
        const response = await fetch(`https://openrouter.ai/api/v1/${endpoint}`, {
          headers: { Authorization: `Bearer ${apiKey}` }, signal: AbortSignal.timeout(10000),
        });
        if (!response.ok) throw new Error(`${endpoint}: HTTP ${response.status}`);
        return response.json();
      };
      orKeyInfo = parseOpenRouterKey(await get("key", token));
      // /credits requires a management key. Never request broader credentials interactively.
      const managementKey = process.env.OPENROUTER_MANAGEMENT_KEY || (orKeyInfo.management ? token : undefined);
      if (managementKey) {
        try {
          orCredits = parseOpenRouterCredits(await get("credits", managementKey));
          if (!orCredits) orCreditsError = "credit response has no valid values";
        } catch (error) {
          orCreditsError = error instanceof Error ? error.message : "credits unavailable";
        }
      }
      orState = "ready";
    } catch (error) {
      orState = "error";
      orError = error instanceof Error ? error.message : "request unavailable";
    } finally {
      orCheckedAt = Date.now();
      orRefreshing = false;
      if (!closed) repaint();
    }
  }

  const repaint = () => { requestRender?.(); quotaRequestRender?.(); };
  const getMetrics = (ctx: ExtensionContext) => {
    const leaf = ctx.sessionManager.getLeafId();
    if (leaf !== metricsLeaf) {
      metrics = cacheMetrics(ctx.sessionManager.getBranch());
      metricsLeaf = leaf;
    }
    return metrics;
  };
  const getLevel = (ctx: ExtensionContext) => {
    const usage = ctx.getContextUsage();
    return handoffLevel(usage?.percent, usage?.tokens, usage?.contextWindow ?? ctx.model?.contextWindow, monitor);
  };
  const monitorTick = () => {
    if (!currentCtx) return;
    const minute = Math.floor(Date.now() / 60000);
    if (minute !== quotaRenderMinute) { quotaRenderMinute = minute; quotaRequestRender?.(); }
    const level = getLevel(currentCtx);
    const alert = level === "handoff" || level === "critical";
    if (level !== lastAlert && (alert || level === "prepare")) {
      currentCtx.ui.notify(level === "prepare"
        ? "Context: prepare next-step notes. This warning is informational; wait for a supervisor order or owner request before handoff."
        : "High context: check /squad-status; use squad_handoff only after a supervisor order or owner request. The cockpit never replaces sessions.", "warning");
    }
    if (alert && monitor.blink) blinkPhase = !blinkPhase;
    else blinkPhase = true;
    if (alert || level !== lastAlert) repaint();
    lastAlert = level;
  };

  async function checkProvider(ctx: ExtensionContext): Promise<void> {
    const model = ctx.model;
    if (!model) {
      providerHealth = "missing";
      providerDetail = "no model";
      repaint();
      return;
    }
    const auth = ctx.modelRegistry.getProviderAuthStatus(model.provider);
    providerHealth = auth.configured ? "configured" : "missing";
    providerDetail = auth.label || auth.source || "";

    repaint();
  }

  async function checkAws(ctx: ExtensionContext): Promise<void> {
    const profile = process.env.AWS_PROFILE || process.env.AWS_DEFAULT_PROFILE;
    if (!profile && !isAwsModel(ctx)) {
      aws = { state: "inactive" };
      repaint();
      return;
    }

    aws = { state: "loading", profile };
    repaint();
    try {
      const result = await pi.exec("aws", ["sts", "get-caller-identity", "--output", "json"], { timeout: 8000 });
      if (result.code !== 0) throw new Error("STS unavailable");
      const identity = JSON.parse(result.stdout) as { Account?: string; Arn?: string };
      const arn = identity.Arn || "";
      const arnParts = arn.split("/");
      const role = arn.includes(":assumed-role/")
        ? arnParts[1]
        : arn.includes(":role/") || arn.includes(":user/") ? arnParts.slice(1).join("/") : undefined;
      const riskText = `${profile || ""} ${identity.Arn || ""} ${role || ""}`.toLowerCase();
      aws = {
        state: "connected",
        profile,
        account: identity.Account,
        role,
        production: /(^|[^a-z])(prod|prd|production)([^a-z]|$)/.test(riskText),
      };
    } catch {
      aws = { state: "error", profile };
    }
    repaint();
  }

  async function checkQuotas(ctx: ExtensionContext): Promise<void> {
    const model = ctx.model;
    const generation = ++quotaGeneration;
    const isCurrent = () => !closed && generation === quotaGeneration;
    fiveHour = undefined;
    weekly = undefined;
    quotaError = "";
    if (!model || !["openai-codex", "anthropic"].includes(model.provider) || (model.provider === "anthropic" && !ctx.modelRegistry.isUsingOAuth(model))) {
      quotaState = "unsupported";
      publishQuota(ctx);
      repaint();
      return;
    }

    quotaState = "loading";
    publishQuota(ctx);
    repaint();
    try {
      const resolved = await ctx.modelRegistry.getProviderAuth(model.provider);
      const token = resolved?.auth.apiKey ?? resolved?.auth.headers?.Authorization?.replace(/^Bearer\s+/i, "");
      if (!token) throw new Error("subscription token unavailable");

      let url: string;
      const headers: Record<string, string> = { Authorization: `Bearer ${token}`, "User-Agent": "pi-usage-dashboard" };
      if (model.provider === "openai-codex") {
        url = "https://chatgpt.com/backend-api/wham/usage";
        const accountId = jwtAccountId(token);
        if (!accountId) throw new Error("ChatGPT account ID unavailable");
        headers["chatgpt-account-id"] = accountId;
      } else {
        url = "https://api.anthropic.com/api/oauth/usage";
        headers["anthropic-version"] = "2023-06-01";
        headers["anthropic-beta"] = "oauth-2025-04-20";
      }

      const response = await fetch(url, { headers, signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error(`usage endpoint returned HTTP ${response.status}`);
      const quotas = parseSubscriptionUsage(model.provider, await response.json());
      if (!isCurrent()) return;
      if (!quotas.fiveHour && !quotas.weekly) throw new Error("usage endpoint returned no quota windows");
      fiveHour = quotas.fiveHour;
      weekly = quotas.weekly;
      quotaState = "ready";
    } catch (error) {
      if (!isCurrent()) return;
      quotaState = "error";
      const message = error instanceof Error ? error.message : "";
      quotaError = /^usage endpoint returned HTTP \d{3}$/.test(message) ? message : "subscription usage unavailable";
    }
    if (isCurrent()) { quotaLastCheckedAt = Date.now(); publishQuota(ctx); repaint(); }
  }

  pi.events.on("pi-mcp-adapter/status/v1", (snapshot: unknown) => {
    const status = asRecord(snapshot);
    if (!status || !Array.isArray(status.servers)) return;
    const servers = status.servers.map(asRecord).filter((s): s is JsonRecord => Boolean(s && typeof s.name === "string"));
    mcp = {
      connected: servers.filter(s => s.status === "connected").map(s => String(s.name)),
      inactive: servers.filter(s => s.status !== "connected").map(s => String(s.name)),
      checkedAt: Date.now(),
    };
    repaint();
  });

  async function checkMcp(): Promise<void> {
    // Consume Pi's own adapter status; never launch Claude to inspect another runtime.
    if (!mcp.checkedAt) mcp = { connected: [], inactive: [], error: "Pi MCP adapter status unavailable" };
    repaint();
  }

  async function refresh(ctx: ExtensionContext): Promise<void> {
    if (refreshing) return;
    refreshing = true;
    try {
      // Do not hit openrouter.ai on a timer for sessions that never used it.
      const checkCosts = ctx.model?.provider === "openrouter" || orState !== "missing" || getOrCosts(ctx).requests > 0;
      await Promise.all([checkProvider(ctx), checkAws(ctx), checkQuotas(ctx), checkMcp(), checkCosts ? checkOpenRouter(ctx) : Promise.resolve()]);
    } finally {
      refreshing = false;
      repaint();
    }
  }

  function installFooter(ctx: ExtensionContext): void {
    ctx.ui.setFooter((tui, theme, footerData) => {
      requestRender = () => tui.requestRender();
      const unsubscribeBranch = footerData.onBranchChange(requestRender);
      const colourFor = (pct: number) => pct >= 80 ? "error" : pct >= 60 ? "warning" : "success";
      const colouredGauge = (percent: number): string => {
        const pct = clampPercent(percent);
        let filled = Math.round((pct * CELLS) / 100);
        if (pct > 0 && filled === 0) filled = 1;
        let bar = "";
        for (let index = 0; index < CELLS; index++) {
          if (index >= filled) {
            bar += theme.fg("dim", "░");
            continue;
          }
          const edge = ((index + 1) * 100) / CELLS;
          const colour = edge > 80 ? "error" : edge > 60 ? "warning" : "success";
          bar += theme.fg(colour, "█");
        }
        return bar;
      };
      const quotaPart = (label: string, quota: Quota | undefined): string => {
        if (!quota) {
          const fallback = quotaState === "loading" ? "…" : quotaState === "unsupported" || quotaState === "ready" ? "N/A" : "?";
          return theme.fg(quotaState === "error" ? "warning" : "dim", `${label} ${fallback}`);
        }
        const reset = quota.resetsAt ? ` ↻${shortDuration((quota.resetsAt - Date.now()) / 1000)}` : "";
        return theme.fg("dim", `${label} `) + colouredGauge(quota.percent) +
          theme.fg(colourFor(quota.percent), ` ${quota.percent.toFixed(0)}%`) + theme.fg("dim", reset);
      };

      return {
        dispose() {
          unsubscribeBranch();
          if (requestRender) requestRender = undefined;
        },
        invalidate() {},
        render(width: number): string[] {
          const usage = ctx.getContextUsage();
          const model = ctx.model;
          const contextPct = usage?.percent;
          const contextTokens = usage?.tokens;
          const contextWindow = usage?.contextWindow ?? model?.contextWindow;
          const contextLeft = contextWindow && contextTokens != null ? Math.max(0, contextWindow - contextTokens) : undefined;
          const context = contextWindow && contextPct != null
            ? theme.fg("dim", "Ctx ") + colouredGauge(contextPct) +
              theme.fg(colourFor(contextPct), ` ${contextPct.toFixed(0)}%`) +
              theme.fg("dim", ` · ${contextLeft == null ? "?" : humanTokens(contextLeft)} left`)
            : theme.fg("dim", "Ctx N/A");

          const healthIcon = providerHealth === "connected" ? theme.fg("success", "●")
            : providerHealth === "configured" ? theme.fg("warning", "◐")
            : theme.fg("error", "●");
          const provider = `${healthIcon} ${providerLabel(ctx)}${providerDetail ? theme.fg("dim", ` (${providerDetail})`) : ""}`;
          const modelPart = theme.fg("accent", model?.id || "no model") +
            (ctx.thinkingLevel ? theme.fg("dim", ` · ${ctx.thinkingLevel}`) : "");
          const branch = footerData.getGitBranch();

          const mcpPart = mcp.error
            ? theme.fg("warning", "MCP ?")
            : mcp.checkedAt
              ? theme.fg("success", `MCP ✓${mcp.connected.length}`) +
                (mcp.inactive.length ? theme.fg("error", ` ⚠${mcp.inactive.length}`) : "")
              : theme.fg("dim", "MCP …");

          const activityPart = agentActive
            ? theme.fg("accent", "Running") +
              (runningTools.size ? theme.fg("dim", ` · ${runningTools.size} ${runningTools.size === 1 ? "tool" : "tools"}`) : "") +
              (ctx.hasPendingMessages() ? theme.fg("warning", " · queued") : "")
            : theme.fg("success", "Idle") + (ctx.hasPendingMessages() ? theme.fg("warning", " · queued") : "");

          const awsPart = aws.state === "inactive"
            ? theme.fg("dim", "AWS ○")
            : aws.state === "loading"
              ? theme.fg("dim", `AWS …${aws.profile ? ` ${aws.profile}` : ""}`)
              : aws.state === "error"
                ? theme.fg("error", `AWS ✗${aws.profile ? ` ${aws.profile}` : ""}`)
                : (() => {
                    const identity = [aws.profile, aws.role, aws.account].filter(Boolean).join("/");
                    const text = `AWS ● ${identity || "connected"}${aws.production ? " PROD" : ""}`;
                    return theme.fg(aws.production ? "error" : "success", text);
                  })();

          const separator = theme.fg("dim", " │ ");
          const stats = getMetrics(ctx);
          const metricGauge = (label: string, pct: number | undefined, goodHigh = false) => {
            if (pct == null) return theme.fg("dim", `${label} N/A`);
            const colour = goodHigh ? (pct >= 80 ? "success" : pct >= 50 ? "warning" : "muted")
              : pct >= 30 ? "error" : pct >= 10 ? "warning" : "success";
            return theme.fg("dim", `${label} `) + theme.fg(colour, `${gauge(pct)} ${pct.toFixed(0)}%`);
          };
          const level = getLevel(ctx);
          const alerting = level === "handoff" || level === "critical";
          const handoff = alerting
            ? theme.fg(blinkPhase ? "error" : "warning", theme.bold(`${blinkPhase ? "●" : "○"} HANDOFF${level === "critical" ? " AGORA" : ""}`))
            : theme.fg(level === "prepare" ? "warning" : "dim", level === "prepare" ? "PREPARAR HANDOFF" : level === "unknown" ? "Handoff ?" : "Handoff OK");
          // Essential context/alert first: long model/provider names never hide them.
          const wrapSegments = (segments: string[]): string[] => {
            const lines: string[] = [];
            let line = "";
            for (const segment of segments.filter(Boolean)) {
              if (line && visibleWidth(line + separator + segment) > width) {
                lines.push(line);
                line = "";
              }
              line = line ? line + separator + segment : truncateToWidth(segment, width, "…");
            }
            if (line) lines.push(line);
            return lines;
          };
          const monitorLines = wrapSegments([
            handoff, context,
            metricGauge("Cache hit", stats.hitPercent, true),
            metricGauge("Reproc~", stats.reprocessedPercent),
            theme.fg("dim", `Cache R ${humanTokens(stats.latestCacheRead)}/req Σ${humanTokens(stats.cacheRead)}`),
            theme.fg("dim", `Reproc~ Σ${humanTokens(stats.reprocessedEstimate)}`),
          ]);
          const costs = getOrCosts(ctx);
          const balance = orCredits ?? orKeyInfo?.balance;
          const balanceLabel = orCredits ? "Account credits" : "Key limit";
          const orLines = costs.requests || model?.provider === "openrouter" || orState !== "missing"
            ? wrapSegments([
                theme.fg("accent", `OR session~ ${usd(costs.session)}`),
                theme.fg("dim", `Task~ ${usd(costs.task)}`),
                theme.fg("dim", `Releitura~ ${usd(costs.cacheRead)} (task ${usd(costs.taskCacheRead)})`),
                balance
                  ? theme.fg(balance.remaining <= 0 ? "error" : "success", `${balanceLabel} ${usd(balance.remaining)}`) +
                    (balance.usedPercent != null ? ` ${colouredGauge(balance.usedPercent)} ${balance.usedPercent.toFixed(0)}% usado` : "")
                  : theme.fg("dim", orState === "loading" ? "Balance …" : orState === "error" ? "Balance unavailable" : orKeyInfo?.unlimited ? "Unlimited key · account credits N/A" : "Balance N/A"),
                orCredits && orKeyInfo?.balance ? theme.fg("dim", `Limite chave ${usd(orKeyInfo.balance.remaining)}`) : "",
              ]) : [];
          const line1 = fitSegments([modelPart, provider, branch ? theme.fg("dim", `git:${branch}`) : ""], width, separator);
          const line2 = fitSegments([quotaPart("5h", fiveHour), quotaPart("Wk", weekly), mcpPart, activityPart, awsPart], width, separator);
          return [...monitorLines, ...orLines, line1, line2].map((line) => visibleWidth(line) <= width ? line : truncateToWidth(line, width, "…"));
        },
      };
    });
  }

  pi.on("session_start", async (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    currentCtx = ctx;
    closed = false;
    orCostsKey = "";
    metricsLeaf = undefined;
    lastAlert = "unknown";
    try {
      monitor = monitorConfig(JSON.parse(readFileSync(MONITOR_CONFIG, "utf8")));
    } catch (error) {
      monitor = monitorConfig(undefined);
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") ctx.ui.notify(`Cockpit: invalid configuration in ${MONITOR_CONFIG}; using defaults.`, "warning");
    }
    agentActive = !ctx.isIdle();
    runningTools.clear();
    providerHealth = ctx.model && ctx.modelRegistry.hasConfiguredAuth(ctx.model) ? "configured" : "missing";
    installFooter(ctx);
    void refresh(ctx);
    if (timer) clearInterval(timer);
    if (monitorTimer) clearInterval(monitorTimer);
    timer = setInterval(() => currentCtx && void refresh(currentCtx), REFRESH_MS);
    timer.unref?.();
    // 1s per phase (0.5 Hz), with persistent text; never ANSI blink or a screen-wide flash.
    monitorTimer = setInterval(monitorTick, 1000);
    monitorTimer.unref?.();
    monitorTick();
  });

  pi.on("model_select", async (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    currentCtx = ctx;
    providerHealth = ctx.model && ctx.modelRegistry.hasConfiguredAuth(ctx.model) ? "configured" : "missing";
    providerDetail = "";
    fiveHour = undefined;
    weekly = undefined;
    quotaState = "loading";
    repaint();
    void Promise.all([checkProvider(ctx), checkAws(ctx), checkQuotas(ctx)]);
  });

  pi.on("agent_start", () => {
    agentActive = true;
    repaint();
  });

  pi.on("agent_settled", () => {
    agentActive = false;
    runningTools.clear();
    repaint();
  });

  pi.on("tool_execution_start", (event) => {
    runningTools.add(event.toolCallId);
    repaint();
  });

  pi.on("tool_execution_end", (event) => {
    runningTools.delete(event.toolCallId);
    repaint();
  });

  pi.on("input", () => {
    queueMicrotask(repaint);
  });

  pi.on("after_provider_response", (event, ctx) => {
    providerHealth = event.status >= 200 && event.status < 400 ? "connected" : "error";
    providerDetail = event.status >= 400 ? `HTTP ${event.status}` : "online";
    // Pi's response event has no originating provider/request identity. Never assign
    // its quota headers to the currently selected provider; query that provider instead.
    if (ctx.mode === "tui" && quotaState !== "loading" && Date.now() - quotaLastCheckedAt > 60000) void checkQuotas(ctx);
    repaint();
  });

  pi.on("message_update", () => repaint());
  pi.on("message_end", () => repaint());
  pi.on("session_compact", () => { metricsLeaf = undefined; monitorTick(); repaint(); });
  pi.on("session_tree", () => { metricsLeaf = undefined; monitorTick(); repaint(); });

  pi.on("session_shutdown", (_event, ctx) => {
    quotaGeneration++;
    if (ctx.mode === "tui") ctx.ui.setWidget("cockpit-quota", undefined);
    quotaRequestRender = undefined;
    if (timer) clearInterval(timer);
    timer = undefined;
    if (monitorTimer) clearInterval(monitorTimer);
    monitorTimer = undefined;
    closed = true;
    agentActive = false;
    runningTools.clear();
    currentCtx = undefined;
    requestRender = undefined;
  });

  pi.registerCommand("cockpit-quota", {
    description: "Refresh the provider's real five-hour subscription usage and reset time",
    handler: async (_args, ctx) => {
      await checkQuotas(ctx);
      pi.sendMessage({ customType: "cockpit-quota-report", display: true, content: fiveHourSummary(ctx.model?.provider ?? "no provider", quotaState, fiveHour, quotaError, Date.now(), weekly), details: {} });
    },
  });

  pi.registerCommand("dashboard", {
    description: "Context, cache rereads, estimated reprocessing, handoff alert, quotas and health",
    handler: async (_args, ctx) => {
      const usage = ctx.getContextUsage();
      const stats = getMetrics(ctx);
      const quotaText = (quota?: Quota) => quota
        ? `${quota.percent.toFixed(0)}%`
        : quotaState === "unsupported" ? "not supported by provider" : quotaState === "loading" ? "loading" : `unavailable${quotaError ? ` (${quotaError})` : ""}`;
      const inactive = mcp.inactive.length ? mcp.inactive.join(", ") : "none";
      const awsIdentity = aws.state === "connected"
        ? [aws.profile, aws.role, aws.account].filter(Boolean).join("/") + (aws.production ? " PROD" : "")
        : aws.state;
      const activity = agentActive
        ? `running (${runningTools.size} tools${ctx.hasPendingMessages() ? ", queued input" : ""})`
        : `idle${ctx.hasPendingMessages() ? " (queued input)" : ""}`;
      ctx.ui.notify(
        `Context: ${usage?.tokens ?? "?"}/${usage?.contextWindow ?? ctx.model?.contextWindow ?? "?"} tokens; handoff: ${getLevel(ctx)}.\n` +
        `Cache hit (latest response): ${stats.hitPercent?.toFixed(1) ?? "N/A"}%; Cache R: ${stats.latestCacheRead}/req, ${stats.cacheRead} cumulative; Cache W: ${stats.cacheWrite}.\n` +
        `Reproc~: ${Math.round(stats.reprocessedEstimate)} tokens (~${stats.reprocessedPercent?.toFixed(1) ?? "N/A"}% of comparable inputs; ${stats.comparableRequests} pairs).\n` +
        `Estimate = max(0, min(previous prompt, current prompt) − cacheRead), for the same model without crossing compaction. This does not prove waste.\n` +
        `Reused cache is not waste; 0 may mean no cache or no provider telemetry. ` +
        `Recorded Cache R cost: ${stats.cacheReadCost > 0 ? `$${stats.cacheReadCost.toFixed(4)} (provider estimate, not an invoice)` : "N/A or reported zero"}.\n` +
        `Totals: ${stats.requests} top-level responses in the active branch; nested tools/models and summaries excluded.\n` +
        `Visual alerts: prepare ${monitor.warningPercent}%, handoff ${monitor.handoffPercent}% (or reserve ≤${monitor.reserveTokens}, capped at 25% of the window), critical ${monitor.criticalPercent}%; blink ${monitor.blink ? "on" : "off"}.\n` +
        `5h: ${quotaText(fiveHour)}; weekly: ${quotaText(weekly)}; ` +
        `provider: ${providerLabel(ctx)} (${providerHealth}); AWS: ${awsIdentity}; activity: ${activity}; inactive MCPs: ${inactive}`,
        mcp.inactive.length || providerHealth === "error" || providerHealth === "missing" ? "warning" : "info",
      );
    },
  });

  pi.registerCommand("dashboard-costs", {
    description: "OpenRouter session/task/cache costs and remaining key limit/account credits (refresh)",
    handler: async (_args, ctx) => {
      await checkOpenRouter(ctx);
      const costs = getOrCosts(ctx);
      const key = orKeyInfo?.balance;
      ctx.ui.notify(
        `OpenRouter · USD\nSession~ ${usd(costs.session)}; current task~ ${usd(costs.task)}.\n` +
        `Cache read~ ${usd(costs.cacheRead)} (task~ ${usd(costs.taskCacheRead)}), already included in totals; do not add again.\n` +
        `Remaining key limit: ${key ? usd(key.remaining) : orKeyInfo?.unlimited ? "no configured limit (not infinite balance)" : "N/A"}.\n` +
        `Account credits: ${orCredits ? usd(orCredits.remaining) : `N/A${orCreditsError ? ` (${orCreditsError})` : "; /credits requires a management key via OPENROUTER_MANAGEMENT_KEY"}`}.\n` +
        `Checked: ${orCheckedAt ? new Date(orCheckedAt).toLocaleTimeString() : "not yet"}${orError ? `; ${orError}` : ""}; refreshes every 10 min or with /dashboard-costs.\n` +
        `~ = Pi-recorded estimates, not a reconciled invoice. Session includes all branches; task = since the latest user message in the active branch.\n` +
        `Only top-level OpenRouter responses; nested calls/summaries without provider identity are excluded. Forks include copied history. Paid cache does not imply waste.`,
        orState === "error" ? "warning" : "info",
      );
    },
  });

  pi.registerCommand("dashboard-blink", {
    description: "Enable/disable handoff blink (on|off); keeps the static alert",
    handler: async (args, ctx) => {
      const value = args.trim();
      if (value !== "on" && value !== "off") {
        ctx.ui.notify("Use /dashboard-blink on or /dashboard-blink off", "info");
        return;
      }
      // Preserve any newer configuration edited by another session.
      let saved: unknown;
      try { saved = JSON.parse(readFileSync(MONITOR_CONFIG, "utf8")); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
      const next = { ...monitorConfig(saved), blink: value === "on" };
      writeFileSync(MONITOR_CONFIG, JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
      monitor = next;
      blinkPhase = true;
      repaint();
      ctx.ui.notify(`Blink ${value}; the text alert remains active.`, "info");
    },
  });

  pi.registerCommand("dashboard-refresh", {
    description: "Refresh provider and MCP health now",
    handler: async (_args, ctx) => {
      await refresh(ctx);
      ctx.ui.notify("Dashboard refreshed", "info");
    },
  });
}
