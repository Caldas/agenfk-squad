import path from "node:path";
import type { Inventory, Resource } from "./resources.ts";
import { within } from "./resources.ts";

// Pi-only routing. No Claude hook is executed and no source resource is rewritten.
const rules: { pattern: RegExp; role?: string; skill?: string }[] = [
  { pattern: /\b((abra|abre|abrir|cria|crie|criar|open) (o |a )?(pr|pull request)\b|review (this|the) pr|gh pr (create|edit)|revis(a|e|ar) (o |a )?pr\b|(descricao|titulo) d[ao] pr\b)/, role: "github", skill: "pull-request" },
  { pattern: /\b(pitch deck|board briefing|slides|apresentacao)\b/, role: "frontend", skill: "apresentacao" },
  { pattern: /\b(recurso de nuvem|bucket|fila sqs|banco rds|s3 bucket|sqs queue|rds database)\b/, role: "infra", skill: "recurso-de-nuvem" },
  { pattern: /\b(modo enxuto|caveman|menos tokens|cara de ia|reads as ai|revis(a|e|ar) (este|esse|o) texto|compact(a|e|ar) (o |a )?(claude\.md|agents\.md|memoria))\b/, skill: "escrita" },
  { pattern: /\b(diagrama de (arquitetura|nuvem|infraestrutura|infra|rede)|architecture diagram|cloud diagram|drawio|draw\.io)\b/, skill: "diagrama-cloud" },
  { pattern: /\b(terraform|tfstate|iam|vpc|pipeline|ci\/cd|github actions|dockerfile|docker-compose|deploy|infraestrutura)\b/, role: "infra" },
  { pattern: /\b(quanto custa|custo mensal|custo de|cotacao|billing|finops|gasto de tokens|quanto gastamos|onde cortar)\b/, role: "finops" },
  { pattern: /\b(precificacao|preco do plano|margem|economia unitaria|unit economics|break-even|runway|receita|investidor)\b/, role: "financas" },
  { pattern: /\b(concorrente|posicionamento|go-to-market|gtm|pitch|primeiros clientes|cliente ideal|como vender|prospec)/, role: "comercial" },
  { pattern: /\b(quanto falta|proximo bloco|priorizar|prioridade|replanejar|roadmap|decompor|epico|epic|planejar a semana)\b/, role: "produto" },
  { pattern: /\b(revisao independente|verificar a branch|verificador|antes do pr|pode mergear|pronto para merge)\b/, role: "verificador" },
  { pattern: /\b(escrever testes|escreva testes|cobertura|teste de regressao|testes do card|falta teste)\b/, role: "testes" },
  { pattern: /\b(worktree|pilha de pr|stack de pr|mergear|merge|rebase|paralelizar|em paralelo|varias sessoes|quem esta onde|o que esta aberto)\b/, role: "github" },
  { pattern: /\b(handoff|hand-off|contexto cheio|compact|de onde parei|retomar|em loop|loop|burn|releitura|trocar de card|fechar o dia)\b/, role: "contexto" },
  { pattern: /\b(tela|pagina|landing|dashboard|componente|interface|ui|ux|design|figma|dark mode|animacao|motion|poster|banner|logo|icone|arte|canvas|visual)\b/, role: "frontend", skill: "design-referencia" },
];
const specialists: Record<string, string[]> = {
  produto: ["project-manager"], desenvolvimento: ["sv-implementer"],
  verificador: ["sv-verifier"], testes: ["agenfk-tester"],
};
function pickAgent(i: Inventory, role: string): Resource | undefined {
  const candidates = i.resources.filter(r => r.kind === "agent");
  const names = [...(specialists[role] ?? []), role];
  // A project specialist wins over the packaged/global default, never a plugin alias.
  for (const root of [...(i.projectRoots ?? [])].reverse()) {
    const local = names.map(name => candidates.find(r => !r.pluginRoot && within(r.file, path.join(root, ".claude", "agents")) &&
      (r.name === name || path.basename(r.file, ".md") === name))).find(Boolean);
    if (local) return local;
  }
  return candidates.find(r => r.name === role);
}
export function routePrompt(prompt: string, inventory: Inventory): string | undefined {
  if (!prompt.trim() || prompt.trimStart().startsWith("/") || prompt.startsWith("Use the actual subagent tool to delegate this task. Agent:")) return;
  const text = prompt.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const hints: string[] = [];
  for (const rule of rules) {
    if (!rule.pattern.test(text)) continue;
    const agent = rule.role && pickAgent(inventory, rule.role);
    const skills = inventory.resources.filter(r => r.kind === "skill" && path.basename(path.dirname(r.file)) === rule.skill);
    const preferred = [...(inventory.projectRoots ?? [])].reverse().map(root => skills.find(r => within(r.file, path.join(root, ".claude", "skills")))).find(Boolean) ?? skills.at(-1);
    const skill = preferred?.manualOnly ? undefined : preferred;
    if (!agent && !skill) continue;
    const hint = [agent && `agente ${agent.name} (subagent real)`, skill && `skill ${skill.name}: leia ${skill.file}`].filter(Boolean).join("; ");
    if (!hints.includes(hint)) hints.push(hint);
    if (hints.length === 2) break;
  }
  if (!hints.length) return;
  return `[rota do squad · Pi]\n${hints.join("\n")}\nUse o especialista do projeto e passe o card ao agente escritor. Pedido pequeno pode ser feito aqui; revisão independente continua obrigatória. Não simule delegação. Não execute hooks Claude para aplicar esta rota. O modelo é o selecionado no Pi; aliases Claude não são forçados.`;
}
