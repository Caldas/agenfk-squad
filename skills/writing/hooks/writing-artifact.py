#!/usr/bin/env python3
"""PreToolUse / Artifact: brings the writing skill's document contract into the Artifact flow.

An Artifact is born from the tool's own guide, which never loads the writing
skill. This hook steps in at two points:

  quickstart  injects the contract (the project's tokens or the neutral
              template, a language toggle only when the page is bilingual, the
              check before publishing)
  publish     runs scripts/artifact_check.py on the .html page; if it fails,
              asks for confirmation (permissionDecision "ask") with the findings

It blocks nothing on its own: the owner decides whether to publish. Registering
the hook in settings.json is the owner's decision, not this skill's:

    {"matcher": "Artifact", "hooks": [{"type": "command",
      "command": "python3 -I -B ~/.claude/skills/writing/hooks/writing-artifact.py"}]}

A read error or invalid JSON on stdin: exits 0 silently (the hook never jams the tool).
"""
import json
import os
import subprocess
import sys

REAL = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SHOWN = "~/.claude/skills/writing"
CHECK = os.path.join(REAL, "scripts", "artifact_check.py")


def contract():
    return f"""Rendered document, by the writing skill. The writing skill owns the text;
the look belongs to the project's design system or to the design-reference skill.

1. The project decides: if there is a DESIGN.md, tokens (tokens.css,
   tailwind.config.*, a theme) or a component library, paste the project's
   tokens into :root and follow them. Say in one line which system the page wears.
2. No system in the project: start from {SHOWN}/templates/document.html
   (tokens in :root, dark mode, no logo, system font).
3. One language by default (the request's, the existing artifact's, the repo
   policy's, otherwise English). A language toggle only when the audience is
   bilingual or the owner asked: start from
   {SHOWN}/templates/document-bilingual.html and declare
   <html data-languages="en pt"> (the first language is the one it opens in).
4. No <img src> pointing at a local path: inline SVG, a URL or data:.
Full rules: {SHOWN}/references/rendered-document.md
Before publishing: python3 -I {SHOWN}/scripts/artifact_check.py <file>"""


def deck():
    return f"""Presentation: a presentation skill, when one is installed, owns the layout;
the writing skill owns the text. If the deck is bilingual, declare
<html data-languages="en pt"> and copy the language bar, the #i18n payload, the
script and the html.render .langbar{{display:none}} rule from
{SHOWN}/templates/document-bilingual.html.
Before publishing: python3 -I {SHOWN}/scripts/artifact_check.py <file>"""


def design():
    return """Design: the Design type owns the canvas. The look follows the project's
design system or the design-reference skill; the writing skill takes care of the text only."""


def emit(obj):
    print(json.dumps({"hookSpecificOutput": dict(hookEventName="PreToolUse", **obj)}, ensure_ascii=False))


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = payload.get("tool_input") or {}
    if not isinstance(tool, dict):
        return 0
    action = tool.get("action") or "publish"
    if action == "quickstart":
        intent = tool.get("intent") or ""
        emit({"additionalContext": deck() if intent == "slides" else design() if intent == "design" else contract()})
        return 0
    if action != "publish":
        return 0
    path = tool.get("file_path") or ""
    if not isinstance(path, str) or not path.lower().endswith((".html", ".htm")) or not os.path.isfile(path):
        return 0
    run = subprocess.run([sys.executable, "-I", "-B", CHECK, path], capture_output=True, text=True)
    if run.returncode == 0:
        return 0
    fails = [line for line in run.stdout.splitlines() if line.startswith("FAIL")]
    if run.returncode != 1 or not fails:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-5:])
        fails = [f"The check did not run (exit {run.returncode}); the page was not verified:", tail]
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            guide = deck() if 'class="slide' in fh.read() else contract()
    except OSError:
        guide = contract()
    reason = ("This page does not pass the writing skill's document check:\n"
              + "\n".join(fails) + "\n\n" + guide
              + "\n\nFix it and publish again, or approve this call to publish it as it is.")
    emit({"permissionDecision": "ask", "permissionDecisionReason": reason})
    return 0


if __name__ == "__main__":
    sys.exit(main())
