#!/usr/bin/env python3
"""The PR gate catches bad titles and bodies, in pt and en, and lets good ones through.

Self-checking: the exit code is the verdict. Throwaway git repositories, a
throwaway HOME and a fake `gh` at the front of PATH: nothing goes out to the
network and nothing touches ~/.claude. It does not depend on the `writing` skill.

    python3 tests/test_pull_request.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # the skill lives in a versioned repo: no __pycache__
# The children below run `python -I -B` so a regression cannot litter this checkout; the scripts must not
# need it, and test_scripts_run_as_documented_write_no_bytecode proves that on a copy, without -B.

if os.name == "nt":
    # its scripts and fakes run through bash and POSIX tools; the pull-request skill is not yet verified on Windows
    print("skipped: the pull-request skill is not yet verified on Windows")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "pull-request")
HOOK = os.path.join(SKILL, "hooks", "pr_gate.py")
INVENTORY = os.path.join(SKILL, "scripts", "inventory.py")
CHECK = os.path.join(SKILL, "scripts", "pr_check.py")
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import pr_check  # noqa: E402
import review_comments  # noqa: E402

# A fake `gh`: prints the file named in FAKE_GH_OUT, or fails as if not logged in.
FAKE_BIN = tempfile.mkdtemp(prefix="pr-fakebin-")
with open(os.path.join(FAKE_BIN, "gh"), "w") as fh:
    fh.write('#!/bin/sh\n[ -n "$FAKE_GH_OUT" ] && exec cat "$FAKE_GH_OUT"\necho "gh: not logged in" >&2\nexit 1\n')
os.chmod(os.path.join(FAKE_BIN, "gh"), 0o755)
os.environ["PATH"] = FAKE_BIN + os.pathsep + os.environ.get("PATH", "")
os.environ.pop("FAKE_GH_OUT", None)
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}

# The Portuguese body stays: the gate supports pt, and these cases keep that support honest.
GOOD_PT = """O aviso do tour guiado aparecia a cada visita, e quem ja tinha visto o tour precisava fecha-lo de novo. A mudanca grava que o aviso foi visto e nao mexe no conteudo do tour.

## Antes e depois

| Comportamento | Antes | Depois |
|---|---|---|
| Aviso do tour | Aparece em toda visita | Aparece uma vez por navegador |

## Recursos criados

Nenhum. A mudanca usa o armazenamento local que ja existe.

## Recursos removidos

Nenhum. Nada sai.

## Estado e fluxo

### Estado

```mermaid
stateDiagram-v2
    [*] --> NaoVisto
    NaoVisto --> Visto
```

### Fluxo

Nenhum. Nao ha fluxo novo entre componentes.

## Funções criadas e removidas

| Função | Arquivo | Mudança | Para quê |
|---|---|---|---|
| `marcarVisto` | `src/tour.ts` | Criada | Grava que o aviso foi visto |

## Custo

Nenhum. Nao ha recurso cobrado.

## Análise de risco

| | |
|---|---|
| Risco de aplicar | Baixo: quem limpa o navegador ve o aviso de novo |
| Risco de não aplicar | O aviso continua atrapalhando quem volta |
| Raio de impacto | So a pagina do tour |
| Reversão | Reverter o commit; nenhum dado se perde |

## Práticas aplicadas

| Prática | Fonte | Onde |
|---|---|---|
| Teste do comportamento novo | `CLAUDE.md` do projeto | `src/tour.test.ts` |

## Varreduras

| Ferramenta | Comando | Resultado |
|---|---|---|
| Lint | `npm run lint` | Passou, 0 avisos |
| Semgrep | Não rodou: nao instalado nesta maquina | - |
| Trivy | `trivy fs .` | Passou |
| Segredos (gitleaks) | `gitleaks detect` | Passou |

## Testes

| Suíte | Comando | Resultado |
|---|---|---|
| unidade | `npm test` | 42 passaram, 0 falharam |
"""

GOOD_EN = """The guided tour notice showed on every visit, so people who had already seen the tour had to close it again. The change records that the notice was seen and leaves the tour content alone.

## Before and after

| Behaviour | Before | After |
|---|---|---|
| Tour notice | Shows on every visit | Shows once per browser |

## Resources created

None. The change uses the existing local storage.

## Resources deleted

None. Nothing goes away.

## State and flow

### State

```mermaid
stateDiagram-v2
    [*] --> Unseen
    Unseen --> Seen
```

### Flow

None. No new flow between components.

## Functions created and deleted

| Function | File | Change | Purpose |
|---|---|---|---|
| `markSeen` | `src/tour.ts` | Created | Records that the notice was seen |

## Cost

None. Nothing billable.

## Risk analysis

| | |
|---|---|
| Risk of applying | Low: clearing the browser shows the notice again |
| Risk of not applying | The notice keeps getting in the way |
| Blast radius | The tour page only |
| Rollback | Revert the commit; no data is lost |

## Practices applied

| Practice | Source | Where |
|---|---|---|
| Test the new behaviour | Project `CLAUDE.md` | `src/tour.test.ts` |

## Scans

| Tool | Command | Result |
|---|---|---|
| Lint | `npm run lint` | Pass, 0 warnings |
| Semgrep | Not run: not installed here | - |
| Trivy | `trivy fs .` | Pass |
| Secrets (gitleaks) | `gitleaks detect` | Pass |

## Tests

| Suite | Command | Result |
|---|---|---|
| unit | `npm test` | 42 passed, 0 failed |
"""


def codes(problems):
    return {p.code for p in problems}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


def repo(files=None, commits=()):
    """A throwaway git repository with these files and, after them, these empty commits."""
    path = tempfile.mkdtemp(prefix="pr-repo-")
    git(path, "init", "-q", "-b", "main")
    for name, text in (files or {}).items():
        full = os.path.join(path, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "--allow-empty", "-m", "Create the test repository")
    for msg in commits:
        git(path, "commit", "-q", "--allow-empty", "-m", msg)
    return path


def without_section(body, heading):
    head, _, rest = body.partition(f"## {heading}\n")
    return head + (rest[rest.index("\n## "):].lstrip("\n") if "\n## " in rest else "")


def hook(payload, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "FAKE_GH"))}
    e["HOME"] = tempfile.mkdtemp(prefix="pr-home-")
    e.update(env or {})
    p = subprocess.run([sys.executable, "-I", "-B", HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=e, timeout=60)
    assert p.returncode == 0, p.stderr
    return p


def decision(p):
    """("passthrough" | "deny" | "allow", message) from the hook's stdout."""
    if not p.stdout.strip():
        return "passthrough", ""
    out = json.loads(p.stdout)["hookSpecificOutput"]
    if out.get("permissionDecision") == "deny":
        return "deny", out["permissionDecisionReason"]
    return "allow", out.get("additionalContext", "")


def bash(cwd, command):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


# --- title --------------------------------------------------------------------

