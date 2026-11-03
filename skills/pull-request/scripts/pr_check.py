#!/usr/bin/env python3
"""Check a PR title and body against the pull-request skill's format.

    pr_check.py BODY.md [--title TITLE] [--lang auto|pt|en] [--kind auto|infra|app]
                        [--repo DIR] [--base REF] [--files FILE]

Exits 0 when the body follows the format, 1 when it does not and 2 on a usage
error. Each problem prints as `CODE  message`, so the hook or the person can
fix them one by one. It checks structure; prose quality belongs to a prose
linter, if you run one next to it.

Language (`--lang auto`, the default): the repository's language rule in
CLAUDE.md / AGENTS.md; otherwise the majority of the last 10 PR titles (`gh`);
otherwise that of the last 10 commits; otherwise en. Section names are
accepted in English and Portuguese; the language decides the title rules.

Standard library only. Run it with `python3 -I`.
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# The skill lives in a versioned repo and `python3 -I` ignores PYTHONDONTWRITEBYTECODE: without this,
# loading pr-evidence by path below writes skills/pr-evidence/scripts/__pycache__.
sys.dont_write_bytecode = True

# --- sections ---------------------------------------------------------------

# The hook runs before the owner approves, in a repo that may carry hostile config:
# no fsmonitor, external diff or textconv defined by the repo.
GIT = ("git", "-c", "core.fsmonitor=false")

# (key, en name, pt name), in the order they appear in the body.
SECTIONS = (
    ("before_after", "Before and after", "Antes e depois"),
    ("created", "Resources created", "Recursos criados"),
    ("deleted", "Resources deleted", "Recursos removidos"),
    ("state_flow", "State and flow", "Estado e fluxo"),
    ("functions", "Functions created and deleted", "Funções criadas e removidas"),
    ("cost", "Cost", "Custo"),
    ("risk", "Risk analysis", "Análise de risco"),
    ("practices", "Practices applied", "Práticas aplicadas"),
    ("scans", "Scans", "Varreduras"),
    ("tests", "Tests", "Testes"),
)
SECTION_KEYS = tuple(k for k, _, _ in SECTIONS)
NO_TABLE = {"state_flow", "cost"}
SUBSECTIONS = (("state", "State", "Estado"), ("flow", "Flow", "Fluxo"))
STATE_DIAGRAMS = ("statediagram", "statediagram-v2")
FLOW_DIAGRAMS = ("flowchart", "graph", "sequencediagram")
# Risk analysis rows: code (en) and the accepted forms, without accents.
RISK_TERMS = (
    ("risk of applying", ("risk of applying", "risco de aplicar")),
    ("risk of not applying", ("risk of not applying", "risco de nao aplicar")),
    ("blast radius", ("blast radius", "raio de impacto")),
    ("rollback", ("rollback", "reversao", "como reverter")),
)
# Scans: one row each; "Did not run" + the reason is a valid answer.
SCANNERS = (
    ("lint", r"\blint\b", "Lint"),
    ("semgrep", r"\bsemgrep\b", "Semgrep"),
    ("trivy", r"\btrivy\b", "Trivy"),
    ("secrets", r"\b(?:segredos|secrets|gitleaks)\b", "Secrets (gitleaks)"),
)
# An infrastructure PR carries no adversarial or mutation tests (owner's rule).
FORBIDDEN_INFRA_TESTS = re.compile(
    r"\b(mutation|mutants?|mutmut|stryker|adversarial|adversariais|mutacao|mutacoes|mutantes?)\b", re.I)
NONE_MARK = re.compile(r"^(?:None|Nenhum|Nenhuma)\.")

# --- title -------------------------------------------------------------------

TITLE_MAX = 72
# Three words: the verb and what it acts on. Fewer than that states no goal.
TITLE_MIN_WORDS = 3
GENERIC_TITLES = {
    "update", "updates", "update files", "update code", "update readme", "fixes", "fix",
    "minor fixes", "minor changes", "minor updates", "small changes", "small fixes",
    "changes", "improvements", "wip", "work in progress", "refactor", "refactor code",
    "cleanup", "cleanup code", "code cleanup", "misc", "misc changes", "tweaks",
    "various", "various fixes", "various changes", "several changes", "general cleanup",
    "assorted fixes", "update doc", "update docs", "update documentation",
    # pt, without accents
    "ajuste", "ajustes", "correcao", "correcoes", "melhoria", "melhorias", "atualizacao",
    "atualizacoes", "mudanca", "mudancas", "alteracao", "alteracoes", "refatoracao", "limpeza",
    "diversos", "varios", "atualiza codigo", "atualiza docs", "atualiza documentacao",
    "atualizar codigo", "atualizar documentacao", "corrige bugs", "corrigir bugs",
}
GENERIC_PATTERN = re.compile(
    r"^(?:various|several|multiple|some|minor|small|misc|miscellaneous|general|assorted|few)\b.*"
    r"\b(?:changes?|fixes|updates?|improvements?|tweaks?|cleanups?|refactors?|adjustments?)$"
    r"|^(?:varios|varias|alguns|algumas|pequenos|pequenas|diversos|diversas|outros|outras|mais)\b.*"
    r"\b(?:ajustes?|correcoes|mudancas|melhorias|alteracoes|atualizacoes|refatoracoes)$"
    r"|^(?:ajustes?|correcoes|melhorias|atualizacoes|mudancas|alteracoes)"
    r"(?: (?:gerais|diversos|diversas|pequenos|pequenas|finos|menores))?$", re.I)
# `feat(scope): ...`, `watch: ...`, `[ABC-12] ...` are decoration; the rest is the title.
CONVENTIONAL = re.compile(r"^[a-z][a-z0-9-]*(\([^)]*\))?!?:\s*", re.I)
TICKET = re.compile(r"^(?:\[?[A-Z][A-Z0-9]+-\d+\]?(?=\s|$|:)\s*(?:[+/,-]\s+)?)+:?\s*")
# A card or phase id only goes in as a suffix in parentheses: "(F6-B4)", "(ABC-12)", "(#12)".
TRAILING_ID = re.compile(
    r"\s*\((?:[A-Z][A-Z0-9]*-[A-Z0-9-]*[A-Z0-9]|[A-Z]\d+|#?\d+|[0-9a-f]{8})\)\s*$")
LEADING_ID = re.compile(r"^\[?(?:[A-Z][A-Z0-9]*-[A-Z0-9-]*\d|[0-9a-f]{8})\]?(?=\s|:|$)")
PHASE_CODE = re.compile(r"\b[A-Z]\d+(?:-[A-Z]?\d+)+\b")
LEADING_PHASE = re.compile(r"^\[?[A-Z]\d+(?:-[A-Z]?\d+)+\]?(?=\s|:|$)")
# In English the title opens with an action: the first word is one of these verbs.
IMPERATIVE_VERBS = frozenset("""
    add adopt alert allow annotate apply archive attach audit automate back backfill backport
    activate align answer ask auto-capitalize auto-create bake bind block bootstrap bound bring build bump bundle
    cache calibrate cancel capture carry centre center centralise centralize change chart clamp
    check clarify clean close collapse collect combine commit compact compare compile complete compress
    configure connect consolidate contain consume convert copy correct cover create cut declare decode
    default defer delay delete deliver deny deploy deprecate describe detect disable discard
    distribute document downgrade download drain drop email embed emit empty enable encode enforce ensure
    escape evaluate exclude expand export expose extend extract fail fan fetch filter finish fix flag
    flatten flip fold force format forward free gate gather generate give gitignore grant group guard
    handle harden hide hoist hold ignore import improve include index inline install instrument
    integrate introduce invert isolate keep kill label land let lift limit link lint load lock
    log loosen lower make manage map mark match measure merge migrate minimise minimize mirror mock
    modernise modernize modify move name namespace normalise normalize notify observe offer offset
    onboard open optimise optimize order organise organize override package page parallelise
    parallelize parse partition patch pin pipe place plan plug point populate port post prepare preserve
    prevent print promote protect provision prune publish pull purge push put queue quote raise
    rate-limit read rebuild record redirect reduce refactor reformat refresh regenerate register
    reinstall reject relax release reload remove rename render reorder reorganise reorganize repeat
    replace repair report reposition require reschedule reset resize resolve respect restart restore
    restrict resume retain retire retry return reuse reveal revert revoke rewrite rotate route run
    sanitise sanitize save say scale scan schedule scope secure seed send separate serialise
    serialize serve set settle setup share shield ship shorten show shrink shut silence simplify
    skip smooth sort source speed spin split stage stamp standardise standardize start stop store stream
    strip structure submit suffix suggest summarise summarize supply support surface suspend swap
    switch sync synchronise synchronize tag take teach hand template terminate test throttle tidy tighten
    toggle track transfer translate trim truncate trust try tune turn type unblock uncomment
    undefine unify uninstall unpin unset untangle unwrap update upgrade upload use validate vendor
    verify version wait warn watch wire wrap write yield
