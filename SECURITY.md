# Security

## What this project runs on your machine

Be clear-eyed about it before installing:

- `hooks/squad-watch.py` runs **before and after every tool call** of every
  Claude Code session, with your user's permissions. It reads session
  transcripts, reads and writes state under `~/.claude/squad/`, and runs
  `git` and `gh` in the session's working directory.
- `hooks/squad-switch.py` **types into a terminal pane** (through herdr):
  `/clear`, then `/clear-pickup pickup <file>`.
- `hooks/squad-turn.py call` types a fixed prompt into a pane.
- Whatever the watcher prints is read by a model **as trusted context**.

That last point is the main attack surface. A string the watcher echoes from a
transcript, a branch name, a PR title or an agent name could carry
instructions to the model. The code defends against that:

- names from hook payloads are stripped of control characters and escape
  sequences and truncated before being printed;
- branch names and PR numbers are matched against strict patterns before
  being passed to `git` or `gh`, which are always called with an argument
  list, never through a shell;
- the session switch sends the pickup a **read-only copy** of the handoff,
  verified by SHA-256, written by that same session after the alert, and never
  "the most recent file in a directory";
- before typing, the switch checks that the pane still hosts the same session;
- merge and sync commands are recognised only in command position, not inside
  quoted text;
- every hook fails open and silent.

## What counts as a vulnerability

Please report, privately:

- any way to make a hook **print attacker-controlled text** to a session
  (from a repository's contents, a branch or file name, a PR, a transcript, a
  handoff file);
- any way to make the session switch or the merge queue **type into the wrong
  pane**, or send a command other than the two fixed ones;
- **command injection** or path traversal through anything a hook reads;
- any way for one session to **forge or steal** another's merge turn or state
  in a manner that causes a destructive action;
- a state or handoff file being written with permissions that expose it to
  other users.

A rule that is too strict or too loose is a bug, not a vulnerability: open a
normal issue.

## Reporting

Use GitHub's private vulnerability reporting for this repository:
**Security → Report a vulnerability**
(<https://github.com/eduardopin/agenfk-squad/security/advisories/new>).

Please do not open a public issue for a vulnerability. Include the version
(commit SHA), what you did, and what happened. You should hear back within a
week. This is a one-maintainer project; there is no bounty.

## Supported versions

Only the `main` branch.

## Vulnerabilities in AgenFK or Claude Code

Report those to their own projects:
[AgenFK](https://github.com/cglab-public/agenfk/security) and
[Anthropic](https://www.anthropic.com/responsible-disclosure-policy).
