#!/usr/bin/env python3
"""scripts/squad_settings.py registers hooks that actually run on the platform.

Self-checking: the exit code is the verdict. Runs in a throwaway config dir and
never touches ~/.claude. The string tests run everywhere; the ones that need a
Windows path say so.

    python3 tests/test_squad_settings.py
"""
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import squad_settings as ss  # noqa: E402

WINDOWS = os.name == "nt"
MANIFEST = os.path.join(ROOT, "hooks", "manifest.json")


def which_only(**found):
    return lambda name: found.get(name)


def test_posix_command_is_what_it_always_was():
    cmd = ss.command_for("/home/u/.claude", "squad-watch.py", windows=False)
    assert cmd == "python3 " + shlex.quote(os.path.join("/home/u/.claude", "hooks", "squad-watch.py")), cmd


def test_windows_command_uses_forward_slashes_and_a_real_interpreter():
    cmd = ss.command_for(r"C:\Users\u\.claude", "squad-watch.py", windows=True, launcher="python")
    assert cmd == 'python "C:/Users/u/.claude/hooks/squad-watch.py"', cmd
    cmd = ss.command_for(r"C:\Users\Fábio T\.claude", "squad-watch.py", windows=True, launcher="py -3")
    assert cmd == 'py -3 "C:/Users/Fábio T/.claude/hooks/squad-watch.py"', cmd


def test_the_windows_interpreter_is_never_the_store_stub():
    stub = r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe"
    real = r"C:\Program Files\Python314\python.exe"
    pick = ss.interpreter
    assert pick(windows=False) == "python3"
    assert pick(windows=True, which=which_only(python=real)) == "python"
    assert pick(windows=True, which=which_only(python=stub, py=r"C:\Windows\py.exe"), probe=lambda: True) == "py -3"
    assert pick(windows=True, which=which_only(py=r"C:\Windows\py.exe"), probe=lambda: True) == "py -3"
    # nothing on PATH: the interpreter that is running this script, by absolute path
    got = pick(windows=True, which=which_only(python=stub), executable=r"C:\Program Files\Python314\python.exe")
    assert got == '"C:/Program Files/Python314/python.exe"', got


def test_the_py_launcher_is_used_only_when_it_has_a_python3():
    pick = ss.interpreter
    py = r"C:\Windows\py.exe"
    exe = r"C:\Program Files\Python314\python.exe"
    assert pick(windows=True, which=which_only(py=py), probe=lambda: True) == "py -3"
    assert pick(windows=True, which=which_only(py=py), executable=exe, probe=lambda: False) == \
        '"C:/Program Files/Python314/python.exe"'


def test_a_stale_python3_entry_is_repaired_on_windows_and_left_alone_on_posix():
    if WINDOWS:
        with tempfile.TemporaryDirectory() as tmp:
            config = config_with_hooks(tmp)
            path = os.path.join(config, "settings.json")
            stale = {"hooks": {"UserPromptSubmit": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "python3 " + shlex.quote(os.path.join(config, "hooks", "squad-router.py")),
                 "timeout": 5}]}]}}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(stale, fh)
            rc, out, _ = run_main("install", "--config", config, "--manifest", MANIFEST)
            assert rc == 0 and "fixed   squad-router.py" in out, out
            cmds = [c for c in squad_commands(json.loads(read(path))) if "squad-router.py" in c]
            assert len(cmds) == 1 and not cmds[0].startswith("python3"), cmds      # repaired, not duplicated
            rc, out, _ = run_main("install", "--config", config, "--manifest", MANIFEST)
            assert "fixed" not in out, out                                          # and then stable
    groups = [{"hooks": [{"type": "command", "command": "python3 /home/u/.claude/hooks/squad-router.py"}]}]
    assert ss.repair_stale(groups, "/home/u/.claude", "squad-router.py", windows=False) == 0
    assert groups[0]["hooks"][0]["command"].startswith("python3 ")


def test_split_reads_both_spellings_of_a_windows_command():
    words = ss.split_command(r'python "C:\Users\u\.claude\hooks\squad-watch.py"', windows=True)
    assert words == ["python", r"C:\Users\u\.claude\hooks\squad-watch.py"], words
    words = ss.split_command('py -3 "C:/Users/u/.claude/hooks/squad-watch.py"', windows=True)
    assert words == ["py", "-3", "C:/Users/u/.claude/hooks/squad-watch.py"], words
    assert ss.split_command("python3 '/home/u/a b/x.py'", windows=False) == ["python3", "/home/u/a b/x.py"]
    assert ss.split_command('python "unterminated', windows=True) is None


