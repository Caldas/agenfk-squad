#!/usr/bin/env python3
"""Every agent in agents/*.md carries the same standing-order sections, in the same order.

Self-checking: the exit code is the verdict.

    python3 tests/test_agents.py

Each agent answers the same six questions in a fixed place, as level-2
headings, in this order:

    ## Authority       what it may do
    ## Trigger         when it runs
    ## Approval gate   what needs someone else's approval
    ## Escalation      when it stops and asks
    ## Steps           how it does the work
    ## Never           what it never does

Other sections (Deliverable, Skills, a method of its own) may sit between or
after them. Each of the six has a body. The frontmatter keeps `name` (equal to
the file name), `description` and `tools`.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS = os.path.join(ROOT, "agents")
SECTIONS = ("Authority", "Trigger", "Approval gate", "Escalation", "Steps", "Never")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def headings(text):
    """[(level, title, body)] for every Markdown heading outside fenced code."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{1,6}) (.+?)\s*$", line)
        if m:
            out.append([len(m.group(1)), m.group(2), []])
        elif out:
            out[-1][2].append(line)
    return [(lvl, title, "\n".join(body)) for lvl, title, body in out]


def section_problems(text):
    """What is wrong with an agent's standing-order sections; empty when nothing is."""
    hs = headings(text)
    found = [t for lvl, t, _ in hs if lvl == 2 and t in SECTIONS]
    problems = []
    missing = [s for s in SECTIONS if s not in found]
    if missing:
        problems.append("missing section(s): " + ", ".join(missing))
    if found != [s for s in SECTIONS if s in found]:                # a repeat also lands here
        problems.append("sections out of order or repeated: " + ", ".join(found)
                        + " (expected " + ", ".join(SECTIONS) + ")")
    for i, (lvl, title, body) in enumerate(hs):
        if lvl == 2 and title in SECTIONS:
            nested = any(l > 2 for l, _, _ in hs[i + 1:i + 2])     # a subsection counts as body
            if not body.strip() and not nested:
                problems.append(f"empty section: {title}")
    return problems


def agent_files():
    return sorted(glob.glob(os.path.join(AGENTS, "*.md")))


def test_there_are_agents_to_check():
    assert len(agent_files()) >= 11, agent_files()


def test_every_agent_has_the_standing_order_sections_in_order():
    failures = []
    for path in agent_files():
        with open(path, encoding="utf-8") as fh:
            for p in section_problems(fh.read()):
                failures.append(f"{os.path.relpath(path, ROOT)}: {p}")
    assert not failures, "\n" + "\n".join(failures)


def test_frontmatter_keeps_name_description_and_tools():
    failures = []
    for path in agent_files():
        with open(path, encoding="utf-8") as fh:
            m = FRONTMATTER.match(fh.read())
        rel = os.path.relpath(path, ROOT)
        if not m:
            failures.append(f"{rel}: no frontmatter")
            continue
        keys = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l)
        for k in ("name", "description", "tools"):
            if not keys.get(k, "").strip():
                failures.append(f"{rel}: frontmatter without {k}")
        if keys.get("name", "").strip() != os.path.basename(path)[:-3]:
            failures.append(f"{rel}: name {keys.get('name', '').strip()!r} is not the file name")
    assert not failures, "\n" + "\n".join(failures)


GOOD = "---\nname: x\n---\n# x\n\n" + "".join(f"## {s}\n\nbody\n\n" for s in SECTIONS)


def test_the_checker_names_a_missing_section():
    assert section_problems(GOOD) == [], section_problems(GOOD)
    bad = GOOD.replace("## Escalation\n\nbody\n\n", "")
    assert section_problems(bad) == ["missing section(s): Escalation"], section_problems(bad)


def test_the_checker_ignores_a_heading_inside_code_and_a_level_3_heading():
    bad = GOOD.replace("## Never\n", "```\n## Never\n```\n### Never\n")
    assert "missing section(s): Never" in section_problems(bad), section_problems(bad)


def test_the_checker_refuses_the_wrong_order_and_an_empty_section():
    swapped = GOOD.replace("## Steps", "## TMP").replace("## Never", "## Steps").replace("## TMP", "## Never")
    assert any(p.startswith("sections out of order") for p in section_problems(swapped)), section_problems(swapped)
    empty = GOOD.replace("## Trigger\n\nbody\n\n", "## Trigger\n\n")
    assert section_problems(empty) == ["empty section: Trigger"], section_problems(empty)
    sub = GOOD.replace("## Steps\n\nbody\n\n", "## Steps\n\n### First\n\nbody\n\n")
    assert section_problems(sub) == [], section_problems(sub)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
