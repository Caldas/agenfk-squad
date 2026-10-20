import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { Type } from "typebox";
import { StringEnum } from "@earendil-works/pi-ai";
import { getAgentDir, truncateHead, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { discover, publicInventory, resourceBody, json, type Inventory, type Hook } from "./resources.ts";
import { runAgent, runHook, hookMatches, hookPayload, lspRequest, nativeRuntime } from "./runtime.ts";
import { routePrompt } from "./routing.ts";
import { attachVigia } from "./vigia.ts";

export function result(value: unknown): { content: { type: "text"; text: string }[]; details: { file?: string } } {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const truncated = truncateHead(text, { maxBytes: 48000, maxLines: 1800 });
  if (!truncated.truncated) return { content: [{ type: "text" as const, text }], details: {} };
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-claude-result-"));
  fs.chmodSync(dir, 0o700);
  const file = path.join(dir, "result.txt"); fs.writeFileSync(file, text, { mode: 0o600 });
  return { content: [{ type: "text" as const, text: `${truncated.content}\n[Truncated; full result: ${file}]` }], details: { file } };
}
export function portableSafetyHook(h: Hook): boolean {
  const approved = new Set([
    "$HOME/.claude/hooks/bash-guard.sh",
    path.join(os.homedir(), ".claude", "hooks", "bash-guard.sh"),
    'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/setup/root-checkout-guard.sh" pre-tool',
    'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/setup/agenfk-lock.sh" pre-tool',
  ]);
  return h.event === "PreToolUse" && !h.unsupported.length && Boolean(h.command && approved.has(h.command));
}
export function generatePrompts(i: Inventory, cwd: string, dir: string): string[] {
  const cache = path.join(dir, "claude-compat", "prompts", createHash("sha256").update(cwd).digest("hex").slice(0, 20));
  fs.mkdirSync(cache, { recursive: true, mode: 0o700 });
  const files: string[] = [];
  for (const resource of i.resources.filter(r => r.kind === "command")) {
    // Never turn a resource name into a filesystem traversal.
    const name = resource.name.replace(/[^a-zA-Z0-9:_-]/g, "-");
    const file = path.join(cache, `${name}.md`);
    const content = `---\ndescription: ${JSON.stringify(resource.description)}\n---\n${resourceBody(resource)}\n`;
    fs.writeFileSync(file, content, { mode: 0o600 }); files.push(file);
  }
  const swarm = path.join(cache, "swarm.md");
  fs.writeFileSync(swarm, '---\ndescription: Delegate to a swarm agent using the selected Pi model\nargument-hint: "<agent> <task>"\n---\nUse the actual subagent tool for $ARGUMENTS. Do not simulate delegation.\n', { mode: 0o600 });
  files.push(swarm);
  return files;
}
export function generateSkills(i: Inventory, cwd: string, dir: string): string[] {
  const cache = path.join(dir, "claude-compat", "skills", createHash("sha256").update(cwd).digest("hex").slice(0, 20));
  return i.resources.filter(r => r.kind === "skill").map(r => {
    const folder = path.join(cache, createHash("sha256").update(r.file).digest("hex").slice(0, 20));
    fs.mkdirSync(folder, { recursive: true, mode: 0o700 });
    const file = path.join(folder, "SKILL.md");
    fs.writeFileSync(file, `---\nname: ${JSON.stringify(r.name)}\ndescription: ${JSON.stringify(r.description.slice(0, 1024))}\ndisable-model-invocation: ${Boolean(r.manualOnly)}\n---\n${resourceBody(r)}\n`, { mode: 0o600 });
    return file;
  });
}
export async function fetchText(address: string, signal?: AbortSignal) {
  const url = new URL(address);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Use an HTTP(S) URL without embedded credentials.");
  const response = await fetch(url, { signal: AbortSignal.any([signal ?? new AbortController().signal, AbortSignal.timeout(20_000)]) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  if (!/text|json|xml|javascript/.test(response.headers.get("content-type") ?? "")) throw new Error("Non-text content; use a dedicated download or browser tool.");
  if (!response.body) return "";
  const reader = response.body.getReader(); const chunks: Buffer[] = []; let size = 0;
  try { while (true) { const next = await reader.read(); if (next.done) break; size += next.value.length; if (size > 1024 * 1024) throw new Error("Web response exceeds 1 MiB; request a smaller page."); chunks.push(Buffer.from(next.value)); } }
  finally { await reader.cancel(); }
  return Buffer.concat(chunks).toString("utf8");
}
export function searchResults(xml: string) {
  const decode = (s: string) => s.replace(/^<!\[CDATA\[([\s\S]*)\]\]>$/, "$1").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  return [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 10).map(item => {
    const field = (key: string) => decode(new RegExp(`<${key}>([\\s\\S]*?)<\\/${key}>`).exec(item[1])?.[1] ?? "");
    return { title: field("title"), url: field("link"), snippet: field("description") };
  });
}
export default function claudeCompat(pi: ExtensionAPI) {
  let inventory: Inventory = discover(process.cwd(), false);
  const registrations: { dispose(): Promise<void> }[] = [];
  const registrationStatus = new Map<string, string>();
  const options = () => json(path.join(getAgentDir(), "claude-compat.json")) ?? {};
  attachVigia(pi, () => options().vigia);
  const refresh = (ctx: any) => inventory = discover(ctx.cwd, ctx.isProjectTrusted(), os.homedir(), typeof options().swarmRoot === "string" ? options().swarmRoot : undefined);
  const enabledHook = (h: Hook) => portableSafetyHook(h) || (options().enabledHookCommands ?? []).includes(h.command);

  pi.on("session_start", async (_event, ctx) => {
    refresh(ctx); registrationStatus.clear();
    for (const s of inventory.servers) {
      const request: any = { version: 1, name: s.name, definition: { ...s.definition, lifecycle: "lazy" } };
      pi.events.emit("pi-mcp-adapter:runtime-register:v1", request);
      if (request.result?.ok) { registrations.push(request.result.registration); registrationStatus.set(s.name, "registered-lazy"); }
      else registrationStatus.set(s.name, request.result ? "existing-config-or-registration-error (inspect /mcp)" : "MCP adapter unavailable");
    }
  });
  pi.on("session_shutdown", async () => { for (const r of registrations.splice(0)) await r.dispose(); });
  pi.on("resources_discover", (event, ctx) => {
    refresh(ctx);
    return { skillPaths: generateSkills(inventory, event.cwd, getAgentDir()), promptPaths: generatePrompts(inventory, event.cwd, getAgentDir()) };
  });
  pi.on("before_agent_start", (event, ctx) => {
    const agents = inventory.resources.filter(r => r.kind === "agent").map(r => `- ${r.name}: ${r.description}`).join("\n");
    const loaded = new Set((event.systemPromptOptions?.contextFiles ?? []).map(f => { try { return fs.realpathSync(f.path); } catch { return f.path; } }));
    const guidance = inventory.guidance.filter(f => !loaded.has(fs.realpathSync(f))).map(f => `\nSource ${f}:\n${fs.readFileSync(f, "utf8")}`).join("\n");
    const route = routePrompt(event.prompt, inventory);
    return { ...(route ? { message: { customType: "swarm-route", content: route, display: true } } : {}), systemPrompt: `${event.systemPrompt}\n\n<claude_compat>\n` +
      "Claude resources are available in Pi independent of model provider. Use claude_resources to list/load skills, agents and commands, or /plugin:command for imported commands. " +
      "Run agents with the real subagent tool (isolated Pi process inheriting the current provider/model), not simulated delegation. Claude command inline-shell ! syntax is not pre-executed; use real tools for authorized commands and never invent their output. " +
      "Map Read→read, Bash→bash, Edit→edit, Write→write, Glob→find, Grep→grep, WebFetch→web_fetch, WebSearch→web_search, Task/Agent→subagent. AskUserQuestion means ask the user. " +
      "Load skills with read before following them. Resolve relative files against the original resource directory, not the generated prompt cache. " +
      "Never claim unavailable tools, Claude Desktop connectors, authentication, model vision, hook semantics or sandbox isolation. Tool allowlists are not an OS sandbox. " +
      "MCP is lazy: search via mcp and connect/authenticate as needed. Use claude_lsp for imported language servers. Unsupported and legacy hooks remain catalogued, not silently enabled. " +
      `Active provider/model: ${ctx.model?.provider}/${ctx.model?.id}. Available agents:\n${agents}\n${guidance}\n</claude_compat>` };
  });
  pi.registerTool({
    name: "claude_resources", label: "Claude resources", description: "List imported Claude plugins, skills, agents, commands, hook and LSP readiness; or load original instructions. Output capped at 48 KB, with full results saved privately when larger.",
    parameters: Type.Object({ kind: Type.Optional(StringEnum(["skill", "command", "agent", "plugin", "hook", "mcp", "lsp", "all"] as const)), name: Type.Optional(Type.String()), query: Type.Optional(Type.String()) }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      refresh(ctx);
      if (params.name && ["skill", "command", "agent"].includes(params.kind ?? "")) {
        const resource = inventory.resources.find(r => r.kind === params.kind && r.name === params.name);
        if (!resource) throw new Error(`Unknown ${params.kind}: ${params.name}`);
        return result(resourceBody(resource));
      }
      const catalog: any = publicInventory(inventory);
      catalog.hooks = inventory.hooks.map((h, id) => ({ id, event: h.event, matcher: h.matcher, source: h.source, autoEnabled: enabledHook(h), unsupported: h.unsupported }));
      catalog.mcp = inventory.servers.map(s => ({ name: s.name, source: s.source, state: registrationStatus.get(s.name) ?? "discovered" }));
      let output: any = params.kind && params.kind !== "all" ? ["skill", "command", "agent"].includes(params.kind) ? catalog.resources.filter((r: any) => r.kind === params.kind) : catalog[({ plugin: "plugins", hook: "hooks" } as any)[params.kind] ?? params.kind] : catalog;
      if (params.query && Array.isArray(output)) output = output.filter(r => JSON.stringify(r).toLowerCase().includes(params.query!.toLowerCase()));
      return result(output);
    },
  });
  pi.registerTool({
    name: "subagent", label: "Claude agent", description: "Execute an imported Claude agent in an isolated Pi subprocess using the current model and a subset of the parent's active tools. Requires a trusted project. No nested delegation. 180-second deadline; output capped at 48 KB. Not an OS sandbox.",
    parameters: Type.Object({ agent: Type.String(), task: Type.String() }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      refresh(ctx);
      const resource = inventory.resources.find(r => r.kind === "agent" && r.name === params.agent);
      if (!resource) throw new Error(`Unknown agent ${params.agent}; list agents with claude_resources.`);
      if (!ctx.model) throw new Error("No active model to inherit.");
      const active = pi.getActiveTools();
      if (pi.getAllTools().some(t => active.includes(t.name) && t.sourceInfo.source === "sdk")) throw new Error("SDK-only tool implementations cannot be inherited by a CLI child; use a host-controlled delegation broker.");
      const response = await runAgent(resource, params.task, { cwd: ctx.cwd, model: `${ctx.model.provider}/${ctx.model.id}`, thinking: ctx.thinkingLevel ?? "off", tools: active, trusted: ctx.isProjectTrusted(), signal, parentPrompt: ctx.getSystemPrompt(), runtime: nativeRuntime(process.argv, name => pi.getFlag(name)) });
      return { ...result({ agent: params.agent, model: response.model, turns: response.turns, missingTools: response.missing, output: response.answer }), usage: response.usage, details: { agent: params.agent, model: response.model, turns: response.turns, missingTools: response.missing } };
    },
  });
  pi.registerTool({
    name: "claude_hook", label: "Claude hook", description: "Run a catalogued synchronous command hook explicitly. Legacy/async/prompt hooks are not emulated. Requires UI confirmation unless that exact command is enabled in global claude-compat.json. No credentials are copied.",
    parameters: Type.Object({ id: Type.Integer({ minimum: 0 }), payload: Type.String({ description: "JSON hook payload" }) }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      refresh(ctx);
      const hook = inventory.hooks[params.id]; if (!hook) throw new Error("Unknown hook id; list current hooks first.");
      if (hook.unsupported.length) throw new Error(`Unsupported hook semantics: ${hook.unsupported.join(", ")}`);
      if (!ctx.isProjectTrusted()) throw new Error("Trust the project first.");
      if (!enabledHook(hook) && (!ctx.hasUI || !await ctx.ui.confirm("Run Claude command hook?", `${hook.event}: ${hook.command}`))) throw new Error("Hook execution not approved.");
      const payload = JSON.parse(params.payload);
      const response = await runHook(hook, { ...payload, hook_event_name: hook.event, cwd: ctx.cwd }, ctx.cwd, signal);
      if (response.code !== 0) throw new Error(`Hook failed (${response.code}): ${response.stderr || response.stdout}`);
      return result(response.data ?? response.stdout);
    },
  });
  pi.on("tool_call", async (event, ctx) => {
    const converted = hookPayload(event.toolName, event.input);
    for (const h of inventory.hooks.filter(h => h.event === "PreToolUse" && enabledHook(h) && hookMatches(h, converted.tool_name))) {
      try {
        const r = await runHook(h, { ...converted, hook_event_name: "PreToolUse", cwd: ctx.cwd, session_id: ctx.sessionManager.getSessionId(), permission_mode: "default" }, ctx.cwd, ctx.signal);
        const out = r.data?.hookSpecificOutput;
        if (r.code !== 0 || r.data?.decision === "block" || r.data?.continue === false || out?.permissionDecision === "deny")
          return { block: true, reason: out?.permissionDecisionReason ?? r.data?.reason ?? r.stderr ?? "Claude hook blocked this tool" };
        if (out?.updatedInput) return { block: true, reason: "This hook modifies tool inputs; adapt it to Pi before use." };
        if (out?.permissionDecision === "ask" && (!ctx.hasUI || !await ctx.ui.confirm("Claude hook approval", out.permissionDecisionReason ?? event.toolName))) return { block: true, reason: "Approval required by Claude safety hook." };
      } catch (error) { return { block: true, reason: `Claude safety hook failed closed: ${String(error)}` }; }
    }
  });
  pi.registerTool({
    name: "claude_lsp", label: "Claude LSP", description: "Query an imported language server for hover, definitions, references or document symbols. Requires its executable on PATH. Uses zero-based line/character positions and reads only files inside the trusted current worktree.",
    parameters: Type.Object({ server: Type.String(), file: Type.String(), method: StringEnum(["hover", "definition", "references", "documentSymbol"] as const), line: Type.Optional(Type.Integer({ minimum: 0 })), character: Type.Optional(Type.Integer({ minimum: 0 })) }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      if (!ctx.isProjectTrusted()) throw new Error("Trust the project first."); refresh(ctx);
      const server = inventory.lsp.find(s => s.name === params.server); if (!server) throw new Error("Unknown language server; list LSP resources first.");
      return result(await lspRequest(server, params.file, params.method, params.line ?? 0, params.character ?? 0, ctx.cwd, signal));
    },
  });
  pi.registerTool({
    name: "web_fetch", label: "Fetch web page", description: "Fetch a public HTTP(S) page without browser sign-ins or JavaScript. Returns up to 48 KB of text. For authenticated browser interaction use a configured browser MCP server.",
    parameters: Type.Object({ url: Type.String() }),
    async execute(_id, params, signal) { return result(await fetchText(params.url, signal)); },
  });
  pi.registerTool({
    name: "web_search", label: "Web search", description: "Search public web pages using Bing RSS. Returns source links and snippets, not verified facts. Does not use Claude subscriptions, browser sign-ins or paid search APIs.",
    parameters: Type.Object({ query: Type.String() }),
    async execute(_id, params, signal) {
      const url = new URL("https://www.bing.com/search"); url.searchParams.set("format", "rss"); url.searchParams.set("q", params.query);
      const results = searchResults(await fetchText(url.href, signal));
      if (!results.length) throw new Error("Search returned no RSS results or was blocked; use a configured browser/search MCP server.");
      return result({ source: url.href, results });
    },
  });
  const summary = async (_args: string, ctx: any) => {
    refresh(ctx); const count = (kind: string) => inventory.resources.filter(r => r.kind === kind).length;
    pi.sendMessage({ customType: "claude-compat-report", display: true, content: `${count("skill")} Claude skills, ${count("command")} commands, ${count("agent")} agents, ${inventory.plugins.length} enabled plugins, ${inventory.servers.length} discovered MCP servers, ${inventory.hooks.length} hooks (${inventory.hooks.filter(enabledHook).length} auto-enabled), ${inventory.lsp.length} language servers.\nUse /plugin:command, /skill:name, claude_resources, subagent, claude_lsp and /mcp. Discovery does not prove authentication or runtime readiness.`, details: {} });
  };
  const roster = (ctx: any) => pi.sendMessage({ customType: "swarm-roster", display: true, content: `Pi swarm · ${ctx.model?.provider}/${ctx.model?.id}\n` + inventory.resources.filter(r => r.kind === "agent").map(r => `${r.name}: ${r.description}`).join("\n"), details: {} });
  pi.on("input", (event, ctx) => {
    const match = /^\/swarm(?:\s+(\S+))?(?:\s+([\s\S]+))?$/.exec(event.text.trim());
    if (!match) return;
    refresh(ctx);
    const [, agent, task] = match;
    if (!agent) { roster(ctx); return { action: "handled" as const }; }
    if (!inventory.resources.some(r => r.kind === "agent" && r.name === agent) || !task?.trim()) {
      pi.sendMessage({ customType: "swarm-usage", display: true, content: `Usage: /swarm <known-agent> <task>. Unknown or incomplete agent request: ${agent}`, details: {} });
      return { action: "handled" as const };
    }
    // Transform the original input rather than starting a reentrant agent turn from
    // a slash-command callback. The normal tool pipeline still enforces every gate.
    return { action: "transform" as const, text: `Use the actual subagent tool to delegate this task. Agent: ${JSON.stringify(agent)}. Task: ${JSON.stringify(task)}. Inherit the current Pi model; do not simulate delegation.` };
  });
  pi.registerCommand("swarm-list", { description: "List swarm agents and the selected Pi model", handler: async (_args, ctx) => { refresh(ctx); roster(ctx); } });
  pi.registerCommand("claude-compat", { description: "Show imported Claude resources and compatibility status", handler: summary });
  pi.registerCommand("claude-skills", { description: "Alias for /claude-compat", handler: summary });
}