""".split())
# In Portuguese the title is a sentence with a verb in any position:
# "Move a exportacao para um job" or "O aviso passou a aparecer uma vez so".
PT_INFINITIVES = """
    abrir aceitar acelerar adicionar agendar agrupar ajustar alterar ampliar apagar aparecer aplicar
    arquivar atualizar autorizar avisar baixar bloquear buscar calcular cancelar capturar carregar
    centralizar checar cobrar coletar combinar comparar compartilhar completar comprimir conectar
    configurar consolidar converter copiar corrigir cortar criar declarar definir deixar desativar
    descartar descrever desligar detectar dividir documentar eliminar emitir encerrar encurtar
    entregar enviar escapar esconder esperar estender evitar excluir executar exibir exigir expandir
    exportar expor extrair falhar fechar ficar filtrar finalizar formatar fundir garantir gerar
    gravar guardar habilitar ignorar impedir implementar importar incluir indexar informar inserir
    instalar integrar isolar juntar levar liberar ligar limitar limpar listar manter marcar medir
    migrar montar mostrar mover mudar negar normalizar notificar obrigar ocultar ordenar organizar
    otimizar padronizar parar passar pausar permitir preencher preservar prevenir processar
    promover propagar proteger publicar purgar receber recusar reduzir refatorar reforcar
    registrar reiniciar rejeitar remover renomear reordenar reorganizar repetir resolver responder
    restaurar restringir retirar retornar reutilizar reverter revogar rodar salvar separar
    simplificar sincronizar subir substituir suportar tornar tratar trocar unificar unir usar
    validar verificar vincular voltar ganhar perder aceitar acompanhar apontar chamar contar
    entrar mandar pedir seguir sumir surgir travar
