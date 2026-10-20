import path from "node:path";
import type { Inventory, Resource } from "./resources.ts";
import { within } from "./resources.ts";

// Pi-only hints. Never execute a Claude hook or rewrite the selected resource.
const rules: { pattern: RegExp; role?: string; skills?: string[] }[] = [
  { pattern: /\b((open|create|review|edit) (a |the |this )?(pr|pull request)\b|gh pr (create|edit)|revis(a|e|ar) (o |a )?pr\b|(abra|abre|abrir|cria|crie|criar) (o |a )?(pr|pull request)\b|(descricao|titulo) d[ao] pr\b)/, role: "github", skills: ["pr-evidence", "pull-request"] },
  { pattern: /\b(pitch deck|board briefing|slides|presentation|apresentacao)\b/, role: "frontend", skills: ["presentation", "apresentacao"] },
  { pattern: /\b(cloud resource|recurso de nuvem|bucket|fila sqs|banco rds|s3 bucket|sqs queue|rds database)\b/, role: "infra", skills: ["cloud-resource", "recurso-de-nuvem"] },
  { pattern: /\b(writing|make it concise|caveman|reads as ai|modo enxuto|menos tokens|cara de ia|revis(a|e|ar) (este|esse|o) texto|compact(a|e|ar) (o |a )?(claude\.md|agents\.md|memoria))\b/, skills: ["writing", "escrita"] },
  { pattern: /\b(diagrama de (arquitetura|nuvem|infraestrutura|infra|rede)|architecture diagram|cloud diagram|drawio|draw\.io)\b/, skills: ["cloud-diagram", "diagrama-cloud"] },
  { pattern: /\b(terraform|tfstate|iam|vpc|pipeline|ci\/cd|github actions|dockerfile|docker-compose|deploy|infrastructure|infraestrutura)\b/, role: "infra" },
  { pattern: /\b(how much does|monthly cost|token cost|cost of|cloud cost|quanto custa|custo mensal|custo de|cotacao|billing|finops|gasto de tokens|quanto gastamos|onde cortar)\b/, role: "finops" },
  { pattern: /\b(pricing|plan price|margin|revenue|investor|precificacao|preco do plano|margem|economia unitaria|unit economics|break-even|runway|receita|investidor)\b/, role: "finance" },
  { pattern: /\b(competitor|positioning|ideal customer|first customers|how to sell|concorrente|posicionamento|go-to-market|gtm|pitch|primeiros clientes|cliente ideal|como vender|prospec)/, role: "gtm" },
  { pattern: /\b(how much is left|next block|prioriti[sz]e|replan|decompose|plan the week|quanto falta|proximo bloco|priorizar|prioridade|replanejar|roadmap|decompor|epico|epic|planejar a semana)\b/, role: "product" },
  { pattern: /\b(independent review|verify the branch|verifier|before the pr|ready to merge|revisao independente|verificar a branch|verificador|antes do pr|pode mergear|pronto para merge)\b/, role: "verifier" },
  { pattern: /\b(write tests|test coverage|regression test|missing tests|escrever testes|escreva testes|cobertura|teste de regressao|testes do card|falta teste)\b/, role: "tester" },
  { pattern: /\b(worktree|pr stack|parallel|multiple sessions|who is where|what is open|pilha de pr|stack de pr|mergear|merge|rebase|paralelizar|em paralelo|varias sessoes|quem esta onde|o que esta aberto)\b/, role: "github" },
  { pattern: /\b(handoff|hand-off|context full|where was i|resume work|switch card|end the day|contexto cheio|compact|de onde parei|retomar|em loop|loop|burn|releitura|trocar de card|fechar o dia)\b/, role: "context" },
  { pattern: /\b(screen|page|component|animation|icon|illustration|tela|pagina|landing|dashboard|componente|interface|ui|ux|design|figma|dark mode|animacao|motion|poster|banner|logo|icone|arte|canvas|visual)\b/, role: "frontend", skills: ["design-reference", "design-referencia"] },
  { pattern: /\b(implement|develop|fix)\b.{0,35}\b(api|backend|logic|feature|bug|endpoint)\b/, role: "developer" },
];
const aliases: Record<string, string[]> = {
  product: ["product", "produto"], developer: ["developer", "desenvolvimento"],
  verifier: ["verifier", "verificador"], tester: ["tester", "testes"],
  finance: ["finance", "financas"], gtm: ["gtm", "comercial"], context: ["context", "contexto"],
};
const specialistTerms: Record<string, string[]> = {
  product: ["project-manager", "product-manager"], developer: ["implementer"],
};
function pickAgent(i: Inventory, role: string): Resource | undefined {
  const candidates = i.resources.filter(r => r.kind === "agent");
  const names = aliases[role] ?? [role], terms = [...names, ...(specialistTerms[role] ?? [])];
  // Match project-defined specialist suffixes, not one private project's names.
  const matches = (r: Resource) => [r.name, path.basename(r.file, ".md")].some(name =>
    terms.some(term => name === term || name.endsWith(`-${term}`)));
  for (const root of [...(i.projectRoots ?? [])].reverse()) {
    const local = candidates.filter(r => !r.pluginRoot && within(r.file, path.join(root, ".claude", "agents")) && matches(r));
    const specialist = local.find(r => !names.includes(r.name) && !names.includes(path.basename(r.file, ".md")));
    if (specialist || local[0]) return specialist ?? local[0];
  }
  return names.map(name => candidates.find(r => r.name === name)).find(Boolean);
}
export function routePrompt(prompt: string, inventory: Inventory): string | undefined {
  if (!prompt.trim() || prompt.trimStart().startsWith("/") || prompt.startsWith("Use the actual subagent tool to delegate this task. Agent:")) return;
  const text = prompt.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const hints: string[] = [];
  for (const rule of rules) {
    if (!rule.pattern.test(text)) continue;
    const agent = rule.role && pickAgent(inventory, rule.role);
    const skills = inventory.resources.filter(r => r.kind === "skill" && rule.skills?.includes(path.basename(path.dirname(r.file))));
    const preferred = [...(inventory.projectRoots ?? [])].reverse().map(root => skills.find(r => within(r.file, path.join(root, ".claude", "skills")))).find(Boolean) ?? skills.at(-1);
    const skill = preferred?.manualOnly ? undefined : preferred;
    if (!agent && !skill) continue;
    const hint = [agent && `agent ${agent.name} (real subagent)`, skill && `skill ${skill.name}: read ${skill.file}`].filter(Boolean).join("; ");
    if (!hints.includes(hint)) hints.push(hint);
    if (hints.length === 2) break;
  }
  if (!hints.length) return;
  return `[squad route · Pi]\n${hints.join("\n")}\nUse the project specialist and pass the card to the writing agent. Small requests can be done here; independent review is still required. Never simulate delegation or execute Claude hooks for this route. Inherit the selected Pi model; do not force Claude aliases.`;
}
