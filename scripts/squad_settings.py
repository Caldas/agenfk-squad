#!/usr/bin/env python3
"""Registers and removes the squad's hooks in Claude Code's settings.json.

The hooks and their events come from hooks/manifest.json; nothing here lists
them. Standard library only. Used by get.sh, and safe to run by hand:

    python3 scripts/squad_settings.py check     [--config DIR]
    python3 scripts/squad_settings.py install   [--config DIR] [--manifest FILE]
    python3 scripts/squad_settings.py uninstall [--config DIR] [--manifest FILE]

--config defaults to ${CLAUDE_CONFIG_DIR:-~/.claude}; the file is
<config>/settings.json, and each hook command runs <config>/hooks/<script>,
the link that install.sh creates.

Guarantees:
  - every other key, and every hook that is not the squad's, stays as it was;
  - running install twice changes nothing the second time (no write at all);
  - before any write, the current file is copied to settings.json.bak-<timestamp>;
  - a settings.json that is not valid JSON, or not shaped like Claude Code's
    settings, is never written: the command stops with exit code 2;
  - a settings.json that is a symlink stays a symlink: its target is updated.

A hook entry is the squad's only when its command is `python3 <path>` (or
`python <path>`), nothing more, and <path>, after ~ and $VARS are expanded,
is <config>/hooks/<script> for one of the manifest's scripts, or resolves to
one of them inside the clone this script belongs to. So the entries from
docs/installation.md (`python3 ~/.claude/hooks/squad-watch.py`) are
recognised, kept on install and removed on uninstall, while a hook of the
user's that merely shares a file name (`python3 /opt/mine/squad-watch.py`,
`grep squad-router.py log`) is never touched.
"""
import contextlib
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

WINDOWS = os.name == "nt"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "hooks", "manifest.json")


class Refused(Exception):
    """settings.json cannot be edited safely; nothing was written."""


def default_config():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def load_manifest(path):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    matchers = m.get("matchers", {})
    plan = {}                                # event -> [(script, timeout)], in manifest order
    for h in m["hooks"]:
        for event in h["events"]:
            plan.setdefault(event, []).append((h["script"], h.get("timeout")))
    return plan, matchers, [h["script"] for h in m["hooks"]]


def load_settings(path):
    """The parsed settings ({} when the file does not exist). Raises Refused."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            settings = json.load(fh)
    except ValueError as e:
        raise Refused(f"{path} is not valid JSON ({e}). Fix it, then run again.") from None
    where = check_shape(settings)
    if where:
        raise Refused(f"{path}: {where}, which is not the shape Claude Code uses. "
                      "Fix it, then run again.")
    return settings


def check_shape(settings):
    """Where the settings stop looking like Claude Code's, or None."""
    if not isinstance(settings, dict):
        return "the top level is not an object"
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return '"hooks" is not an object'
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            return f'"hooks.{event}" is not a list'
        for i, g in enumerate(groups):
            if not isinstance(g, dict) or not isinstance(g.get("hooks", []), list):
                return f'"hooks.{event}[{i}]" is not an object with a "hooks" list'
    return None


def squad_script(command, config, clone=ROOT, windows=None):
    """The squad script this hook command runs, or None when it is not the squad's."""
    if not isinstance(command, str):
        return None
    windows = WINDOWS if windows is None else windows
    words = split_command(command, windows)
    if not words or not is_interpreter(words[0], windows) or len(words) not in (2, 3):
        return None
    if len(words) == 3 and not (windows and words[1] == "-3" and interpreter_name(words[0]) == "py"):
        return None                          # only the launcher takes a flag: `py -3 <script>`
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(words[-1])))
    script = os.path.basename(path)
    if windows:
        script = script.lower()              # the manifest names are lowercase and the file system does not care
    linked = os.path.join(config, "hooks", script)
    real = os.path.normcase(os.path.realpath(path))
    mine = (os.path.realpath(linked), os.path.join(os.path.realpath(clone), "hooks", script))
    if real in tuple(os.path.normcase(m) for m in mine):
        return script
    return None


def split_command(command, windows=None):
    """The words of a hook command, or None when it cannot be read. On Windows a
    backslash is a path separator, not an escape, and the quotes stay for us to strip."""
    windows = WINDOWS if windows is None else windows
    try:
        words = shlex.split(command, posix=not windows)
    except ValueError:
        return None
    if windows:
        words = [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]
    return words


def interpreter_name(word):
    """`C:/Python314/python.exe` -> `python`."""
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def is_interpreter(word, windows=None):
    windows = WINDOWS if windows is None else windows
    name = interpreter_name(word)
    if windows:
        return name in ("python", "python3", "py", "pythonw")
    return word in ("python3", "python")


