#!/usr/bin/env python3
"""Render the squad's Claude-dialect agents into oh-my-pi (omp) task agents.

omp reads `.omp/agents/*.md` (project) and `~/.omp/agent/agents/*.md` (user), and
skips `.claude/agents` on purpose: the frontmatter is a different contract. This
is the adapter between the two dialects. It is idempotent and has a `--check`
mode so a stale render is caught instead of drifting.

Three rules, all one-way and checkable:

  * `tools`: Claude tool names become omp tool names (Read -> read, WebFetch ->
    web_fetch). A name with no mapping is refused unless `--allow-unknown`, so a
    lost capability is never silent.
  * `model`: `inherit` is dropped, so the child uses the parent's active model.
    The Claude aliases (sonnet/opus/haiku) become omp role aliases from
    MODEL_ALIASES; anything naming Anthropic is refused, and the output never
    contains `claude` or `anthropic`.
  * the body is the system prompt, copied verbatim.

Usage:

    python3 omp_agents.py render --src agents --out ~/.omp/agent/agents
    python3 omp_agents.py render --src agents --out ~/.omp/agent/agents --check
"""
import argparse
import os
import re
import sys


class RenderError(ValueError):
    """A source agent cannot be rendered into the omp contract."""


# Claude Code tool name (lowercased) -> oh-my-pi tool name.
TOOL_MAP = {
    "read": "read",
    "grep": "grep",
    "glob": "glob",
    "bash": "bash",
    "edit": "edit",
    "write": "write",
    "task": "task",
    "webfetch": "web_fetch",
    "websearch": "web_search",
}

# Claude model alias -> omp role alias. The install prints the `modelRoles` this
# expects. `inherit` is not here: it is dropped so the child inherits the parent.
MODEL_ALIASES = {
    "sonnet": "@default",
    "opus": "@default",
    "haiku": "@smol",
}

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def map_tools(names):
    """(mapped, unknown) for a list of Claude tool names, order preserved."""
    mapped, unknown = [], []
    for raw in names:
        key = raw.strip().lower()
        if not key:
            continue
        target = TOOL_MAP.get(key)
        if target is None:
            unknown.append(raw.strip())
        elif target not in mapped:
            mapped.append(target)
    return mapped, unknown


def map_model(value):
    """The omp selector for a Claude model field, or None to omit it.

    `inherit` and empty become None. A known Claude alias becomes a role alias.
    Anything naming Anthropic is refused: AGENTS.md forbids those models.
    """
    v = (value or "").strip()
    if not v or v.lower() == "inherit":
        return None
    low = v.lower()
    if low in MODEL_ALIASES:
        return MODEL_ALIASES[low]
    if "claude" in low or "anthropic" in low:
        raise RenderError(f"refusing the Anthropic model selector {v!r}")
    return v


def _yaml_scalar(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_frontmatter(text):
    match = _FRONTMATTER.match(text)
    if not match:
        raise RenderError("missing frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise RenderError(f"bad frontmatter line: {line!r}")
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()
    return fields, text[match.end():]


def render_agent(text, allow_unknown=False):
    """One source agent (Claude dialect) as one omp agent file."""
    fields, body = parse_frontmatter(text)
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if not name or not description:
        raise RenderError("frontmatter needs name and description")

    tools, unknown = map_tools(fields.get("tools", "").split(","))
    if unknown and not allow_unknown:
        raise RenderError(f"{name}: unknown tools {unknown} (use --allow-unknown to drop them)")
    model = map_model(fields.get("model"))

    lines = ["---", f"name: {name}", f"description: {_yaml_scalar(description)}"]
    if tools:
        lines.append("tools:")
        lines += [f"  - {tool}" for tool in tools]
    if model:
        lines.append("model:")
        lines.append(f"  - {_yaml_scalar(model)}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _render_dir(src, out, allow_unknown, check):
    if not os.path.isdir(src):
        raise RenderError(f"no such source dir: {src}")
    drifted = False
    for fname in sorted(os.listdir(src)):
        if not fname.endswith(".md"):
            continue
        rendered = render_agent(_read(os.path.join(src, fname)), allow_unknown=allow_unknown)
        target = os.path.join(out, fname)
        if check:
            try:
                current = _read(target)
            except FileNotFoundError:
                current = None
            if current != rendered:
                print(f"STALE {target}", file=sys.stderr)
                drifted = True
            continue
        os.makedirs(out, exist_ok=True)
        if not os.path.exists(target) or _read(target) != rendered:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(rendered)
            print(f"ok    {target}")
    if check:
        return 1 if drifted else 0
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="render agents into the omp contract")
    render.add_argument("--src", required=True, help="the agents/ directory (Claude dialect)")
    render.add_argument("--out", required=True, help="the omp agents directory")
    render.add_argument("--check", action="store_true",
                        help="do not write; fail when a rendered file is stale")
    render.add_argument("--allow-unknown", action="store_true",
                        help="drop unmapped tools instead of refusing")
    args = parser.parse_args(argv)
    try:
        return _render_dir(args.src, args.out, args.allow_unknown, args.check)
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
