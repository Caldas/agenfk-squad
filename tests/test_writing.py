#!/usr/bin/env python3
"""The writing skill's gates catch the bad case and let the good one through.

Self-checking: the exit code is the verdict. Runs the skill's scripts with
`python3 -I -B`, writes only to a temporary directory and never touches
~/.claude.

    python3 tests/test_writing.py

To also check the skill for names that must not be published (a project, a
customer, a person), list them in SQUAD_PRIVATE_TERMS, comma-separated. The
list lives in your environment, never in the repository.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "writing")
SCRIPTS = os.path.join(SKILL, "scripts")
FIX = os.path.join(SKILL, "fixtures")
ART = os.path.join(FIX, "artifacts")
COMPRESS = os.path.join(FIX, "compress")
HOOK = os.path.join(SKILL, "hooks", "writing-artifact.py")
NEUTRAL = os.path.join(ART, "neutral.html")
BILINGUAL = os.path.join(ART, "bilingual.html")
INCOMPLETE = os.path.join(ART, "bilingual-incomplete.html")
TMP = tempfile.mkdtemp(prefix="writing-")

_terms = [re.escape(t.strip()) for t in os.environ.get("SQUAD_PRIVATE_TERMS", "").split(",") if t.strip()]
PRIVATE = re.compile("|".join([r"/home/[a-z]+/", r"/Users/[A-Za-z]+/", r"skills/escrita\b"] + _terms), re.I)


def py(script, *args):
    r = subprocess.run([sys.executable, "-I", "-B", os.path.join(SCRIPTS, script), *args],
                       capture_output=True, text=True, cwd=SKILL)
    return r.returncode, r.stdout + r.stderr


def fixtures(prefix):
    names = sorted(n for n in os.listdir(FIX) if n.startswith(prefix) and n.endswith(".md"))
    assert names, f"no {prefix}*.md fixture"
    return [os.path.join(FIX, n) for n in names]


def tmp_file(name, text):
    path = os.path.join(tempfile.mkdtemp(dir=TMP), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def tmp_page(src, *subs):
    """Copy a page to a temporary file applying replacements (each one must match)."""
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    for old, new in subs:
        assert old in text, f"{old!r} is not in {src}"
        text = text.replace(old, new)
    return tmp_file("page.html", text)


def artifact(path):
    return py("artifact_check.py", path)


def hook(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([sys.executable, "-I", "-B", HOOK], input=raw, capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stderr)
    return json.loads(r.stdout) if r.stdout.strip() else None


# ---------------------------------------------------------------- slop_lint


def test_skill_selftest_passes():
    r = subprocess.run(["bash", os.path.join(SCRIPTS, "selftest.sh")], capture_output=True, text=True)
    assert r.returncode == 0 and "selftest: all checks passed" in r.stdout, r.stdout[-2000:] + r.stderr


def test_slop_lint_fails_every_slop_fixture():
    for path in fixtures("slop"):
        code, out = py("slop_lint.py", path)
        assert code == 1 and "ERROR" in out, (path, code, out[-500:])


def test_slop_lint_passes_every_clean_fixture():
    for path in fixtures("clean"):
        code, out = py("slop_lint.py", path)
        assert code == 0 and re.search(r"\b0 ERROR\b", out), (path, code, out[-500:])


def test_long_sentence_warning_counts_the_words():
    """Defect: the count lived inside an f-string with a backslash (SyntaxError before
    Python 3.12) and its raw string matched only backslashes and 'w', so every long
    sentence was reported as having 0 words."""
    # the splitter needs a capital after the full stop
    long_one = "Start " + " ".join(f"word{i}" for i in range(59)) + "."
    short = ["Plain " + " ".join(["plain"] * (n - 1)) + "." for n in (4, 9, 6, 14, 5, 11, 7, 20)]
    with tempfile.TemporaryDirectory() as d:
        doc = os.path.join(d, "long.md")
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write("# Title\n\n" + " ".join(short) + " " + long_one + "\n")
        code, out = py("slop_lint.py", "--json", doc)
    found = [f for fs in json.loads(out).values() for f in fs]
    msgs = [str(f) for f in found if "long-sentence" in str(f)]
    assert msgs and any("sentence of 60 words" in m for m in msgs), (code, msgs or out[-500:])


def _lint_checks(name):
    code, out = py("slop_lint.py", "--json", os.path.join(FIX, name))
    rep = json.loads(out)
    return code, [f for fs in rep.values() for f in fs]


def test_slop_lint_named_checks_are_errors():
    """Defect: a blocking check demoted to WARN lets the bad document through the gate."""
    for fixture, check in (("gate-heading.md", "banned-heading"),
                           ("gate-chatbot.md", "chatbot-artifact"),
                           ("gate-list.md", "list-over-prose")):
        code, found = _lint_checks(fixture)
        sev = [f["severity"] for f in found if f["check"] == check]
        assert sev == ["ERROR"], (fixture, check, found)
        assert code == 1, (fixture, code)


def test_slop_lint_in_file_allow_directive_in_both_languages():
    """The directive is `writing: allow`; the Portuguese `escrita: allow` keeps working."""
    body = "# Strategy\n\nThe strategic decision is to keep two AWS accounts.\n"
    code, out = py("slop_lint.py", tmp_file("bare.md", body))
    assert code == 1 and "'strategic'" in out, (code, out)
    for name in ("writing", "escrita"):
        code, out = py("slop_lint.py", tmp_file(f"{name}.md", f"<!-- {name}: allow strategic -->\n" + body))
        assert code == 0 and "declared intentional" in out, (name, code, out)


def test_slop_lint_exposes_the_names_other_skills_import():
    """Contract: another skill's gate imports ALLOW_RE, BANNED_LEXICON and strip_accents
    from slop_lint.py; a rename makes it fall back to its own lexicon without a word."""
    import importlib.util
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("slop_lint_contract", os.path.join(SCRIPTS, "slop_lint.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod              # @dataclass looks its module up here
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    for name in ("ALLOW_RE", "BANNED_LEXICON", "strip_accents"):
        assert hasattr(mod, name), name
    assert isinstance(mod.BANNED_LEXICON, dict) and {"robust", "robusto", "leverage"} <= set(mod.BANNED_LEXICON)
    assert all(isinstance(v, str) and v for v in mod.BANNED_LEXICON.values())
    assert mod.strip_accents("revolucionária ção") == "revolucionaria cao"
    for directive in ("<!-- writing: allow strategic, robust -->", "<!-- escrita: allow strategic, robust -->"):
        m = mod.ALLOW_RE.search(directive)
        assert m and m.group(1) == "strategic, robust", directive


def test_slop_lint_messages_are_english():
    code, out = py("slop_lint.py", os.path.join(FIX, "slop.md"), os.path.join(FIX, "slop-en.md"))
    assert code == 1, out
    messages = "\n".join(line for line in out.splitlines() if ": ERROR: " in line or ": WARN: " in line)
    # Quoted Portuguese constructions name the pattern found; the rest of the message is English.
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"|\[[^\]]*\]", "", messages)
    for word in ("diga", "nomeie", "frase", "linhas", "palavras", "parágrafos", "títulos", "travessão"):
        assert not re.search(rf"\b{word}\b", stripped), (word, messages[:1500])


# ---------------------------------------------------------------- fidelity_check


def test_fidelity_catches_dropped_and_invented_fact():
    code, out = py("fidelity_check.py", os.path.join(FIX, "clean.md"), os.path.join(FIX, "clean-lossy.md"))
    assert code == 1, (code, out)
    assert "MISSING" in out and "INVENTED" in out, out
    assert "123456789012" in out and "123456789013" in out, out   # the swapped account id shows


def test_fidelity_passes_a_faithful_rewrite():
    code, out = py("fidelity_check.py", os.path.join(FIX, "adversarial-fidelity-original.md"),
                   os.path.join(FIX, "faithful-rewrite.md"))
    assert code == 0, (code, out)


def _fid(rewrite, *flags):
    return py("fidelity_check.py", *flags, os.path.join(FIX, "gate-original.md"), os.path.join(FIX, rewrite))


def test_fidelity_loss_alone_exits_1_and_no_flag_releases_it():
    """Defect: the MISSING `return 1` masked by the others. Pure loss fails even with both flags."""
    code, out = _fid("gate-only-missing.md")
    assert code == 1 and "MISSING" in out and "INVENTED" not in out and "REVIEW" not in out, (code, out)
    code, out = _fid("gate-only-missing.md", "--allow-added", "--accept-semantic")
    assert code == 1 and "MISSING" in out, (code, out)


def test_fidelity_invention_alone_exits_1_and_allow_added_releases_it():
    """Defect: an invention let through; --allow-added is the only way out, and only for it."""
    code, out = _fid("gate-only-invented.md")
    assert code == 1 and "INVENTED" in out and "MISSING" not in out and "REVIEW" not in out, (code, out)
    code, out = _fid("gate-only-invented.md", "--allow-added")
    assert code == 0 and "WARNING" in out, (code, out)
    code, out = _fid("gate-only-invented.md", "--accept-semantic")
    assert code == 1, (code, out)


def test_fidelity_semantic_alone_exits_1_and_accept_semantic_releases_it():
    """Defect: an added negation (`will` -> `will not`) passes as faithful; --accept-semantic is only for it."""
    code, out = _fid("gate-only-semantic.md")
    assert code == 1 and "REVIEW" in out and "MISSING" not in out and "INVENTED" not in out, (code, out)
    code, out = _fid("gate-only-semantic.md", "--accept-semantic")
    assert code == 0 and "WARNING" in out, (code, out)
    code, out = _fid("gate-only-semantic.md", "--allow-added")
    assert code == 1, (code, out)


def test_compressed_faithful_passes_after_the_semantic_check():
    orig, faithful = os.path.join(COMPRESS, "original.md"), os.path.join(COMPRESS, "faithful.md")
    code, out = py("fidelity_check.py", orig, faithful)
    # "voce deve rodar" -> "rode" changes the modality: the script asks for a check, it does not approve alone
    assert code == 1 and "REVIEW" in out and "MISSING" not in out and "INVENTED" not in out, out
    code, out = py("fidelity_check.py", orig, faithful, "--accept-semantic")
    assert code == 0, out


def test_compressed_that_lost_a_negation_and_a_number_fails():
    orig, lost = os.path.join(COMPRESS, "original.md"), os.path.join(COMPRESS, "lost.md")
    code, out = py("fidelity_check.py", orig, lost)
    assert code == 1 and "[negation]" in out, out
    assert re.search(r"MISSING.*\n.*300", out) and re.search(r"INVENTED.*\n.*500", out), out
    code, out = py("fidelity_check.py", orig, lost, "--accept-semantic")
    assert code == 1, "accepting the semantic change must not release a swapped number: " + out


# ---------------------------------------------------------------- artifact_check


def test_artifact_fails_the_incomplete_bilingual_page():
    code, out = artifact(INCOMPLETE)
    assert code == 1, (code, out)
    assert 'FAIL toggle: the language bar has no data-lang="en" button' in out, out
    assert 'FAIL i18n: the key "body" is missing in: en' in out, out


def test_artifact_passes_the_neutral_and_the_bilingual_page():
    for path in (NEUTRAL, BILINGUAL):
        code, out = artifact(path)
        assert code == 0 and "FAIL" not in out, (path, code, out)


def test_artifact_does_not_require_a_toggle_on_a_one_language_page():
    # the neutral page has no bar, payload or data-t, and passes: the toggle is optional
    code, out = artifact(NEUTRAL)
    assert code == 0 and "toggle" not in out and "i18n" not in out, out
    # one language in data-languages is not bilingual either
    page = tmp_page(NEUTRAL, ('<html lang="en">', '<html lang="en" data-languages="en">'))
    code, out = artifact(page)
    assert code == 0, (code, out)


def test_artifact_toggle_without_declaration_fails():
    page = tmp_page(BILINGUAL, (' data-languages="pt en"', ""))
    code, out = artifact(page)
    assert code == 1 and "FAIL languages" in out, (code, out)


def test_artifact_each_bilingual_rule_fails_on_its_own():
    cases = {
        "toggle": (('<button type="button" data-lang="en" aria-pressed="false" translate="no">EN</button>', ""),),
        "i18n": (('"th-min": "Minutes",', ""),),
        "initial-language": (('<html lang="pt-BR"', '<html lang="en"'),),
        "export": (("html.render .langbar{display:none!important}", ""),),
    }
    for rule, subs in cases.items():
        code, out = artifact(tmp_page(BILINGUAL, *subs))
        assert code == 1 and f"FAIL {rule}" in out, (rule, code, out)
        others = {r for r in re.findall(r"^FAIL ([\w-]+)", out, re.M)} - {rule}
        assert not others, (rule, others, out)


def test_artifact_rules_for_every_page():
    cases = {
        "local-image": (("<h1>", '<img src="logo.svg" alt="Logo"><h1>'),),
        "title": (("<title>Neutral artifact_check fixture</title>", "<title> </title>"),),
        "tokens": ((":root{--bg", "body{--bg"),),        # swaps both: the light one and the dark @media one
    }
    for rule, subs in cases.items():
        code, out = artifact(tmp_page(NEUTRAL, *subs))
        assert code == 1 and f"FAIL {rule}" in out, (rule, code, out)
    # an image by URL or data: is not local
    page = tmp_page(NEUTRAL, ("<h1>", '<img src="https://example.org/a.png" alt="A">'
                                      '<img src="data:image/png;base64,AA" alt="B"><h1>'))
    code, out = artifact(page)
    assert code == 0, (code, out)


NEUTRAL_ROOT = ":root{--bg:#ffffff; --text:#1d2433; --accent:#2f5fa7}"
DS_NAMES = ("--ds-bg", "--ds-surface", "--ds-fg", "--ds-fg-2", "--ds-accent", "--ds-border",
            "--ds-font-display", "--ds-font-body", "--ds-font-mono")
DS_VALUES = ("#fdfcfb", "#ffffff", "#1c1917", "#57534e", "#0f766e", "#e7e5e4", "serif", "sans-serif", "monospace")
DS_DECLS = ";".join(f"{n}:{v}" for n, v in zip(DS_NAMES, DS_VALUES))
DS_USE = ":root{--bg:var(--ds-bg); --text:var(--ds-fg); --accent:var(--ds-accent)}"


def test_artifact_accepts_a_page_with_the_projects_design_system():
    # a project's --ds-* block, with no brand required
    page = tmp_page(NEUTRAL, (NEUTRAL_ROOT, "/* project design system */\n:root{" + DS_DECLS + "}\n" + DS_USE))
    code, out = artifact(page)
    assert code == 0 and "FAIL" not in out, out


def test_artifact_ds_used_without_the_block_fails():
    code, out = artifact(tmp_page(NEUTRAL, (NEUTRAL_ROOT, DS_USE)))
    assert code == 1 and "FAIL ds-contract" in out and "--ds-bg" in out, out


def test_artifact_ds_defined_outside_root_does_not_count():
    # all of them defined, but in a component selector: only :root counts as a pasted block
    code, out = artifact(tmp_page(NEUTRAL, (NEUTRAL_ROOT, ".card{" + DS_DECLS + "}\n" + DS_USE)))
    assert code == 1 and "FAIL ds-contract" in out and "--ds-bg" in out, out


def test_artifact_unreadable_file_exits_3():
    code, out = artifact(os.path.join(TMP, "does-not-exist.html"))
    assert code == 3 and "ERROR" in out, (code, out)


# ---------------------------------------------------------------- hook


def test_hook_asks_for_confirmation_only_when_the_page_fails():
    out = hook({"tool_input": {"action": "publish", "file_path": INCOMPLETE}})
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and spec["permissionDecision"] == "ask", spec
    assert "FAIL toggle" in spec["permissionDecisionReason"], spec
    assert hook({"tool_input": {"action": "publish", "file_path": NEUTRAL}}) is None
    assert hook({"tool_input": {"action": "publish", "file_path": os.path.join(FIX, "slop.md")}}) is None
    assert hook({"tool_input": {"action": "publish", "file_path": os.path.join(TMP, "missing.html")}}) is None
    assert hook("this is not json") is None


def test_hook_stays_silent_on_json_that_is_not_an_object():
    """Defect: a JSON list or string on stdin crashed the hook with a traceback instead of exiting 0."""
    for raw in ("[]", '"publish"', "3"):
        assert hook(raw) is None, raw


def test_hook_quickstart_injects_the_contract_with_nothing_private():
    ctx = hook({"tool_input": {"action": "quickstart"}})["hookSpecificOutput"]["additionalContext"]
    for needle in ("templates/document.html", "templates/document-bilingual.html",
                   "data-languages", "artifact_check.py", "skills/writing"):
        assert needle in ctx, (needle, ctx)
    assert not PRIVATE.search(ctx), ctx
    deck = hook({"tool_input": {"action": "quickstart", "intent": "slides"}})["hookSpecificOutput"]["additionalContext"]
    assert deck.startswith("Presentation") and "document-bilingual.html" in deck, deck
    design = hook({"tool_input": {"action": "quickstart", "intent": "design"}})["hookSpecificOutput"]["additionalContext"]
    assert design.startswith("Design") and "design-reference" in design, design


def test_hook_check_that_did_not_run_asks_for_confirmation():
    """Defect: the check exits 3 (unreadable file) and the hook stays quiet, publishing an unchecked page."""
    path = tmp_page(NEUTRAL)
    os.chmod(path, 0)
    try:
        assert os.geteuid() != 0, "the test needs an unprivileged user to make the file unreadable"
        spec = hook({"tool_input": {"action": "publish", "file_path": path}})["hookSpecificOutput"]
    finally:
        os.chmod(path, 0o600)
    assert spec["permissionDecision"] == "ask", spec
    reason = spec["permissionDecisionReason"]
    assert "did not run" in reason and "exit 3" in reason, spec


def test_hook_other_action_on_a_failing_page_stays_silent():
    """Defect: the hook checking pages on an action that is not publish."""
    assert hook({"tool_input": {"action": "publish", "file_path": INCOMPLETE}}) is not None
    for action in ("preview", "list", "delete"):
        assert hook({"tool_input": {"action": action, "file_path": INCOMPLETE}}) is None, action


# ---------------------------------------------------------------- hygiene


def test_skill_has_nothing_private():
    hits = []
    for base, dirs, files in os.walk(SKILL):
        for name in files:
            path = os.path.join(base, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if PRIVATE.search(line):
                        hits.append(f"{os.path.relpath(path, ROOT)}:{n}: {line.strip()[:80]}")
    assert not hits, "\n".join(hits)


def test_skill_ships_no_logo():
    assert not os.path.exists(os.path.join(SKILL, "assets")), "logos do not go in"


def test_zz_no_pycache_in_the_skill():
    # runs last (alphabetical order), after every test that runs the scripts
    dirty = [base for base, dirs, files in os.walk(SKILL) if os.path.basename(base) == "__pycache__"]
    assert not dirty, dirty


if __name__ == "__main__":
    failures = 0
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print("ok  ", name)
                except Exception as e:  # an AssertionError or any unexpected error fails
                    failures += 1
                    print("FAIL", name, "\n     ", f"{type(e).__name__}: {e}"[:1500].replace("\n", "\n      "))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failures else 0)
