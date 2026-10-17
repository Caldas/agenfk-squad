#!/usr/bin/env python3
"""get.sh installs, updates and uninstalls, and never breaks what the user had.

Self-checking: the exit code is the verdict. Every run of get.sh gets a
throwaway HOME and CLAUDE_CONFIG_DIR and clones a throwaway file:// copy of
this tree, so it never touches ~/.claude or the network.

    python3 tests/test_get.py
"""
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GET = os.path.join(ROOT, "get.sh")
with open(os.path.join(ROOT, "hooks", "manifest.json")) as _fh:
    MANIFEST = json.load(_fh)
WANTED = [(h["script"], e) for h in MANIFEST["hooks"] for e in h["events"]]

TMP = tempfile.mkdtemp(prefix="get-")
GITCONFIG = os.path.join(TMP, "gitconfig")       # no global git config of the machine's user
open(GITCONFIG, "w").close()
GIT_ENV = {"GIT_CONFIG_GLOBAL": GITCONFIG, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                          env=dict(os.environ, **GIT_ENV)).stdout.strip()


def build_source():
    """A repository shaped like the real one: main with two release tags (v0.2.0,
    then v0.10.0, so that only a version sort picks the right one) and a commit
    after them, tagged v1.0.0-rc2 (a pre-release, not stable); beta ahead of
    main, with a v* tag that never reached main; and
    'ancient', a branch from before this installer existed."""
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
    git(src, "rm", "-q", "-r", "--cached", "scripts", "hooks/manifest.json", "get.sh")
    git(src, "commit", "-q", "-m", "before the installer")
    refs["ancient"] = git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", "-f", "main")
    git(src, "clean", "-q", "-fdx")
    return src, refs


SRC, REFS = build_source()


def home(name="home"):
    h = tempfile.mkdtemp(prefix=name + "-", dir=TMP)
    return h


def path_without(tools):
    """This PATH, where every directory that holds one of `tools` is replaced by
    a mirror of links to everything else in it."""
    dirs = []
    for i, d in enumerate(filter(None, os.environ.get("PATH", "").split(os.pathsep))):
        if not any(os.path.lexists(os.path.join(d, t)) for t in tools):
            dirs.append(d)
            continue
        mirror = os.path.join(TMP, f"path-{i}")
        os.makedirs(mirror)
        for name in os.listdir(d):
            if name not in tools:
                os.symlink(os.path.join(d, name), os.path.join(mirror, name))
        dirs.append(mirror)
    return dirs


SH = shutil.which("sh")
PATH = path_without({"claude", "agenfk"})    # the warnings do not depend on this machine


def sandbox_path(fake=None):
    """PATH with the test's python3 first and without claude or agenfk. `fake`
    maps a tool name to a shell script that shadows it."""
    bin_dir = tempfile.mkdtemp(prefix="bin-", dir=TMP)
    os.symlink(sys.executable, os.path.join(bin_dir, "python3"))
    for name, body in (fake or {}).items():
        path = os.path.join(bin_dir, name)
        if os.path.lexists(path):
            os.unlink(path)
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
    return os.pathsep.join([bin_dir] + PATH)


def run(h, *args, env=None, fake=None):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("SQUAD_", "CLAUDE_")) and k != "PYTHONPATH"}
    e.update(GIT_ENV, HOME=h, CLAUDE_CONFIG_DIR=os.path.join(h, ".claude"),
             SQUAD_REPO="file://" + SRC, PATH=sandbox_path(fake))
    e.update(env or {})
    r = subprocess.run([SH, GET, *args], capture_output=True, text=True, env=e, cwd=h)
    r.out = r.stdout + r.stderr
    return r


def config(h):
    return os.path.join(h, ".claude")


def settings_path(h):
    return os.path.join(config(h), "settings.json")


def read_settings(h):
    with open(settings_path(h)) as fh:
        return json.load(fh)


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def clone(h):
    return os.path.join(h, ".local", "share", "agenfk-squad")


def head(h):
    return git(clone(h), "rev-parse", "HEAD")


def backups(h):
    return sorted(f for f in os.listdir(config(h)) if f.startswith("settings.json.bak-"))


def squad_commands(settings, script, event):
    """The commands on this event that end in this script's file name."""
    return [hk["command"] for g in settings.get("hooks", {}).get(event, []) for hk in g.get("hooks", [])
            if os.path.basename(shlex.split(hk["command"])[-1]) == script]


