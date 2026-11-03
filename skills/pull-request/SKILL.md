---
name: pull-request
description: The squad's method for writing and reviewing pull requests. A title that states the outcome (never a branch name, phase or card title), an opening paragraph, ten sections that are always present with "None." + reason, the infrastructure-PR rule, the repository's language (en or pt), the `pr_check.py` gate and an optional PreToolUse hook on `gh pr create|edit`, `agenfk pr create` and the MCP create-PR tool; a review on four axes (practices, blast radius, security, risk of applying against risk of not applying). Use before every `gh pr create`, `gh pr edit` or `agenfk pr create`, and for "open the PR", "write the PR description", "fix the PR title", "review PR 12", "draft the pull request", "abre o PR", "revisa o PR".
---

# pull-request: the title states the outcome, the body proves it with facts

The failure this method prevents: a PR with a planning title ("Phase 6",
"pull-request skill adapted to the squad", `feature/x`) and a body written from
memory, which forces the reviewer to open the diff to learn what changes, and
where "tests passing" points at no command. The second failure: a review that
vetoes on style and lets the blast radius through.

Two jobs: **Write** (open or edit a PR) and **Review** (read someone's PR, or
your own before asking for approval, and draft the verdict).

`$PR` below is this skill's directory: `~/.claude/skills/pull-request`.

## 0. The project decides

- The project's `CLAUDE.md` / `AGENTS.md` and project skills (`.claude/skills/`)
  win over this one. A project with its own PR skill (for example a
  `acme-pr-delivery` skill with an English-only gate) or its own hook that
  mentions `gh pr create` uses its own: this hook steps aside by itself
  (section 9).
- **Repository template.** `.github/pull_request_template.md` (and the other
  usual locations) adds sections to the ten; whatever is left over becomes an
  extra section after Tests. The heading comparison is not done here: the gate
  calls `template_problems` from the **`pr-evidence`** skill, which reports
  `TEMPLATE_SECTION_MISSING` and `TEMPLATE_SECTION_EMPTY`. Install `pr-evidence`
  next to this skill; without it the gate blocks with `TEMPLATE_CHECKER_MISSING`.
  This skill only finds and reads the template safely: a template outside the
  repository, not a regular file or larger than 128 KiB blocks with
  `TEMPLATE_UNREADABLE`.
- **PR language**, in this order: what the owner asked for > the language of
  the existing PR (when editing) > the repository's rule (CLAUDE.md /
  AGENTS.md, or the latest PR and commit titles) > English.
  `pr_check.py --lang auto` does this math (section 2).
- If you run a prose linter, pass the title and body through it before opening.

## 1. Who uses it, in the squad

| Agent | What it does with this skill |
|---|---|
| `github` | Builds the body and **opens** the PR, only after the `verifier`'s SHIP and when the flow step asks for it |
| `verifier` | **Reviews** (section 8); a Blocking finding becomes FIX_FIRST or REJECT, the rest becomes a comment |
| `developer`, `frontend`, `tester`, `infra`, `finops` | Deliver the facts the body cites: diff, suite, `plan`, scans, quote |

Nobody in the squad merges, posts a review or a comment on GitHub, or
publishes without the owner confirming, on the owner's own PR too (squad
rule 5).

## 2. Language

```bash
python3 -I "$PR/scripts/pr_check.py" body.md --title "<title>" --repo .   # --lang auto
```

`--lang auto` reads, in order: the CLAUDE.md / AGENTS.md line that talks about
PRs, titles or commits and names a language; the majority of the last 10 PR
titles (`gh pr list`); the majority of the last 10 commits; otherwise en. The
output says where it came from (`language en (CLAUDE.md)`). `--lang en|pt`
forces it.

The language decides the title rules. Section names are accepted in English
and Portuguese; `templates/body.md` is the English body.

## 3. Write

1. **Title from the change, not from the plan.** Read the diff and write the
   outcome in one line (section 4). Never reuse a branch name, the card title
   or the ticket summary.
2. **Facts before text.** Each table comes from a command
   (`references/evidence.md`):
   - `agenfk get <id> --json`: what the card asks for and its acceptance criteria;
   - the `verifier`'s report (SHIP, reproduced suite);
   - `agenfk log-test` recorded by the `tester`: suites and counts;
   - the `finops` quote: Cost, when there is a cloud resource;
   - `python3 -I "$PR/scripts/inventory.py" --repo . --base main`: resources and
     functions the branch creates and deletes;
   - the `infra` `plan`, scans, `gh pr checks`.
   A number no command measured does not go in.