def test_bad_pt_title_is_denied_with_the_right_code():
    """Pins every title rule for pt: each bad title must come back with its own code, not just any."""
    bad = {
        "Permissões dos seis papéis": "TITLE_NO_VERB",
        "Skill pull-request adaptada ao squad": "TITLE_NO_VERB",
        "Fase 6: cria o bucket de exportação": "TITLE_STEP_LABEL",
        "F6-B4: Move a exportação para um job": "TITLE_STEP_LABEL",
        "ABC-12: Move a exportação para um job": "TITLE_ID_PREFIX",
        "Adicionando cache ao relatório": "TITLE_ACTIVITY",
        "Move dealer exports to a background job": "TITLE_NOT_PORTUGUESE",
        "Ajustes": "TITLE_GENERIC",
        "feature/skill-pull-request": "TITLE_BRANCH_NAME",
        "Move o bucket aws_s3_bucket.exports para outra conta": "TITLE_CODE_IDENTIFIER",
    }
    for title, code in bad.items():
        got = codes(pr_check.check_title(title, "pt"))
        assert code in got, (title, got)


def test_good_pt_title_passes_with_id_only_as_suffix():
    """Pins that a good pt title is not flagged, and that a ticket id is fine as a suffix."""
    for title in ("O aviso do tour guiado passou a aparecer uma vez só",
                  "Move a exportação para um job em segundo plano",
                  "Move a exportação para um job em segundo plano (F6-B4)",
                  "Monitor: limiar invalido no ambiente nao desliga o freio",
                  "Corrige o login quando a senha tem acento"):
        assert pr_check.check_title(title, "pt") == [], (title, pr_check.check_title(title, "pt"))


def test_en_title_bad_and_good():
    """Pins the en title rules: bad titles carry their code, good titles (id suffix, prefix) pass."""
    bad = {
        "permissions boundaries for the six roles": "TITLE_NO_VERB",
        "Adding cache to reports": "TITLE_ACTIVITY",
        "Move a exportação para um job em segundo plano": "TITLE_NOT_ENGLISH",
        "Add the export bucket for phase 6": "TITLE_STEP_LABEL",
        "Updates": "TITLE_GENERIC",
    }
    for title, code in bad.items():
        got = codes(pr_check.check_title(title, "en"))
        assert code in got, (title, got)
    for title in ("Move dealer exports to a background job",
                  "Deny Terraform apply in the agent (ABC-12)",
                  "feat(export): Move dealer exports to a background job"):
        assert pr_check.check_title(title, "en") == [], (title, pr_check.check_title(title, "en"))


# --- body ---------------------------------------------------------------------

def test_good_body_passes_and_sections_hold_in_both_languages():
    """Pins that the good body passes in its own language and that en headings are also accepted under pt."""
    assert pr_check.check_body(GOOD_PT, "app", "pt") == []
    assert pr_check.check_body(GOOD_EN, "app", "en") == []
    assert pr_check.check_body(GOOD_EN, "app", "pt") == []


def test_body_missing_a_section_or_the_secrets_row_is_denied():
    """Pins SECTION_MISSING (named in English whatever the body language) and SCAN_MISSING:secrets."""
    got = codes(pr_check.check_body(without_section(GOOD_PT, "Varreduras"), "app", "pt"))
    assert "SECTION_MISSING:Scans" in got, got
    got = codes(pr_check.check_body(without_section(GOOD_EN, "Risk analysis"), "app", "en"))
    assert "SECTION_MISSING:Risk analysis" in got, got
    no_secrets = GOOD_PT.replace("| Segredos (gitleaks) | `gitleaks detect` | Passou |\n", "")
    assert codes(pr_check.check_body(no_secrets, "app", "pt")) == {"SCAN_MISSING:secrets"}


def test_raw_template_is_denied_for_placeholders():
    """Pins PLACEHOLDER: the unfilled body template must not pass as a body."""
    with open(os.path.join(SKILL, "templates", "body.md"), encoding="utf-8") as fh:
        got = codes(pr_check.check_body(fh.read(), "app", "en"))
    assert "PLACEHOLDER" in got, got


def test_infra_pr_with_mutation_in_tests_is_denied():
    """Pins TESTS_FORBIDDEN: an infra PR cannot list mutation testing, an app PR can; same through the CLI."""
    row = "| unidade | `npm test` | 42 passaram, 0 falharam |"
    with_mutation = GOOD_PT.replace(row, row + "\n| mutação | `mutmut run` | 12 mutantes mortos |")
    assert "TESTS_FORBIDDEN" in codes(pr_check.check_body(with_mutation, "infra", "pt"))
    assert "TESTS_FORBIDDEN" not in codes(pr_check.check_body(with_mutation, "app", "pt"))
    en = GOOD_EN.replace("| unit | `npm test` | 42 passed, 0 failed |",
                         "| mutation | `stryker run` | 90% killed |")
    assert "TESTS_FORBIDDEN" in codes(pr_check.check_body(en, "infra", "en"))
    # through the CLI: the kind comes from the PR's file list
    d = tempfile.mkdtemp(prefix="pr-cli-")
    body_file, files_file = os.path.join(d, "body.md"), os.path.join(d, "files")
    with open(body_file, "w", encoding="utf-8") as fh:
        fh.write(with_mutation)
    with open(files_file, "w") as fh:
        fh.write("stacks/export/main.tf\n")
    p = subprocess.run([sys.executable, "-I", "-B", CHECK, body_file, "--lang", "pt", "--files", files_file,
                        "--title", "Move a exportação para um job em segundo plano"],
                       capture_output=True, text=True)
    assert p.returncode == 1 and "TESTS_FORBIDDEN" in p.stdout and "infra PR" in p.stdout, p.stdout


# --- language -----------------------------------------------------------------

def test_auto_language_reads_claude_md_then_prs_then_commits_else_en():
    """Pins the detection order (policy file, PR titles, commits) and that the last resort is en, not pt."""
    r = repo({"CLAUDE.md": "# Regras\n\nConversa em português; títulos de PR e commits em inglês.\n"},
             commits=["Corrige o login quando a senha tem acento"])
    assert pr_check.detect_lang(r) == ("en", "CLAUDE.md")
    r = repo({"AGENTS.md": "Commits e PRs em português do Brasil.\n"})
    assert pr_check.detect_lang(r) == ("pt", "AGENTS.md")

    r = repo(commits=["Corrige o login quando a senha tem acento", "Move a exportação para um job"])
    out = os.path.join(tempfile.mkdtemp(), "titles")
    with open(out, "w") as fh:
        fh.write("Move dealer exports to a background job\nAdd a retry to the export\nFix the login for the admin\n")
    os.environ["FAKE_GH_OUT"] = out
    try:
        assert pr_check.detect_lang(r) == ("en", "PR titles")
    finally:
        del os.environ["FAKE_GH_OUT"]
    assert pr_check.detect_lang(r) == ("pt", "commits")  # gh not logged in: falls back to the commits

    r = repo(commits=["Add the export job", "Move the retry to the worker for the admin"])
    assert pr_check.detect_lang(r) == ("en", "commits")
    assert pr_check.detect_lang(tempfile.mkdtemp()) == ("en", "default")


# --- hook ---------------------------------------------------------------------

