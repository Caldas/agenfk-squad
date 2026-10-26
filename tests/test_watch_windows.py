#!/usr/bin/env python3
"""The watcher's platform seams: lock, file owner, handoff paths, detached children.

Self-checking: the exit code is the verdict. Runs in a throwaway profile and
never touches ~/.claude. Everything that can be checked from either platform
is checked on both; the rest says which platform it needs.

    python3 tests/test_watch_windows.py
"""
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "squad-watch.py")
SCRIPTS = os.path.join(ROOT, "skills", "session-context", "scripts")
WINDOWS = os.name == "nt"

# the module computes ~/.claude at import: point it at a throwaway profile first
# (Windows reads USERPROFILE, not HOME)
_profile = tempfile.mkdtemp(prefix="watchwin-")
os.environ["HOME"] = os.environ["USERPROFILE"] = _profile
_spec = importlib.util.spec_from_file_location("squad_watch", HOOK)
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)


def test_the_hook_imports_on_this_platform():
    assert hasattr(sw, "lock_file") and hasattr(sw, "owned_by_me")


def test_the_lock_keeps_a_second_process_out_until_released():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "q.lock")
        # the child waits up to argv[1] seconds: the OS may release a closed handle's lock a moment late
        child = textwrap.dedent(f"""
            import importlib.util, sys, time
            spec = importlib.util.spec_from_file_location("squad_watch", {HOOK!r})
            sw = importlib.util.module_from_spec(spec); spec.loader.exec_module(sw)
            fh = open({path!r}, "a")
            deadline = time.time() + float(sys.argv[1])
            while not sw.lock_file(fh, block=False):
                if time.time() > deadline:
                    print(False)
                    break
                time.sleep(0.05)
            else:
                print(True)
        """)
        env = dict(os.environ, HOME=tmp, USERPROFILE=tmp)
        with open(path, "w") as held:
            sw.lock_file(held)
            r = subprocess.run([sys.executable, "-c", child, "0.3"], capture_output=True, text=True, env=env, timeout=30)
            assert r.stdout.strip() == "False", (r.stdout, r.stderr)
        r = subprocess.run([sys.executable, "-c", child, "10"], capture_output=True, text=True, env=env, timeout=30)
        assert r.stdout.strip() == "True", (r.stdout, r.stderr)


def test_a_file_of_mine_is_mine():
    with tempfile.NamedTemporaryFile() as fh:
        assert sw.owned_by_me(os.stat(fh.name))


def test_the_owner_check_is_uid_on_posix_and_the_profile_acl_on_windows():
    other = 12345 if WINDOWS else os.getuid() + 1
    fake = os.stat_result((stat.S_IFREG | 0o600, 0, 0, 1, other, 0, 0, 0, 0, 0))
    assert sw.owned_by_me(fake) is WINDOWS      # Windows has no uid to compare: the ACL is the boundary


def test_handoff_paths_in_both_spellings():
    ok = sw.handoff_path_ok
    assert ok("/srv/u/.claude/handoffs/20261026-101010-win.md", windows=False)
    assert ok(r"C:\Profiles\u\.claude\handoffs\20261026-101010-win.md", windows=True)
    assert ok("C:/Profiles/u/.claude/handoffs/20261026-101010-win.md", windows=True)
    assert ok(r"C:\Profiles\Fábio T\.claude\handoffs\a.md", windows=True)     # accents and spaces live in profiles
    assert ok(r"C:\Profiles\FABIOT~1\.claude\handoffs\a.md", windows=True)    # 8.3 short names


def test_handoff_paths_that_must_be_refused():
    ok = sw.handoff_path_ok
    assert not ok(r"C:\Profiles\u\..\handoffs\a.md", windows=True)            # parent segment
    assert not ok(r"handoffs\a.md", windows=True)                          # relative
    assert not ok(r"\\server\share\handoffs\a.md", windows=True)           # UNC share
    assert not ok(r"C:\Profiles\u\handoffs\a.txt", windows=True)              # not a handoff file
    assert not ok(r"C:\Profiles\u\handoffs\a;b.md", windows=True)             # shell metacharacter
    assert not ok(r"C:\Profiles\...\handoffs\a.md", windows=True)             # a segment of dots only
    assert not ok(r"C:\Profiles\ \handoffs\a.md", windows=True)               # a segment of spaces only
    assert not ok(r"C:\Profiles\u\handoffs\a.md:stream", windows=True)        # alternate data stream
    assert not ok("/srv/u/../handoffs/a.md", windows=False)
    assert not ok("/srv/u/handoffs/a b.md", windows=False)                # POSIX stays strict
    assert not ok(r"C:\Profiles\u\handoffs\a.md", windows=False)              # a drive path is not POSIX


def test_the_harness_is_read_from_a_windows_path():
    h = sw.harness
    assert h({"transcript_path": r"C:\Profiles\u\.omp\agent\sessions\p\s.jsonl"}) == "omp"
    assert h({"transcript_path": r"C:\Profiles\u\.pi\agent\sessions\p\s.jsonl"}) == "pi"
    assert h({"transcript_path": r"C:\Profiles\u\.codex\sessions\s.jsonl"}) == "codex"
    assert h({"transcript_path": r"C:\Profiles\u\.claude\projects\p\s.jsonl"}) == "claude"