3. **Copy the template** out of the repository and fill it in.
4. **Run the gate** and fix sentence by sentence, never rewriting everything:

   ```bash
   python3 -I "$PR/scripts/pr_check.py" body.md --title "<title>" --repo .
   ```

5. **Opening belongs to `github`**, after SHIP:

   ```bash
   agenfk pr create <id> --title "<title>" --body "$(cat body.md)" --model <id> --harness <name>
   gh pr create --title "<title>" --body-file body.md
   ```

   Always pass `--title`: without it `agenfk` uses the card title, which is
   planning vocabulary. A corrected title goes in with `gh pr edit --title` and
   passes the same gate.

## 4. Title

One line, up to 72 characters, that says what the PR does and for whom or
where. Someone who never saw the card has to understand the change from the
title alone.

| | English | Portuguese |
|---|---|---|
| Shape | Opens with an imperative verb | A sentence with a verb, in any position |
| Good | `Move dealer exports to a background job` | `O aviso do tour guiado passou a aparecer uma vez só` |
| | `Deny Terraform apply in the agent` | `Move a exportação para um job em segundo plano` |
| Card or phase id | Ticket prefix (`ABC-12: ...`) where the repo uses one; suffix `(F6-B4)` | **Only** a suffix in parentheses: `... em segundo plano (F6-B4)` |

A conventional prefix (`feat(export): ...`, `watch: ...`) is decoration: what
follows has to stand on its own. Never:

- a branch name or the card title (`agenfk pr create` uses the card title if
  you do not pass `--title`);
- a phase, step, wave or workstream label (`phase 6`, `Wave 1`, `F6-B4:` at the start);
- a Terraform address or code identifier (`aws_s3_bucket.exports`) in place of
  the thing it names;
- a sentence with no verb (`Permissions for the six roles`);
- the agent's activity (`Adding ...`);
- the other language.

`pr_check.py` refuses each failure with its code: `TITLE_NO_VERB`,
`TITLE_ACTIVITY`, `TITLE_BRANCH_NAME`, `TITLE_STEP_LABEL`, `TITLE_ID_PREFIX`,
`TITLE_CODE_IDENTIFIER`, `TITLE_NOT_ENGLISH`, `TITLE_NOT_PORTUGUESE`,
`TITLE_GENERIC`, `TITLE_SHORT`, `TITLE_LONG`, `TITLE_TICKET_ONLY`,
`TITLE_TRUNCATED`. Before opening, read only the title and say what changed
and for whom. If you cannot, rewrite it.

## 5. Opening paragraph

The first thing in the body, before any section heading. From 12 to 120
words, in words an outsider understands: what is wrong or missing today, what
the PR changes and what it leaves out. No "This PR ...".

## 6. The ten sections

Always present, always in this order. When one does not apply, the heading
stays and the content is `None.` followed by the reason on the same line, so
the reviewer can tell "checked, there is nothing" from "forgot".

| Section | Content |
|---|---|
| Before and after | Table with `Before` and `After` columns per changed resource or behaviour |
| Resources created | Table: resource, type, environment, purpose |
| Resources deleted | Table: resource, type, environment, why |
| State and flow | `### State`: mermaid `stateDiagram-v2`. `### Flow`: mermaid `flowchart` or `sequenceDiagram` |
| Functions created and deleted | Table: function, file, change, purpose |
| Cost | Monthly cost. An infrastructure PR states a dollar amount, even US$ 0.00 |
| Risk analysis | Rows: risk of applying, risk of not applying, blast radius, rollback |
| Practices applied | Table: practice, **source** (the document, standard or skill that asks for it), where |
| Scans | One row each for Lint, Semgrep, Trivy and Secrets (gitleaks): the result, or `Did not run` and the reason |
| Tests | Table: suite, command, counts. Never "tests passing" without a number |

## 7. Infrastructure PR

A PR is infrastructure when it changes `.tf`, `.tfvars`, `.hcl`, `.bicep`, a
Helm chart (`Chart.yaml`, `charts/<name>/values*.yaml`,
`charts/<name>/templates/`), `kustomization.yaml`, `Pulumi.yaml`, `cdk.json`,
`samconfig.toml` or `serverless.yml`. CDK or SAM code without the marker file
is not detected: pass `--kind infra`.