def _repo_with_bodies(extra=None):
    files = {"CLAUDE.md": "Títulos de PR em português.\n", "good-body.md": GOOD_PT,
             "bad-body.md": without_section(GOOD_PT, "Varreduras")}
    files.update(extra or {})
    return repo(files)


def test_hook_denies_bad_title_and_body():
    """Pins that the hook reports the title and the body problems together, and denies a missing title."""
    r = _repo_with_bodies()
    d, msg = decision(hook(bash(r, 'gh pr create --title "Ajustes" --body-file bad-body.md')))
    assert d == "deny" and "TITLE_GENERIC" in msg and "SECTION_MISSING:Scans" in msg, (d, msg)
    d, msg = decision(hook(bash(r, 'agenfk pr create abc --title "Ajustes" --body "$(cat good-body.md)"')))
    assert d == "deny" and "TITLE_GENERIC" in msg, (d, msg)
    d, msg = decision(hook(bash(r, 'gh pr create --body-file good-body.md')))
    assert d == "deny" and "no --title" in msg, (d, msg)


def test_hook_lets_a_good_pr_through_and_ignores_what_is_not_a_pr():
    """Pins the allow message (with the detected language) and that grep/label edits are not PR creation."""
    r = _repo_with_bodies()
    d, msg = decision(hook(bash(r, 'gh pr create --title "O aviso do tour passou a aparecer uma vez só" '
                                   '--body-file good-body.md')))
    assert d == "allow" and "passed (language pt)" in msg, (d, msg)
    assert decision(hook(bash(r, 'git log --oneline | grep "gh pr create"')))[0] == "passthrough"
    assert decision(hook(bash(r, 'gh pr edit 12 --add-label infra')))[0] == "passthrough"


def test_hook_mcp_tool_denies_and_allows():
    """Pins that the MCP create_pull_request tool goes through the same gate as the Bash command."""
    r = _repo_with_bodies()
    tool = "mcp__plugin_github_github__create_pull_request"
    bad = {"tool_name": tool, "cwd": r, "tool_input": {"owner": "o", "repo": "r", "title": "Ajustes",
                                                        "body": GOOD_PT, "head": "x", "base": "main"}}
    d, msg = decision(hook(bad))
    assert d == "deny" and "TITLE_GENERIC" in msg, (d, msg)
    good = json.loads(json.dumps(bad))
    good["tool_input"]["title"] = "Move a exportação para um job em segundo plano"
    assert decision(hook(good))[0] == "allow"


def test_hook_passes_through_when_the_project_has_its_own_gate():
    """Pins the hand-off: a project skill or hook that already gates PRs wins, and SQUAD_PR_GATE=0 turns ours off."""
    bad = 'gh pr create --title "Ajustes" --body-file bad-body.md'
    with_skill = _repo_with_bodies({".claude/skills/acme-pr-delivery/SKILL.md": "---\nname: acme-pr-delivery\n---\n"})
    assert decision(hook(bash(with_skill, bad))) == ("passthrough", "")
    with_hook = _repo_with_bodies({".claude/hooks/guard.sh": '#!/bin/sh\ncase "$1" in *"gh pr create"*) exit 2;; esac\n'})
    assert decision(hook(bash(with_hook, bad))) == ("passthrough", "")
    # a PR-stack skill is not a format gate: the squad gate still applies
    stack_only = _repo_with_bodies({".claude/skills/prs-stack/SKILL.md": "---\nname: prs-stack\n---\n"})
    assert decision(hook(bash(stack_only, bad)))[0] == "deny"
    assert decision(hook(bash(_repo_with_bodies(), bad), {"SQUAD_PR_GATE": "0"})) == ("passthrough", "")


