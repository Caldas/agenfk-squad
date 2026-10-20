import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export type MonitorConfig = {
  warningPercent: number;
  handoffPercent: number;
  criticalPercent: number;
  reserveTokens: number;
  blink: boolean;
};

export const DEFAULT_MONITOR: MonitorConfig = {
  warningPercent: 60,
  handoffPercent: 70,
  criticalPercent: 85,
  reserveTokens: 20000,
  blink: true,
};

export function monitorConfig(value: unknown): MonitorConfig {
  if (!value || typeof value !== "object") return { ...DEFAULT_MONITOR };
  const raw = value as Partial<MonitorConfig>;
  const result = { ...DEFAULT_MONITOR };
  if (typeof raw.blink === "boolean") result.blink = raw.blink;
  if (typeof raw.reserveTokens === "number" && Number.isFinite(raw.reserveTokens) && raw.reserveTokens >= 0) {
    result.reserveTokens = Math.round(raw.reserveTokens);
  }
  const warning = raw.warningPercent ?? result.warningPercent;
  const handoff = raw.handoffPercent ?? result.handoffPercent;
  const critical = raw.criticalPercent ?? result.criticalPercent;
  if ([warning, handoff, critical].every(n => typeof n === "number" && Number.isFinite(n)) &&
      warning > 0 && warning < handoff && handoff < critical && critical <= 100) {
    result.warningPercent = warning;
    result.handoffPercent = handoff;
    result.criticalPercent = critical;
  }
  return result;
}

export type HandoffLevel = "unknown" | "ok" | "prepare" | "handoff" | "critical";
export function handoffLevel(percent: number | null | undefined, tokens: number | null | undefined,
  window: number | undefined, config: MonitorConfig): HandoffLevel {
  if (percent == null || !Number.isFinite(percent)) return "unknown";
  if (percent >= config.criticalPercent) return "critical";
  // Cap the reserve at 25% of small context windows; don't warn on an empty session.
  const lowReserve = window != null && window > 0 && tokens != null &&
    window - tokens <= Math.min(config.reserveTokens, window * 0.25);
  if (percent >= config.handoffPercent || lowReserve) return "handoff";
  return percent >= config.warningPercent ? "prepare" : "ok";
}

export type CacheMetrics = {
  requests: number;
  promptTokens: number;
  cacheRead: number;
  cacheWrite: number;
  latestPrompt: number;
  latestCacheRead: number;
  hitPercent?: number;
  reprocessedEstimate: number;
  comparablePrompt: number;
  comparableRequests: number;
  reprocessedPercent?: number;
  cacheReadCost: number;
};

const nonnegative = (n: unknown): number => typeof n === "number" && Number.isFinite(n) ? Math.max(0, n) : 0;

/** Main assistant requests on the active branch, not nested tools or summary model calls.
 * Pi Usage.input excludes cacheRead/cacheWrite. Cache read is reuse, NOT waste.
 * Reprocessing is only a size-based proxy, never a billing measurement or content comparison.
 */
export function cacheMetrics(entries: readonly SessionEntry[]): CacheMetrics {
  const result: CacheMetrics = {
    requests: 0, promptTokens: 0, cacheRead: 0, cacheWrite: 0, latestPrompt: 0,
    latestCacheRead: 0, reprocessedEstimate: 0, comparablePrompt: 0,
    comparableRequests: 0, cacheReadCost: 0,
  };
  let previous: { model: string; prompt: number } | undefined;
  for (const entry of entries) {
    if (entry.type === "compaction" || entry.type === "branch_summary" || entry.type === "model_change") {
      previous = undefined;
      continue;
    }
    if (entry.type !== "message" || entry.message.role !== "assistant") continue;
    const message = entry.message;
    const usage = message.usage;
    if (!usage) { previous = undefined; continue; }
    const input = nonnegative(usage.input);
    const read = nonnegative(usage.cacheRead);
    const write = nonnegative(usage.cacheWrite);
    const prompt = input + read + write;
    if (!prompt) { previous = undefined; continue; }
    result.requests++;
    result.promptTokens += prompt;
    result.cacheRead += read;
    result.cacheWrite += write;
    result.cacheReadCost += nonnegative(usage.cost?.cacheRead);
    result.latestPrompt = prompt;
    result.latestCacheRead = read;
    result.hitPercent = read / prompt * 100;
    const model = `${message.provider}/${message.model}/${message.api}`;
    if (previous?.model === model && message.stopReason !== "error" && message.stopReason !== "aborted") {
      // Previous prompt size approximates the recurring prefix. Newly added tokens are excluded.
      result.reprocessedEstimate += Math.max(0, Math.min(previous.prompt, prompt) - read);
      result.comparablePrompt += prompt;
      result.comparableRequests++;
    }
    previous = message.stopReason === "error" || message.stopReason === "aborted" ? undefined : { model, prompt };
  }
  if (result.comparablePrompt) result.reprocessedPercent = result.reprocessedEstimate / result.comparablePrompt * 100;
  return result;
}
