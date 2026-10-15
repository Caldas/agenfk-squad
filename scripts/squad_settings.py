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

A hook entry is the squad's when its command names one of the manifest's
scripts (by file name), whatever the path: entries registered by hand from
docs/installation.md are recognised, kept on install and removed on uninstall.
"""
import argparse
import json
import os
import shlex
import shutil
import sys
import time

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


def names_script(command, scripts):
    """True when the command runs one of these scripts (compared by file name)."""
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return any(os.path.basename(w) in scripts for w in words)


def command_for(config, script):
    return "python3 " + shlex.quote(os.path.join(config, "hooks", script))


def install(settings, config, plan, matchers, report):
    """Adds what is missing. Returns True when settings changed."""
    changed = False
    for event, wanted in plan.items():
        groups = settings.get("hooks", {}).get(event, [])
        missing = []
        for script, timeout in wanted:
            there = any(names_script(h.get("command"), {script})
                        for g in groups for h in g.get("hooks", []) if isinstance(h, dict))
            if there:
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


def uninstall(settings, scripts, report):
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
                    if not (isinstance(h, dict) and names_script(h.get("command"), scripts))]
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
    bak = None
    if os.path.exists(path):
        bak = backup_path(path)
        shutil.copy2(path, bak)
    target = os.path.realpath(path)          # a symlinked settings.json keeps its link
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    if os.path.exists(target):
        shutil.copymode(target, tmp)
    os.replace(tmp, target)
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
        changed = uninstall(settings, set(scripts), report)
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
