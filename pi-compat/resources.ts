import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { parseFrontmatter } from "@earendil-works/pi-coding-agent";

export type Resource = { kind: "skill" | "command" | "agent"; name: string; description: string; file: string; pluginRoot?: string; tools?: string[]; deniedTools?: string[]; model?: string; manualOnly?: boolean; unsupported: string[] };
export type Hook = { event: string; matcher: string; command?: string; root?: string; source: string; timeout: number; unsupported: string[] };
export type Server = { name: string; definition: Record<string, unknown>; source: string };
export type Inventory = { projectRoots?: string[]; resources: Resource[]; plugins: { name: string; root?: string }[]; hooks: Hook[]; servers: Server[]; lsp: { name: string; definition: Record<string, unknown>; root: string }[]; guidance: string[]; warnings: string[] };
export const json = (file: string): any => { try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return undefined; } };
export const within = (file: string, root: string) => { const rel = path.relative(path.resolve(root), path.resolve(file)); return rel === "" || (!rel.startsWith(`..${path.sep}`) && rel !== ".." && !path.isAbsolute(rel)); };
export function walk(root: string, suffix: string, seen = new Set<string>()): string[] {
  try {
    const real = fs.realpathSync(root);
    if (seen.has(real)) return [];
    seen.add(real);
    if (fs.statSync(root).isFile()) return root.endsWith(suffix) ? [root] : [];
    return fs.readdirSync(root).sort().flatMap(n => n.startsWith(".") || ["node_modules", "inactive-skills"].includes(n) ? [] : walk(path.join(root, n), suffix, seen));
  } catch { return []; }
}
function lineage(cwd: string): string[] {
  let top = cwd;
  try { top = execFileSync("git", ["rev-parse", "--show-toplevel"], { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim(); } catch { /* Outside Git, only trust cwd. */ }
  const dirs = [cwd];
  while (dirs[0] !== top && within(dirs[0], top)) dirs.unshift(path.dirname(dirs[0]));
  try {
    const common = execFileSync("git", ["rev-parse", "--git-common-dir"], { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    const main = path.dirname(path.resolve(cwd, common));
    if (path.basename(path.resolve(cwd, common)) === ".git" && !dirs.includes(main)) dirs.unshift(main);
  } catch { /* Not a Git repository. */ }
  return dirs;
}
function stringList(value: unknown): string[] | undefined {
  const list = (Array.isArray(value) ? value : typeof value === "string" ? value.split(",") : []).filter((x): x is string => typeof x === "string").map(x => x.trim()).filter(Boolean);
  return list.length ? list : undefined;
}
export function frontmatter(text: string) {
  try { return parseFrontmatter<Record<string, unknown>>(text); }
  catch {
    // Some shared Claude skills contain an unquoted colon in a single-line description.
    // Repair only the in-memory copy; never rewrite the original skill.
    const fixed = text.replace(/^(description:)[ \t]+([^\n]+)$/m, (_match, key, value) => `${key} ${JSON.stringify(value)}`);
    return parseFrontmatter<Record<string, unknown>>(fixed);
  }
}
export function loadResource(kind: Resource["kind"], file: string, namespace = "", pluginRoot?: string, relativeName?: string): Resource | undefined {
  try {
    const { frontmatter: fm } = frontmatter(fs.readFileSync(file, "utf8"));
    const base = typeof fm.name === "string" ? fm.name : kind === "skill" ? path.basename(path.dirname(file)) : relativeName ?? path.basename(file, ".md");
    if (kind === "skill" && (typeof fm.description !== "string" || !fm.description.trim())) return undefined;
    const unsupported = ["hooks", "permissionMode", "isolation", "memory", "background"].filter(k => fm[k] !== undefined);
    return { kind, name: namespace + base, description: typeof fm.description === "string" ? fm.description : `${kind}: ${base}`, file, pluginRoot,
      tools: stringList(fm.tools ?? fm["allowed-tools"]), deniedTools: stringList(fm.disallowedTools), model: typeof fm.model === "string" ? fm.model : undefined, manualOnly: fm["disable-model-invocation"] === true, unsupported };
  } catch { return undefined; }
}
export function discover(cwd: string, trusted: boolean, home = os.homedir(), swarmRoot?: string): Inventory {
  cwd = path.resolve(cwd);
  const result: Inventory = { resources: [], plugins: [], hooks: [], servers: [], lsp: [], guidance: [], warnings: [] };
  const claude = path.join(home, ".claude");
  const dirs = [claude, ...(trusted ? lineage(cwd).map(d => path.join(d, ".claude")) : [])];
  const settingsFiles = dirs.flatMap(d => [path.join(d, "settings.json"), path.join(d, "settings.local.json")]);
  const enabled = new Map<string, boolean>();
  const addHooks = (config: any, source: string, root?: string) => {
    for (const [event, groups] of Object.entries(config?.hooks ?? {})) {
      if (!Array.isArray(groups)) continue;
      for (const group of groups) for (const h of Array.isArray(group.hooks) ? group.hooks : []) {
        const unsupported = ["async", "asyncRewake", "if"].filter(k => h[k] !== undefined);
        if (h.type !== "command") unsupported.push(`type:${h.type}`);
        result.hooks.push({ event, matcher: group.matcher ?? "*", command: h.command, root, source, timeout: Math.max(1, Math.min(180, Number(h.timeout) || 10)), unsupported });
      }
    }
  };
  for (const file of settingsFiles) {
    const settings = json(file);
    for (const [name, value] of Object.entries(settings?.enabledPlugins ?? {})) if (typeof value === "boolean") enabled.set(name, value);
    addHooks(settings, file);
  }
  const addDir = (dir: string, kind: Resource["kind"], namespace = "", root?: string) => {
    for (const file of walk(dir, kind === "skill" ? "SKILL.md" : ".md")) {
      const r = loadResource(kind, file, namespace, root, path.relative(dir, file).replace(/\.md$/, "").split(path.sep).join(":"));
      if (r) result.resources.push(r); else result.warnings.push(`Cannot parse ${kind}: ${file}`);
    }
  };
  const addServers = (config: any, source: string, root?: string, namespace = "") => {
    const raw = config?.mcpServers ?? config;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
    for (const [name, value] of Object.entries(raw)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      let definition = value as Record<string, unknown>;
      if (!definition.command && !definition.url && !definition.socket) continue;
      if (root) definition = JSON.parse(JSON.stringify(definition).replaceAll("${CLAUDE_PLUGIN_ROOT}", root.replaceAll("\\", "\\\\")));
      result.servers.push({ name: namespace + name, definition, source });
    }
  };
  // Lower-precedence plugins first; user/project definitions override by resource name below.
  const installed = json(path.join(claude, "plugins", "installed_plugins.json"))?.plugins ?? {};
  const projectRoots = trusted ? lineage(cwd) : [];
  result.projectRoots = projectRoots;
  for (const [name, on] of enabled) {
    if (!on) continue;
    const applicable = (installed[name] ?? []).filter((e: any) => e.scope === "user" || (trusted && e.projectPath && projectRoots.some(p => within(p, e.projectPath))));
    applicable.sort((a: any, b: any) => (b.scope === "user" ? 0 : 1) - (a.scope === "user" ? 0 : 1) || (b.projectPath?.length ?? 0) - (a.projectPath?.length ?? 0) || String(b.lastUpdated ?? b.installedAt).localeCompare(String(a.lastUpdated ?? a.installedAt)));
    const root = applicable.find((e: any) => e.installPath && fs.existsSync(e.installPath))?.installPath;
    result.plugins.push({ name, root });
    if (!root) { result.warnings.push(`Enabled plugin is not installed: ${name}`); continue; }
    const manifest = json(path.join(root, ".claude-plugin", "plugin.json")) ?? {};
    const namespace = `${name.split("@")[0]}:`;
    for (const kind of ["skill", "command", "agent"] as const) {
      const conventional = kind === "skill" ? ["skills", "workflow-skills"] : [`${kind}s`];
      const custom = manifest[`${kind}s`];
      for (const entry of [...conventional, ...(Array.isArray(custom) ? custom : typeof custom === "string" ? [custom] : [])]) {
        const full = path.resolve(root, entry);
        if (within(full, root)) addDir(full, kind, kind === "skill" ? "" : namespace, root);
      }
    }
    const hooksFile = path.join(root, "hooks", "hooks.json");
    addHooks(json(hooksFile), hooksFile, root);
    if (manifest.hooks && typeof manifest.hooks === "object") addHooks(manifest.hooks, root, root);
    else if (typeof manifest.hooks === "string") {
      const hp = path.resolve(root, manifest.hooks);
      if (within(hp, root) && hp !== hooksFile) addHooks(json(hp), hp, root);
    }
    addServers(json(path.join(root, ".mcp.json")), root, root, `${name.split("@")[0]}__`);
    const lsp = json(path.join(root, ".lsp.json")) ?? manifest.lspServers ?? (name.startsWith("typescript-lsp@") ? { typescript: { command: "typescript-language-server", args: ["--stdio"], extensionToLanguage: { ".ts": "typescript", ".tsx": "typescriptreact", ".js": "javascript", ".jsx": "javascriptreact" } } } : undefined);
    if (lsp && typeof lsp === "object") for (const [server, definition] of Object.entries(lsp)) {
      if (definition && typeof definition === "object") {
        const effective = { ...definition } as Record<string, unknown>;
        const localBin = path.join(process.env.PI_CODING_AGENT_DIR ?? path.join(home, ".pi", "agent"), "claude-compat", "tools", "node_modules", ".bin", String(effective.command));
        if (fs.existsSync(localBin)) {
          effective.command = localBin;
          const compiler = path.join(path.dirname(path.dirname(localBin)), "typescript", "lib", "tsserver.js");
          if (path.basename(localBin) === "typescript-language-server" && fs.existsSync(compiler)) {
            const init = (effective.initializationOptions ?? {}) as Record<string, any>;
            effective.initializationOptions = { ...init, tsserver: { ...init.tsserver, path: init.tsserver?.path ?? compiler } };
          }
        }
        result.lsp.push({ name: `${namespace}${server}`, definition: effective, root });
      }
    }
  }
  for (const dir of dirs) {
    for (const kind of ["skill", "command", "agent"] as const) addDir(path.join(dir, `${kind}s`), kind);
    const guidance = path.join(dir, "CLAUDE.md");
    // Project .claude/CLAUDE.md is not discovered by Pi's native root-file loader.
    // dirs contains project paths only after trust; canonical worktree rules precede local ones.
    if (fs.existsSync(guidance) && !result.guidance.some(f => fs.realpathSync(f) === fs.realpathSync(guidance))) result.guidance.push(guidance);
    if (dir === claude && swarmRoot) {
      const previous = [...result.resources];
      const start = result.resources.length;
      addDir(path.join(swarmRoot, "agents"), "agent");
      addDir(path.join(swarmRoot, "skills"), "skill");
      const standalone = result.resources.slice(start);
      const reserved = new Set(result.resources.map(r => `${r.kind}:${r.name}`));
      for (const prior of previous) {
        const replacement = standalone.find(r => r.kind === prior.kind && r.name === prior.name);
        if (prior.kind === "agent" && replacement && fs.realpathSync(prior.file) !== fs.realpathSync(replacement.file) && within(prior.file, claude)) {
          const base = `user-${prior.name}`;
          let alias = base, suffix = 0;
          while (reserved.has(`agent:${alias}`)) alias = `${base}-${createHash("sha256").update(prior.file).digest("hex").slice(0, 8)}-${++suffix}`;
          prior.name = alias;
          reserved.add(`agent:${alias}`);
        }
      }
      const sourceGuidance = path.join(swarmRoot, "CLAUDE.md");
      if (fs.existsSync(sourceGuidance) && !result.guidance.some(f => fs.realpathSync(f) === fs.realpathSync(sourceGuidance))) result.guidance.unshift(sourceGuidance);
    }
  }
  const host = json(path.join(home, ".claude.json"));
  addServers(host?.mcpServers, path.join(home, ".claude.json"));
  if (trusted) for (const root of projectRoots) {
    addServers(host?.projects?.[root]?.mcpServers, path.join(home, ".claude.json"));
    addServers(json(path.join(root, ".mcp.json")), path.join(root, ".mcp.json"));
  }
  const distinctSources = new Map<string, Resource>();
  for (const r of result.resources) distinctSources.set(`${r.kind}:${fs.realpathSync(r.file)}`, r);
  const counts = new Map<string, number>();
  for (const r of distinctSources.values()) counts.set(`${r.kind}:${r.name}`, (counts.get(`${r.kind}:${r.name}`) ?? 0) + 1);
  const dedup = new Map<string, Resource>();
  for (const r of distinctSources.values()) {
    if (r.kind === "skill") {
      const originalName = r.name;
      const native = path.join(home, ".agents", "skills", originalName, "SKILL.md");
      const nativeCollision = fs.existsSync(native);
      // Equal Markdown can resolve to different scripts/assets. Only the same physical
      // source file proves a mirror without auditing every referenced dependency.
      if (nativeCollision && fs.realpathSync(native) === fs.realpathSync(r.file)) continue;
      if (nativeCollision || (counts.get(`skill:${originalName}`) ?? 0) > 1) {
        const plugin = result.plugins.find(p => p.root === r.pluginRoot)?.name.split("@")[0];
        const prefix = plugin ?? (nativeCollision ? "claude" : swarmRoot && within(r.file, swarmRoot) ? "swarm" : within(r.file, claude) ? "user" : "project");
        r.name = `${prefix}-${originalName}`;
      }
      if (r.name.length > 64 || dedup.has(`skill:${r.name}`)) r.name = `${r.name.slice(0, 51)}-${createHash("sha256").update(r.file).digest("hex").slice(0, 12)}`;
    }
    const prior = dedup.get(`${r.kind}:${r.name}`);
    if (prior) {
      const base = `${prior.name}-${createHash("sha256").update(prior.file).digest("hex").slice(0, 8)}`;
      let alias = base, suffix = 0;
      while (dedup.has(`${prior.kind}:${alias}`)) alias = `${base}-${++suffix}`;
      prior.name = alias;
      dedup.set(`${prior.kind}:${alias}`, prior);
      result.warnings.push(`Resource override: ${r.kind}:${r.name}; previous source retained as ${alias}`);
    }
    dedup.set(`${r.kind}:${r.name}`, r);
  }
  result.resources = [...dedup.values()];
  result.servers = [...new Map(result.servers.map(s => [s.name, s])).values()];
  return result;
}
export function resourceBody(resource: Resource): string {
  const { body } = frontmatter(fs.readFileSync(resource.file, "utf8"));
  return `Source: ${resource.file}\nBase directory: ${path.dirname(resource.file)} (resolve relative references here).\n` +
    (resource.unsupported.length ? `Claude-only metadata not enforced by Pi: ${resource.unsupported.join(", ")}. Do not claim these guarantees.\n` : "") +
    body.replaceAll("${CLAUDE_PLUGIN_ROOT}", resource.pluginRoot ?? path.dirname(resource.file));
}
export function publicInventory(i: Inventory) {
  return { plugins: i.plugins, resources: i.resources.map(({ kind, name, description, file, tools, model, unsupported }) => ({ kind, name, description, file, tools, model, unsupported })),
    hooks: i.hooks.map(({ event, matcher, source, unsupported }) => ({ event, matcher, source, unsupported })),
    mcp: i.servers.map(({ name, source }) => ({ name, source })), lsp: i.lsp.map(({ name, definition }) => ({ name, command: definition.command })), warnings: i.warnings };
}