def launcher_has_python3():
    """The `py` launcher can be on PATH with no Python 3 behind it."""
    try:
        return subprocess.run(["py", "-3", "-c", "pass"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def interpreter(windows=None, which=shutil.which, executable=sys.executable, probe=launcher_has_python3):
    """What a hook command starts with. `python3` is the Microsoft Store stub on a stock Windows, so there it is
    `python` when that is a real install, else the `py` launcher (when it has a Python 3), else the interpreter
    running this script, by absolute path. That last form needs a shell that runs a quoted path (Git Bash does;
    PowerShell wants `& `), which is why it is the last resort."""
    windows = WINDOWS if windows is None else windows
    if not windows:
        return "python3"
    found = which("python")
    if found and "windowsapps" not in found.replace("/", "\\").lower():
        return "python"
    if which("py") and probe():
        return "py -3"
    return '"' + executable.replace("\\", "/") + '"'


def command_for(config, script, windows=None, launcher=None):
    windows = WINDOWS if windows is None else windows
    path = os.path.join(config, "hooks", script)
    if windows:
        return f'{launcher or interpreter(True)} "{path.replace(chr(92), "/")}"'
    return "python3 " + shlex.quote(path)


def repair_stale(groups, config, script, windows=None):
    """On Windows an entry written as `python3 ...` runs the Microsoft Store stub and does nothing: point it at
    a real interpreter. Returns how many entries were rewritten."""
    windows = WINDOWS if windows is None else windows
    fixed = 0
    for g in groups:
        for h in g.get("hooks", []):
            if isinstance(h, dict) and squad_script(h.get("command"), config, windows=windows) == script:
                words = split_command(h["command"], windows)
                if windows and interpreter_name(words[0]) == "python3":
                    h["command"] = command_for(config, script, windows=True)
                    fixed += 1
    return fixed


def install(settings, config, plan, matchers, report):
    """Adds what is missing. Returns True when settings changed."""
    changed = False
    for event, wanted in plan.items():
        groups = settings.get("hooks", {}).get(event, [])
        missing = []
        for script, timeout in wanted:
            there = any(squad_script(h.get("command"), config) == script
                        for g in groups for h in g.get("hooks", []) if isinstance(h, dict))
            if there:
                if repair_stale(groups, config, script):
                    changed = True
                    report.append(f"fixed   {script:<16} {event} (was `python3`, the Microsoft Store stub)")
                    continue
                report.append(f"on      {script:<16} {event} (already registered)")
            elif not os.path.exists(os.path.join(config, "hooks", script)):
                report.append(f"SKIPPED {script:<16} {event}: {os.path.join(config, 'hooks', script)} "
                              "does not exist (did install.sh skip it?)")
            else:
                entry = {"type": "command", "command": command_for(config, script)}
                if timeout:
                    entry["timeout"] = timeout
                missing.append(entry)
                report.append(f"on      {script:<16} {event} (added)")
        if missing:
            group = {"matcher": matchers[event]} if event in matchers else {}
            group["hooks"] = missing
            settings.setdefault("hooks", {}).setdefault(event, []).append(group)
            changed = True
    return changed


def uninstall(settings, config, scripts, report):
    """Removes every hook entry that runs one of the squad's scripts, then the
    groups and events that only held those. Returns True when settings changed."""
    hooks = settings.get("hooks")
    if not hooks:
        return False
    changed = False
    for event in list(hooks):
        groups = hooks[event]
        kept_groups = []
        for g in groups:
            entries = g.get("hooks", [])
            kept = [h for h in entries
                    if not (isinstance(h, dict) and squad_script(h.get("command"), config) in scripts)]
            for h in entries:
                if h not in kept:
                    report.append(f"off     {event}: {h.get('command')}")
            if len(kept) == len(entries):
                kept_groups.append(g)
            elif kept:
                kept_groups.append(dict(g, hooks=kept))
        if kept_groups != groups:
            changed = True
            if kept_groups:
                hooks[event] = kept_groups
            else:                            # it only held the squad's hooks
                del hooks[event]
    if changed and not hooks:
        del settings["hooks"]
    return changed


def backup_path(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate, n = f"{path}.bak-{stamp}", 1
    while os.path.exists(candidate):
        candidate, n = f"{path}.bak-{stamp}-{n}", n + 1
    return candidate


def write(path, settings):
    """Backs the current file up, then replaces it atomically. Returns the backup path."""
    text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    bak = None
    if os.path.exists(path):
        bak = backup_path(path)
        shutil.copy2(path, bak)
    target = os.path.realpath(path)          # a symlinked settings.json keeps its link
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        if os.path.exists(target):
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return bak


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["check", "install", "uninstall"])
    ap.add_argument("--config", default=None, help="Claude Code config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    ap.add_argument("--manifest", default=MANIFEST, help="hook manifest (default: hooks/manifest.json next to this script)")
    a = ap.parse_args(argv)
    config = os.path.abspath(a.config or default_config())
    path = os.path.join(config, "settings.json")
    try:
        settings = load_settings(path)
    except Refused as e:
        print(f"ERROR   {e}", file=sys.stderr)
        return 2
    if a.action == "check":
        return 0
    plan, matchers, scripts = load_manifest(a.manifest)
    report = []
    if a.action == "install":
        changed = install(settings, config, plan, matchers, report)
    else:
        changed = uninstall(settings, config, set(scripts), report)
    for line in report:
        print(line)
    if changed:
        bak = write(path, settings)
        print(f"wrote   {path}" + (f" (backup: {bak})" if bak else ""))
    else:
        print(f"same    {path} (nothing to change)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