def leftovers(h):
    """Temporary files the settings writer left in the config dir."""
    return [f for f in os.listdir(config(h)) if ".tmp-" in f]


def links_into(h, target):
    found = []
    for root in (config(h), os.path.join(h, ".local", "bin")):
        for dirpath, dirs, files in os.walk(root):
            for name in dirs + files:
                p = os.path.join(dirpath, name)
                if os.path.islink(p) and os.readlink(p).startswith(target + "/"):
                    found.append(p)
    return found


def assert_ok(r):
    assert r.returncode == 0, r.out


def assert_registered(h):
    """Each manifest pair registered once, as `python3 <config>/hooks/<script>`,
    in a group with the manifest's matcher (or none, where it has none)."""
    s = read_settings(h)
    for script, event in WANTED:
        exact = ["python3", os.path.join(config(h), "hooks", script)]
        groups = [g for g in s["hooks"].get(event, [])
                  for hk in g["hooks"] if shlex.split(hk["command"]) == exact]
        assert len(groups) == 1, (script, event, s["hooks"].get(event))
        assert groups[0].get("matcher") == MANIFEST["matchers"].get(event), (event, groups[0])
    return s


# ---------------------------------------------------------------- tests

def test_fresh_install_takes_the_latest_release_tag_and_registers_every_hook():
    h = home("a home with spaces")
    r = run(h)
    assert_ok(r)
    assert head(h) == REFS["v0.10.0"], "stable is the highest v* tag on main, by version"
    assert_registered(h)
    assert "PostToolUseFailure" in read_settings(h)["hooks"]
    assert backups(h) == [], "there was nothing to back up"
    assert leftovers(h) == []
    for path in ("agents/developer.md", "hooks/squad-watch.py", "hooks/squad-router.py", "CLAUDE.md"):
        assert os.path.islink(os.path.join(config(h), path)), path
    assert os.path.islink(os.path.join(h, ".local", "bin", "squad-turn"))
    assert "stable (v0.10.0)" in r.out and "open a NEW Claude Code session" in r.out, r.out
    assert "'claude') is not on PATH" in r.out and "'agenfk' CLI is not on PATH" in r.out, r.out


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
    os.makedirs(os.path.join(h, "elsewhere"))
    mine = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my-guard.sh"}]}],
            "Notification": [{"hooks": [{"type": "command", "command": "notify-send hi"}]}],
        },
    }
    text = json.dumps(mine, indent=4) + "\n"
    write(settings_path(h), text)
    write(os.path.join(config(h), "agents", "mine.md"), "my agent\n")
    os.symlink(os.path.join(h, "elsewhere"), os.path.join(config(h), "agents", "linked-elsewhere"))

    assert_ok(run(h))
    s = assert_registered(h)
    assert s["model"] == "opus" and s["permissions"] == mine["permissions"]
    assert s["hooks"]["PreToolUse"][0] == mine["hooks"]["PreToolUse"][0], "the user's group comes first, intact"
    assert s["hooks"]["Notification"] == mine["hooks"]["Notification"]
    assert len(backups(h)) == 1 and raw(os.path.join(config(h), backups(h)[0])).decode() == text

    r = run(h, "--uninstall")
    assert_ok(r)
    assert read_settings(h) == mine, "only what the user had is left"
    assert links_into(h, clone(h)) == []
    assert os.path.isfile(os.path.join(config(h), "agents", "mine.md"))
    assert os.path.islink(os.path.join(config(h), "agents", "linked-elsewhere")), "a link elsewhere is not ours"
    assert os.path.isdir(clone(h)), "the clone stays without --purge"

    assert_ok(run(h, "--uninstall", "--purge"))
    assert not os.path.exists(clone(h))
    assert read_settings(h) == mine


def test_hooks_registered_by_hand_are_not_duplicated_and_are_removed():
    h = home()
    by_hand = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py", "timeout": 30}]}]}}
    write(settings_path(h), json.dumps(by_hand))
    assert_ok(run(h))
    s = read_settings(h)
    assert squad_commands(s, "squad-watch.py", "PreToolUse") == ["python3 ~/.claude/hooks/squad-watch.py"]
    assert s["hooks"]["PreToolUse"] == by_hand["hooks"]["PreToolUse"], "the user's own timeout is kept"
    assert len(squad_commands(s, "squad-watch.py", "Stop")) == 1
    assert_ok(run(h, "--uninstall"))
    assert read_settings(h) == {}


