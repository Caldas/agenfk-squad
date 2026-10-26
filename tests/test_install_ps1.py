#!/usr/bin/env python3
"""install.ps1 links the squad into Claude Code's config dir on Windows, and never breaks what the user had.

Self-checking: the exit code is the verdict. Windows only (it says so and exits 0 elsewhere). Every run
gets a throwaway profile and a throwaway copy of this tree, so it never touches ~/.claude.
Directories are linked as junctions (no privilege needed); files as symbolic links when Windows allows it,
otherwise as marked copies that the next run updates. `-NoSymlink` forces that fallback, so the test does
not depend on whether this account may create symbolic links.

    python tests/test_install_ps1.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

if os.name != "nt" or not POWERSHELL:
    print("skipped: install.ps1 is for Windows (use install.sh elsewhere)")
    sys.exit(0)

TMP = tempfile.mkdtemp(prefix="inst-")


def build_template():
    template = os.path.join(TMP, "template")
    listed = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            check=True, capture_output=True, text=True).stdout.split("\0")
    for rel in filter(None, listed):
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(os.path.join(template, rel)), exist_ok=True)
            shutil.copy2(src, os.path.join(template, rel))
    return template


TEMPLATE = build_template()


def repo_copy():
    dst = tempfile.mkdtemp(prefix="repo-", dir=TMP)
    shutil.rmtree(dst)
    shutil.copytree(TEMPLATE, dst)
    return dst


def run(repo, h, *args, env=None):
    cfg = os.path.join(h, ".claude")
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "CLAUDE_"))}
    e.update(HOME=h, USERPROFILE=h, **(env or {}))
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(repo, "install.ps1"),
           "-ConfigDir", cfg, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=h,
                       timeout=600)
    r.out = r.stdout + r.stderr
    return r


def profile():
    return tempfile.mkdtemp(prefix="home-", dir=TMP)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def points_into(path, repo):
    real = os.path.normcase(os.path.realpath(path))
    return real.startswith(os.path.normcase(os.path.realpath(repo)) + os.sep)


def is_squad_link(path, repo):
    """A link (junction or symbolic) into the repo, or a copy with the repo file's bytes."""
    return os.path.islink(path) and points_into(path, repo) or (
        os.path.isjunction(path) and points_into(path, repo))


def test_a_fresh_install_links_directories_and_copies_files_with_a_mark():
    repo, h = repo_copy(), profile()
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 0, r.out
    cfg = os.path.join(h, ".claude")
    for name in ("clear-pickup", "canvas-design", "session-context"):                 # directories: junctions into the repo
        assert is_squad_link(os.path.join(cfg, "skills", name), repo), name
    for rel in ("agents/developer.md", "agents/verifier.md", "CLAUDE.md", "hooks/squad-watch.py",
                "hooks/squad-router.py", "hooks/squad-switch.py", "hooks/squad-turn.py"):
        src = os.path.join(repo, *rel.split("/"))
        dst = os.path.join(cfg, *rel.split("/"))
        assert os.path.isfile(dst) and not os.path.islink(dst), rel
        assert sha(dst) == sha(src), rel                                              # a copy, byte for byte
    marks = read(os.path.join(cfg, "squad", "copies.txt"))
    assert sha(os.path.join(cfg, "hooks", "squad-watch.py")) in marks, marks            # the mark that makes it updatable
    assert os.path.isfile(os.path.join(h, ".local", "bin", "squad-turn.cmd"))
    assert "sessions started after this step" in r.out, r.out


def test_a_second_run_changes_nothing():
    repo, h = repo_copy(), profile()
    assert run(repo, h, "-NoSymlink").returncode == 0
    cfg = os.path.join(h, ".claude")
    watch = os.path.join(cfg, "hooks", "squad-watch.py")
    mark, before = os.path.getmtime(watch), read(os.path.join(cfg, "squad", "copies.txt"))
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 0, r.out
    assert os.path.getmtime(watch) == mark, "an unchanged copy is not rewritten"
    assert read(os.path.join(cfg, "squad", "copies.txt")) == before
    assert "same    " in r.out and "copy    " not in r.out, r.out


