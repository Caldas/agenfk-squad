/**
 * The squad watcher on oh-my-pi (omp).
 *
 * omp does not speak Claude Code's hook protocol. This extension maps its
 * events onto hooks/squad-watch-omp.py, which writes the payload
 * hooks/squad-watch.py expects and translates its verdict back. Every decision
 * stays in the Python watcher: this file only routes events and applies the
 * answer, so the arithmetic is single-source.
 *
 *   tool_call              -> PreToolUse        (loop denial, merge queue)
 *   before_subagent_spawn  -> PreToolUse "Task" (dispatch caps)
 *   tool_result            -> PostToolUse       (notes)
 *   session_stop           -> Stop              (handoff)
 *   prompt                 -> UserPromptSubmit  (pending notes)
 *
 * A failure anywhere here prints nothing and blocks nothing: the watcher is a
 * brake, never a reason for the host to stop.
 */
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

export interface BridgeVerdict { block?: boolean; reason?: string; context?: string }

interface PiApi {
  on(event: string, handler: (event: any, ctx: any) => unknown): void;
  sendMessage(message: { customType: string; content: string; display?: boolean },
              options?: { deliverAs?: 'steer' | 'followUp' | 'nextTurn'; triggerTurn?: boolean }): void;
}

/** The bridge path: an explicit override, else the squad's installed hook. */
export function bridgePath(env: Record<string, string | undefined> = process.env): string {
  return env.SQUAD_WATCH_OMP_BRIDGE
    || path.join(env.SQUAD_DIR || path.join(os.homedir(), '.claude'), 'hooks', 'squad-watch-omp.py');
}

/** omp names the session file `<timestamp>_<session-id>.jsonl`. */
export function sessionIdFrom(file: string | undefined): string | null {
  if (!file) return null;
  const base = path.basename(file).replace(/\.jsonl$/, '');
  const cut = base.lastIndexOf('_');
  return cut >= 0 ? base.slice(cut + 1) : base;
}

/** A getter on ctx that may not exist; a failure is a miss, never a crash. */
function safeCall(obj: any, fn: string): string | null {
  try {
    const v = obj?.[fn]?.();
    return typeof v === 'string' && v ? v : null;
  } catch {
    return null;
  }
}

/**
 * One omp event, in the shape the bridge reads.
 *
 * The session comes from `ctx.sessionManager`, never from `PI_SESSION_FILE`:
 * omp inherits that variable from a pi parent process, so it can point at a
 * DIFFERENT session (the pi one that launched omp). The env is only a fallback
 * for a context with no session manager.
 */
export function buildEvent(kind: string, payload: Record<string, unknown> | undefined, ctx: any,
                           env: Record<string, string | undefined> = process.env,
                           cwd: string = process.cwd()): Record<string, unknown> {
  const sm = ctx?.sessionManager;
  const file = safeCall(sm, 'getSessionFile') || env.PI_SESSION_FILE || '';
  const sid = safeCall(sm, 'getSessionId') || sessionIdFrom(file);
  const event: Record<string, unknown> = {
    event: kind,
    session_id: sid,
    transcript_path: file,
    cwd,
  };
  if (ctx?.agent?.kind === 'sub') {
    event.agent_id = ctx.agent.id;
    event.agent_type = ctx.agent.name;
    // the child's own session file is the sub-session transcript
    event.agent_transcript_path = file;
  }
  if (kind === 'before_subagent_spawn') {
    event.agent = payload?.agent;
    event.prompt = payload?.prompt ?? payload?.context ?? payload?.description ?? '';
  } else {
    event.tool_name = payload?.toolName;
    event.tool_input = payload?.input;
  }
  return event;
}

function runBridge(event: Record<string, unknown>): BridgeVerdict {
  try {
    const r = spawnSync('python3', [bridgePath()], {
      input: JSON.stringify(event), encoding: 'utf8', timeout: 30_000, windowsHide: true,
    });
    const out = (r.stdout || '').trim();
    return out ? JSON.parse(out) : {};
  } catch {
    return {};
  }
}

/** The verdict, or {} when there is nothing to decide (no session, no bridge). */
export function decide(event: Record<string, unknown>, runner: (e: Record<string, unknown>) => BridgeVerdict = runBridge): BridgeVerdict {
  if (!event.session_id || !event.transcript_path) return {};
  return runner(event);
}

export default function activate(pi: PiApi): void {
  const cwd = process.cwd();
  const fire = (kind: string, payload: Record<string, unknown> | undefined, ctx: any) =>
    decide(buildEvent(kind, payload, ctx, process.env, cwd));

  pi.on('tool_call', (event, ctx) => {
    const v = fire('tool_call', event, ctx);
    return v.block ? { block: true, reason: v.reason } : undefined;
  });

  pi.on('before_subagent_spawn', (event, ctx) => {
    const v = fire('before_subagent_spawn', event, ctx);
    return v.block ? { block: true, reason: v.reason } : undefined;
  });

  pi.on('session_stop', (event, ctx) => {
    const v = fire('session_stop', event, ctx);
    return v.block ? { decision: 'block', reason: v.reason } : undefined;
  });

  const note = (event: any, ctx: any, kind: string) => {
    const v = fire(kind, event, ctx);
    if (v.context) {
      pi.sendMessage({ customType: 'squad-watch', content: v.context, display: true },
                     { deliverAs: 'steer', triggerTurn: false });
    }
    return undefined;
  };
  pi.on('tool_result', (event, ctx) => note(event, ctx, 'tool_result'));
  pi.on('prompt', (event, ctx) => note(event, ctx, 'prompt'));
}
