#!/usr/bin/env python3
"""The cloud-diagram skill fails a drawing with no status or with a floating edge, and its pages pass.

Self-checking: the exit code is the verdict. Writes only to temporary
directories. The render.sh cases need Chrome or Chromium; without one they are
reported as SKIP and do not fail. They run offline: the Google Fonts link is
stripped from the page copy and Chrome resolves no host name.

    python3 tests/test_cloud_diagram.py
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "cloud-diagram")
CHECK = os.path.join(SKILL, "scripts", "diagram_check.py")
RENDER = os.path.join(SKILL, "scripts", "render.sh")
TEMPLATE = os.path.join(SKILL, "references", "template.html")
EXAMPLE = os.path.join(SKILL, "references", "example.html")
CLEAN = os.path.join(SKILL, "fixtures", "clean.drawio")
BASH = shutil.which("bash") or "/bin/bash"
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
# Private context that must never ship: home paths, an AWS account id, a session uuid.
PRIVATE = re.compile(r"/home/[a-z][a-z0-9_-]*/|/Users/[A-Za-z]|\b\d{12}\b"
                     r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
DS = ("--ds-bg", "--ds-surface", "--ds-fg", "--ds-fg-2", "--ds-accent", "--ds-border",
      "--ds-font-display", "--ds-font-body", "--ds-font-mono")


class Skip(Exception):
    pass


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def variant(text, name):
    d = tempfile.mkdtemp(prefix="cloud-diagram-")
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def swap(text, *pairs):
    for a, b in pairs:
        assert a in text, f"{a!r} is not in the fixture"
        text = text.replace(a, b)
    return text


def check(path, *args, script=CHECK):
    r = subprocess.run([sys.executable, "-I", "-B", script, path, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def chrome():
    if os.environ.get("CHROME") and os.access(os.environ["CHROME"], os.X_OK):
        return os.environ["CHROME"]
    for c in CHROME_NAMES:
        if shutil.which(c):
            return shutil.which(c)
    return None


# ---------- diagram_check ----------

def test_clean_drawio_passes():
    code, out = check(CLEAN)
    assert code == 0 and "FAIL" not in out and "WARN" not in out, out


def test_drawio_with_a_floating_edge_and_no_status_fails():
    bad = variant(swap(read(CLEAN), (' source="alb" target="ecs"', ' source="alb"'),
                       ("current, as of 2026-10-01", "overview")), "bad.drawio")
    code, out = check(bad)
    assert code == 1, out
    assert "FAIL floating-edge" in out and "'e2' has no target" in out, out
    assert "FAIL status" in out and "PROPOSED" in out, out


def test_current_with_no_date_fails_and_proposed_passes():
    undated = variant(swap(read(CLEAN), (", as of 2026-10-01", "")), "undated.drawio")
    code, out = check(undated)
    assert code == 1 and "FAIL status" in out and "no date" in out, out
    proposed = variant(swap(read(CLEAN), ("current, as of 2026-10-01", "proposed")), "proposed.drawio")
    code, out = check(proposed)
    assert code == 0, out


def test_ai_sounding_label_fails_and_allow_downgrades():
    slop = variant(swap(read(CLEAN), ('value="ECS checkout service"', 'value="Seamless checkout service"')),
                   "slop.drawio")
    code, out = check(slop)
    assert code == 1 and "FAIL lexicon" in out, out
    code, out = check(slop, "--allow", "seamless")
    assert code == 0 and "WARN lexicon" in out, out
    marked = variant(read(CLEAN).replace("<mxfile", "<!-- writing: allow seamless -->\n<mxfile", 1)
                     .replace('value="ECS checkout service"', 'value="Seamless checkout service"'), "marked.drawio")
    code, out = check(marked)
    assert code == 0 and "WARN lexicon" in out, out


def test_the_writing_skill_lexicon_is_used_when_it_is_installed():
    # A sibling skills/writing/scripts/slop_lint.py replaces the built-in lexicon. "zorbleflux"
    # is only in the stub: if the import path breaks, the gate falls back and this case goes red.
    tree = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        scripts = os.path.join(tree, "skills", "cloud-diagram", "scripts")
        writing = os.path.join(tree, "skills", "writing", "scripts")
        os.makedirs(scripts)
        os.makedirs(writing)
        shutil.copy(CHECK, scripts)
        with open(os.path.join(writing, "slop_lint.py"), "w", encoding="utf-8") as f:
            f.write("import re, unicodedata\n"
                    "ALLOW_RE = re.compile(r'<!--\\s*writing:\\s*allow\\s+(.+?)\\s*-->', re.I)\n"
                    "BANNED_LEXICON = {'zorbleflux': 'stub word'}\n"
                    "def strip_accents(t):\n"
                    "    return ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')\n")
        copy = os.path.join(scripts, "diagram_check.py")
        stub = variant(swap(read(CLEAN), ('value="ECS checkout service"', 'value="ECS zorbleflux service"')),
                       "stub.drawio")
        code, out = check(stub, script=copy)
        assert code == 1 and "FAIL lexicon" in out and "zorbleflux" in out and "stub word" in out, out
        assert "built-in list" not in out, out
        # the stub's lexicon replaces the built-in one, it does not add to it
        builtin = variant(swap(read(CLEAN), ('value="ECS checkout service"', 'value="Seamless checkout service"')),
                          "builtin.drawio")
        code, out = check(builtin, script=copy)
        assert code == 0, out
        assert not [b for b, _, _ in os.walk(writing) if os.path.basename(b) == "__pycache__"]
    finally:
        shutil.rmtree(tree)


def _lone_check(writing_stub=None):
    """diagram_check.py copied into a skills/ tree; writing_stub, when given, is its slop_lint.py."""
    tree = tempfile.mkdtemp(prefix="cloud-diagram-")
    scripts = os.path.join(tree, "skills", "cloud-diagram", "scripts")
    os.makedirs(scripts)
    shutil.copy(CHECK, scripts)
    if writing_stub is not None:
        writing = os.path.join(tree, "skills", "writing", "scripts")
        os.makedirs(writing)
        with open(os.path.join(writing, "slop_lint.py"), "w", encoding="utf-8") as f:
            f.write(writing_stub)
    return tree, os.path.join(scripts, "diagram_check.py")


def test_built_in_lexicon_applies_with_no_writing_skill_and_says_so():
    tree, copy = _lone_check()
    try:
        slop = variant(swap(read(CLEAN), ('value="ECS checkout service"', 'value="Seamless checkout service"')),
                       "slop.drawio")
        code, out = check(slop, script=copy)
        assert code == 1 and "FAIL lexicon" in out and "'seamless'" in out, out
        note = [l for l in out.splitlines() if l.startswith("note:")]
        assert len(note) == 1 and "built-in list of 13 words" in note[0] and "not installed" in note[0], out
        assert "WARN" not in note[0] and "FAIL" not in note[0], note
        code, out = check(CLEAN, script=copy)
        assert code == 0 and "built-in list of 13 words" in out and "WARN" not in out, out
    finally:
        shutil.rmtree(tree)


def test_writing_skill_with_the_wrong_names_falls_back_with_a_note():
    # slop_lint is there but exports LEXICON, not BANNED_LEXICON: the gate must not pass blank.
    tree, copy = _lone_check("import re\nALLOW_RE = re.compile('x')\nLEXICON = {'zorbleflux': 'stub'}\n"
                             "def strip_accents(t):\n    return t\n")
    try:
        slop = variant(swap(read(CLEAN), ('value="ECS checkout service"', 'value="Seamless checkout service"')),
                       "slop.drawio")
        code, out = check(slop, script=copy)
        assert code == 1 and "FAIL lexicon" in out and "'seamless'" in out, out
        note = [l for l in out.splitlines() if l.startswith("note:")]
        assert len(note) == 1 and "built-in list of 13 words" in note[0] and "does not export" in note[0], out
        assert "WARN" not in note[0] and "FAIL" not in note[0], note
    finally:
        shutil.rmtree(tree)


def test_check_help_exits_0_and_a_dash_path_goes_after_double_dash():
    for flag in ("-h", "--help"):
        r = subprocess.run([sys.executable, "-I", "-B", CHECK, flag], capture_output=True, text=True)
        assert r.returncode == 0 and "Check a .drawio diagram" in r.stdout and "[--allow TERM] [--]" in r.stdout, (
            flag, r.returncode, r.stdout + r.stderr)
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        shutil.copy(CLEAN, os.path.join(tmp, "-clean.drawio"))
        r = subprocess.run([sys.executable, "-I", "-B", CHECK, "--", "-clean.drawio"], capture_output=True,
                           text=True, cwd=tmp)
        assert r.returncode == 0 and "ok -clean.drawio" in r.stdout, r.stdout + r.stderr
        r = subprocess.run([sys.executable, "-I", "-B", CHECK, "-clean.drawio"], capture_output=True,
                           text=True, cwd=tmp)
        assert r.returncode == 2 and "unknown option -clean.drawio" in r.stderr, r.stdout + r.stderr
    finally:
        shutil.rmtree(tmp)


def _boxes(n):
    return "".join(
        f'<mxCell id="x{i}" value="Queue {i}" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.sqs;'
        f'fillColor=#E7157B;" vertex="1" parent="1"><mxGeometry x="{20 * i}" y="600" width="40" height="40" '
        f'as="geometry" /></mxCell>' for i in range(n))


def test_label_and_box_limits_at_the_boundary():
    base = read(CLEAN)
    six = check(variant(swap(base, ('value="Users"', 'value="one two three four five six"')), "6.drawio"))[1]
    seven = check(variant(swap(base, ('value="Users"', 'value="one two three four five six seven"')), "7.drawio"))[1]
    assert "label-length" not in six and "WARN label-length" in seven and "'users'" in seven, (six, seven)
    four = check(variant(swap(base, ('id="e1" value="HTTPS"', 'id="e1" value="one two three four"')), "4.drawio"))[1]
    five = check(variant(swap(base, ('id="e1" value="HTTPS"', 'id="e1" value="one two three four five"')), "5.drawio"))[1]
    assert "label-length" not in four and "WARN label-length" in five and "'e1'" in five, (four, five)
    # the first page already has 4 boxes (Users, ALB, ECS, RDS): +21 = 25 passes, +22 = 26 warns
    first = base.index("</root>")
    twenty_five = check(variant(base[:first] + _boxes(21) + base[first:], "25.drawio"))[1]
    twenty_six = check(variant(base[:first] + _boxes(22) + base[first:], "26.drawio"))[1]
    assert "crowded" not in twenty_five and "WARN crowded" in twenty_six and "26 boxes" in twenty_six, (
        twenty_five, twenty_six)


def test_compressed_page_and_duplicate_id_fail():
    text = read(CLEAN)
    compressed = re.sub(r"(<diagram[^>]*>)\s*<mxGraphModel.*?</mxGraphModel>\s*(</diagram>)",
                        r"\1jZJNb4MwDIZ/DdcJSLu11/VjO+zUw86ImIRJIFEISvn3MxBga6tJk5DsP7Zfx45M+GRYYnlh\2",
                        text, count=1, flags=re.S)
    code, out = check(variant(compressed, "compressed.drawio"))
    assert code == 1 and "FAIL compressed" in out, out
    dup = variant(swap(text, ('id="ecs"', 'id="alb"')), "dup.drawio")
    code, out = check(dup)
    assert code == 1 and "FAIL duplicate-id" in out, out


def test_doctype_is_refused_before_parsing():
    bomb = variant('<?xml version="1.0"?>\n<!DOCTYPE m [<!ENTITY a "aaaa">]>\n' + read(CLEAN), "dtd.drawio")
    code, out = check(bomb)
    assert code == 1 and "FAIL xml" in out and "DOCTYPE" in out, out


def test_unreadable_drawio_exits_3_and_bad_usage_exits_2():
    code, _ = check(os.path.join(tempfile.mkdtemp(prefix="cloud-diagram-"), "missing.drawio"))
    assert code == 3, code
    r = subprocess.run([sys.executable, "-I", "-B", CHECK], capture_output=True, text=True)
    assert r.returncode == 2, r.returncode


# ---------- template, example and skill, no Chrome ----------

def test_template_has_a_status_and_reads_the_design_system():
    html = read(TEMPLATE)
    css = "".join(re.findall(r"<style>(.*?)</style>", html, re.S))
    assert re.search(r"<dt>Status</dt><dd>(PROPOSED|CURRENT as of \d{4}-\d{2}-\d{2})", html), "stamp with no Status"
    assert "<dt>State</dt>" in html, "the State cell stays"
    block = re.search(r":root \{(.*?)\}", css, re.S).group(1)
    for v in DS:
        assert v + ":" in block, f"{v} has no built-in default"
    for chrome_var in ("--page:var(--ds-bg)", "--surface:var(--ds-surface)", "--ink:var(--ds-fg)",
                       "--accent:var(--ds-accent)", "--display:var(--ds-font-display)", "--body:var(--ds-font-body)"):
        assert chrome_var in css, f"the chrome does not read --ds-*: {chrome_var}"
    assert ':root[data-theme="dark"] {' in css
    assert "data-diagram" in html, "the probe finds the diagram by data-diagram"
    externals = set(re.findall(r'(?:src|href)="(https?://[^"/]+)', html))
    assert externals <= {"https://fonts.googleapis.com"}, externals


def test_example_is_a_dated_current_drawing_with_an_inventory():
    html = read(EXAMPLE)
    assert re.search(r"<dt>Status</dt><dd>CURRENT as of \d{4}-\d{2}-\d{2} · source: ", html), "example status"
    assert "fictional" in html.lower(), "the example says it is not a real system"
    assert re.search(r"<th>Source</th>", html), "the example carries an inventory with a source per node"
    externals = set(re.findall(r'(?:src|href)="(https?://[^"/]+)', html))
    assert externals <= {"https://fonts.googleapis.com"}, externals


def test_skill_is_generic_english_and_documents_the_rules():
    md = read(os.path.join(SKILL, "SKILL.md"))
    front = md.split("---")[1]
    assert re.findall(r"(?m)^(\w+):", front) == ["name", "description"]
    assert re.search(r"(?m)^name: cloud-diagram$", front)
    for term in ("Inventory before geometry", "Status", "Audience", "Isomorphism", "Education",
                 "design-reference/scripts/sweep.py", "diagram_check.py", "references/template.html",
                 "references/example.html", "render.sh", "## Origin"):
        assert term in md, term
    assert re.search(r"`design-reference/scripts/sweep\.py`\s+is\s+not\s+installed", md), \
        "SKILL.md says what to do when the sweep is not installed"
    for p in ("references/template.html", "references/example.html", "references/inventory-and-drawio.md",
              "fixtures/clean.drawio", "scripts/probe.js", "scripts/render.sh", "THIRD_PARTY_NOTICES.md"):
        assert os.path.exists(os.path.join(SKILL, p)), p
    assert "Apache License, Version 2.0" in read(os.path.join(SKILL, "THIRD_PARTY_NOTICES.md"))
    # every relative skill path the docs name exists
    for doc in ("SKILL.md", "references/inventory-and-drawio.md", "THIRD_PARTY_NOTICES.md"):
        for ref in re.findall(r"`((?:references|scripts|fixtures)/[\w.-]+)`", read(os.path.join(SKILL, doc))):
            assert os.path.exists(os.path.join(SKILL, ref)), f"{doc} names {ref}, which does not exist"


def test_no_private_context_and_no_portuguese_prose_in_the_skill():
    found = []
    for base, _, files in os.walk(SKILL):
        for a in files:
            p = os.path.join(base, a)
            for n, line in enumerate(read(p).splitlines(), 1):
                if PRIVATE.search(line):
                    found.append(f"{os.path.relpath(p, ROOT)}:{n}: {line.strip()[:80]}")
    assert not found, "\n".join(found)
    # The docs and pages are English; Portuguese words stay only as detection data in the scripts.
    pt = re.compile(r"[ãõç]|\b(?:não|você|diagrama|prancha|seta|rótulo|sonda|situação)\b", re.I)
    for rel in ("SKILL.md", "references/inventory-and-drawio.md", "references/template.html",
                "references/example.html", "fixtures/clean.drawio", "scripts/render.sh"):
        bad = [f"{rel}:{n}: {l.strip()[:80]}" for n, l in enumerate(read(os.path.join(SKILL, rel)).splitlines(), 1)
               if pt.search(l)]
        assert not bad, "\n".join(bad)


def test_render_without_chrome_exits_2_and_names_the_way_forward():
    # A PATH holding only what render.sh needs before it looks for Chrome: no browser on it.
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        env = _no_chrome_env(tmp)
        r = subprocess.run([BASH, RENDER, TEMPLATE, os.path.join(tmp, "out")], capture_output=True, text=True,
                           env=env, timeout=60)
        assert r.returncode == 2 and "no Chrome/Chromium on PATH" in r.stdout and "$CHROME" in r.stdout, (
            r.returncode, r.stdout + r.stderr)
        env["CHROME"] = os.path.join(tmp, "not-a-browser")
        r = subprocess.run([BASH, RENDER, TEMPLATE, os.path.join(tmp, "out")], capture_output=True, text=True,
                           env=env, timeout=60)
        assert r.returncode == 2 and "no Chrome at $CHROME=" in r.stdout, (r.returncode, r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(tmp, "out")), "nothing is written before Chrome is found"
    finally:
        shutil.rmtree(tmp)


def _no_chrome_env(tmp):
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    os.symlink(shutil.which("dirname"), os.path.join(bin_dir, "dirname"))
    env = {k: v for k, v in os.environ.items() if k != "CHROME"}
    env["PATH"] = bin_dir
    return env


def test_render_help_exits_0_and_a_dash_page_goes_after_double_dash():
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        env = _no_chrome_env(tmp)         # help needs no browser and no tool on PATH
        for flag in ("-h", "--help"):
            r = subprocess.run([BASH, RENDER, flag], capture_output=True, text=True, env=env, timeout=60)
            assert r.returncode == 0 and "render.sh [--] <page.html>" in r.stdout and "status=NO-DIAGRAM" in r.stdout, (
                flag, r.returncode, r.stdout + r.stderr)
            assert not r.stdout.lstrip().startswith("#!"), r.stdout
        shutil.copy(TEMPLATE, os.path.join(tmp, "-page.html"))
        # after --, -page.html is the page: render.sh goes on and stops only for the missing Chrome
        r = subprocess.run([BASH, RENDER, "--", "-page.html", "out"], capture_output=True, text=True, env=env,
                           cwd=tmp, timeout=60)
        assert r.returncode == 2 and "no Chrome/Chromium on PATH" in r.stdout, (r.returncode, r.stdout + r.stderr)
        r = subprocess.run([BASH, RENDER, "-page.html", "out"], capture_output=True, text=True, env=env,
                           cwd=tmp, timeout=60)
        assert r.returncode == 3 and "unknown option -page.html" in r.stderr, (r.returncode, r.stdout + r.stderr)
        r = subprocess.run([BASH, RENDER], capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 3 and "usage: render.sh" in r.stderr, (r.returncode, r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(tmp, "out")), "nothing is written before Chrome is found"
    finally:
        shutil.rmtree(tmp)


# ---------- render.sh (SKIP without Chrome) ----------

def _offline(tmp):
    """A Chrome wrapper that resolves no host name, so the suite never reaches the network."""
    real = chrome()
    if not real:
        raise Skip("no Chrome/Chromium on PATH and no $CHROME: render.sh not run")
    wrapper = os.path.join(tmp, "chrome-offline")
    with open(wrapper, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nexec {shlex.quote(real)} --host-resolver-rules="MAP * ~NOTFOUND" "$@"\n')
    os.chmod(wrapper, 0o755)
    return {**os.environ, "CHROME": wrapper}


def _page(tmp, text, name):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(re.sub(r'<link[^>]*fonts\.googleapis\.com[^>]*>\n?', "", text))
    return p


def _render(env, page, out):
    return subprocess.run([BASH, RENDER, page, out, "1100"], capture_output=True, text=True, timeout=300, env=env)


def test_render_passes_the_template_and_fails_without_status():
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        env = _offline(tmp)
        r = _render(env, _page(tmp, read(TEMPLATE), "ok.html"), os.path.join(tmp, "ok"))
        assert r.returncode == 0 and "status=ok" in r.stdout and "problems=0" in r.stdout, r.stdout + r.stderr
        assert "diagrams=1 " in r.stdout, r.stdout
        none = re.sub(r"<div><dt>Status</dt><dd>[^<]*</dd></div>", "", read(TEMPLATE))
        r = _render(env, _page(tmp, none, "none.html"), os.path.join(tmp, "none"))
        assert r.returncode == 1 and "status=MISSING" in r.stdout and "no Status cell" in r.stdout, r.stdout
        current = swap(read(TEMPLATE), ("PROPOSED · sample drawing", "CURRENT"))
        r = _render(env, _page(tmp, current, "current.html"), os.path.join(tmp, "current"))
        assert r.returncode == 1 and "no YYYY-MM-DD date" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp)


def test_render_passes_the_example_and_catches_a_crossing_arrow():
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        env = _offline(tmp)
        r = _render(env, _page(tmp, read(EXAMPLE), "example.html"), os.path.join(tmp, "example"))
        assert r.returncode == 0 and "status=ok" in r.stdout and "problems=0" in r.stdout, r.stdout + r.stderr
        assert "diagrams=1 " in r.stdout, r.stdout
        # a vertical arrow dropped through the request row crosses it away from any junction
        crossed = swap(read(EXAMPLE), ('<path class="ar" d="M779 474H609"',
                                       '<path class="ar" d="M474 150V420"/>\n<path class="ar" d="M779 474H609"'))
        r = _render(env, _page(tmp, crossed, "crossed.html"), os.path.join(tmp, "crossed"))
        assert r.returncode == 1 and "arrow x arrow" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp)


def test_render_fails_a_page_with_no_diagram_and_reads_a_dash_page_after_double_dash():
    tmp = tempfile.mkdtemp(prefix="cloud-diagram-")
    try:
        env = _offline(tmp)
        empty = _page(tmp, "<main><h1>Checkout</h1><p>No drawing on this page.</p></main>\n", "empty.html")
        r = _render(env, empty, os.path.join(tmp, "empty"))
        assert r.returncode == 1 and "diagrams=0 " in r.stdout and "status=NO-DIAGRAM" in r.stdout, r.stdout
        assert "status=ok" not in r.stdout and "no diagram found" in r.stdout, r.stdout
        # a relative page whose name starts with - and a relative output folder
        _page(tmp, read(TEMPLATE), "-ok.html")
        r = subprocess.run([BASH, RENDER, "--", "-ok.html", "dash", "1100"], capture_output=True, text=True,
                           timeout=300, env=env, cwd=tmp)
        assert r.returncode == 0 and "diagrams=1 " in r.stdout and "status=ok" in r.stdout, r.stdout + r.stderr
        assert os.path.exists(os.path.join(tmp, "dash", "shot-light-1100.png")), os.listdir(tmp)
    finally:
        shutil.rmtree(tmp)


def test_zz_no_pycache_in_the_skill():
    dirty = [b for b, _, _ in os.walk(SKILL) if os.path.basename(b) == "__pycache__"]
    assert not dirty, dirty


if __name__ == "__main__":
    failures = skipped = passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print("ok  ", name)
            except Skip as e:
                skipped += 1
                print("SKIP", name, "-", e)
            except Exception as e:  # an AssertionError and an unexpected error both fail
                failures += 1
                print("FAIL", name, "\n     ", f"{type(e).__name__}: {e}"[:1500].replace("\n", "\n      "))
    print(f"{passed} passed, {skipped} skipped, {failures} failed")
    sys.exit(1 if failures else 0)
