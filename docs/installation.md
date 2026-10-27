# Installation

The squad installs at the **user level** of Claude Code: it applies to every
project you open. Read this page once before running the installer, because
one of the things it links is your global `CLAUDE.md`.

## Requirements

| Needed | Why |
|---|---|
| [Claude Code](https://claude.com/claude-code) | The harness the agents and hooks run in |
| Python 3.10 or newer, as `python3` (`python` on Windows) | The hooks and the session report. Standard library only |
| `git` | Worktrees, the merge queue, the handoff's ground truth |
| [AgenFK](https://github.com/cglab-public/agenfk) | Cards, flow and gates. The agents call its CLI |
| Linux, macOS or Windows 10/11 | POSIX file locking (`fcntl`) on Linux and macOS, `msvcrt` file locking on Windows. Developed and run daily on Linux; macOS is untested; Windows has its own installer and its own CI job: see [Windows](#windows) |

### Optional dependencies

| Optional | What you get | Without it |
|---|---|---|
| **herdr** (a terminal pane manager for agent sessions) | The automatic session switch, and `MERGE TURN` delivered as a prompt into the waiting pane | The watcher still orders the handoff; you type `/clear` and `/clear-pickup pickup`. A queued session sees `MERGE TURN` on its next prompt |
| **GitHub CLI** (`gh`), logged in | The merge queue releases the turn as soon as the PR shows MERGED or CLOSED | The turn is released by `squad-turn release` or by timeout |
| A status line that writes `~/.claude/cache/session-tokens/<session>.json` with a `window` field | The watcher learns a window larger than 1M | Set `SQUAD_WINDOW` yourself |

## Install

On Windows, skip to [Windows](#windows): the commands below are for Linux,
macOS and WSL.

```bash
git clone https://github.com/eduardopin/agenfk-squad.git
cd agenfk-squad
./install.sh
```

Keep the clone. The installer creates **symlinks** into it, so the directory
has to stay where it is, and `git pull` is how you update.

### What the installer does

It links, into `${CLAUDE_CONFIG_DIR:-~/.claude}`:

| Link | Target |
|---|---|
| `agents/<name>.md` | each file in `agents/` |
| `skills/<name>` | each skill directory that has a `SKILL.md`, including those in `skills/vendor/` |
| `CLAUDE.md` | `CLAUDE.md` |
| `hooks/squad-router.py`, `squad-watch.py`, `squad-switch.py`, `squad-turn.py` | the four files in `hooks/` |

and, so that the merge queue can be called by name:

| Link | Target |
|---|---|
| `~/.local/bin/squad-turn` | `hooks/squad-turn.py` |

Make sure `~/.local/bin` is on your `PATH`.

### What it will not do

- **It never overwrites a real file.** If the destination exists and is not a
  symlink, it prints `SKIPPED`, leaves the file alone, and exits non-zero at
  the end so you notice.
- **It does not edit `settings.json`.** Registering the hooks is the next
  step, by hand.
- **It does not install AgenFK.** It warns if `agenfk` is not on your PATH.

It is idempotent: running it again refreshes the links.

### If you already have a `~/.claude/CLAUDE.md`

The installer skips it. You then have two options:

- **Merge by hand.** Copy the sections of this repository's `CLAUDE.md` into
  yours. You lose automatic updates of that file.
- **Import.** Keep your file and add a line that pulls the squad's rules in:

  ```markdown
  @/absolute/path/to/agenfk-squad/CLAUDE.md
  ```

The same applies to an agent or skill of yours with a clashing name: rename
yours, or leave the squad's one unlinked.

## Register the hooks

Add this to `~/.claude/settings.json`, merging with any `hooks` you already
have. Replace `~/.claude` with the absolute path if your shell does not expand
`~` inside the command.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-router.py", "timeout": 5 },
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 10 }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 10 }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 10 }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 10 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 10 }
        ]
      }
    ]
  }
}
```

| Script | Events |
|---|---|
| `squad-router.py` | `UserPromptSubmit` |
| `squad-watch.py` | `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `Stop` |

`squad-switch.py` and `squad-turn.py` are not registered: the watcher starts
them when needed.

You can adopt the squad in stages. The agents and skills work without any
hook. The router works without the watcher. The watcher works without herdr.

## Check it

Start a **new** Claude Code session (agents, skills and hooks are read at
session start) and:

```bash
# the report runs and lists your sessions
python3 skills/session-context/scripts/session_context.py

# the queue answers, from inside any git repository
squad-turn status

# the suite passes
python3 tests/test_watch.py
```

In the session, `/agents` should list the eleven squad agents, and a prompt
such as `how much is left on this epic?` should come back with a
`[squad route]` hint.

