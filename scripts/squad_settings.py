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

The manifest decides each squad hook's matcher: a hook's own "matchers"
({event: matcher}, where null means no matcher) wins over the top-level one.
A squad entry found under any other matcher on that event (moved by hand, or
left by an older manifest) is moved to the manifest's, so a narrow hook never
stays registered on every tool call.
"""
import contextlib
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


class BadManifest(Exception):
    """The hook manifest says something install cannot act on; nothing was written."""


def default_config():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def load_manifest(path):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    matchers = m.get("matchers", {})
    plan = {}                                # event -> [(script, timeout, matcher)], in manifest order
    for h in m["hooks"]:
        own = h.get("matchers", {})          # a hook's own matcher wins for its event
        if not isinstance(own, dict):
            raise BadManifest(f'{path}: "matchers" of {h["script"]} is not an object')
        unknown = set(own) - set(h["events"])
        if unknown:                          # a typo here would fall back to the broad matcher
            raise BadManifest(f'{path}: {h["script"]} has matchers for events it does not list: '
                              f'{", ".join(sorted(unknown))}')
        for event in h["events"]:
            matcher = own.get(event, matchers.get(event))
            if matcher is not None and not isinstance(matcher, str):
                raise BadManifest(f'{path}: the matcher of {h["script"]} on {event} is not a string: {matcher!r}')
            plan.setdefault(event, []).append((h["script"], h.get("timeout"), matcher))
    return plan, [h["script"] for h in m["hooks"]]


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


def squad_script(command, config, clone=ROOT):
    """The squad script this hook command runs, or None when it is not the squad's."""
    if not isinstance(command, str):
        return None
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if len(words) != 2 or words[0] not in ("python3", "python"):
        return None
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(words[1])))
    script = os.path.basename(path)
    linked = os.path.join(config, "hooks", script)
    real = os.path.realpath(path)
    if real in (os.path.realpath(linked), os.path.join(os.path.realpath(clone), "hooks", script)):
        return script
    return None


def command_for(config, script):
    return "python3 " + shlex.quote(os.path.join(config, "hooks", script))


def runs(group, script, config):
    return any(isinstance(h, dict) and squad_script(h.get("command"), config) == script
               for h in group.get("hooks", []))


def drop(settings, event, script, config, matcher):
    """Removes this script's entries from the event's groups under any matcher
    but this one, and the groups that only held them. Every other entry keeps
    its group and its place."""
    kept = []
    for g in settings["hooks"][event]:
        if g.get("matcher") == matcher:
            kept.append(g)
            continue
        entries = [h for h in g.get("hooks", [])
                   if not (isinstance(h, dict) and squad_script(h.get("command"), config) == script)]
        if len(entries) == len(g.get("hooks", [])):
            kept.append(g)
        elif entries:
            kept.append(dict(g, hooks=entries))
    settings["hooks"][event] = kept


def install(settings, config, plan, report):
    """Adds what is missing, and moves a squad hook whose matcher the manifest
    changed. Returns True when settings changed."""
    changed = False
    for event, wanted in plan.items():
        missing = {}                         # matcher -> entries, one group per matcher
        for script, timeout, matcher in wanted:
            groups = settings.get("hooks", {}).get(event, [])
            right = any(runs(g, script, config) and g.get("matcher") == matcher for g in groups)
            stale = any(runs(g, script, config) and g.get("matcher") != matcher for g in groups)
            if right:
                if stale:                    # a second copy would still run on every tool call
                    drop(settings, event, script, config, matcher)
                    changed = True
                    report.append(f"on      {script:<16} {event} (copy under another matcher removed)")
                else:
                    report.append(f"on      {script:<16} {event} (already registered)")
                continue
            if not os.path.exists(os.path.join(config, "hooks", script)):
                left = ""
                if stale:                    # it would fail on every tool call it still matches
                    drop(settings, event, script, config, matcher)
                    changed = True
                    left = "; its old registration was removed"
                report.append(f"SKIPPED {script:<16} {event}: {os.path.join(config, 'hooks', script)} "
                              f"does not exist (did install.sh skip it?){left}")
                continue
            if stale:
                drop(settings, event, script, config, matcher)
                report.append(f"on      {script:<16} {event} (moved to matcher {matcher or 'none'})")
            else:
                report.append(f"on      {script:<16} {event} (added)")
            entry = {"type": "command", "command": command_for(config, script)}
            if timeout:
                entry["timeout"] = timeout
            missing.setdefault(matcher, []).append(entry)
        for matcher, entries in missing.items():
            group = {"matcher": matcher} if matcher is not None else {}
            group["hooks"] = entries
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
    try:
        plan, scripts = load_manifest(a.manifest)
    except BadManifest as e:
        print(f"ERROR   {e}", file=sys.stderr)
        return 2
    report = []
    if a.action == "install":
        changed = install(settings, config, plan, report)
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
