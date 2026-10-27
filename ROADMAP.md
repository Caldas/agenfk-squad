# Roadmap

Open problems, roughly in the order they hurt. None of these has an owner or a
date. If one interests you, open an issue to say you are taking it and how.

## Known gaps

### Waking a session outside herdr
The automatic session switch and the `MERGE TURN` prompt both need to type
into a terminal pane, and today that means herdr. Outside it, the handoff is
written and the owner types two commands; a queued session only sees its turn
on its next prompt.

*Wanted:* a small adapter interface (is the pane idle, which session is in it,
send this line) with implementations for tmux, Zellij, WezTerm and kitty, or a
way to do it through Claude Code itself with no terminal involved.

### Two sessions in the same worktree
"One session per card per worktree" is a rule in a prompt. The `github` agent
records a writer claim, but nothing stops a second session from editing the
same checkout.

*Wanted:* detection in `PreToolUse`. When a session is about to edit inside a
worktree where another live session has edited recently, deny the first edit
and say which session holds the tree and how to get a worktree of its own.

### Other harnesses
The agents are Markdown and the session report already reads Codex, pi and
oh-my-pi transcripts. The hooks speak only Claude Code's hook protocol.

Oh-my-pi (omp) is ported: `skills/harness-port/SKILL.md` renders the agents
into its task-agent contract, `hooks/squad-watch-omp.py` plus
`extensions/squad-watch-omp.ts` route its events into the watcher, and the
skill states which rules omp enforces mechanically and which it can only
advise.

*Wanted:* the same for Codex, pi, Gemini CLI or OpenCode. The arithmetic
(`handoff_math`) is harness-neutral; the event plumbing is not. A port should
say which rules the harness can enforce mechanically and which it can only
advise.

### An observe-only mode
There is no way to run the watcher so that it logs what it *would* have done
without doing it. That makes it hard to try on a machine you depend on.

*Wanted:* `SQUAD_WATCH=dry`, which writes each decision to a log and never
denies or blocks.

### The flow in the AgenFK registry
`flows/squad-delivery.json` has to be recreated by hand in the Flow Editor.

*Wanted:* the flow published to
[cglab-public/agenfk-flows](https://github.com/cglab-public/agenfk-flows) so
that `agenfk flow install squad-delivery.json` works, and kept in step with
this repository. Also worth exploring with upstream: step roles and checks, so
that AgenFK itself can require a suite run when leaving IMPLEMENT.

### Read-only agents that hold a shell
`product`, `verifier`, `finops`, `finance` and `gtm` are read-only by rule but
have `Bash`, which can write.

*Wanted:* per-agent permission rules that allow the read-only commands each
one needs (`git log`, `git diff`, the suite, `agenfk`, `gh pr view`) and deny
the rest. The verifier is the hard one: it mutates code to test the tests, so
it needs a scratch worktree it can write to and nothing else.

### Internationalisation
Everything is in English. The two regexes that read the owner's prompt accept
English and Portuguese.

*Wanted:* more languages in those two regexes. Translating the agents is a
different question, and an open one: is a prompt in the owner's language
better, or one in the language the model was mostly trained on?

## Open questions

These need data more than code.

- **Are the defaults right for a 200k window?** They were tuned at 1M. The
  floor arithmetic scales with the window, but the absolute ceilings
  (`SQUAD_CTX_CEILING`, the sub-session thresholds) do not.
- **Is reread share the right signal?** It is cheap to compute and matches
  cost. It says nothing about whether the model is reasoning worse, which is
  the other reason to hand off. Is there a cheap signal for that?
- **How good is the handoff?** A fresh session is only cheaper if it does not
  have to rediscover what the old one knew. Nobody has measured how much is
  lost across a handoff, or which template sections earn their tokens.
- **Does a second review ever change the outcome?** The cap is two rounds and
  six dispatches because of one bad week. A distribution across many cards
  would say what the cap should be.
- **Should the orchestrator limit be per machine or per repository?** Three
  orchestrators on one machine is a budget rule. Per repository it would be a
  collision rule. They may both be needed.
- **Teams.** Everything here assumes one owner and one machine. The merge
  queue is local state; two people on two machines get no queue at all.
  Should the turn live in the repository (a ref, a lock file, a PR label)?

## Smaller things

- macOS: untested. The hooks use `fcntl` and POSIX paths; reports welcome.
- Windows: supported natively (`get.ps1`, `install.ps1`, a Windows CI job);
  WSL behaves like Linux. Open on Windows: a session switch without herdr, a
  marked copy that becomes a link by itself when Developer Mode is turned on,
  and a hook command that works in PowerShell when only an absolute
  interpreter path is found. See [Known limitations on
  Windows](docs/installation.md#known-limitations-on-windows).
- `install.sh --uninstall` and `install.sh --dry-run`.
- A `squad-watch doctor` command that checks hook registration and prints the
  effective thresholds.
- A report that turns `metrics.jsonl` into the table at the top of the
  README, for your own machine.
- More tests around the session report (`session_context.py`); the suite
  covers the watcher far better than the report.

## Not planned

- A background daemon. Hooks see the call before it runs; a daemon does not.
- Dependencies in the hooks.
- Auto-merge, auto-apply or auto-deploy by any agent.
- A board, a flow engine or gates of our own. That is AgenFK's job.