def test_a_users_hook_that_only_shares_a_script_name_is_not_the_squads():
    h = home()
    mine = {"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "python3 /opt/mine/squad-watch.py"}]}],
        "PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "python3 /opt/mine/squad-watch.py --extra"}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "grep -c squad-router.py /var/log/x"}]}],
        "Notification": [{"hooks": [                # the squad's path, but not the squad's command
            {"type": "command", "command": "python3 ~/.claude/hooks/squad-watch.py --debug"},
            {"type": "command", "command": "cat ~/.claude/hooks/squad-router.py"}]}],
    }}
    write(settings_path(h), json.dumps(mine))
    assert_ok(run(h))
    s = assert_registered(h)                      # the squad's Stop hook is on all the same
    for event, groups in mine["hooks"].items():
        assert s["hooks"][event][0] == groups[0], event
    assert_ok(run(h, "--uninstall"))
    assert read_settings(h) == mine, "the user's hooks survive the uninstall"


def test_a_hook_that_runs_a_script_inside_the_clone_is_the_squads():
    h = home()
    in_clone = "python3 " + os.path.join(clone(h), "hooks", "squad-watch.py")
    write(settings_path(h), json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": in_clone}]}]}}))
    assert_ok(run(h))
    s = read_settings(h)
    assert [hk["command"] for g in s["hooks"]["Stop"] for hk in g["hooks"]] == [in_clone], "not doubled"
    os.unlink(os.path.join(config(h), "hooks", "squad-watch.py"))   # recognised by the clone, not the link
    assert_ok(run(h, "--uninstall"))
    assert read_settings(h) == {}


def test_a_symlinked_settings_json_stays_a_link_and_keeps_its_mode():
    h = home()
    real = os.path.join(h, "dotfiles", "claude-settings.json")
    write(real, json.dumps({"model": "opus"}))
    os.chmod(real, 0o600)
    os.makedirs(config(h))
    os.symlink(real, settings_path(h))
    assert_ok(run(h))
    assert os.path.islink(settings_path(h)) and os.readlink(settings_path(h)) == real
    assert_registered(h)
    assert stat.S_IMODE(os.stat(real).st_mode) == 0o600, oct(os.stat(real).st_mode)
    assert len(backups(h)) == 1 and leftovers(h) == [] and os.listdir(os.path.dirname(real)) == ["claude-settings.json"]


def test_a_failed_write_leaves_no_temporary_file_and_the_settings_intact():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import squad_settings as ss
    h = home()
    path = settings_path(h)
    write(path, '{"model": "opus"}\n')
    original = ss.shutil.copymode

    def broken(*_a, **_k):
        raise OSError("disk full")
    ss.shutil.copymode = broken
    try:
        ss.write(path, {"model": "opus", "hooks": {}})
        raise AssertionError("the write should have failed")
    except OSError:
        pass
    finally:
        ss.shutil.copymode = original
    assert raw(path) == b'{"model": "opus"}\n' and leftovers(h) == []


def test_squad_home_that_is_not_a_clone_is_refused():
    h = home()
    elsewhere = os.path.join(h, "elsewhere")
    os.makedirs(elsewhere)
    os.makedirs(os.path.join(config(h), "agents"))
    link = os.path.join(config(h), "agents", "mine.md")
    os.symlink(os.path.join(h, "notes.md"), link)                 # a link of the user's, into $HOME
    write(settings_path(h), '{"model": "opus"}')
    for args in (["--uninstall"], ["--uninstall", "--purge"]):
        r = run(h, *args, env={"SQUAD_HOME": h})
        assert r.returncode != 0 and "not look like an agenfk-squad clone" in r.out, r.out
        assert os.path.islink(link) and os.path.isdir(elsewhere)
        assert raw(settings_path(h)) == b'{"model": "opus"}'
    git(h, "init", "-q")                                          # $HOME under git, as dotfiles often are
    git(h, "add", "-A")
    git(h, "commit", "-q", "-m", "dotfiles")
    before = git(h, "rev-parse", "HEAD")
    r = run(h, env={"SQUAD_HOME": h})
    assert r.returncode != 0 and "not look like an agenfk-squad clone" in r.out, r.out
    assert git(h, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD" and git(h, "rev-parse", "HEAD") == before


def test_settings_that_cannot_be_parsed_are_left_untouched_and_nothing_is_installed():
    for text in ('{"hooks": {"Stop": [', '{"hooks": []}', '[1, 2]'):
        h = home()
        write(settings_path(h), text)
        r = run(h)
        assert r.returncode != 0, r.out
        assert raw(settings_path(h)) == text.encode(), "byte for byte as it was"
        assert backups(h) == []
        assert not os.path.exists(os.path.join(config(h), "agents")), "no links either"
        assert "nothing was installed" in r.out, r.out


def test_beta_ref_and_their_environment_variables():
    h = home()
    r = run(h, "--beta")
    assert_ok(r)
    assert head(h) == REFS["beta"] and "channel  beta" in r.out, r.out
    before = raw(settings_path(h))
    r = run(h, "--ref", "v0.2.0")                 # an existing clone moves to the new ref
    assert_ok(r)
    assert head(h) == REFS["v0.2.0"] and "ref v0.2.0" in r.out, r.out
    assert raw(settings_path(h)) == before
    assert_ok(run(h, "--ref=main"))
    assert head(h) == REFS["main"]
    assert_ok(run(h, env={"SQUAD_CHANNEL": "beta"}))
    assert head(h) == REFS["beta"]
    assert_ok(run(h, env={"SQUAD_REF": "v0.10.0"}))
    assert head(h) == REFS["v0.10.0"]
    assert_ok(run(h, "--stable", env={"SQUAD_REF": "beta"}))     # an option wins over a variable
    assert head(h) == REFS["v0.10.0"]
    assert_ok(run(h, "--ref=" + REFS["v0.2.0"][:12]))             # a commit
    assert head(h) == REFS["v0.2.0"]
    r = run(h, "--ref", "no-such-thing")
    assert r.returncode != 0 and "not a branch, tag or commit" in r.out, r.out
    r = run(h, "--beta", "--ref", "main")
    assert r.returncode != 0 and "choose one" in r.out, r.out
    assert head(h) == REFS["v0.2.0"]


def test_a_ref_older_than_this_installer_is_refused_before_checkout():
    h = home()
    assert_ok(run(h))
    r = run(h, "--ref", "ancient")
    assert r.returncode != 0 and "predates this installer" in r.out, r.out
    assert head(h) == REFS["v0.10.0"]


def test_local_changes_in_the_clone_are_refused_and_kept():
    for change in ("tracked", "untracked"):
        h = home()
        assert_ok(run(h))
        settings = raw(settings_path(h))
        path = os.path.join(clone(h), "agents/developer.md" if change == "tracked" else "notes.txt")
        write(path, "my local edit\n")
        r = run(h, "--beta")
        assert r.returncode != 0 and "local changes" in r.out, r.out
        assert head(h) == REFS["v0.10.0"], "no checkout"
        with open(path) as fh:
            assert fh.read() == "my local edit\n"
        assert raw(settings_path(h)) == settings
        r = run(h, "--uninstall", "--purge")
        assert r.returncode != 0 and os.path.exists(path), "purge does not delete local work either"


def python_that_reports(version):
    """A python3 that runs get.sh's own version check as if it were `version`,
    and is the real interpreter for everything else."""
    real = shlex.quote(sys.executable)
    fake_info = repr(tuple(version) + (0, "final", 0))
    return (f'if [ "$1" = -c ]; then exec {real} -c "import sys; sys.version_info = {fake_info}; '
            f'exec(sys.argv[1])" "$2"; fi\nexec {real} "$@"')


def test_python_older_than_3_10_stops_with_the_fix_and_changes_nothing():
    h = home()
    r = run(h, fake={"python3": python_that_reports((3, 9))})
    assert r.returncode != 0, r.out
    assert "3.10 or newer (found 3.9)" in r.out and "Nothing was changed" in r.out, r.out
    assert not os.path.exists(clone(h)) and not os.path.exists(config(h))
    r = run(h, fake={"python3": python_that_reports((3, 10))})
    assert_ok(r)                                  # 3.10 itself is enough
    assert_registered(h)


def test_a_real_file_in_the_way_is_reported_but_the_hooks_are_still_registered():
    h = home()
    write(os.path.join(config(h), "CLAUDE.md"), "my rules\n")
    r = run(h)
    assert r.returncode == 1 and "SKIPPED" in r.out, r.out
    with open(os.path.join(config(h), "CLAUDE.md")) as fh:
        assert fh.read() == "my rules\n"
    assert_registered(h)


def test_unknown_option_and_purge_without_uninstall_are_refused():
    h = home()
    for args in (["--nope"], ["--purge"]):
        r = run(h, *args)
        assert r.returncode != 0, r.out
    assert not os.path.exists(clone(h))


if __name__ == "__main__":
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print("ok ", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