def test_hook_with_an_internal_error_warns_and_does_not_break():
    """Pins fail-open: a payload the hook cannot handle warns on stderr and never blocks the tool call."""
    r = _repo_with_bodies()
    p = hook({"tool_name": "Bash", "tool_input": {"command": ["gh", "pr", "create"]}, "cwd": r})
    assert p.stdout.strip() == "" and "internal error" in p.stderr, (p.stdout, p.stderr)
    p = subprocess.run([sys.executable, "-I", "-B", HOOK], input="this is not json", capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip() == ""


def test_hook_outside_a_git_repo_falls_back_to_en():
    """Pins the hook's fallback: with no repository to read a language from, the gate checks in en."""
    outside = tempfile.mkdtemp(prefix="pr-norepo-")
    assert pr_check.repo_root(outside) is None
    tool = "mcp__plugin_github_github__create_pull_request"
    payload = {"tool_name": tool, "cwd": outside,
               "tool_input": {"title": "Show the guided tour notice once per browser", "body": GOOD_EN}}
    d, msg = decision(hook(payload))
    assert d == "allow" and "language en" in msg, (d, msg)
    payload["tool_input"].update(title="Move a exportação para um job em segundo plano", body=GOOD_PT)
    d, msg = decision(hook(payload))
    assert d == "deny", (d, msg)


def test_scripts_run_as_documented_write_no_bytecode():
    """Pins that `python3 -I` (no -B) on the scripts and the hook leaves no __pycache__ in the skills:
    -I ignores PYTHONDONTWRITEBYTECODE, and pr_check loads pr-evidence by path."""
    copy = tempfile.mkdtemp(prefix="pr-copy-")
    try:
        for name in ("pull-request", "pr-evidence"):
            shutil.copytree(os.path.join(ROOT, "skills", name), os.path.join(copy, "skills", name),
                            ignore=shutil.ignore_patterns("__pycache__"))
        scripts = os.path.join(copy, "skills", "pull-request", "scripts")
        r = repo({".github/pull_request_template.md": "## Summary\n", "good-body.md": GOOD_EN})
        body = os.path.join(r, "good-body.md")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        env["HOME"] = tempfile.mkdtemp(prefix="pr-home-")
        runs = [[os.path.join(scripts, "pr_check.py"), body, "--repo", r],
                [os.path.join(scripts, "inventory.py"), "--repo", r, "--base", "HEAD"],
                [os.path.join(copy, "skills", "pull-request", "hooks", "pr_gate.py")]]
        payload = json.dumps({"tool_name": "mcp__plugin_github_github__create_pull_request", "cwd": r,
                              "tool_input": {"title": "Show the guided tour notice once per browser", "body": GOOD_EN}})
        for argv in runs:
            p = subprocess.run([sys.executable, "-I", *argv], input=payload, capture_output=True, text=True,
                               env=env, timeout=60)
            assert "Traceback" not in p.stderr, (argv, p.stderr)
        assert "TEMPLATE_SECTION_MISSING" in subprocess.run(
            [sys.executable, "-I", *runs[0]], capture_output=True, text=True, env=env, timeout=60).stdout
        caches = [d for d, _, _ in os.walk(copy) if os.path.basename(d) == "__pycache__"]
        assert caches == [], caches
    finally:
        shutil.rmtree(copy, ignore_errors=True)


# --- inventory and review -----------------------------------------------------

def test_inventory_in_a_temporary_git_repo():
    """Pins that the inventory lists created and deleted resources and functions, in JSON and in markdown."""
    r = repo({"main.tf": 'resource "aws_s3_bucket" "old" {\n}\n', "app.py": "def old():\n    pass\n"})
    git(r, "checkout", "-q", "-b", "feat")
    with open(os.path.join(r, "main.tf"), "w") as fh:
        fh.write('resource "aws_s3_bucket" "new" {\n}\n')
    with open(os.path.join(r, "app.py"), "w") as fh:
        fh.write("def new():\n    pass\n")
    git(r, "commit", "-q", "-am", "Swap the bucket and the function")
    p = subprocess.run([sys.executable, "-I", "-B", INVENTORY, "--repo", r, "--base", "main", "--format", "json"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    inv = json.loads(p.stdout)
    assert [i["name"] for i in inv["resources"]["created"]] == ["aws_s3_bucket.new"], inv
    assert [i["name"] for i in inv["resources"]["deleted"]] == ["aws_s3_bucket.old"], inv
    assert [i["name"] for i in inv["functions"]["created"]] == ["new"], inv
    assert [i["name"] for i in inv["functions"]["deleted"]] == ["old"], inv
    md = subprocess.run([sys.executable, "-I", "-B", INVENTORY, "--repo", r, "--base", "main"],
                        capture_output=True, text=True).stdout
    assert "| `new` | `app.py` | Created |" in md and "| `old` | `app.py` | Deleted |" in md, md


def test_blocking_review_requests_changes_and_self_review_only_comments():
    """Pins build_review: Blocking inside the diff requests changes with an inline comment, Minor outside the
    diff goes in the body and approves, self-review is always COMMENT. English is the default text; pt still works."""
    diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = secret\n")
    finding = {"severity": "Blocking", "path": "a.py", "line": 2,
               "problem": "Secret in the code.", "fix": "Read it from the environment."}
    rev = review_comments.build_review(diff, [dict(finding)])
    assert rev["event"] == "REQUEST_CHANGES" and len(rev["comments"]) == 1, rev
    assert "**Blocking.**" in rev["comments"][0]["body"]
    minor = dict(finding, severity="Minor", line=40)  # outside the diff: goes in the body
    rev = review_comments.build_review(diff, [minor])
    assert rev["event"] == "APPROVE" and rev["comments"] == [] and "Outside the diff" in rev["body"], rev
    assert review_comments.build_review(diff, [dict(finding)], self_review=True)["event"] == "COMMENT"
    # pt text stays supported, and the pt severity word is accepted as input under the default language
    rev = review_comments.build_review(diff, [dict(finding, severity="Bloqueante")], lang="pt")
    assert rev["event"] == "REQUEST_CHANGES" and "**Bloqueante.**" in rev["comments"][0]["body"], rev
    assert "Fora do diff" in review_comments.build_review(diff, [minor], lang="pt")["body"]
    rev = review_comments.build_review(diff, [dict(finding, severity="Bloqueante")])
    assert "**Blocking.**" in rev["comments"][0]["body"], rev


# --- body rules, one by one ---------------------------------------------------

GOOD = {"pt": GOOD_PT, "en": GOOD_EN}


def swap(body, old, new):
    assert old in body, old
    return body.replace(old, new, 1)


def with_opening(body, text):
    return text + "\n\n" + body.split("\n\n", 1)[1]


def title_of(n, lang):
    """A good title with exactly n characters."""
    base = "Move a exportação para um job em " if lang == "pt" else "Move dealer exports to a job in "
    return base + "a" * (n - len(base))


def test_title_is_long_only_above_72_characters_in_both_languages():
    """Pins TITLE_MAX and the `>`: 72 passes, 73 is TITLE_LONG (a wrong limit or `>=` would move one of them)."""
    for lang in ("pt", "en"):
        assert len(title_of(72, lang)) == 72
        assert "TITLE_LONG" not in codes(pr_check.check_title(title_of(72, lang), lang)), lang
        assert "TITLE_LONG" in codes(pr_check.check_title(title_of(73, lang), lang)), lang
        assert "TITLE_LONG" in codes(pr_check.check_title(title_of(300, lang), lang)), lang


def test_opening_short_long_and_boilerplate_with_exact_limits():
    """Pins OPENING_MIN_WORDS (12), OPENING_MAX_WORDS (120) and BOILERPLATE, in pt and en."""
    for lang in ("pt", "en"):
        body = GOOD[lang]
        words = lambda n: " ".join(["word"] * n)  # noqa: E731
        got = codes(pr_check.check_body(with_opening(body, words(11)), "app", lang))
        assert "OPENING_SHORT" in got and "OPENING_LONG" not in got, (lang, got)
        assert codes(pr_check.check_body(with_opening(body, words(12)), "app", lang)) == set(), lang
        assert codes(pr_check.check_body(with_opening(body, words(120)), "app", lang)) == set(), lang
        got = codes(pr_check.check_body(with_opening(body, words(121)), "app", lang))
        assert "OPENING_LONG" in got and "OPENING_SHORT" not in got, (lang, got)
    for lang, opening in (("pt", "Este PR muda o aviso do tour guiado para aparecer uma vez só por navegador em cada visita."),
                          ("pt", "Neste PR o aviso do tour guiado passa a aparecer uma vez só por navegador em cada visita."),
                          ("en", "This PR makes the guided tour notice show once per browser instead of on every single visit."),
                          ("en", "In this pull request the guided tour notice should show once per browser instead of on every visit.")):
        got = codes(pr_check.check_body(with_opening(GOOD[lang], opening), "app", lang))
        assert got == {"OPENING_BOILERPLATE"}, (opening, got)


def test_sections_out_of_order_are_denied_in_both_languages():
    """Pins SECTION_ORDER: swapping Cost and Risk analysis must not pass."""
    for lang, a, b in (("pt", "Custo", "Análise de risco"), ("en", "Cost", "Risk analysis")):
        body = GOOD[lang]
        i, j = body.index(f"## {a}\n"), body.index(f"## {b}\n")
        k = body.index("\n## ", j + 1)
        swapped = body[:i] + body[j:k + 1] + body[i:j] + body[k + 1:]
        assert codes(pr_check.check_body(swapped, "app", lang)) == {"SECTION_ORDER"}, lang
        assert "SECTION_ORDER" not in codes(pr_check.check_body(body, "app", lang))


def test_section_with_a_heading_and_no_content_is_denied():
    """Pins SECTION_EMPTY: an empty `## Cost` does not count as `None.`."""
    for lang, heading, text in (("pt", "Custo", "Nenhum. Nao ha recurso cobrado."),
                                ("en", "Cost", "None. Nothing billable.")):
        empty = swap(GOOD[lang], f"## {heading}\n\n{text}\n\n", f"## {heading}\n\n")
        assert codes(pr_check.check_body(empty, "app", lang)) == {"SECTION_EMPTY:Cost"}, lang


def test_state_and_flow_diagrams_pt_and_en():
    """Pins _check_diagrams: a missing subsection, a missing mermaid block and a wrong diagram type are denied."""
    for lang in ("pt", "en"):
        body = GOOD[lang]
        unseen = "NaoVisto" if lang == "pt" else "Unseen"
        wrong = swap(body, "stateDiagram-v2", "flowchart TD")
        assert codes(pr_check.check_body(wrong, "app", lang)) == {"DIAGRAM_KIND:State"}, lang
        no_block = swap(body, "```mermaid\nstateDiagram-v2\n    [*] --> " + unseen,
                        "```text\nx\n    [*] --> " + unseen)
        assert codes(pr_check.check_body(no_block, "app", lang)) == {"DIAGRAM_MISSING:State"}, lang
        flow_heading = "### Fluxo" if lang == "pt" else "### Flow"
        no_flow = body.replace(flow_heading, "### Something else")
        assert codes(pr_check.check_body(no_flow, "app", lang)) == {"DIAGRAM_MISSING:Flow"}, lang
        only_sequence = swap(body, "```mermaid\nstateDiagram-v2", "```mermaid\nsequenceDiagram")
        assert codes(pr_check.check_body(only_sequence, "app", lang)) == {"DIAGRAM_KIND:State"}, lang
        # a flow with sequenceDiagram is valid
        flow_ok = swap(body, "None. No new flow between components." if lang == "en"
                       else "Nenhum. Nao ha fluxo novo entre componentes.",
                       "```mermaid\nsequenceDiagram\n    A->>B: hi\n```")
        assert codes(pr_check.check_body(flow_ok, "app", lang)) == set(), lang


def test_infra_cost_requires_a_dollar_amount():
    """Pins COST_AMOUNT_MISSING: only for infra PRs, and only when there is no amount."""
    for lang, none, with_amount in (("pt", "Nenhum. Nao ha recurso cobrado.", "US$ 0.00 por mes."),
                                    ("en", "None. Nothing billable.", "$12.50/month for the new bucket.")):
        assert codes(pr_check.check_body(GOOD[lang], "infra", lang)) == {"COST_AMOUNT_MISSING"}, lang
        assert codes(pr_check.check_body(GOOD[lang], "app", lang)) == set(), lang
        priced = swap(GOOD[lang], none, with_amount)
        assert codes(pr_check.check_body(priced, "infra", lang)) == set(), lang


def test_section_without_a_table_is_denied_and_none_waives_it():
    """Pins TABLE_MISSING: prose where the table belongs is denied; a `None.` answer waives the table."""
    for lang, heading, code in (("pt", "Práticas aplicadas", "Practices applied"),
                                ("en", "Practices applied", "Practices applied")):
        body = GOOD[lang]
        i = body.index(f"## {heading}\n")
        k = body.index("\n## ", i + 1)
        prose = body[:i] + f"## {heading}\n\nWe follow the project rules.\n" + body[k:]
        assert codes(pr_check.check_body(prose, "app", lang)) == {f"TABLE_MISSING:{code}"}, lang
        none = body[:i] + f"## {heading}\n\nNenhum. None. Nothing new.\n" + body[k:]
        assert codes(pr_check.check_body(none, "app", lang)) == set(), lang


def test_before_and_after_requires_before_and_after_columns():
    """Pins BEFORE_AFTER_COLUMNS."""
    cases = {"pt": ("| Comportamento | Antes | Depois |", "| Comportamento | Valor | Outro |"),
             "en": ("| Behaviour | Before | After |", "| Behaviour | Value | Other |")}
    for lang, (right, wrong) in cases.items():
        got = codes(pr_check.check_body(swap(GOOD[lang], right, wrong), "app", lang))
        assert got == {"BEFORE_AFTER_COLUMNS"}, (lang, got)


def test_risk_analysis_requires_the_four_rows():
    """Pins RISK_MISSING: dropping each table row reports exactly that term."""
    rows = {"pt": (("Risco de aplicar", "risk of applying"), ("Risco de não aplicar", "risk of not applying"),
                   ("Raio de impacto", "blast radius"), ("Reversão", "rollback")),
            "en": (("Risk of applying", "risk of applying"), ("Risk of not applying", "risk of not applying"),
                   ("Blast radius", "blast radius"), ("Rollback", "rollback"))}
    for lang, items in rows.items():
        for label, term in items:
            without = "\n".join(l for l in GOOD[lang].split("\n") if not l.startswith(f"| {label} |"))
            assert without != GOOD[lang], label
            assert codes(pr_check.check_body(without, "app", lang)) == {f"RISK_MISSING:{term}"}, (lang, label)


def test_practices_require_a_source_column():
    """Pins PRACTICE_SOURCE_MISSING."""
    for lang, right, wrong in (("pt", "| Prática | Fonte | Onde |", "| Prática | Origem | Onde |"),
                               ("en", "| Practice | Source | Where |", "| Practice | Origin | Where |")):
        without = swap(GOOD[lang], right, wrong)
        assert codes(pr_check.check_body(without, "app", lang)) == {"PRACTICE_SOURCE_MISSING"}, lang


def test_scans_require_one_row_per_tool():
    """Pins SCAN_MISSING per tool (lint, semgrep, trivy)."""
    for lang in ("pt", "en"):
        for tool, label in (("lint", "| Lint |"), ("semgrep", "| Semgrep |"), ("trivy", "| Trivy |")):
            without = "\n".join(l for l in GOOD[lang].split("\n") if not l.startswith(label))
            assert codes(pr_check.check_body(without, "app", lang)) == {f"SCAN_MISSING:{tool}"}, (lang, tool)


def test_pr_base_only_becomes_a_ref_when_it_is_safe():
    """Pins SAFE_REF: a base git would read as an option never reaches the list of refs."""
    assert pr_check.base_refs("feat/x")[:2] == ["origin/feat/x", "feat/x"]
    for bad in ("--output=/tmp/x", "-p", "a b", "x;y", ""):
        refs = pr_check.base_refs(bad)
        assert refs == list(pr_check.DEFAULT_BASES), (bad, refs)
    assert pr_check.base_refs(None) == list(pr_check.DEFAULT_BASES)
    # and through real git: --output=... must not write a file
    r = repo()
    target = os.path.join(tempfile.mkdtemp(), "written")
    assert pr_check.changed_files(r, f"--output={target}") == []
    assert not os.path.exists(target)


# --- hook parser, command by command ------------------------------------------

sys.path.insert(0, os.path.join(SKILL, "hooks"))
import pr_gate  # noqa: E402

GOOD_TITLE = "O aviso do tour passou a aparecer uma vez só"
BAD = 'gh pr create --title "Ajustes" --body-file good-body.md'  # denied for TITLE_GENERIC


def verdict(r, command, env=None):
    return decision(hook(bash(r, command), env))


def test_hook_reads_the_heredoc_body_inside_body_cat():
    """Pins the heredoc cut: `--body "$(cat <<'EOF' ... EOF)"` is checked, not skipped."""
    r = _repo_with_bodies()
    cmd = lambda body, quotes="'EOF'": (f'gh pr create --title "{GOOD_TITLE}" --body "$(cat <<{quotes}\n{body}\nEOF\n)"')  # noqa: E731
    d, msg = decision(hook(bash(r, cmd(without_section(GOOD_PT, "Varreduras")))))
    assert d == "deny" and "SECTION_MISSING:Scans" in msg, (d, msg)
    d, msg = decision(hook(bash(r, cmd(GOOD_PT))))
    assert d == "allow" and "passed" in msg, (d, msg)
    d, msg = decision(hook(bash(r, cmd(without_section(GOOD_PT, "Varreduras"), "EOF"))))
    assert d == "deny" and "SECTION_MISSING:Scans" in msg, (d, msg)


def test_hook_does_not_read_heredoc_text_as_a_command():
    """Pins heredoc as data: quoting `gh pr create` inside a heredoc or quotes does not open a PR."""
    r = _repo_with_bodies()
    assert verdict(r, "cat <<EOF\ngh pr create --title Ajustes\nEOF") == ("passthrough", "")
    assert verdict(r, "git commit -F - <<'EOF'\nExplains gh pr create --title Ajustes\nEOF") == ("passthrough", "")
    assert verdict(r, 'echo "gh pr create --title Ajustes"') == ("passthrough", "")
    # a heredoc with no terminator does not hide the command that comes before it
    assert verdict(r, BAD + " <<EOF\nno end")[0] == "deny"


def test_hook_follows_eval_bash_c_and_bash_with_heredoc():
    """Pins eval, `bash -c` and `bash <<EOF`: the PR inside them is checked."""
    r = _repo_with_bodies()
    for cmd in ("eval 'gh pr create --title \"Ajustes\" --body-file good-body.md'",
                "bash -c 'gh pr create --title \"Ajustes\" --body-file good-body.md'",
                "sh -lc 'gh pr create --title \"Ajustes\" --body-file good-body.md'",
                "bash <<EOF\ngh pr create --title \"Ajustes\" --body-file good-body.md\nEOF"):
        d, msg = verdict(r, cmd)
        assert d == "deny" and "TITLE_GENERIC" in msg, (cmd, d, msg)
    assert verdict(r, "bash -c 'echo gh pr create'") == ("passthrough", "")


def test_hook_tracks_cd_to_find_the_right_repo():
    """Pins `cd`/`pushd` tracking: the project's own gate and the language are those of the directory where the command runs."""
    skill = {".claude/skills/acme-pr-delivery/SKILL.md": "x"}
    free, gated = _repo_with_bodies(), _repo_with_bodies(skill)
    assert verdict(free, BAD)[0] == "deny"
    assert verdict(free, f"cd {gated} && " + BAD) == ("passthrough", "")
    assert verdict(free, f"cd ../{os.path.basename(gated)} && " + BAD) == ("passthrough", "")
    assert verdict(free, f"pushd {gated} && " + BAD) == ("passthrough", "")
    assert verdict(gated, BAD) == ("passthrough", "")
    d, msg = verdict(gated, f"cd {free} && " + BAD)
    assert d == "deny" and "TITLE_GENERIC" in msg, (d, msg)
    # a subshell's cd does not outlive it; a `{ }` group's does
    assert verdict(free, f"(cd {gated}; true); " + BAD)[0] == "deny"
    assert verdict(free, f"(cd {gated} && {BAD})") == ("passthrough", "")
    assert verdict(free, f"{{ cd {gated}; }}; " + BAD) == ("passthrough", "")


def test_hook_computed_cd_does_not_guess_the_directory():
    """Pins `cd` with `$` or a backtick: the directory is unknown, so a relative body is denied with the right reason."""
    r = _repo_with_bodies()
    for target in ("$DESTINATION", "`pwd`", '"$(mktemp -d)"'):
        d, msg = verdict(r, f"cd {target} && " + BAD)
        assert d == "deny" and "computed at run time" in msg, (target, d, msg)
    d, msg = verdict(r, f'cd $DESTINATION && gh pr create --title "Ajustes" --body-file {r}/good-body.md')
    assert d == "deny" and "TITLE_GENERIC" in msg and "computed at run time" not in msg, (d, msg)


def test_hook_ignores_a_comment_and_does_not_mistake_a_hash_inside_a_word():
    """Pins the `#` stripping: an open quote inside a comment does not make the command unreadable."""
    r = _repo_with_bodies()
    d, msg = verdict(r, BAD + ' # note "unclosed')
    assert d == "deny" and "TITLE_GENERIC" in msg and "could not be parsed" not in msg, (d, msg)
    d, msg = verdict(r, f'gh pr create --title "{GOOD_TITLE}" --body-file good-body.md # ok')
    assert d == "allow", (d, msg)
    # `#` in the middle of a word does not open a comment: the whole title is read
    d, msg = verdict(r, 'gh pr create --title Ajustes#12 --body-file good-body.md')
    assert d == "deny" and "Ajustes#12" in msg, (d, msg)


def test_hook_body_the_gate_cannot_read_is_denied_with_the_reason():
    """Pins $(...), backtick, stdin, missing file, --web/--editor, unreadable command and absent body."""
    r = _repo_with_bodies()
    t = f'gh pr create --title "{GOOD_TITLE}" '
    cases = (
        (t + '--body "$(date)"', "gate does not run"),
        (t + '--body "`date`"', "gate does not run"),
        (t + "--body-file -", "stdin"),
        (t + "--body-file missing.md", "does not exist yet"),
        (t + "--body-file good-body.md --web", "the browser or the editor"),
        (t + "-e --body-file good-body.md", "the browser or the editor"),
        (t + "--editor", "the browser or the editor"),
        (t.rstrip() + ' --body-file "good-body.md', "could not be parsed"),
        (t.strip(), "no body"),
        ("gh pr create --body-file good-body.md", "no --title"),
        ("gh pr new --body-file good-body.md", "no --title"),
    )
    for cmd, snippet in cases:
        d, msg = verdict(r, cmd)
        assert d == "deny" and snippet in msg, (cmd, d, msg)
    # with the right body, the same commands pass
    assert verdict(r, t + "--body-file good-body.md")[0] == "allow"
    assert verdict(r, t + "--body-file=good-body.md")[0] == "allow"


def test_hook_body_file_that_is_big_or_not_utf8_is_denied():
    """Pins the body file limits: 1 MB and UTF-8."""
    r = _repo_with_bodies()
    with open(os.path.join(r, "big.md"), "w") as fh:
        fh.write("x" * 1_000_001)
    with open(os.path.join(r, "latin.md"), "wb") as fh:
        fh.write(b"acentua\xe7\xe3o")
    t = f'gh pr create --title "{GOOD_TITLE}" '
    assert "is over 1000 kB" in verdict(r, t + "--body-file big.md")[1]
    assert "UTF-8" in verdict(r, t + "--body-file latin.md")[1]


def test_hook_help_is_ignored():
    """Pins --help/-h: asking for the command's help is not opening a PR."""
    r = _repo_with_bodies()
    for cmd in ("gh pr create --help", "gh pr create -h", "gh pr edit --help", "agenfk pr create --help"):
        assert verdict(r, cmd) == ("passthrough", ""), cmd
    assert verdict(r, "gh pr create --title Ajustes")[0] == "deny"


def test_hook_edit_and_new_are_checked_and_agenfk_only_creates():
    """Pins GH_ACTIONS: `gh pr edit` with a title or body and `gh pr new` count as create; a label edit does not."""
    r = _repo_with_bodies()
    d, msg = verdict(r, 'gh pr edit 12 --title "Ajustes"')
    assert d == "deny" and "gh pr edit" in msg and "TITLE_GENERIC" in msg, (d, msg)
    assert "no body" not in msg and "no --title" not in msg
    d, msg = verdict(r, "gh pr edit 12 --body-file bad-body.md")
    assert d == "deny" and "SECTION_MISSING:Scans" in msg, (d, msg)
    assert verdict(r, f'gh pr edit 12 --title "{GOOD_TITLE}" --body-file good-body.md')[0] == "allow"
    d, msg = verdict(r, "gh pr edit 12 --web")
    assert d == "deny" and "browser" in msg, (d, msg)
    d, msg = verdict(r, 'gh pr new --title "Ajustes" --body-file good-body.md')
    assert d == "deny" and "gh pr create" in msg and "TITLE_GENERIC" in msg, (d, msg)
    assert verdict(r, f'gh pr new --title "{GOOD_TITLE}" --body-file good-body.md')[0] == "allow"
    assert verdict(r, 'agenfk pr edit abc --title "Ajustes"') == ("passthrough", "")
    assert verdict(r, "gh pr edit 12 --add-reviewer someone") == ("passthrough", "")
    assert verdict(r, "gh pr view 12 --json title") == ("passthrough", "")
    assert verdict(r, "gh pr -R o/r create --title Ajustes --body-file good-body.md")[0] == "deny"
    assert verdict(r, "gh pr --repo=o/r create --title Ajustes --body-file good-body.md")[0] == "deny"
    # gh also accepts -R/--repo before `pr`; without this the gate let it through
    assert verdict(r, "gh -R o/r pr create --title Ajustes --body-file good-body.md")[0] == "deny"
    assert verdict(r, "gh --repo o/r pr create --title Ajustes --body-file good-body.md")[0] == "deny"
    assert verdict(r, "gh --repo=o/r pr -R o/r create --title Ajustes --body-file good-body.md")[0] == "deny"
    assert verdict(r, f'gh -R o/r pr create --title "{GOOD_TITLE}" --body-file good-body.md')[0] == "allow"


def test_hook_prefilter_does_not_parse_what_does_not_mention_a_pr():
    """Pins MENTIONS_TOOL/MENTIONS_PR: a command without `gh`/`agenfk` or without `pr` never reaches the parser."""
    calls = []
    original = pr_gate.find_pr_commands
    pr_gate.find_pr_commands = lambda *a, **k: calls.append(a) or []
    try:
        for cmd in ("ls -la", "git status && echo pr", "gh issue list", "agenfk list", "echo ghx prx"):
            assert pr_gate.evaluate(cmd, ".") == (None, ""), cmd
        assert calls == [], calls
        pr_gate.evaluate("gh pr list", ".")
        pr_gate.evaluate("agenfk pr create x", ".")
        assert len(calls) == 2, calls
    finally:
        pr_gate.find_pr_commands = original


# --- pass-through to the project's own gate -----------------------------------

def test_mcp_passes_through_when_the_project_has_its_own_gate():
    """Pins the evaluate_mcp bypass: an MCP call with a bad title in a repo with its own gate is not denied."""
    tool = "mcp__plugin_github_github__create_pull_request"
    bad = {"tool_name": tool, "tool_input": {"title": "Ajustes", "body": GOOD_PT, "head": "x", "base": "main"}}
    gated = _repo_with_bodies({".claude/skills/acme-pr-delivery/SKILL.md": "x"})
    ungated = _repo_with_bodies()
    assert decision(hook(dict(bad, cwd=gated))) == ("passthrough", "")
    assert decision(hook(dict(bad, cwd=ungated)))[0] == "deny"
    # no title / no body
    for field, snippet in (("title", "no title"), ("body", "no body")):
        payload = dict(bad["tool_input"], **{field: "  "})
        d, msg = decision(hook(dict(bad, tool_input=payload, cwd=ungated)))
        assert d == "deny" and snippet in msg, (field, d, msg)


def test_owner_home_never_counts_as_the_projects_own_gate():
    """Pins the $HOME exclusion: the squad skill installed in ~/.claude is not the project's gate."""
    r = _repo_with_bodies({".claude/skills/acme-pr-delivery/SKILL.md": "x"})
    assert decision(hook(bash(r, BAD), {"HOME": tempfile.mkdtemp()})) == ("passthrough", "")
    d, msg = decision(hook(bash(r, BAD), {"HOME": r}))
    assert d == "deny" and "TITLE_GENERIC" in msg, (d, msg)
    tool = "mcp__plugin_github_github__create_pull_request"
    mcp = {"tool_name": tool, "cwd": r, "tool_input": {"title": "Ajustes", "body": GOOD_PT}}
    assert decision(hook(mcp, {"HOME": r}))[0] == "deny"


def test_own_gate_in_settings_only_counts_if_it_is_a_hook():
    """Pins 7d78583: `Bash(gh pr create:*)` in permissions allows the command and is NOT a gate; a mention in hooks is."""
    permission = json.dumps({"permissions": {"allow": ["Bash(gh pr create:*)"], "ask": ["Bash(gh pr new:*)"]}})
    hooks_cfg = json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "~/.claude/hooks/my-gate.sh gh pr create"}]}]}})
    cases = (
        ({".claude/settings.json": permission}, "deny"),
        ({".claude/settings.local.json": permission}, "deny"),
        ({".claude/settings.json": hooks_cfg}, "passthrough"),
        ({".claude/settings.local.json": hooks_cfg}, "passthrough"),
        ({".claude/settings.json": json.dumps({"hooks": {}, "permissions": {"allow": ["Bash(gh pr create:*)"]}})}, "deny"),
        ({".claude/settings.json": json.dumps({"hooks": "gh pr create"})}, "passthrough"),
        ({".claude/settings.json": "{not json gh pr create"}, "deny"),
        ({".claude/settings.json": "[1, 2]"}, "deny"),
        ({".claude/hooks/config.json": '{"cmd": "gh pr create"}'}, "passthrough"),
        ({".claude/hooks/nothing.sh": "echo hi\n"}, "deny"),
        ({".claude/skills/prs-stack/SKILL.md": "x"}, "deny"),
        ({".claude/skills/pull-request/SKILL.md": "x"}, "passthrough"),
    )
    for files, expected in cases:
        r = _repo_with_bodies(files)
        d, msg = decision(hook(bash(r, BAD)))
        assert d == expected, (list(files), d, msg)
    # in-process: the return value says what it found
    r = _repo_with_bodies({".claude/settings.json": hooks_cfg})
    assert pr_gate.own_pr_gate(r) == ".claude/settings.json"
    assert pr_gate.own_pr_gate(_repo_with_bodies({".claude/settings.json": permission})) is None
    assert pr_gate.own_pr_gate(tempfile.mkdtemp()) is None
    assert pr_gate.own_pr_gate(None) is None