def test_a_marked_copy_follows_the_repo_but_never_a_users_edit():
    repo, h = repo_copy(), profile()
    assert run(repo, h, "-NoSymlink").returncode == 0
    cfg = os.path.join(h, ".claude")
    developer = os.path.join(cfg, "agents", "developer.md")
    with open(os.path.join(repo, "agents", "developer.md"), "a", encoding="utf-8") as fh:
        fh.write("\nNew rule from a newer squad.\n")
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 0 and "update  " in r.out, r.out
    assert "New rule from a newer squad." in read(developer)
    with open(developer, "a", encoding="utf-8") as fh:                                # now the user edits their copy...
        fh.write("\nMy own note.\n")
    with open(os.path.join(repo, "agents", "developer.md"), "a", encoding="utf-8") as fh:
        fh.write("\nAnother upstream change.\n")                                      # ...and the repo moves again
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 1, r.out
    assert "SKIPPED" in r.out and "developer.md" in r.out and "edited" in r.out, r.out
    assert "My own note." in read(developer) and "Another upstream change." not in read(developer)


def test_a_real_file_in_the_way_is_reported_and_the_rest_is_still_installed():
    repo, h = repo_copy(), profile()
    cfg = os.path.join(h, ".claude")
    os.makedirs(cfg)
    with open(os.path.join(cfg, "CLAUDE.md"), "w", encoding="utf-8") as fh:
        fh.write("my own instructions\n")
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 1, r.out
    assert "SKIPPED" in r.out and "CLAUDE.md" in r.out, r.out
    assert read(os.path.join(cfg, "CLAUDE.md")) == "my own instructions\n"
    assert os.path.isfile(os.path.join(cfg, "hooks", "squad-watch.py"))
    assert os.path.isfile(os.path.join(cfg, "agents", "developer.md"))