An infrastructure PR **carries no adversarial or mutation tests**: do not run
them, do not list them; `pr_check.py` refuses a Tests section that cites them
(`TESTS_FORBIDDEN`). The evidence is the `plan` summary, `terraform validate`,
`terraform test` and the scans. `infra` stops at `plan` and never applies; a
new cloud resource has a `finops` quote first, and that quote is the source of
the Cost section.

## 8. Review

Follow `references/review.md`. In short: collect the PR with `gh`, check title
and body with `pr_check.py --files`, and judge four axes.

| Axis | Question |
|---|---|
| Practices | Does the change follow the documents that govern it, each one named? |
| Blast radius | What can break, in which accounts and environments, for how many users or services? |
| Security | Identity, exposure, data, secrets, supply chain, injection |
| Risk of applying against risk of not applying | Which side is bigger, and does a revert undo the merge? |

Severity is narrow on purpose. **Blocking**: breakage, a security exposure or
a regression risk (the exact list is in the reference). **Minor**: everything
else worth saying; a comment, not a veto. Never block on style, documentation,
naming or the title.

In the squad the `verifier` reviews: a Blocking finding fixable on the branch
becomes **FIX_FIRST**; a Blocking finding that hits its automatic REJECT
(committed secret, real network in the suite, a test removed without an
argument, a forbidden path) becomes **REJECT**; with no Blocking finding,
**SHIP** with the Minor ones as warnings. Check each finding in the code
before writing it.

`scripts/review_comments.py` builds the review payload with inline comments.
**Posting** (`gh api .../reviews`) only happens after the owner reads the
draft and confirms, on the owner's own PR too.

### A review tied to a commit, and the response cycle

Load `pr-evidence` to review, respond, or say a PR is ready. It checks the
review/checks/threads snapshot on the current head, not markers in text. The
author does not approve themselves; a push invalidates earlier evidence. Two
rounds at most, then it is the owner's decision. Comments and resolving
threads still need confirmation, on your own PR too. There is no automatic
posting and no waking of sessions. An incomplete snapshot never becomes green.

## 9. The gate (optional hook)

`hooks/pr_gate.py` is a PreToolUse hook that runs `pr_check.py` before:

- Bash with `gh pr create`, `gh pr new`, `gh pr edit` (with a title or body)
  and `agenfk pr create`, in command position; `grep "gh pr create"`, a commit
  message or a heredoc do not count;
- the MCP tool `mcp__plugin_github_github__create_pull_request`.

Failed: it denies the call with the codes. Passed: the normal permission flow
carries on. A body the gate cannot read (stdin, `$(command)`, `--web`,
`--fill`) is denied with the instruction to use `--body-file`.

It **steps aside** (exits 0, silent) when:

- the repository has its own PR gate: a skill in `.claude/skills/` with the
  token `pr` or `pull-request` in its name (`acme-pr-delivery` yes,
  `prs-stack` no), or a file in `.claude/hooks/` or `.claude/settings*.json`
  that mentions `gh pr create`;
- `SQUAD_PR_GATE=0` is set in the environment;
- the gate itself breaks: an internal error comes out as a warning on stderr
  and the call goes ahead.

Registering the hook is **the owner's decision** (the squad does not edit
settings, and `install.sh` does not register it). The snippet, for when the
owner decides:

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__plugin_github_github__create_pull_request",
  "hooks": [{"type": "command",
             "command": "python3 -I ~/.claude/skills/pull-request/hooks/pr_gate.py"}]}]}}
```

## 10. Files

| Path | Use |
|---|---|
| `templates/body.md` | The body to copy |
| `references/evidence.md` | Where each section's facts come from, with commands |
| `references/review.md` | Review procedure, severities, draft format |
| `scripts/pr_check.py` | Title and body gate; exits 1 with the problem codes |
| `scripts/inventory.py` | Resources and functions the branch creates, deletes or changes |
| `scripts/review_comments.py` | Findings → review payload with inline comments (does not post) |
| `hooks/pr_gate.py` | The PreToolUse hook described in section 9 |

All standard-library Python, run with `python3 -I`. Tests:
`python3 tests/test_pull_request.py` and `python3 tests/test_repository_template.py`
in the squad repository.
