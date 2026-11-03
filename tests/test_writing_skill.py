#!/usr/bin/env python3
"""The writing skill's SKILL.md, references, templates and notices.

    python3 tests/test_writing_skill.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "writing")
TPL = os.path.join(SKILL, "templates")
RULES = ("title", "tokens", "ds-contract", "local-image", "toggle", "i18n",
         "initial-language", "export", "languages")


def read(*parts):
    with open(os.path.join(SKILL, *parts), encoding="utf-8") as fh:
        return fh.read()


def artifact(path):
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(SKILL, "scripts", "artifact_check.py"), path],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_templates_pass_the_artifact_check_as_shipped():
    for name in ("document.html", "document-bilingual.html"):
        code, out = artifact(os.path.join(TPL, name))
        assert code == 0 and "FAIL" not in out, (name, code, out)


def test_bilingual_template_declares_data_languages_and_opens_in_the_first():
    html = read("templates", "document-bilingual.html")
    assert '<html lang="en" data-languages="en pt">' in html, html[:600]
    assert "data-idiomas" not in html


def test_skill_md_is_lean_and_lists_its_triggers():
    md = read("SKILL.md")
    assert len(md.splitlines()) <= 340, len(md.splitlines())
    front = md.split("---")[1]
    assert re.findall(r"(?m)^(\w+):", front) == ["name", "description"]
    assert re.search(r"(?m)^name: writing$", front)
    for trigger in ("caveman", "lean mode", "fewer tokens", "compress CLAUDE.md", "commit message"):
        assert trigger in front, trigger
    assert "**Compress**" in md and "references/lean.md" in md
    assert "<!-- writing: allow" in md


def test_every_file_skill_md_names_exists():
    md = read("SKILL.md")
    named = set(re.findall(r"`((?:references|scripts|hooks)/[\w.-]+)`", md))
    assert len(named) >= 12, named
    missing = [p for p in sorted(named) if not os.path.exists(os.path.join(SKILL, p))]
    assert not missing, missing


def test_files_the_hook_cites_exist():
    hook = read("hooks", "writing-artifact.py")
    for rel in re.findall(r"\{SHOWN\}/((?:templates|references|scripts)/[\w.-]*\w)", hook):
        assert os.path.exists(os.path.join(SKILL, rel)), rel


def test_rendered_document_names_every_rule_of_the_check():
    doc = read("references", "rendered-document.md") + read("references", "checks.md")
    for rule in RULES:
        assert f"`{rule}`" in doc, rule


def test_notices_carry_the_licences():
    notices = read("THIRD_PARTY_NOTICES.md")
    for needle in ("humanizer", "Permission is hereby granted", "no-ai-slop",
                   "Apache License, Version 2.0", "Julius Brussee",
                   "Copyright (c) 2025 Siqi Chen", "Copyright (c) 2026 Peter Yang"):
        assert needle in notices, needle


def test_no_file_claims_a_licence_the_notices_do_not():
    """The notices claim no licence for claudekit `brand`; no other file may say MIT for it."""
    for name in ("SKILL.md", "references/voice-profile.md"):
        text = " ".join(read(name).split())
        assert "claudekit `brand` (MIT)" not in text and "`brand` skill (MIT)" not in text, name


def test_visuals_send_cloud_diagrams_to_their_skill():
    vis = read("references", "visuals.md")
    assert "`cloud-diagram`" in vis and "inventory before geometry" in " ".join(vis.lower().split())
    for term in ("drawio", "floating-edge", "diagrama-cloud", "apresentacao"):
        assert term not in vis.lower(), term


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # an AssertionError or any unexpected error fails
                failures += 1
                print("FAIL", name, "-", e)
    sys.exit(1 if failures else 0)