def test_own_gate_only_looks_at_the_repository_root():
    """Pins the use of repo_root: .claude/ in a subfolder is not a gate; the root seen from a subfolder is."""
    r = _repo_with_bodies({".claude/skills/acme-pr-delivery/SKILL.md": "x", "sub/.claude/settings.json": "{}"})
    assert pr_gate.own_pr_gate(os.path.join(r, "sub")) == ".claude/skills/acme-pr-delivery"
    r2 = _repo_with_bodies({"sub/.claude/skills/acme-pr-delivery/SKILL.md": "x"})
    assert pr_gate.own_pr_gate(os.path.join(r2, "sub")) is None


# --- hostile repository config ------------------------------------------------

def _hostile_repo():
    """A repo with fsmonitor, diff.external and textconv pointing at scripts that create sentinels."""
    r = repo({"CLAUDE.md": "Títulos de PR em português.\n", "good-body.md": GOOD_PT, "app.py": "a\n", "x.dat": "1\n"})
    sent = tempfile.mkdtemp(prefix="pr-sentinel-")
    for name in ("fsmonitor", "external", "textconv"):
        path = os.path.join(sent, name + ".sh")
        with open(path, "w") as fh:
            fh.write(f'#!/bin/sh\ntouch "{sent}/{name}"\ncat "$2" 2>/dev/null\n')
        os.chmod(path, 0o755)
    with open(os.path.join(r, ".gitattributes"), "w") as fh:
        fh.write("*.dat diff=evil\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "Attributes")
    git(r, "checkout", "-q", "-b", "feat")
    with open(os.path.join(r, "app.py"), "w") as fh:
        fh.write("b\n")
    with open(os.path.join(r, "x.dat"), "w") as fh:
        fh.write("2\n")
    git(r, "commit", "-q", "-am", "Change")
    git(r, "config", "core.fsmonitor", os.path.join(sent, "fsmonitor.sh"))
    git(r, "config", "diff.external", os.path.join(sent, "external.sh"))
    git(r, "config", "diff.evil.textconv", os.path.join(sent, "textconv.sh"))
    return r, sent


def _sentinels(sent):
    return sorted(n for n in os.listdir(sent) if not n.endswith(".sh"))


def test_hostile_repo_config_runs_nothing_in_the_gate():
    """Pins 7d78583: the repo's fsmonitor, diff.external and textconv do not run in the hook or in pr_check."""
    r, sent = _hostile_repo()
    # control: with the hostile config plain git RUNS the scripts; without this the test would prove nothing
    env = {**os.environ, **GIT_ENV}
    subprocess.run(["git", "-C", r, "status"], capture_output=True, env=env)
    subprocess.run(["git", "-C", r, "diff", "main...HEAD"], capture_output=True, env=env)
    subprocess.run(["git", "-C", r, "-c", "diff.external=", "diff", "--no-ext-diff", "main...HEAD"],
                   capture_output=True, env=env)
    assert _sentinels(sent) == ["external", "fsmonitor", "textconv"], _sentinels(sent)
    for n in _sentinels(sent):
        os.unlink(os.path.join(sent, n))

    cmd = f'gh pr create --title "{GOOD_TITLE}" --body-file good-body.md'
    assert decision(hook(bash(r, cmd), {"FAKE_GH_OUT": ""}))[0] == "allow"
    mcp = {"tool_name": "mcp__plugin_github_github__create_pull_request", "cwd": r,
           "tool_input": {"title": GOOD_TITLE, "body": GOOD_PT}}
    assert decision(hook(mcp))[0] == "allow"
    p = subprocess.run([sys.executable, "-I", "-B", CHECK, os.path.join(r, "good-body.md"), "--repo", r,
                        "--base", "main", "--title", GOOD_TITLE], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout
    assert pr_check.changed_files(r, "main") == ["app.py", "x.dat"]
    assert pr_check.detect_lang(r)[0] == "pt"
    assert _sentinels(sent) == [], _sentinels(sent)

    # the inventory reads the whole diff: diff.external and textconv would have run here
    p = subprocess.run([sys.executable, "-I", "-B", INVENTORY, "--repo", r, "--base", "main", "--format", "json"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    assert _sentinels(sent) == [], _sentinels(sent)


def test_every_git_call_of_the_gate_drops_fsmonitor_and_diff_has_no_external_driver():
    """Pins 7d78583 through argv: no git call from pr_check, the hook or the inventory omits
    `-c core.fsmonitor=false`, and every `diff` carries --no-ext-diff and --no-textconv (git only runs the
    fsmonitor script on `status`; the argv is the only proof the flag is still there)."""
    real = shutil.which("git")
    spy = tempfile.mkdtemp(prefix="pr-spy-")
    log = os.path.join(spy, "argv")
    with open(os.path.join(spy, "git"), "w") as fh:
        fh.write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec "{real}" "$@"\n')
    os.chmod(os.path.join(spy, "git"), 0o755)
    env = {**os.environ, **GIT_ENV, "PATH": spy + os.pathsep + os.environ["PATH"]}
    r = repo({"CLAUDE.md": "Títulos de PR em português.\n", "good-body.md": GOOD_PT, "a.py": "1\n"})
    git(r, "checkout", "-q", "-b", "feat")
    with open(os.path.join(r, "a.py"), "w") as fh:
        fh.write("2\n")
    git(r, "commit", "-q", "-am", "Change")

    def calls():
        with open(log) as fh:
            return [l.strip() for l in fh if l.strip()]

    subprocess.run([sys.executable, "-I", "-B", HOOK],
                   input=json.dumps(bash(r, f'gh pr create --title "{GOOD_TITLE}" --body-file good-body.md')),
                   capture_output=True, text=True, env={**env, "HOME": tempfile.mkdtemp()})
    subprocess.run([sys.executable, "-I", "-B", CHECK, os.path.join(r, "good-body.md"), "--repo", r, "--base", "main"],
                   capture_output=True, text=True, env=env)
    no_policy = repo(commits=["Corrige o login quando a senha tem acento"])  # the language comes from git log
    subprocess.run([sys.executable, "-I", "-B", CHECK, os.path.join(r, "good-body.md"), "--repo", no_policy],
                   capture_output=True, text=True, env=env)
    by_hook_and_check = calls()
    assert any(" diff " in f" {c} " for c in by_hook_and_check) and any("rev-parse" in c for c in by_hook_and_check) \
        and any(" log " in f" {c} " for c in by_hook_and_check), by_hook_and_check
    subprocess.run([sys.executable, "-I", "-B", INVENTORY, "--repo", r, "--base", "main"],
                   capture_output=True, text=True, env=env)
    all_calls = calls()
    assert len(all_calls) > len(by_hook_and_check), all_calls
    for c in all_calls:
        assert "-c core.fsmonitor=false" in c, c
        if " diff " in f" {c} ":
            assert "--no-ext-diff" in c and "--no-textconv" in c, c


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print("ok ", name)
    finally:
        shutil.rmtree(FAKE_BIN, ignore_errors=True)