def junction(link, target):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_source_that_resolves_outside_the_repo_is_refused():
    outside = tempfile.mkdtemp(prefix="outside-", dir=TMP)
    with open(os.path.join(outside, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: evil\ndescription: x\n---\n")
    repo, h = repo_copy(), profile()
    junction(os.path.join(repo, "skills", "evil"), outside)
    r = run(repo, h, "-NoSymlink")
    cfg = os.path.join(h, ".claude")
    assert r.returncode == 1, r.out
    refusals = [line for line in r.out.splitlines() if line.startswith("REFUSED")]
    assert len(refusals) == 1 and "evil" in refusals[0], r.out
    assert os.path.normcase(os.path.realpath(outside)) in os.path.normcase(r.out)         # where it really points
    assert "skills/vendor/" in r.out and "LOCK" in r.out                                  # the way forward
    assert not os.path.lexists(os.path.join(cfg, "skills", "evil"))
    assert is_squad_link(os.path.join(cfg, "skills", "clear-pickup"), repo)               # the rest is still linked


def test_a_sibling_that_shares_the_repo_prefix_is_refused():
    repo, h = repo_copy(), profile()
    sibling = repo + "-evil"                                                              # <repo>-evil starts with <repo>
    os.makedirs(sibling)
    with open(os.path.join(sibling, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: evil\ndescription: x\n---\n")
    junction(os.path.join(repo, "skills", "evil"), sibling)
    r = run(repo, h, "-NoSymlink")
    assert r.returncode == 1, r.out
    assert any(line.startswith("REFUSED") for line in r.out.splitlines()), r.out
    assert not os.path.lexists(os.path.join(h, ".claude", "skills", "evil"))


def test_the_squad_turn_command_runs_from_the_shim():
    repo, h = repo_copy(), profile()
    assert run(repo, h, "-NoSymlink").returncode == 0
    work = tempfile.mkdtemp(prefix="work-", dir=TMP)
    subprocess.run(["git", "init", "-q", work], check=True)
    shim = os.path.join(h, ".local", "bin", "squad-turn.cmd")
    e = dict(os.environ, HOME=h, USERPROFILE=h)
    r = subprocess.run(["cmd", "/c", shim, "status"], capture_output=True, text=True, env=e, cwd=work, timeout=120)
    assert r.returncode == 0 and "Merge queue of" in r.stdout, (r.stdout, r.stderr)


def test_oh_my_pi_gets_its_extension_and_its_agents_when_omp_is_on_the_path():
    repo, h = repo_copy(), profile()
    fake = tempfile.mkdtemp(prefix="bin-", dir=TMP)
    with open(os.path.join(fake, "omp.cmd"), "w") as fh:
        fh.write("@echo off\r\n")
    r = run(repo, h, "-NoSymlink", env={"PATH": fake + os.pathsep + os.environ["PATH"]})
    assert r.returncode == 0, r.out
    ext = os.path.join(h, ".omp", "agent", "extensions", "squad-watch-omp.ts")
    assert os.path.isfile(ext) and sha(ext) == sha(os.path.join(repo, "extensions", "squad-watch-omp.ts"))
    rendered = os.listdir(os.path.join(h, ".omp", "agent", "agents"))
    assert "developer.md" in rendered, rendered
    assert "note    omp not on PATH" not in r.out, r.out


def test_a_profile_with_an_accent_still_runs_the_shim():
    repo = repo_copy()
    h = tempfile.mkdtemp(prefix="José-", dir=TMP)               # a common profile name in Portuguese
    assert run(repo, h, "-NoSymlink").returncode == 0
    work = tempfile.mkdtemp(prefix="work-", dir=TMP)
    subprocess.run(["git", "init", "-q", work], check=True)
    shim = os.path.join(h, ".local", "bin", "squad-turn.cmd")
    # the shim points at the squad's clone, which lives under the accented profile in real life
    clone = os.path.join(h, "José clone")
    shutil.copytree(repo, clone)
    assert run(clone, h, "-NoSymlink").returncode == 0
    e = dict(os.environ, HOME=h, USERPROFILE=h)
    r = subprocess.run(["cmd", "/c", shim, "status"], capture_output=True, text=True, env=e, cwd=work, timeout=120)
    assert r.returncode == 0 and "Merge queue of" in r.stdout, (r.stdout, r.stderr)


def test_a_relative_config_dir_means_where_the_user_is_standing():
    repo, h = repo_copy(), profile()
    sub = os.path.join(h, "sub")
    os.makedirs(sub)
    script = os.path.join(repo, "install.ps1").replace("'", "''")
    e = dict(os.environ, HOME=h, USERPROFILE=h)
    r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        f"Set-Location '{sub}'; & '{script}' -ConfigDir rel -NoSymlink"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=h, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.isfile(os.path.join(sub, "rel", "hooks", "squad-watch.py"))
    assert not os.path.exists(os.path.join(h, "rel"))


def test_a_copy_that_cannot_be_written_is_reported_not_claimed():
    import ctypes
    repo, h = repo_copy(), profile()
    assert run(repo, h, "-NoSymlink").returncode == 0
    developer = os.path.join(h, ".claude", "agents", "developer.md")
    with open(os.path.join(repo, "agents", "developer.md"), "a", encoding="utf-8") as fh:
        fh.write("\nNew rule from a newer squad.\n")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    # GENERIC_READ, FILE_SHARE_READ only: nobody else may write while it is open
    handle = k32.CreateFileW(developer, 0x80000000, 1, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        r = run(repo, h, "-NoSymlink")
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))
    assert r.returncode == 1, r.out
    assert "SKIPPED" in r.out and "could not be copied" in r.out, r.out
    assert "update  " not in r.out, r.out
    assert "New rule from a newer squad." not in read(developer)
    assert run(repo, h, "-NoSymlink").returncode == 0                      # and it heals once it is free
    assert "New rule from a newer squad." in read(developer)


def test_the_default_mode_works_whatever_this_account_may_link():
    repo, h = repo_copy(), profile()
    r = run(repo, h)
    assert r.returncode == 0, r.out
    cfg = os.path.join(h, ".claude")
    assert sha(os.path.join(cfg, "hooks", "squad-watch.py")) == sha(os.path.join(repo, "hooks", "squad-watch.py"))
    assert is_squad_link(os.path.join(cfg, "skills", "clear-pickup"), repo)


def test_uninstall_removes_what_the_squad_made_and_keeps_what_is_not_its_own():
    repo, h = repo_copy(), profile()
    cfg = os.path.join(h, ".claude")
    os.makedirs(os.path.join(cfg, "agents"))
    with open(os.path.join(cfg, "agents", "mine.md"), "w", encoding="utf-8") as fh:
        fh.write("mine\n")
    assert run(repo, h, "-NoSymlink").returncode == 0
    with open(os.path.join(cfg, "agents", "developer.md"), "a", encoding="utf-8") as fh:
        fh.write("\nMy own note.\n")                                                      # edited: not ours any more
    r = run(repo, h, "-NoSymlink", "-Uninstall")
    assert r.returncode == 0, r.out
    assert not os.path.lexists(os.path.join(cfg, "skills", "clear-pickup"))
    assert not os.path.lexists(os.path.join(cfg, "hooks", "squad-watch.py"))
    assert not os.path.lexists(os.path.join(cfg, "agents", "verifier.md"))
    assert not os.path.lexists(os.path.join(h, ".local", "bin", "squad-turn.cmd"))
    assert read(os.path.join(cfg, "agents", "mine.md")) == "mine\n"
    assert "My own note." in read(os.path.join(cfg, "agents", "developer.md"))             # kept, and said so
    assert "edited" in r.out and "developer.md" in r.out, r.out
    assert os.path.isdir(os.path.join(repo, "skills", "clear-pickup")), "uninstalling a junction must not touch its target"
    assert os.path.isfile(os.path.join(repo, "skills", "clear-pickup", "SKILL.md"))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