""".split()
PT_IRREGULAR = frozenset("""
    é são está estão foi foram era eram fica ficam faz fazem fez fizeram fazer tem têm teve tiveram
    ter vem vêm veio vieram vir vai vão ir dá dão deu deram dar põe põem pôs puseram pôr traz trazem
    trouxe trazer lê leem leu ler sai saem saiu sair cai caem caiu cair diz dizem disse dizer pode
    podem pôde quer querem precisa precisam há houve continua continuam volta voltam
""".split())
# Generated forms that are almost always another part of speech.
PT_NOT_VERB = frozenset({"para", "pela", "pelo", "conta", "contas"})
PT_WORDS = frozenset("""
    para com sem nao uma um ao aos das dos pela pelo pelas pelos nas nos que como mas ate desde
    entre sobre contra quando onde qual quais isso isto este esta esse essa aquele aquela
    adicionar adiciona adicione ajustar ajusta ajuste corrigir corrige corrigido remover remova
    remocao mover atualizar atualiza atualizacao melhorar melhora melhore permitir permite
    impedir impede garantir garante evitar evita usar usa suportar suporta configurar configura
    configuracao habilitar habilita desabilitar desabilita implementar implementa recurso recursos
    aplicacao servico servicos contas conta ambiente producao versao chave dados usuario usuaria
    usuarios empresa fila tabela rede seguranca permissao permissoes acesso politica papel criar
    cria criacao adotar adota consolidar consolida migrar migra excluir exclui substituir
    substitui renomear renomeia dividir divide juntar junta tornar torna manter mantem suporte
    painel tela botao campo valor valores erro erros fluxo pedido pedidos cliente clientes lista
    listas regra regras mensagem mensagens pagina paginas
""".split())
# Function words only one of the two languages uses (to classify history).
PT_ONLY = PT_WORDS | frozenset("de da das do dos em na e o os um uma passou ja mais".split()) - {"do"}
EN_ONLY = frozenset("""
    the to for of and with from into by when instead without after before only not is are this
    that in on its it be an
""".split())
PT_LETTERS = re.compile(r"[ãõçáàâéêíóôú]", re.I)
BRANCH_PREFIX = re.compile(r"^(?:feat|fix|chore|docs|ci|test|tests|refactor|build|perf|style|revert|release|feature|bugfix|hotfix)/", re.I)
GLUED_TICKET = re.compile(r"^[A-Z][A-Z0-9]+-\d+[-_/][a-z]")
SINGLE_REF = re.compile(r"^[a-z0-9]+(?:[-_/][a-z0-9]+){2,}$", re.I)
CODE_ADDRESS = re.compile(r"\b(?:aws|azurerm|google|oci|random|local|data|module|var|each|count)\.[a-z0-9_]+", re.I)
SNAKE_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", re.I)
# The step letter is upper case and stands apart: "Part A" counts, "passou a" and "passo a passo" do not.
STEP_LABEL = re.compile(
    r"\b(?i:phase|part|step|wave|workstream|milestone|fase|etapa|passo|onda|parte|marco|frente|sprint)"
    r"(?:\s*[-:#]?\s*\d+\b|(?:\s+|\s*[-:#]\s*)[A-Z]\b)|\bW\d+\b")
TRUNCATED = {
    "en": re.compile(r"(?:…|\.\.\.)\s*$|\b(?:and|or|the|a|an|of|to|for|with|from|by)\s*$", re.I),
    "pt": re.compile(r"(?:…|\.\.\.)\s*$|\b(?:e|ou|de|do|da|dos|das|para|com|sem|o|a|os|as|um|uma|que|em"
                     r"|no|na|pelo|pela|ao)\s*$", re.I),
}

# --- opening, placeholders, kind --------------------------------------------

OPENING_MIN_WORDS = 12
OPENING_MAX_WORDS = 120
BOILERPLATE = re.compile(
    r"^(this (pr|pull request|change|merge request)|in this (pr|pull request)"
    r"|est[ea] (pr|pull request|mudanca|merge request)|nest[ea] (pr|pull request))\b", re.I)
# CDK and SAM code is plain TypeScript or YAML: only the marker files count.
IAC_FILE = re.compile(
    r"(\.tf|\.tfvars|\.tf\.json|\.hcl|\.bicep)$"
    r"|(^|/)(Chart\.ya?ml|kustomization\.ya?ml|Pulumi\.ya?ml|cdk\.json|samconfig\.toml|serverless\.ya?ml)$"
    r"|(^|/)charts/[^/]+/(values[^/]*\.ya?ml|templates/)")
IAC_WORDS = re.compile(r"\b(terraform|opentofu|tofu|terragrunt|tflint|checkov|helm|cloudformation)\b", re.I)
SAFE_REF = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*")
DEFAULT_BASES = ("origin/HEAD", "origin/main", "main", "origin/master", "master")
TEMPLATES = (Path(__file__).resolve().parent.parent / "templates" / "body.md",)
# Placeholder: a token the template itself uses, or a lower-case phrase between
# angle brackets: `<what changes>`. Comparisons, autolinks, e-mail, generics
# such as Promise<void> and HTML tags do not match.
PLACEHOLDER_PHRASE = re.compile(
    r"(?<![\w])<(?!/?(?:details|summary|div|span|img|a|p|br|table|tr|td|th|sub|sup|kbd|code|pre)\b)"
    r"[a-zà-ÿ][a-zà-ÿ0-9.,'-]*(?: [a-zà-ÿ0-9.,'()-]+)+>")
MERMAID = re.compile(r"```mermaid\s*\n(.*?)```", re.S)
ANGLE = re.compile(r"<[^<>\n]+>")

# --- repository language ------------------------------------------------------

POLICY_FILES = ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md")
POLICY_TOPIC = re.compile(r"\b(prs?|pull requests?|titulos?|titles?|commits?|corpo|body|bodies)\b")
POLICY_LANG = re.compile(r"\b(english|ingles|en-us|portuguese|portugues|pt-br|pt_br)\b")
HISTORY = 10
GH_TIMEOUT = 8


@dataclass(frozen=True)
class Problem:
    code: str
    message: str

    def __str__(self):
        return f"{self.code}  {self.message}"


def fold(text):
    """Lower case without accents: the form in which words and names are compared."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _section_name(key, lang):
    for k, en, pt in SECTIONS + SUBSECTIONS:
        if k == key:
            return pt if lang == "pt" else en
    return key


