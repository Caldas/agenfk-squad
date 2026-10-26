#!/usr/bin/env python3
"""get.ps1 installs, updates and uninstalls on Windows, and never breaks what the user had.

Self-checking: the exit code is the verdict. Windows only (it says so and exits 0 elsewhere). Every run of
get.ps1 gets a throwaway profile and CLAUDE_CONFIG_DIR and clones a throwaway file:// copy of this tree, so it
never touches ~/.claude or the network. The POSIX twin is tests/test_get.py.

    python tests/test_get_ps1.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GET = os.path.join(ROOT, "get.ps1")
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

if os.name != "nt" or not POWERSHELL:
    print("skipped: get.ps1 is for Windows (use get.sh elsewhere)")
    sys.exit(0)

with open(os.path.join(ROOT, "hooks", "manifest.json"), encoding="utf-8") as _fh:
    MANIFEST = json.load(_fh)
WANTED = [(h["script"], e) for h in MANIFEST["hooks"] for e in h["events"]]

TMP = tempfile.mkdtemp(prefix="getps-")
GITCONFIG = os.path.join(TMP, "gitconfig")        # no global git config of the machine's user
open(GITCONFIG, "w").close()
GIT_ENV = {"GIT_CONFIG_GLOBAL": GITCONFIG, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                          env=dict(os.environ, **GIT_ENV)).stdout.strip()


def build_source():
    """A repository shaped like the real one: main with two release tags (v0.2.0, then v0.10.0, so only a
    version sort picks the right one) and a commit after them tagged v1.0.0-rc2 (a pre-release, not stable);
    beta ahead of main; and 'ancient', a branch from before this installer existed."""
    src = os.path.join(TMP, "src")
    listed = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            check=True, capture_output=True, text=True).stdout.split("\0")
    for rel in filter(None, listed):
        if os.path.isfile(os.path.join(ROOT, rel)):
            os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, rel), os.path.join(src, rel))
    git(src, "init", "-q", "-b", "main")
    refs = {}

    def commit(msg, tag=None):
        with open(os.path.join(src, "RELEASE"), "w") as fh:
            fh.write(msg + "\n")
        git(src, "add", "-A")
        git(src, "commit", "-q", "-m", msg)
        if tag:
            git(src, "tag", tag)
        refs[tag or msg] = git(src, "rev-parse", "HEAD")

    commit("first", "v0.2.0")
    commit("second", "v0.10.0")
    commit("after the release", "v1.0.0-rc2")
    refs["main"] = refs["v1.0.0-rc2"]
    git(src, "checkout", "-q", "-b", "beta")
    commit("beta work", "v9.0.0")
    refs["beta"] = refs["v9.0.0"]
    git(src, "checkout", "-q", "--orphan", "ancient")
    git(src, "rm", "-q", "-r", "--cached", "scripts", "hooks/manifest.json", "get.ps1", "install.ps1")
    git(src, "commit", "-q", "-m", "before the installer")
    refs["ancient"] = git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", "-f", "main")
    git(src, "clean", "-q", "-fdx")
    return src, refs


SRC, REFS = build_source()


def home(name="home"):
    return tempfile.mkdtemp(prefix=name + "-", dir=TMP)


def config(h):
    return os.path.join(h, ".claude")


def clone(h):
    return os.path.join(h, ".local", "share", "agenfk-squad")


def settings_path(h):
    return os.path.join(config(h), "settings.json")


def run(h, *args, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "CLAUDE_")) and k != "PYTHONPATH"}
    e.update(GIT_ENV, HOME=h, USERPROFILE=h, CLAUDE_CONFIG_DIR=config(h), SQUAD_REPO="file:///" + SRC.replace("\\", "/"))
    e.update(env or {})
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", GET, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=h,
                       timeout=900)
    r.out = r.stdout + r.stderr
    return r


def head(h):
    return git(clone(h), "rev-parse", "HEAD")


def read_settings(h):
    with open(settings_path(h), encoding="utf-8") as fh:
        return json.load(fh)


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def squad_commands(settings):
    return [x["command"] for groups in settings.get("hooks", {}).values() for g in groups for x in g["hooks"]]


def assert_ok(r):
    assert r.returncode == 0, r.out


def assert_registered(h):
    hooks = read_settings(h)["hooks"]
    for script, event in WANTED:
        found = [x for g in hooks.get(event, []) for x in g["hooks"] if f"hooks/{script}" in x["command"]]
        assert len(found) == 1, (script, event, hooks.get(event))
        assert not found[0]["command"].startswith("python3"), found[0]       # the Microsoft Store stub


def backups(h):
    return [n for n in os.listdir(config(h)) if ".bak-" in n]


def test_fresh_install_takes_the_latest_release_tag_and_registers_every_hook():
    h = home("a home with spaces")
    r = run(h)
    assert_ok(r)
    assert head(h) == REFS["v0.10.0"], "stable is the highest v* tag on main, by version"
    assert_registered(h)
    assert "PostToolUseFailure" in read_settings(h)["hooks"]
    assert backups(h) == [], "there was nothing to back up"
    for rel in ("agents/developer.md", "hooks/squad-watch.py", "hooks/squad-router.py", "CLAUDE.md"):
        assert os.path.isfile(os.path.join(config(h), *rel.split("/"))), rel
    assert os.path.isdir(os.path.join(config(h), "skills", "clear-pickup"))
    assert os.path.isfile(os.path.join(h, ".local", "bin", "squad-turn.cmd"))
    assert "stable (v0.10.0)" in r.out and "NEW Claude Code session" in r.out, r.out


def test_the_registered_hook_command_runs():
    h = home()
    assert_ok(run(h))
    cmd = next(c for c in squad_commands(read_settings(h)) if "squad-router.py" in c)
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hello",
                          "cwd": h, "transcript_path": os.path.join(h, "t.jsonl")})
    r = subprocess.run(cmd, shell=True, input=payload, capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, HOME=h, USERPROFILE=h))
    assert r.returncode == 0, (cmd, r.stdout, r.stderr)


def test_second_run_changes_nothing():
    h = home()
    assert_ok(run(h))
    before = raw(settings_path(h))
    r = run(h)
    assert_ok(r)
    assert raw(settings_path(h)) == before, "settings.json is byte for byte the same"
    assert backups(h) == [], "nothing written, so nothing backed up"
    assert "nothing to change" in r.out, r.out


def test_user_settings_and_hooks_survive_install_and_uninstall():
    h = home()
    os.makedirs(config(h))
    theirs = {"type": "command", "command": "python C:/opt/mine/squad-watch.py"}
    mine = {"model": "opus", "env": {"A": "1"}, "hooks": {"Stop": [{"hooks": [theirs]}]}}
    with open(settings_path(h), "w", encoding="utf-8") as fh:
        json.dump(mine, fh)
    assert_ok(run(h))
    got = read_settings(h)
    assert got["model"] == "opus" and got["env"] == {"A": "1"}
    assert theirs in [x for g in got["hooks"]["Stop"] for x in g["hooks"]]
    assert len(backups(h)) == 1
    r = run(h, "-Uninstall")
    assert_ok(r)
    assert read_settings(h) == mine, "uninstall gives the user's settings back exactly"


def test_uninstall_removes_hooks_and_links_but_keeps_the_clone_until_purge():
    h = home()
    assert_ok(run(h))
    r = run(h, "-Uninstall")
    assert_ok(r)
    assert squad_commands(read_settings(h) if os.path.exists(settings_path(h)) else {}) == []
    assert not os.path.lexists(os.path.join(config(h), "hooks", "squad-watch.py"))
    assert not os.path.lexists(os.path.join(config(h), "skills", "clear-pickup"))
    assert not os.path.lexists(os.path.join(h, ".local", "bin", "squad-turn.cmd"))
    assert os.path.isdir(os.path.join(clone(h), ".git")) and "-Purge" in r.out, r.out
    assert_ok(run(h, "-Uninstall", "-Purge"))
    assert not os.path.exists(clone(h))


def test_squad_home_that_is_not_a_clone_is_refused():
    h = home()
    os.makedirs(os.path.join(h, "dotfiles"))
    with open(os.path.join(h, "dotfiles", "keep.txt"), "w") as fh:
        fh.write("mine")
    r = run(h, "-Uninstall", "-Purge", env={"SQUAD_HOME": os.path.join(h, "dotfiles")})
    assert r.returncode != 0 and "does not look like an agenfk-squad clone" in r.out, r.out
    assert os.path.isfile(os.path.join(h, "dotfiles", "keep.txt"))


def test_settings_that_cannot_be_parsed_are_left_untouched_and_nothing_is_installed():
    h = home()
    os.makedirs(config(h))
    with open(settings_path(h), "w") as fh:
        fh.write("{ not json")
    r = run(h)
    assert r.returncode != 0 and "nothing was installed" in r.out, r.out
    assert raw(settings_path(h)) == b"{ not json"
    assert not os.path.exists(os.path.join(config(h), "hooks", "squad-watch.py"))


def test_beta_ref_and_their_environment_variables():
    h = home()
    assert_ok(run(h, "-Beta"))
    assert head(h) == REFS["beta"]
    assert_ok(run(h, "-Ref", "v0.2.0"))
    assert head(h) == REFS["v0.2.0"]
    assert_ok(run(h, env={"SQUAD_CHANNEL": "beta"}))
    assert head(h) == REFS["beta"]
    assert_ok(run(h, env={"SQUAD_REF": "v0.2.0"}))
    assert head(h) == REFS["v0.2.0"]
    assert_ok(run(h, "-Stable"))
    assert head(h) == REFS["v0.10.0"]


def test_a_ref_older_than_this_installer_is_refused_before_checkout():
    h = home()
    assert_ok(run(h))
    r = run(h, "-Ref", "ancient")
    assert r.returncode != 0 and "predates this installer" in r.out, r.out
    assert head(h) == REFS["v0.10.0"]


def test_local_changes_in_the_clone_are_refused_and_kept():
    h = home()
    assert_ok(run(h))
    with open(os.path.join(clone(h), "agents", "developer.md"), "a", encoding="utf-8") as fh:
        fh.write("\nlocal edit\n")
    r = run(h, "-Ref", "v0.2.0")
    assert r.returncode != 0 and "local changes" in r.out, r.out
    assert "local edit" in open(os.path.join(clone(h), "agents", "developer.md"), encoding="utf-8").read()
    assert head(h) == REFS["v0.10.0"]


def test_python_older_than_3_10_stops_with_the_fix_and_changes_nothing():
    h = home()
    fake = os.path.join(h, "oldpython.cmd")
    with open(fake, "w") as fh:
        fh.write('@echo off\r\necho 3.9\r\nexit /b 1\r\n')
    r = run(h, env={"SQUAD_PYTHON": fake})
    assert r.returncode != 0 and "MISSING python 3.10 or newer" in r.out, r.out
    assert not os.path.exists(clone(h)) and not os.path.exists(config(h)), "nothing was changed"


def test_a_real_file_in_the_way_is_reported_but_the_hooks_are_still_registered():
    h = home()
    os.makedirs(config(h))
    with open(os.path.join(config(h), "CLAUDE.md"), "w", encoding="utf-8") as fh:
        fh.write("my own instructions\n")
    r = run(h)
    assert r.returncode == 1 and "SKIPPED" in r.out, r.out
    assert open(os.path.join(config(h), "CLAUDE.md"), encoding="utf-8").read() == "my own instructions\n"
    assert_registered(h)


def run_in_session(h, command, env=None):
    """Runs `command` inside a PowerShell session of its own, the way a pasted one-liner runs: no -File."""
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "CLAUDE_")) and k != "PYTHONPATH"}
    e.update(GIT_ENV, HOME=h, USERPROFILE=h, CLAUDE_CONFIG_DIR=config(h), SQUAD_REPO="file:///" + SRC.replace("\\", "/"))
    e.update(env or {})
    r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=h, timeout=900)
    r.out = r.stdout + r.stderr
    return r


def test_the_documented_one_liners_report_an_error_and_give_the_prompt_back():
    # `irm ... | iex` and `& ([scriptblock]::Create(...))` run in the user's own session: an `exit` there would
    # close their terminal before they could read why
    h = home()
    script = GET.replace("'", "''")
    for how, call in (("iex", f"Get-Content -Raw -LiteralPath '{script}' | iex"),
                      ("scriptblock", f"& ([scriptblock]::Create((Get-Content -Raw -LiteralPath '{script}'))) -Ref no-such-ref")):
        r = run_in_session(h, call + "; 'STILL HERE'", env={"SQUAD_REF": "no-such-ref"} if how == "iex" else None)
        assert "STILL HERE" in r.out, (how, r.out)                  # the session survived the error
        assert "is not a branch, tag or commit" in r.out, (how, r.out)
        assert not os.path.exists(os.path.join(config(h), "hooks", "squad-watch.py")), how


def test_a_one_liner_install_works_and_leaks_nothing_into_the_session():
    h = home()
    script = GET.replace("'", "''")
    call = (f"& ([scriptblock]::Create((Get-Content -Raw -LiteralPath '{script}'))) -Beta; "
            "'FN=' + [bool](Get-Command Invoke-SquadGet -ErrorAction SilentlyContinue) + ' LEAK=' + "
            "[bool](Get-Variable squadState,squadExit -ErrorAction SilentlyContinue)")
    r = run_in_session(h, call)
    assert "FN=False LEAK=False" in r.out, r.out
    assert head(h) == REFS["beta"]
    assert_registered(h)


def test_a_relative_squad_home_means_where_the_user_is_standing():
    h = home()
    sub = os.path.join(h, "elsewhere")
    os.makedirs(sub)
    script = GET.replace("'", "''")
    r = run_in_session(h, f"Set-Location '{sub}'; & '{script}'", env={"SQUAD_HOME": "clonehere", "CLAUDE_CONFIG_DIR": "cfg"})
    assert r.returncode == 0, r.out
    assert os.path.isdir(os.path.join(sub, "clonehere", ".git")), r.out
    assert os.path.isfile(os.path.join(sub, "cfg", "settings.json")), r.out


def test_a_clone_that_cannot_be_checked_out_stops_the_install():
    h = home()
    assert_ok(run(h))
    # a file where git needs a directory: the checkout of the older tag cannot write there
    bad = os.path.join(clone(h), "RELEASE")
    git(clone(h), "update-index", "--assume-unchanged", "RELEASE")
    os.remove(bad)
    os.makedirs(bad)                                 # RELEASE is now a directory, and the old tree has a file
    with open(os.path.join(bad, "keep.txt"), "w") as fh:
        fh.write("x")
    r = run(h, "-Ref", "v0.2.0")
    assert r.returncode != 0, r.out
    assert "could not check out" in r.out and "Nothing was installed" in r.out, r.out


def test_unknown_option_and_purge_without_uninstall_are_refused():
    h = home()
    r = run(h, "-Frobnicate")
    assert r.returncode != 0 and "unknown option" in r.out, r.out
    r = run(h, "-Purge")
    assert r.returncode != 0 and "only goes with" in r.out, r.out
    r = run(h, "-Beta", "-Ref", "main")
    assert r.returncode != 0 and "choose one" in r.out, r.out
    assert not os.path.exists(clone(h)) and not os.path.exists(config(h))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