Then set up AgenFK for your project and activate the flow:
[agenfk-integration.md](agenfk-integration.md#setting-it-up).

## Update

```bash
cd agenfk-squad
git pull
./install.sh      # only needed when files were added or renamed
```

## Uninstall

Remove the hook entries from `settings.json`, then remove the links. This
deletes only symlinks that point into your clone:

```bash
SQUAD="$(pwd)"    # run from the agenfk-squad clone
find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" "$HOME/.local/bin" -maxdepth 2 -type l \
  -lname "$SQUAD/*" -print -delete
```

State under `~/.claude/squad/` is plain files; delete the directory if you
want it gone.

## Windows

The squad runs natively on Windows 10 and 11 with Claude Code for Windows.
`get.ps1` and `install.ps1` are the twins of `get.sh` and `install.sh`: same
steps, same refusals, no administrator rights.

### Requirements on Windows

| Needed | Notes |
|---|---|
| PowerShell 5.1 (the one every Windows has, and the one the CI tests) or PowerShell 7 | The commands below work in either |
| Python 3.10 or newer | Install it from python.org or `winget`. A stock Windows has a `python3` that is the **Microsoft Store** stub: it prints nothing and does nothing. Turn it off in Settings → Apps → Advanced app settings → App execution aliases (`python.exe` and `python3.exe`), or the installer will not trust it. The installer uses `SQUAD_PYTHON` if set, else a real `python`, else `py -3`; with none of them it stops and says what is missing |
| `git` | [Git for Windows](https://gitforwindows.org) |
| [AgenFK](https://github.com/cglab-public/agenfk) | As on Linux |
| Developer Mode (optional) | Settings → System → For developers. It lets the installer create symbolic links without administrator rights. Without it, directories become junctions and files become [marked copies](#known-limitations-on-windows) |

`core.autocrlf=true`, the default of Git for Windows, is fine: the
repository's `.gitattributes` keeps text files at LF (only `.cmd` and `.bat` files are CRLF), because
`skills/vendor/LOCK` pins the sha256 of LF bytes.

### Install on Windows

In a PowerShell window, not as administrator. A stock Windows client does not
let PowerShell run script files (execution policy `Restricted`), and the
installer runs the clone's `install.ps1`, so allow scripts for this window
only; it changes nothing permanent:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1 | iex
```

It checks `git` and Python, clones the repository to
`%USERPROFILE%\.local\share\agenfk-squad` (`SQUAD_HOME` moves it), runs the
clone's `install.ps1`, and registers the hooks from `hooks/manifest.json` in
`settings.json` with `scripts/squad_settings.py` (merge, idempotent, a backup
first, a `settings.json` that is not valid JSON is left alone). It never
closes your window: an error is reported and the prompt comes back.

To choose what to install, pass options through a script block (a pipe cannot
carry them):

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1))) -Beta
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1))) -Ref main
```

| Option | Same as | Installs |
|---|---|---|
| `-Stable` (default) | `SQUAD_CHANNEL=stable` | The latest `vX.Y.Z` tag on `main`, or `main` while there is none |
| `-Beta` | `SQUAD_CHANNEL=beta` | The `beta` branch |
| `-Ref <name>` | `SQUAD_REF=<name>` | A tag, a branch or a commit |

An option wins over its variable. `SQUAD_REPO` changes where to clone from,
`SQUAD_PYTHON` names the Python to use, `CLAUDE_CONFIG_DIR` moves Claude
Code's configuration directory (default `%USERPROFILE%\.claude`).

By hand, from a clone you made yourself, `install.ps1` links the files and,
like `install.sh`, leaves `settings.json` to you:

```powershell
git clone https://github.com/eduardopin/agenfk-squad.git
cd agenfk-squad
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
python scripts\squad_settings.py check
python scripts\squad_settings.py install
```

`install.ps1 -NoSymlink` skips symbolic links (junctions and marked copies
only); `-ConfigDir <path>` installs somewhere other than `%USERPROFILE%\.claude`.

What `install.ps1` makes, and what it refuses, is what `install.sh` does:
a real file in the way is `SKIPPED` and the exit code is 1; a source that
resolves outside the repository is `REFUSED`. Two things are Windows-only:

- `squad-turn` is a `squad-turn.cmd` in `%USERPROFILE%\.local\bin` that runs
  `hooks\squad-turn.py` with the interpreter it found. Put that directory on
  your `PATH` (Settings → System → About → Advanced system settings →
  Environment Variables → your user's `Path` → Edit → New), then open a new
  window; `squad-turn status` in the check below fails until you do. The
  installer warns while it is missing.
- The hook commands in `settings.json` read `python "C:/.../hooks/squad-watch.py"`
  (forward slashes, `python` rather than `python3`). An old entry written as
  `python3 ...` is rewritten, because on Windows it would run the Store stub
  and do nothing.

Check it the way [Check it](#check-it) says, with `python` for `python3`:

```powershell
python skills\session-context\scripts\session_context.py
squad-turn status
python tests\test_watch_windows.py
```

### Update on Windows

Run the same command again, with the same option: without one it means
`-Stable`, so a `-Beta` or `-Ref` install would be moved to the latest stable
tag. It fetches, checks out what you asked for and runs `install.ps1`. A clone with local changes is refused, never overwritten. If
you installed by hand: `git pull`, then `install.ps1` again, as in the previous section.

### Uninstall on Windows

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1))) -Uninstall
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.ps1))) -Uninstall -Purge
```

`-Uninstall` removes the squad's entries from `settings.json` (and nobody
else's), the links into the clone, the `squad-turn.cmd` shim, and the marked
copies that you did not edit (an edited copy is kept, with a warning); the
clone stays. `-Purge` deletes the clone too, unless it has local changes: then
it refuses and you delete it by hand. By hand:
`powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall`
and `python scripts\squad_settings.py uninstall`.
State under `%USERPROFILE%\.claude\squad` is plain files; delete the
directory if you want it gone.

### Known limitations on Windows

- **No herdr.** There is no herdr on Windows, so the automatic session
  switch does not run. The watcher still orders the handoff and writes it;
  you type `/clear` and then `/clear-pickup pickup`. `MERGE TURN` reaches a
  queued session on its next prompt. Everything else in the watcher is the
  same.
- **No chmod.** The squad's state under `%USERPROFILE%\.claude\squad` is
  protected by your profile's folder permissions (ACLs), not by mode bits:
  the `0600` and `0700` the Linux hooks set are not applied, and the
  "owned by me" checks rely on that profile boundary. Do not point
  `CLAUDE_CONFIG_DIR` at a folder other users can write to.
- **A marked copy is not a link.** Without Developer Mode a file cannot be a
  symbolic link, so `install.ps1` copies it and records the copy and its
  sha256 in `%USERPROFILE%\.claude\squad\copies.txt`. `git pull` does not
  update a copy: run the installer again, which refreshes the copies you did
  not edit and leaves an edited one alone (it prints `SKIPPED`). The
  installer does not turn a copy into a link after you enable Developer Mode:
  run `install.ps1 -Uninstall` once, then install again.
- **A hook command that falls back to an absolute interpreter path** (neither
  `python` nor `py -3` found) is a quoted path
  (`"C:/.../python.exe" "C:/.../hooks/squad-watch.py"`). A shell like Git Bash
  runs that; PowerShell would need a `&` in front, so the entry does nothing
  if your hooks run through PowerShell. Install a Python that puts `python`
  on `PATH` and that case never happens.
- **Clones made with CRLF line endings.** A clone made before the repository
  had `.gitattributes`, with `core.autocrlf=true`, holds CRLF files and fails
  the vendor check. Commit or stash your changes, update the clone to a
  commit that has `.gitattributes` (run the install command again), then
  renormalize it. This rewrites the work tree, so nothing uncommitted
  survives:

  ```powershell
  git rm --cached -r -q .
  git reset --hard -q
  ```

  A fresh clone is already right.
- **Detached helpers.** The session switch and the merge-queue helper start
  as detached processes, without a console window. If a tool runs your
  terminal inside a job object that kills its children when it closes, a
  helper dies with the window.

### WSL

WSL is for when Claude Code itself runs **inside WSL**: there it is Linux, so
use `get.sh` and `install.sh` and the instructions above this section, and
nothing here applies. WSL and Windows have separate homes (`/home/<you>` and
`%USERPROFILE%`), so a squad installed on one is not installed on the other,
and the two do not share `~/.claude`. Claude Code for Windows with the squad
in WSL, or the reverse, does not work: install it where Claude Code runs.

## Turning parts off without uninstalling

```bash
export SQUAD_WATCH=0     # the whole watcher
export SQUAD_SWITCH=0    # only the automatic session switch
export SQUAD_TURN=0      # only the merge queue
```

All variables: [configuration.md](configuration.md).

## A note on "the cockpit"

Some files mention a *cockpit*. It is the author's Claude Code status line,
which shows the same numbers the watcher computes (context, burn, reread
share) and records each session's real window. It is not part of this
repository and nothing here needs it: the watcher reads the transcripts
itself.

## Troubleshooting

| Symptom | Look at |
|---|---|
| No `[squad-watch]` messages at all | Is the hook registered for the event? Is `SQUAD_WATCH=0` set? `~/.claude/squad/watch-errors.log` |
| The handoff was ordered but the session did not switch | `~/.claude/squad/switches.log` says which check gave up. Outside herdr, this is expected |
| `squad-turn: command not found` | `~/.local/bin` is not on your `PATH` |
| A merge is denied and nobody seems to hold the turn | `squad-turn status`. A stale turn clears by itself after `SQUAD_TURN_IDLE` seconds |
| The handoff comes too early or too late | `session_context.py --session <id> --detail` shows the numbers the watcher used. Then [configuration.md](configuration.md#choosing-your-own-numbers) |
| An agent is not picked for a request | A project agent with the same role wins. Otherwise check the `description` in `agents/<name>.md` |
