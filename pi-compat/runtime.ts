import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import type { Resource, Hook, Inventory } from "./resources.ts";
import { resourceBody, within } from "./resources.ts";

export function runProcess(command: string, args: string[], options: { cwd: string; env?: NodeJS.ProcessEnv; input?: string; timeout?: number; signal?: AbortSignal; line?: (line: string) => void }) {
  return new Promise<{ code: number; stdout: string; stderr: string }>((resolve, reject) => {
    if (options.signal?.aborted) { reject(new Error("Cancelled")); return; }
    const p = spawn(command, args, { cwd: options.cwd, env: options.env ?? process.env, detached: process.platform !== "win32", stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "", buffer = "", bytes = 0, failure: Error | undefined;
    const kill = () => { try { if (p.pid) process.platform === "win32" ? p.kill("SIGKILL") : process.kill(-p.pid, "SIGKILL"); } catch { /* Already exited. */ } };
    const abort = () => { failure = new Error("Cancelled"); kill(); };
    const timer = setTimeout(() => { failure = new Error("Process deadline exceeded"); kill(); }, options.timeout ?? 120_000);
    options.signal?.addEventListener("abort", abort, { once: true });
    const cleanup = () => { clearTimeout(timer); options.signal?.removeEventListener("abort", abort); };
    p.stdout.on("data", (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > (options.line ? 16 * 1024 * 1024 : 51200)) { failure = new Error("Process output exceeded its safe byte limit"); kill(); return; }
      if (options.line) {
        buffer += chunk.toString();
        const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
        for (const line of lines) options.line(line);
      } else stdout += chunk.toString();
    });
    p.stderr.on("data", (chunk: Buffer) => { stderr = (stderr + chunk.toString()).slice(-8000); });
    p.stdin.on("error", () => { /* A child may close stdin before consuming the payload. */ });
    p.stdin.end(options.input);
    p.on("error", error => { cleanup(); reject(error); });
    p.on("close", code => { cleanup(); if (buffer) options.line?.(buffer); failure ? reject(failure) : resolve({ code: code ?? 1, stdout, stderr }); });
  });
}
export const toolMap: Record<string, string> = { Read: "read", Bash: "bash", Write: "write", Edit: "edit", MultiEdit: "edit", Glob: "find", Grep: "grep", WebFetch: "web_fetch", WebSearch: "web_search", Task: "subagent", Agent: "subagent" };
export function agentTools(resource: Resource, active: string[]) {
  const requested = resource.tools?.map(t => toolMap[t] ?? t);
  const denied = resource.deniedTools?.map(t => toolMap[t.split("(")[0]] ?? t) ?? [];
  const deniedMatch = (tool: string) => denied.some(d => new RegExp(`^${d.split("*").map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*")}$`).test(tool));
  const permitted = requested ? active.filter(t => requested.includes(t)) : active.filter(t => t !== "subagent");
  return { permitted: permitted.filter(t => t !== "subagent" && !deniedMatch(t)), missing: requested?.filter(t => !active.includes(t)) ?? [] };
}
export function nativeRuntime(argv = process.argv, flagValue?: (name: string) => unknown) {
  const entry = argv[1] ? fs.realpathSync(argv[1]) : "";
  if (!/[\\/]@earendil-works[\\/]pi-coding-agent[\\/]dist[\\/](?:bundle[\\/])?cli\.js$/.test(entry))
    throw new Error("Delegation requires native Pi CLI so configured permission extensions can be preserved; SDK-only runtimes need an explicit broker.");
  const forwarded: string[] = [];
  const coreValues = new Set(["--mode", "--provider", "--model", "--thinking", "--models", "--session", "--session-dir", "--name", "-n", "--tools", "-t", "--exclude-tools", "-xt", "--system-prompt", "--append-system-prompt", "--tui-mode", "--use-theme"]);
  const coreBooleans = new Set(["-p", "--print", "--no-session", "-c", "--continue", "-r", "--resume", "--verbose", "-a", "--approve", "-na", "--no-approve", "--no-tools", "-nt", "--no-builtin-tools", "-nbt", "--offline"]);
  for (let i = 2; i < argv.length && argv[i] !== "--"; i++) {
    const arg = argv[i], key = arg.split("=")[0];
    if (key === "--api-key") throw new Error("Ephemeral CLI credentials cannot be safely inherited; configure provider authentication before delegating.");
    if (["-e", "--extension", "--skill", "--prompt-template"].includes(key)) {
      forwarded.push(arg);
      if (!arg.includes("=")) { if (!argv[i + 1]) throw new Error(`Missing parent runtime argument: ${arg}`); forwarded.push(argv[++i]); }
    } else if (["--no-extensions", "--no-skills", "--no-context-files", "-nc", "--no-prompt-templates"].includes(key)) forwarded.push(arg);
    else if (coreValues.has(key)) { if (!arg.includes("=")) i++; }
    else if (coreBooleans.has(key)) { /* Child values are derived from the actual session. */ }
    else if (arg.startsWith("-")) {
      const value = flagValue?.(key.replace(/^--/, ""));
      if (value === undefined) throw new Error(`Cannot inherit unknown runtime flag ${key}; refusing a potentially different execution backend.`);
      forwarded.push(arg);
      if (typeof value === "string" && !arg.includes("=")) { if (!argv[i + 1]) throw new Error(`Missing runtime flag value: ${key}`); forwarded.push(argv[++i]); }
    }
  }
  return { command: process.execPath, prefix: [entry, ...forwarded] };
}
export async function runAgent(resource: Resource, task: string, config: { cwd: string; model: string; thinking: string; tools: string[]; trusted: boolean; signal?: AbortSignal; parentPrompt?: string; runtime?: { command: string; prefix: string[] } }) {
  if (!config.trusted) throw new Error("Trust the project before delegating an agent with access to its files.");
  if (Number(process.env.PI_CLAUDE_CHILD_DEPTH ?? 0) >= 1) throw new Error("Nested subagents are disabled; delegate from the parent session.");
  if (!task.trim()) throw new Error("Agent task cannot be empty.");
  // Isolation/memory/permission metadata cannot be silently reduced to prompt text.
  if (resource.unsupported.some(k => ["isolation", "permissionMode", "hooks", "memory", "background"].includes(k))) {
    throw new Error(`Agent ${resource.name} needs unsupported execution controls: ${resource.unsupported.join(", ")}. Load its instructions as a persona, or adapt the definition explicitly.`);
  }
  const runtime = config.runtime ?? nativeRuntime();
  const { permitted, missing } = agentTools(resource, config.tools);
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "pi-claude-agent-"));
  fs.chmodSync(temp, 0o700);
  const prompt = path.join(temp, "instructions.md");
  fs.writeFileSync(prompt, (config.parentPrompt ? `${config.parentPrompt}\n\n` : "") + resourceBody(resource) + `\n\nRun as ${resource.name}. Use the inherited Pi model, not the Claude model alias in the source. Missing tools: ${missing.join(", ") || "none"}. Never claim unavailable capabilities. Do not advance cards, publish, merge or deploy.\n`, { mode: 0o600 });
  const args = ["--mode", "json", "-p", "--no-session", "--model", config.model, "--thinking", config.thinking,
    config.trusted ? "--approve" : "--no-approve", "--append-system-prompt", prompt];
  args.push(...(permitted.length ? ["--tools", permitted.join(",")] : ["--no-tools"]));
  // Use a fixed task prefix: delegated text must not become a CLI flag or a file argument.
  args.push("--", `Delegated task:\n${task}`);
  let answer = "", modelError = "", turns = 0;
  let usage: any;
  const addUsage = (u: any) => {
    if (!u) return;
    usage ??= { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
    for (const k of ["input", "output", "cacheRead", "cacheWrite", "totalTokens"]) usage[k] += u[k] ?? 0;
    for (const k of ["input", "output", "cacheRead", "cacheWrite", "total"]) usage.cost[k] += u.cost?.[k] ?? 0;
  };
  try {
    const result = await runProcess(runtime.command, [...runtime.prefix, ...args], { cwd: config.cwd, timeout: 180_000, signal: config.signal,
      env: { ...process.env, PI_CLAUDE_CHILD_DEPTH: "1", PI_OFFLINE: "1" },
      line: line => {
        let event: any; try { event = JSON.parse(line); } catch { return; }
        if (event.type === "message_end" && event.message?.role === "assistant") {
          const m = event.message; turns++; addUsage(m.usage);
          if (m.stopReason === "error" || m.stopReason === "aborted") modelError = m.errorMessage ?? m.stopReason;
          const text = (m.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n");
          if (text) answer = text.slice(-48000);
        }
      } });
    if (result.code !== 0 || modelError || !answer) throw new Error(`Subagent failed: ${modelError || result.stderr || `exit ${result.code}, no final text`}`);
    return { answer, turns, model: config.model, missing, usage };
  } finally { fs.rmSync(temp, { recursive: true, force: true }); }
}
export function hookMatches(h: Hook, tool: string) {
  if (!h.matcher || h.matcher === "*") return true;
  try { return new RegExp(`^(?:${h.matcher})$`).test(tool); } catch { return false; }
}
export function hookPayload(toolName: string, input: Record<string, unknown>) {
  const reverse: Record<string, string> = { read: "Read", bash: "Bash", edit: "Edit", write: "Write", find: "Glob", grep: "Grep", subagent: "Task", web_fetch: "WebFetch", web_search: "WebSearch" };
  const converted = { ...input };
  if (typeof input.path === "string") converted.file_path = input.path;
  if (Array.isArray(input.edits) && input.edits.length === 1) {
    const edit = input.edits[0] as any; converted.old_string = edit.oldText; converted.new_string = edit.newText;
  }
  return { tool_name: reverse[toolName] ?? toolName, tool_input: converted };
}
export async function runHook(h: Hook, payload: Record<string, unknown>, cwd: string, signal?: AbortSignal) {
  if (h.unsupported.length || !h.command) throw new Error(`Unsupported hook controls: ${h.unsupported.join(", ")}`);
  const result = await runProcess("bash", ["-c", h.command], { cwd, input: JSON.stringify(payload), timeout: h.timeout * 1000, signal,
    env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, ...(h.root ? { CLAUDE_PLUGIN_ROOT: h.root } : {}) } });
  let data: any; try { data = JSON.parse(result.stdout); } catch {
    if (result.stdout.trim().startsWith("{")) throw new Error("Malformed hook JSON; refusing to ignore a possible deny decision.");
    // Plain text guidance is valid, but cannot override a permission decision.
  }
  return { ...result, data };
}
export async function lspRequest(server: Inventory["lsp"][number], file: string, method: string, line: number, character: number, cwd: string, signal?: AbortSignal): Promise<unknown> {
  const target = fs.realpathSync(path.resolve(cwd, file));
  if (!within(target, fs.realpathSync(cwd))) throw new Error("LSP file must be inside the current worktree.");
  const definition: any = server.definition;
  if (typeof definition.command !== "string") throw new Error("LSP server has no executable command.");
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error("Cancelled")); return; }
    const p = spawn(definition.command, definition.args ?? [], { cwd, env: { ...process.env, ...definition.env }, detached: process.platform !== "win32", stdio: ["pipe", "pipe", "pipe"] });
    let buffer = Buffer.alloc(0), settled = false, stderr = "";
    const finish = (error?: Error, value?: unknown) => {
      if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener("abort", abort);
      try { if (p.pid) process.platform === "win32" ? p.kill("SIGKILL") : process.kill(-p.pid, "SIGKILL"); } catch { /* Already exited. */ }
      error ? reject(error) : resolve(value);
    };
    const abort = () => finish(new Error("Cancelled"));
    const timer = setTimeout(() => finish(new Error("LSP deadline exceeded")), 20_000);
    signal?.addEventListener("abort", abort, { once: true });
    const send = (msg: any) => { const body = JSON.stringify({ jsonrpc: "2.0", ...msg }); p.stdin.write(`Content-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`); };
    p.on("error", error => finish(error));
    p.stdin.on("error", error => finish(error));
    p.stderr.on("data", data => { stderr = (stderr + data).slice(-2000); });
    p.on("exit", code => { if (!settled) finish(new Error(`LSP exited (${code}): ${stderr}`)); });
    p.stdout.on("data", (data: Buffer) => {
      buffer = Buffer.concat([buffer, data]);
      if (buffer.length > 2 * 1024 * 1024) { finish(new Error("LSP message exceeded 2 MiB")); return; }
      while (!settled) {
        const split = buffer.indexOf("\r\n\r\n"); if (split < 0) break;
        const length = Number(/Content-Length:\s*(\d+)/i.exec(buffer.subarray(0, split).toString())?.[1]);
        if (!Number.isFinite(length) || length > 2 * 1024 * 1024) { finish(new Error("Invalid LSP framing")); break; }
        if (buffer.length < split + 4 + length) break;
        let msg: any; try { msg = JSON.parse(buffer.subarray(split + 4, split + 4 + length).toString()); } catch { finish(new Error("Invalid LSP JSON")); break; }
        buffer = buffer.subarray(split + 4 + length);
        if (msg.id === 1) {
          if (msg.error) { finish(new Error(JSON.stringify(msg.error))); break; }
          send({ method: "initialized", params: {} });
          const ext = path.extname(target);
          const languageId = definition.extensionToLanguage?.[ext] ?? (ext.includes("ts") ? "typescript" : "javascript");
          send({ method: "textDocument/didOpen", params: { textDocument: { uri: pathToFileURL(target).href, languageId, version: 1, text: fs.readFileSync(target, "utf8") } } });
          send({ id: 2, method: `textDocument/${method}`, params: { textDocument: { uri: pathToFileURL(target).href }, position: { line, character }, context: { includeDeclaration: true } } });
        } else if (msg.id === 2) msg.error ? finish(new Error(JSON.stringify(msg.error))) : finish(undefined, msg.result);
        else if (msg.method && msg.id !== undefined) send({ id: msg.id, result: msg.method === "workspace/configuration" ? (msg.params?.items ?? []).map(() => ({})) : null });
      }
    });
    send({ id: 1, method: "initialize", params: { processId: process.pid, rootUri: pathToFileURL(cwd).href, capabilities: {}, initializationOptions: definition.initializationOptions ?? {} } });
  });
}