def test_a_detached_child_is_detached_the_way_the_platform_does_it():
    posix = sw.detached_kwargs(windows=False)
    assert posix.get("start_new_session") is True and "creationflags" not in posix
    win = sw.detached_kwargs(windows=True)
    assert win["creationflags"] == 0x08000000 | 0x00000200      # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    assert "start_new_session" not in win


def test_a_detached_child_really_runs_after_being_started():
    with tempfile.TemporaryDirectory() as tmp:
        marker = os.path.join(tmp, "ran")
        code = f"open({marker!r}, 'w').write('x')"
        subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **sw.detached_kwargs())
        for _ in range(100):
            if os.path.exists(marker):
                break
            time.sleep(0.1)
        assert os.path.exists(marker)


def write_transcript_with_handoff(tmp, body_on_disk, content):
    folder = os.path.join(tmp, "proj", ".claude", "handoffs")
    os.makedirs(folder)
    path = os.path.join(folder, "20261026-000000-x.md")
    with open(path, "wb") as fh:
        fh.write(body_on_disk)
    transcript = os.path.join(tmp, "s.jsonl")
    rec = {"type": "assistant", "isSidechain": False, "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": path, "content": content}}]}}
    with open(transcript, "w") as fh:
        fh.write(json.dumps(rec) + "\n")
    return path, transcript


def test_own_handoff_reads_the_path_as_this_platform_writes_it_and_digests_the_disk():
    with tempfile.TemporaryDirectory() as tmp:
        body = b"# handoff\nNext step: X\n"
        path, transcript = write_transcript_with_handoff(tmp, body, body.decode())
        assert sw.own_handoff(transcript, 0) == (path, hashlib.sha256(body).hexdigest())


def test_crlf_on_disk_passes_on_windows_and_is_refused_on_posix():
    with tempfile.TemporaryDirectory() as tmp:
        text = "# handoff\nNext step: X\n"
        on_disk = text.replace("\n", "\r\n").encode()
        path, transcript = write_transcript_with_handoff(tmp, on_disk, text)
        got = sw.own_handoff(transcript, 0)
        if WINDOWS:
            assert got == (path, hashlib.sha256(on_disk).hexdigest())      # the switch checks the disk bytes
        else:
            assert got is None                                              # byte for byte, as before


def load_switch(copies):
    spec = importlib.util.spec_from_file_location("squad_switch", os.path.join(ROOT, "hooks", "squad-switch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.COPIES = copies
    return mod


def test_the_switch_takes_the_same_handoff_paths_as_the_watcher():
    sws = load_switch(os.path.join(_profile, "copies"))
    assert sws.handoff_ok("/srv/u/.claude/handoffs/a.md") is sw.handoff_path_ok("/srv/u/.claude/handoffs/a.md")
    assert not sws.handoff_ok("/srv/u/../handoffs/a.md")
    if WINDOWS:
        assert sws.handoff_ok(r"C:\Profiles\u\.claude\handoffs\a.md")
        assert not sws.handoff_ok(r"\\server\share\handoffs\a.md")


def test_the_sealed_copy_can_be_made_twice_and_a_changed_handoff_is_refused():
    # the copy is read-only: on Windows os.replace cannot overwrite it, so the second call reuses it
    with tempfile.TemporaryDirectory() as tmp:
        body = b"# handoff\nNext step: X\n"
        digest = hashlib.sha256(body).hexdigest()
        original = os.path.join(tmp, "proj", ".claude", "handoffs", "a.md")
        os.makedirs(os.path.dirname(original))
        with open(original, "wb") as fh:
            fh.write(body)
        sws = load_switch(os.path.join(tmp, "copies"))
        first = sws.sealed_copy(original, digest, "abcdef12-0001")
        second = sws.sealed_copy(original, digest, "abcdef12-0001")
        assert first and first == second, (first, second)
        with open(first, "rb") as fh:
            assert fh.read() == body
        assert sws.sealed_copy(original, "0" * 64, "abcdef12-0001") is None


def test_without_herdr_the_session_cannot_be_switched():
    old = os.environ.pop("HERDR_PANE_ID", None)
    try:
        assert not sw.can_switch()
    finally:
        if old is not None:
            os.environ["HERDR_PANE_ID"] = old


def test_the_handoff_search_ends_at_the_top_of_the_tree():
    # `while probe != "/"` never ends on a drive root: dirname("C:\\") is "C:\\"
    sys.path.insert(0, SCRIPTS)
    import session_context as cx
    result = []
    with tempfile.TemporaryDirectory() as tmp:
        t = threading.Thread(target=lambda: result.append(cx.latest_handoff(tmp)), daemon=True)
        t.start()
        t.join(15)
        assert not t.is_alive(), "latest_handoff() is still walking up the tree"
    assert result[0] == (None, None), result


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
