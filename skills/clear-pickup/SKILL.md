---
name: clear-pickup
description: "Handoff and pickup across a /clear. Writes a handoff file with ground truth (git state + session state) before the context is cleared, and reloads the most recent handoff to resume after /clear or /new. Use when the context window is filling up, when the Pi cockpit flashes HANDOFF, before /compact, when pausing work, or when resuming a session that was cleared. Triggers: handoff, pickup, clear-pickup, clear context, /clear, resume, where did I stop, where was I, save the session state, done for today."
---

# clear-pickup

One skill, two modes. Decide by what the user asked for:

- handoff / "save", "wrap up", "I'm going to /clear", "context is full" → **MODE A**
- pickup / "resume", "continue", "where did I stop", "what were we doing" → **MODE B**
- ambiguous → ask in one line which of the two.

## Rules

1. **Ground truth beats memory.** Run the git commands and read the files; do not rely on recollection for a SHA, branch, path or file name.
2. **Never overwrite an earlier handoff.** One file per handoff; the history is append-only.
3. **Short.** The next session pays tokens for this file. No code dump, no replay of the conversation.
4. **Nothing invented.** Whatever was not verified goes in as `UNKNOWN`.
5. **Nothing destructive in the handoff.** Do not commit, do not stash, do not delete anything unless the user asked for it.
6. Never clear the session yourself. You write the handoff; the `/clear` or `/new` belongs to the user.

## Where the handoff lives

- Project root: `git rev-parse --show-toplevel` (if it fails, use the current directory).
- Directory: `<root>/.claude/handoffs/`. If it is not writable, use `~/.claude/handoffs/`.
- Name: `YYYYMMDD-HHMMSS-<slug>.md`, with a kebab-case slug of up to 5 words taken from the subject of the session.

## MODE A — handoff (write)

**Step 1 — Collect the ground truth.** Run, without skipping any:

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse --short HEAD
git status --short
git log --oneline -5
git stash list
git diff --stat
```

**Step 2 — Fill in the template** below. Every item under "Current state" has to come from a command or from a file you read.

**Step 3 — Write it** to `<root>/.claude/handoffs/YYYYMMDD-HHMMSS-<slug>.md` (create the directory).

**Step 4 — Reply** with: the file path, a 1-line summary, and the exact resume command:

- Pi: `/new` and then `/skill:clear-pickup pickup`
- Claude Code: `/clear` and then `/clear-pickup pickup`

## MODE B — pickup (read)

**Step 1 — Find this project's most recent handoff:**

```bash
ls -t "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"/.claude/handoffs/*.md ~/.claude/handoffs/*.md 2>/dev/null | head -1
```

**Step 2 — Read the whole file.**

**Step 3 — Verify against the repository.** Does the branch match? Is the current HEAD equal to or a descendant of the recorded one? Are the dirty files still dirty? Record the drift explicitly (e.g. "handoff says HEAD abc123, repo is at def456 — 2 commits ahead"). Do not assume the handoff is wrong, nor that it is right: show the difference.

**Step 4 — Report** in at most 10 lines: goal, state, next step.

**Step 5 — Start** with the first action under "Next step". Ask before anything destructive or irreversible.

## Handoff template

```markdown
# Handoff — <subject>

- **When:** <ISO 8601 with time zone>
- **Project:** <root>
- **Branch:** <branch> @ <short sha>
- **Session:** <session name or id, if any>

## Goal
<1–3 sentences: what the user wants to achieve.>

## Current state
<Verified with git/files. Short list.>
- Done: <...>
- In progress: <...>
- Dirty in git: <files or "nothing">
- Blockers: <... or "none">

## Decisions
<Decisions made and why. Only what changes the next action.>

## Key files
<Paths the next session should read first, with 1 line on why.>

## Next step
1. <Concrete, verifiable action.>
2. <...>

## Useful commands
<Exact commands to validate or continue.>

## Do not
<Traps, attempts that failed, what to avoid.>
```

## Integration with the Pi cockpit (optional second harness)

When the Pi footer flashes `HANDOFF` (or shows `PREPARE HANDOFF`), this is the moment: run **MODE A** before starting another task. The alert only warns; it does not clear anything.

ARGUMENTS: $ARGUMENTS