ALIASES = {fold(name): key for key, en, pt in SECTIONS for name in (en, pt)}
SUB_ALIASES = {fold(name): key for key, en, pt in SUBSECTIONS for name in (en, pt)}

# --- markdown -----------------------------------------------------------------


def _plain_lines(text):
    """Text lines with fenced blocks blanked: a heading inside an example does not count."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return out


def _strip_fences(text):
    return "\n".join(_plain_lines(text))


def headings(text, level=2):
    marker = "#" * level + " "
    return [line[len(marker):].strip() for line in _plain_lines(text) if line.startswith(marker)]


def _norm(heading):
    return fold(heading.strip().rstrip(":"))


def sections(text, level=2):
    """Normalised heading -> raw content (with blocks), up to the next heading of the same level."""
    marker = "#" * level + " "
    plain = _plain_lines(text)
    raw = text.splitlines()
    found, current, buf = {}, None, []
    for plain_line, raw_line in zip(plain, raw):
        if plain_line.startswith(marker) or (level == 3 and plain_line.startswith("## ")):
            if current is not None:
                found.setdefault(current, "\n".join(buf).strip())
            current = _norm(plain_line[len(marker):]) if plain_line.startswith(marker) else None
            buf = []
        elif current is not None:
            buf.append(raw_line)
    if current is not None:
        found.setdefault(current, "\n".join(buf).strip())
    return found


def _keyed(found, aliases):
    """Content by canonical key, accepting the en or pt name of the section."""
    out = {}
    for name, content in found.items():
        key = aliases.get(name)
        if key is not None:
            out.setdefault(key, content)
    return out


def _is_none(content):
    return bool(NONE_MARK.match(content.strip()))


def _tables(content):
    """Header row of each markdown table in the content, cells lower case without accents."""
    lines = content.splitlines()
    out = []
    for i in range(len(lines) - 1):
        if lines[i].strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            out.append([fold(c.strip()) for c in lines[i].strip().strip("|").split("|")])
    return out


def _mermaid_kinds(content):
    kinds = []
    for block in MERMAID.findall(content):
        first = next((l.strip() for l in block.splitlines() if l.strip()), "")
        kinds.append(first.split()[0].lower() if first else "")
    return kinds

# --- title -------------------------------------------------------------------


def _pt_forms(infinitive):
    inf = fold(infinitive)
    stem, end = inf[:-2], inf[-2:]
    if end == "ar":
        return {inf, stem + "a", stem + "am", stem + "ou", stem + "aram", stem + "ara", stem + "arao"}
    if end == "er":
        return {inf, stem + "e", stem + "em", stem + "eu", stem + "eram", stem + "era", stem + "erao"}
    return {inf, stem + "e", stem + "em", stem + "iu", stem + "iram", stem + "ira", stem + "irao"}


PT_VERB_FORMS = frozenset().union(*(_pt_forms(v) for v in PT_INFINITIVES)) - PT_NOT_VERB


def _is_pt_verb(word):
    low = word.lower()
    if low in PT_IRREGULAR:
        return True
    plain = fold(word)
    if not plain.isalpha() or plain in PT_NOT_VERB:
        return False
    # regular preterite (passou, deixou, ficou) outside the list
    return plain in PT_VERB_FORMS or (len(plain) >= 5 and plain.endswith("ou"))


def _en_activity_base(word):
    """The imperative verb an English gerund at the start comes from, or None."""
    if word.endswith("ing") and len(word) > 4 and word.isalpha():
        stem = word[:-3]
        for candidate in (stem, stem[:-1], stem + "e"):
            if candidate in IMPERATIVE_VERBS:
                return candidate
    return None


def _pt_activity_base(word):
    """The present-tense verb for a Portuguese gerund at the start, or None."""
    plain = fold(word)
    if len(plain) > 5 and plain.isalpha():
        for gerund, present in (("ando", "a"), ("endo", "e"), ("indo", "e")):
            if plain.endswith(gerund):
                return word[:-len(gerund)] + present
    return None


def _is_portuguese(core):
    """Two Portuguese signals: known words (without accents), and one for an accent."""
    signals = 1 if PT_LETTERS.search(core) else 0
    for word in re.findall(r"[^\W\d_]+", core):
        if fold(word) in PT_WORDS:
            signals += 1
            if signals >= 2:
                return True
    return signals >= 2


def _scores(core):
    """(pt signals, en signals) of a title."""
    words = re.findall(r"[a-z]+", fold(core))
    pt = (1 if PT_LETTERS.search(core) else 0) + sum(w in PT_ONLY for w in words)
    en = sum(w in EN_ONLY for w in words) + (1 if words and words[0] in IMPERATIVE_VERBS else 0)
    return pt, en


def _branch_shape(title, core):
    if BRANCH_PREFIX.match(title):
        return "a branch prefix"
    if GLUED_TICKET.match(core):
        return "a ticket id glued to a slug"
    if SINGLE_REF.match(core):
        return "a single hyphenated token"
    return None


def _strip_prefixes(title, tickets=True):
    """Strip conventional prefixes (and ticket ones, in en) as many times as needed."""
    core = TRAILING_ID.sub("", title).strip().rstrip(".")
    for _ in range(4):
        stripped = CONVENTIONAL.sub("", core)
        if tickets:
            stripped = TICKET.sub("", stripped)
        stripped = stripped.strip()
        if stripped == core:
            break
        core = stripped
    return core


def check_title(title, lang="en"):
    t = (title or "").strip()
    if not t:
        return [Problem("TITLE_EMPTY", "The PR has no title.")]
    problems = []
    if len(t) > TITLE_MAX:
        problems.append(Problem("TITLE_LONG", f"{len(t)} characters; the limit is {TITLE_MAX}."))
    if LEADING_PHASE.match(t):
        problems.append(Problem("TITLE_STEP_LABEL",
                                f'"{t}" opens with a phase code. State the outcome; the phase goes in as a '
                                'suffix in parentheses, "(F6-B4)", or in the body.'))
        t_rest = LEADING_PHASE.sub("", t).lstrip(" :]-")
    elif lang == "pt" and LEADING_ID.match(t):
        problems.append(Problem("TITLE_ID_PREFIX",
                                f'"{t}" opens with the card id. In pt the id only goes in as a suffix in '
                                'parentheses: "Move a exportacao para um job em segundo plano (ABC-12)".'))
        t_rest = LEADING_ID.sub("", t).lstrip(" :]-")
    else:
        t_rest = t
    core = _strip_prefixes(t_rest, tickets=(lang == "en"))
    if not core:
        return problems + [Problem("TITLE_TICKET_ONLY", "A ticket id is not a goal. Say what the PR does.")]

    pt_signals, en_signals = _scores(core)
    if lang == "en" and _is_portuguese(core):
        problems.append(Problem("TITLE_NOT_ENGLISH",
                                f'The title is not in English: "{t}". This repository titles PRs in '
                                'English: "Move dealer exports to a background job".'))
    elif lang == "pt" and pt_signals == 0 and en_signals >= 2:
        problems.append(Problem("TITLE_NOT_PORTUGUESE",
                                f'The title is in English: "{t}". This repository titles PRs in '
                                'Portuguese: "Move a exportacao para um job em segundo plano".'))
    shape = _branch_shape(t, core)
    if shape:
        problems.append(Problem("TITLE_BRANCH_NAME",
                                f'"{t}" looks like a branch or card name ({shape}). Write a sentence '
                                'that states the outcome.'))
    if CODE_ADDRESS.search(core) or SNAKE_IDENTIFIER.search(core):
        problems.append(Problem("TITLE_CODE_IDENTIFIER",
                                f'"{t}" quotes a code or Terraform identifier. Name the thing '
                                'in words, not its address: "a bucket for the exports".'))
    step = STEP_LABEL.search(core) or PHASE_CODE.search(core)
    if step:
        problems.append(Problem("TITLE_STEP_LABEL",
                                f'"{step.group(0)}" is planning vocabulary. Say what the PR does; the phase '
                                'goes in the body or as a suffix in parentheses.'))
    if TRUNCATED[lang].search(core):
        problems.append(Problem("TITLE_TRUNCATED", f'"{t}" ends mid-sentence. Finish the sentence.'))

    plain = fold(core)
    if plain in GENERIC_TITLES or GENERIC_PATTERN.match(plain):
        example = ('"Move a exportacao para um job em segundo plano"' if lang == "pt"
                   else '"Move dealer exports to a background job"')
        problems.append(Problem("TITLE_GENERIC", f'"{core}" does not say what the PR does. Example: {example}.'))
        return problems
    words = core.split()
    if len(words) < TITLE_MIN_WORDS:
        problems.append(Problem("TITLE_SHORT",
                                f'"{core}" is too short to state the goal; say what, and for whom.'))
    first = words[0].strip('"\'(),;:!?')
    if lang == "en":
        base = _en_activity_base(first.lower())
        if base:
            problems.append(Problem("TITLE_ACTIVITY",
                                    f'"{words[0]}" narrates the work. Write the outcome: '
                                    f'"{base.capitalize()} ...", not "{words[0]} ...".'))
        elif first.lower() not in IMPERATIVE_VERBS:
            problems.append(Problem("TITLE_NO_VERB",
                                    f'"{words[0]}" is a thing, not an action. Open with a verb: '
                                    '"Add ... for ...", "Move ... to ...".'))
    else:
        base = _pt_activity_base(first)
        if base:
            problems.append(Problem("TITLE_ACTIVITY",
                                    f'"{words[0]}" narrates the work. Write the outcome: '
                                    f'"{base.capitalize()} ...", not "{words[0]} ...".'))
        elif not any(_is_pt_verb(w.strip('"\'(),;:!?.')) for w in words):
            problems.append(Problem("TITLE_NO_VERB",
                                    f'"{core}" has no verb. Write a sentence that states the outcome: '
                                    '"Move a exportacao para ...", "O aviso passou a aparecer ...".'))
    return problems

# --- body ---------------------------------------------------------------------


def _check_opening(text):
    before = _strip_fences(text).split("\n## ", 1)[0]
    if text.lstrip().startswith("## "):
        before = ""
    para = next((p.strip() for p in re.split(r"\n\s*\n", before)
                 if p.strip() and not p.strip().startswith(("#", "<!--", ">"))), "")
    if not para:
        return [Problem("OPENING_MISSING", "Open with a plain-language paragraph: the problem and the change.")]
    problems = []
    words = len(para.split())
    if BOILERPLATE.match(fold(para)):
        problems.append(Problem("OPENING_BOILERPLATE", 'Do not open with "This PR ..." / "Este PR ..."; state the problem and the change.'))
    if words < OPENING_MIN_WORDS:
        problems.append(Problem("OPENING_SHORT", f"The opening has {words} words; explain the problem and the change."))
    elif words > OPENING_MAX_WORDS:
        problems.append(Problem("OPENING_LONG", f"The opening has {words} words; the limit is {OPENING_MAX_WORDS}."))
    return problems


def _check_diagrams(content, lang):
    if _is_none(content):
        return []
    problems = []
    subs = _keyed(sections(content, level=3), SUB_ALIASES)
    for key, allowed in (("state", STATE_DIAGRAMS), ("flow", FLOW_DIAGRAMS)):
        name = _section_name(key, lang)
        code = "State" if key == "state" else "Flow"
        sub = subs.get(key)
        if sub is None or not sub.strip():
            problems.append(Problem(f"DIAGRAM_MISSING:{code}",
                                    f"Include `### {name}` with a mermaid diagram, or `None.` and the reason."))
            continue
        if _is_none(sub):
            continue
        kinds = _mermaid_kinds(sub)
        if not kinds:
            problems.append(Problem(f"DIAGRAM_MISSING:{code}", f"`### {name}` has no mermaid block."))
        elif not any(k in allowed for k in kinds):
            problems.append(Problem(f"DIAGRAM_KIND:{code}",
                                    f"`### {name}` needs {' or '.join(allowed)}; found {', '.join(kinds)}."))
    return problems


def _without_comments(text):
    return re.sub(r"<!--.*?-->", "", "\n".join(_plain_lines(text)), flags=re.S)


def _read_templates():
    out = []
    for path in TEMPLATES:
        try:
            out.append(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    return out


def template_placeholders():
    return {m.group(0) for t in _read_templates() for m in ANGLE.finditer(_without_comments(t))}


def template_diagram_placeholders():
    return {m.group(0) for t in _read_templates() for block in MERMAID.findall(t)
            for m in ANGLE.finditer(block)}


def _check_placeholders(text):
    known = template_placeholders()
    plain = _without_comments(text)
    spans = re.findall(r"`([^`\n]*)`", plain)
    prose = re.sub(r"`[^`\n]*`", "", plain)
    left = {m.group(0) for m in PLACEHOLDER_PHRASE.finditer(prose)}
    left |= {m.group(0) for m in ANGLE.finditer(prose) if m.group(0) in known}
    left |= {s for s in spans if s in known}
    diagram_tokens = template_diagram_placeholders()
    left |= {m.group(0) for block in MERMAID.findall(text) for m in ANGLE.finditer(block)
             if m.group(0) in diagram_tokens}
    left = sorted(left)
    if not left:
        return []
    shown = ", ".join(left[:5]) + (" ..." if len(left) > 5 else "")
    return [Problem("PLACEHOLDER", f"Template placeholders left in the body: {shown}")]


def check_body(text, kind="app", lang="en"):
    problems = _check_opening(text) + _check_placeholders(text)
    found = _keyed(sections(text), ALIASES)
    order = [ALIASES[h] for h in map(_norm, headings(text)) if h in ALIASES]
    expected = [k for k in SECTION_KEYS if k in order]
    if order != expected:
        problems.append(Problem("SECTION_ORDER", "Sections follow this order: "
                                + ", ".join(_section_name(k, lang) for k in SECTION_KEYS) + "."))

    for key in SECTION_KEYS:
        name = _section_name(key, lang)
        code = _section_name(key, "en")
        content = found.get(key)
        if content is None:
            problems.append(Problem(f"SECTION_MISSING:{code}",
                                    f"Include `## {name}`; when it does not apply, write `None.` and the reason."))
            continue
        if not content:
            problems.append(Problem(f"SECTION_EMPTY:{code}",
                                    f"`## {name}` is empty; fill it in or write `None.` and the reason."))
            continue
        if key == "state_flow":
            problems += _check_diagrams(content, lang)
            continue
        lower = fold(content)
        if key == "cost":
            amount = re.search(r"\$\s?\d|\d\s?(usd|brl|/month|/mes)", lower) or (
                re.search(r"\$/(month|mes)|usd", lower) and re.search(r"\d+[.,]\d{2}", lower))
            if kind == "infra" and not amount:
                problems.append(Problem("COST_AMOUNT_MISSING",
                                        "An infrastructure PR states the monthly cost in dollars, even when it is US$ 0.00."))
            continue
        if _is_none(content):
            continue
        tables = _tables(content)
        if key not in NO_TABLE and not tables:
            problems.append(Problem(f"TABLE_MISSING:{code}", f"`## {name}` needs a table, or `None.` and the reason."))
            continue
        if key == "before_after" and not any(
                ("before" in t and "after" in t) or ("antes" in t and "depois" in t) for t in tables):
            problems.append(Problem("BEFORE_AFTER_COLUMNS", "The before-and-after table needs `Before` and `After` columns."))
        elif key == "risk":
            for term, forms in RISK_TERMS:
                if not any(f in lower for f in forms):
                    problems.append(Problem(f"RISK_MISSING:{term}",
                                            f"The risk analysis has no `{forms[0].capitalize()}` / `{forms[1].capitalize()}` row."))
        elif key == "practices" and not any("source" in t or "fonte" in t for t in tables):
            problems.append(Problem("PRACTICE_SOURCE_MISSING",
                                    "Each practice cites its source (document, standard or skill) in a `Source` column."))
        elif key == "scans":
            for tool, pattern, label in SCANNERS:
                if not re.search(pattern, lower):
                    problems.append(Problem(f"SCAN_MISSING:{tool}",
                                            f"Include the `{label}` row: the result, or `Did not run` and the reason."))
        elif key == "tests" and kind == "infra" and FORBIDDEN_INFRA_TESTS.search(lower):
            problems.append(Problem("TESTS_FORBIDDEN",
                                    "An infrastructure PR carries no mutation or adversarial tests; remove them."))
    return problems

# --- kind and language --------------------------------------------------------


def detect_kind(text, changed_files):
    if changed_files:
        return "infra" if any(IAC_FILE.search(f) for f in changed_files) else "app"
    return "infra" if IAC_WORDS.search(text or "") else "app"


def base_refs(base=None):
    """Candidate bases. A base git could read as an option is dropped."""
    given = [f"origin/{base}", base] if base and SAFE_REF.fullmatch(base) else []
    return given + list(DEFAULT_BASES)


def changed_files(repo, base=None):
    """Files the branch changes against the base; empty when git cannot tell."""
    for ref in base_refs(base):
        try:
            out = subprocess.run([*GIT, "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv", "--name-only", f"{ref}...HEAD"],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return []
        if out.returncode == 0:
            return [l for l in out.stdout.splitlines() if l.strip()]
    return []


def repo_root(path):
    """Root of the git repository containing path, or None."""
    try:
        out = subprocess.run([*GIT, "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def policy_lang(text):
    """Language a CLAUDE.md / AGENTS.md asks for PRs and commits, or None."""
    for line in text.splitlines():
        plain = fold(line)
        topic = POLICY_TOPIC.search(plain)
        if not topic:
            continue
        langs = [(m.start(), "en" if m.group(1) in ("english", "ingles", "en-us") else "pt")
                 for m in POLICY_LANG.finditer(plain)]
        if not langs:
            continue
        after = [l for pos, l in langs if pos > topic.start()]
        return after[0] if after else langs[-1][1]
    return None


def history_lang(titles):
    """Language of most titles, or None on a tie or when it cannot tell."""
    pt = en = 0
    for title in titles:
        p, e = _scores(_strip_prefixes(title))
        if p > e:
            pt += 1
        elif e > p:
            en += 1
    if pt > en:
        return "pt"
    if en > pt:
        return "en"
    return None


def _gh_titles(root):
    gh = shutil.which("gh")
    if not gh:
        return []
    try:
        out = subprocess.run([gh, "pr", "list", "--state", "all", "--limit", str(HISTORY),
                              "--json", "title", "--jq", ".[].title"],
                             cwd=root, capture_output=True, text=True, timeout=GH_TIMEOUT,
                             env={**os.environ, "GH_PROMPT_DISABLED": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l for l in out.stdout.splitlines() if l.strip()] if out.returncode == 0 else []


def _commit_titles(root):
    try:
        out = subprocess.run([*GIT, "-C", root, "log", f"-{HISTORY}", "--no-merges", "--format=%s"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l for l in out.stdout.splitlines() if l.strip()] if out.returncode == 0 else []


def detect_lang(repo):
    """(language, where it came from) for the repository at repo."""
    root = repo_root(repo) if repo else None
    if root:
        for name in POLICY_FILES:
            try:
                text = (Path(root) / name).read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                continue
            lang = policy_lang(text)
            if lang:
                return lang, name
        lang = history_lang(_gh_titles(root))
        if lang:
            return lang, "PR titles"
        lang = history_lang(_commit_titles(root))
        if lang:
            return lang, "commits"
    return "en", "default"


def resolve_lang(lang, repo):
    if lang in ("pt", "en"):
        return lang, "--lang"
    return detect_lang(repo)


def repository_template_problems(text, repo):
    """The repo template adds sections; never run config or code from the target repo."""
    root = repo_root(repo) if repo else None
    if root is None:
        return []
    root = Path(root).resolve()
    for name in (".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md",
                 "pull_request_template.md", "PULL_REQUEST_TEMPLATE.md",
                 "docs/pull_request_template.md", "docs/PULL_REQUEST_TEMPLATE.md"):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > 131072:
                raise ValueError("template outside the repo, not a regular file or larger than 128 KiB")
            template = path.read_text(encoding="utf-8")
            helper = Path(__file__).resolve().parents[2] / "pr-evidence/scripts/pr_evidence.py"
            if not helper.is_file():
                return [Problem("TEMPLATE_CHECKER_MISSING",
                                "Install pr-evidence next to pull-request to check the repository template.")]
            spec = importlib.util.spec_from_file_location("squad_pr_evidence", helper)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return [Problem(code, message.strip()) for code, message in
                    (p.split(":", 1) for p in module.template_problems(template, text))]
        except (OSError, UnicodeError, ValueError, ImportError, RuntimeError, SyntaxError) as exc:
            return [Problem("TEMPLATE_UNREADABLE", f"Could not check {name}: {exc}")]
    return []


def check(text, title=None, kind="auto", repo=None, base=None, files=None, lang="auto"):
    """(problems, kind, language, language source)."""
    if kind == "auto":
        if files is None:
            files = changed_files(repo, base) if repo else []
        kind = detect_kind(text, files)
    lang, source = resolve_lang(lang, repo)
    problems = check_title(title, lang) if title is not None else []
    return problems + check_body(text, kind, lang) + repository_template_problems(text, repo), kind, lang, source


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a PR title and body against the pull-request skill format.")
    ap.add_argument("body", help="markdown with the PR body, or - for stdin")
    ap.add_argument("--title")
    ap.add_argument("--lang", choices=("auto", "pt", "en"), default="auto",
                    help="title language; auto reads CLAUDE.md, PR titles, commits, otherwise en")
    ap.add_argument("--kind", choices=("auto", "infra", "app"), default="auto")
    ap.add_argument("--repo", default=".", help="repository used for the kind and the language")
    ap.add_argument("--base", help="base branch; default origin/HEAD, then main")
    ap.add_argument("--files", help="file with the paths the PR changes, one per line (- for stdin); "
                    "decides the kind instead of the local git diff")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.body == "-" else Path(args.body).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"could not read {args.body}: {e}", file=sys.stderr)
        return 2
    files = None
    if args.files:
        raw = sys.stdin.read() if args.files == "-" else Path(args.files).read_text(encoding="utf-8")
        files = [line.strip() for line in raw.splitlines() if line.strip()]
    problems, kind, lang, source = check(text, args.title, args.kind, args.repo, args.base, files, args.lang)
    for p in problems:
        print(p)
    tail = f"{kind} PR, language {lang} ({source})."
    print(f"{len(problems)} problem(s), {tail}" if problems else f"OK, {tail}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
