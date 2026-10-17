#!/usr/bin/env python3
"""The omp adapter renders the squad's agents without leaking Anthropic models.

Self-checking: the exit code is the verdict. Works in a throwaway dir and never
touches ~/.omp.

    python3 tests/test_omp_agents.py
"""
import contextlib
import io
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "harness-port", "scripts"))
import omp_agents as oa  # noqa: E402

SAMPLE = """---
name: sample
description: A sample agent whose description has: a colon, "quotes", and a comma.
tools: Read, Grep, Glob, Bash, Edit, Write, WebFetch, WebSearch
model: sonnet
---

Body line one.
Body line two.
"""


def test_map_tools_normalizes_the_claude_dialect():
    mapped, unknown = oa.map_tools(
        ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "WebFetch", "WebSearch"]
    )
    assert mapped == ["read", "grep", "glob", "bash", "edit", "write", "web_fetch", "web_search"], mapped
    assert unknown == []


def test_map_tools_reports_unknown_names_instead_of_dropping_them():
    mapped, unknown = oa.map_tools(["Read", "TodoWrite", "Bogus"])
    assert mapped == ["read"]
    assert unknown == ["TodoWrite", "Bogus"]


def test_map_model_never_emits_anthropic():
    assert oa.map_model("inherit") is None
    assert oa.map_model("") is None
    assert oa.map_model("sonnet") == "@default"
    assert oa.map_model("haiku") == "@smol"
    assert oa.map_model("openrouter/deepseek/deepseek-v4.1-flash") == \
        "openrouter/deepseek/deepseek-v4.1-flash"
    for bad in ("claude-3-opus", "anthropic/claude", "CLAUDE-SONNET"):
        try:
            oa.map_model(bad)
        except oa.RenderError:
            continue
        raise AssertionError(f"{bad} should be refused")


def test_render_agent_keeps_the_body_and_the_classification():
    out = oa.render_agent(SAMPLE)
    assert out.startswith("---\n")
    assert "\nname: sample\n" in out
    assert "Body line one.\nBody line two.\n" in out          # body verbatim, case kept
    assert "  - read\n" in out
    assert '  - "@default"\n' in out
    low = out.lower()
    assert "sonnet" not in low and "claude" not in low and "anthropic" not in low
    # the description keeps its colon, quotes and comma as one scalar
    assert 'description: "A sample agent whose description has: a colon, \\"quotes\\", and a comma."' in out


def test_render_agent_drops_inherit():
    out = oa.render_agent(SAMPLE.replace("model: sonnet", "model: inherit"))
    assert "model:" not in out


def cli(*args):
    """Run the CLI with its stdout/stderr swallowed, so this test's own output
    stays one line per test."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return oa.main(list(args))


def test_cli_render_then_check_roundtrip_and_drift():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "agents")
        out = os.path.join(tmp, "omp")
        os.makedirs(src)
        with open(os.path.join(src, "sample.md"), "w") as fh:
            fh.write(SAMPLE)
        assert cli("render", "--src", src, "--out", out) == 0
        rendered = os.path.join(out, "sample.md")
        assert os.path.exists(rendered)
        assert cli("render", "--src", src, "--out", out, "--check") == 0
        with open(rendered, "a") as fh:
            fh.write("\ndrift\n")
        assert cli("render", "--src", src, "--out", out, "--check") == 1
        assert cli("render", "--src", src, "--out", out) == 0
        assert cli("render", "--src", src, "--out", out, "--check") == 0


def test_unknown_tool_fails_unless_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "agents")
        out = os.path.join(tmp, "omp")
        os.makedirs(src)
        with open(os.path.join(src, "bad.md"), "w") as fh:
            fh.write(SAMPLE.replace(
                "tools: Read, Grep, Glob, Bash, Edit, Write, WebFetch, WebSearch",
                "tools: Read, Telepathy",
            ))
        assert cli("render", "--src", src, "--out", out) == 1
        assert cli("render", "--src", src, "--out", out, "--allow-unknown") == 0
        assert "Telepathy" not in open(os.path.join(out, "bad.md")).read()


def test_the_squad_agents_render_without_anthropic_and_all_present():
    src = os.path.join(ROOT, "agents")
    with tempfile.TemporaryDirectory() as tmp:
        assert cli("render", "--src", src, "--out", tmp) == 0
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(tmp))
        assert names == sorted(os.path.splitext(f)[0] for f in os.listdir(src)), names
        for fname in os.listdir(tmp):
            text = open(os.path.join(tmp, fname)).read()
            # Prose may name `CLAUDE.md` or Claude Code; only the model selector
            # is a compliance surface, and it may never name Anthropic.
            block = re.search(r"^model:\s*\n((?:[ \t]+-.*\n?)*)", text, re.M)
            model_block = (block.group(1) if block else "").lower()
            assert "claude" not in model_block and "anthropic" not in model_block, fname
            assert "\nname: " in text and "\ndescription: " in text, fname


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
