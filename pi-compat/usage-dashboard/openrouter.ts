import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export type OpenRouterCosts = { requests: number; session: number; task: number; cacheRead: number; taskCacheRead: number };
const amount = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;

/** Costs recorded by Pi, not a reconciled OpenRouter invoice. All session branches count. */
export function openRouterCosts(entries: readonly SessionEntry[], branch: readonly SessionEntry[]): OpenRouterCosts {
  const result: OpenRouterCosts = { requests: 0, session: 0, task: 0, cacheRead: 0, taskCacheRead: 0 };
  for (const entry of entries) {
    if (entry.type !== "message" || entry.message.role !== "assistant" || entry.message.provider !== "openrouter") continue;
    const usage = entry.message.usage;
    if (!usage) continue;
    result.requests++;
    result.session += amount(usage.cost?.total) ?? 0;
    result.cacheRead += amount(usage.cost?.cacheRead) ?? 0;
  }
  for (const entry of branch) {
    if (entry.type !== "message") continue;
    if (entry.message.role === "user") { result.task = 0; result.taskCacheRead = 0; }
    if (entry.message.role === "assistant" && entry.message.provider === "openrouter") {
      result.task += amount(entry.message.usage?.cost?.total) ?? 0;
      result.taskCacheRead += amount(entry.message.usage?.cost?.cacheRead) ?? 0;
    }
  }
  return result;
}

export type Balance = { remaining: number; total?: number; usedPercent?: number };
export type KeyInfo = { balance?: Balance; unlimited: boolean; management: boolean };
function data(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== "object") return {};
  const body = (payload as { data?: unknown }).data;
  return body && typeof body === "object" ? body as Record<string, unknown> : {};
}

export function parseOpenRouterKey(payload: unknown): KeyInfo {
  const body = data(payload);
  const total = amount(body.limit);
  const reportedRemaining = amount(body.limit_remaining);
  const used = amount(body.usage);
  const remaining = reportedRemaining ?? (total != null && used != null ? Math.max(0, total - used) : undefined);
  return {
    unlimited: body.limit === null,
    management: body.is_management_key === true,
    balance: remaining == null ? undefined : {
      remaining, total,
      usedPercent: total != null && total > 0 ? Math.max(0, Math.min(100, (total - remaining) / total * 100)) : undefined,
    },
  };
}

export function parseOpenRouterCredits(payload: unknown): Balance | undefined {
  const body = data(payload);
  const total = amount(body.total_credits);
  const used = amount(body.total_usage);
  if (total == null || used == null) return undefined;
  return {
    total, remaining: Math.max(0, total - used),
    usedPercent: total > 0 ? Math.min(100, used / total * 100) : used > 0 ? 100 : undefined,
  };
}

export function usd(value: number): string {
  if (value > 0 && value < 0.0001) return "<$0.0001";
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}