def test_a_windows_hook_command_is_recognised_as_the_squads():
    if not WINDOWS:
        return        # needs Windows path semantics (drive letters, case-insensitive)
    with tempfile.TemporaryDirectory() as tmp:
        config = os.path.join(tmp, ".claude")
        os.makedirs(os.path.join(config, "hooks"))
        script = os.path.join(config, "hooks", "squad-watch.py")
        open(script, "w").close()
        fwd, back = script.replace("\\", "/"), script
        ok = lambda c: ss.squad_script(c, config, windows=True)       # noqa: E731
        assert ok(f'python "{fwd}"') == "squad-watch.py"
        assert ok(f'python "{back}"') == "squad-watch.py"
        assert ok(f'py -3 "{fwd}"') == "squad-watch.py"
        assert ok(f'python3 "{fwd}"') == "squad-watch.py"
        assert ok(f'"{sys.executable}" "{fwd}"') == "squad-watch.py"
        assert ok(f'python "{fwd.upper()}"') == "squad-watch.py"      # Windows paths do not care about case
        # a user's own hook that shares the file name, and things that are not an interpreter call
        assert ok('python "C:/opt/mine/squad-watch.py"') is None
        assert ok(f'grep squad-watch.py "{fwd}"') is None
        assert ok(f'python -c "{fwd}"') is None
        assert ok(f'python "{fwd}" --extra') is None


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = ss.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def config_with_hooks(tmp):
    config = os.path.join(tmp, ".claude")
    os.makedirs(os.path.join(config, "hooks"))
    for name in ("squad-router.py", "squad-watch.py"):
        with open(os.path.join(config, "hooks", name), "w") as fh:
            fh.write('print("ran " + __file__.replace("\\\\", "/").rsplit("/", 1)[-1])\n')
    return config


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def squad_commands(settings):
    return [h["command"] for groups in settings.get("hooks", {}).values() for g in groups for h in g["hooks"]]


def test_install_twice_writes_once_and_the_command_runs():
    with tempfile.TemporaryDirectory() as tmp:
        config = config_with_hooks(tmp)
        path = os.path.join(config, "settings.json")
        rc, out, _ = run_main("install", "--config", config, "--manifest", MANIFEST)
        assert rc == 0 and "wrote" in out, out
        first = read(path)
        rc, out, _ = run_main("install", "--config", config, "--manifest", MANIFEST)
        assert rc == 0 and "nothing to change" in out, out
        assert read(path) == first
        assert not [n for n in os.listdir(config) if ".bak-" in n], os.listdir(config)   # no file existed the first time
        cmds = squad_commands(json.loads(first))
        assert cmds, first
        if WINDOWS:
            assert not any(c.startswith("python3") for c in cmds), cmds              # the Store stub
        # the command a hook event would run, through a shell, does what the script does
        done = subprocess.run(next(c for c in cmds if "squad-router.py" in c), shell=True, capture_output=True,
                              text=True, timeout=60)
        assert done.stdout.strip() == "ran squad-router.py", (done.stdout, done.stderr)


def test_uninstall_takes_the_squads_entries_and_nothing_else():
    with tempfile.TemporaryDirectory() as tmp:
        config = config_with_hooks(tmp)
        path = os.path.join(config, "settings.json")
        theirs = {"type": "command", "command": "python /opt/mine/squad-watch.py"}
        other = {"hooks": {"Stop": [{"hooks": [theirs]}]}, "model": "opus", "env": {"A": "1"}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(other, fh)
        run_main("install", "--config", config, "--manifest", MANIFEST)
        rc, out, _ = run_main("uninstall", "--config", config, "--manifest", MANIFEST)
        assert rc == 0, out
        left = json.loads(read(path))
        assert left == other, left


def test_the_entries_from_the_installation_doc_are_still_recognised():
    # docs/installation.md registers `python3 ~/.claude/hooks/<script>`: install must keep them, uninstall remove them
    with tempfile.TemporaryDirectory() as tmp:
        saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
        try:
            config = config_with_hooks(tmp)
            path = os.path.join(config, "settings.json")
            doc = {"hooks": {"UserPromptSubmit": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "python3 ~/.claude/hooks/squad-router.py", "timeout": 5}]}]}}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            rc, out, _ = run_main("install", "--config", config, "--manifest", MANIFEST)
            if WINDOWS:      # there `python3` is the Store stub: install repairs the entry instead of keeping it
                assert rc == 0 and "fixed   squad-router.py" in out, out
            else:
                assert rc == 0 and "squad-router.py  UserPromptSubmit (already registered)" in out, out
            rc, out, _ = run_main("uninstall", "--config", config, "--manifest", MANIFEST)
            assert rc == 0 and "off     UserPromptSubmit:" in out and "squad-router.py" in out, out
            assert squad_commands(json.loads(read(path))) == []
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
