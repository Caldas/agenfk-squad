#!/usr/bin/env python3
"""scripts/check_private_paths.py: no person's home directory in the tree, on either platform.

Self-checking: the exit code is the verdict. It writes throwaway trees under the OS temp dir and also runs
the check on this repository, which is what CI does.

    python3 tests/test_private_paths.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "check_private_paths.py")

# The paths under test are built from parts: written out whole, this very file would be a hit of the check.
POSIX_HOME = "/ho" + "me/"
WIN_USERS = "C:" + "\\Us" + "ers\\"
WIN_USERS_FWD = "C:" + "/Us" + "ers/"


def check(files):
    """Runs the check on a tree made of {relative path: text}; returns (exit code, output)."""
    with tempfile.TemporaryDirectory() as tree:
        for rel, text in files.items():
            path = os.path.join(tree, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        r = subprocess.run([sys.executable, CHECK, tree], capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout + r.stderr


def test_a_clean_tree_passes():
    rc, out = check({"a.md": "nothing private here\n", "b/c.py": "print('/srv/squad/x')\n"})
    assert rc == 0 and out.strip() == "", out


def test_a_posix_home_is_reported_with_file_and_line():
    rc, out = check({"docs/x.md": "ok\nsee " + POSIX_HOME + "alice/project/x\n"})
    assert rc == 1, out
    assert "x.md:2" in out.replace("\\", "/") and POSIX_HOME + "alice/" in out, out


def test_a_windows_profile_is_reported_in_every_spelling():
    for text in (WIN_USERS + "alice\\Desktop", WIN_USERS_FWD + "alice/Desktop",
                 (WIN_USERS + "Alice\\x").lower(),
                 (WIN_USERS + "alice\\x").replace("\\", "\\\\"),          # the same path inside JSON
                 "/mnt/c/Us" + "ers/alice/Desktop",                       # the same profile, seen from WSL
                 "D:" + "\\Us" + "ers\\alice\\x"):
        rc, out = check({"a.txt": text + "\n"})
        assert rc == 1, (text, out)


def test_other_spellings_of_a_profile_are_reported():
    for text in ("/Us" + "ers/alice/Desktop",                          # macOS
                 "file:///" + WIN_USERS_FWD + "alice/x",                # a file URL
                 "\\\\?\\" + WIN_USERS + "alice\\x"):                   # the extended-length form
        rc, out = check({"a.txt": text + "\n"})
        assert rc == 1, (text, out)


def test_a_route_or_a_url_that_says_users_is_not_a_profile():
    for text in ("GET:/us" + "ers/42/orders", "https://us" + "ers/api/x", "ssh://us" + "ers/x/y",
                 WIN_USERS + "..\\x", WIN_USERS + ".\\x", "api/us" + "ers/alice/orders", "/Us" + "ers/Shared/x"):
        rc, out = check({"a.txt": text + "\n"})
        assert rc == 0, (text, out)


def test_utf16_text_is_read_and_line_numbers_match_an_editor():
    with tempfile.TemporaryDirectory() as tree:
        with open(os.path.join(tree, "log.txt"), "wb") as fh:                  # what a Windows tool writes
            fh.write(("clean\r\nsee " + WIN_USERS + "alice\\x\r\n").encode("utf-16"))
        with open(os.path.join(tree, "b.txt"), "w", encoding="utf-8", newline="") as fh:
            fh.write("one\x0ctwo\n" + POSIX_HOME + "alice/x\n")                  # a form feed is not a line end
        r = subprocess.run([sys.executable, CHECK, tree], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 1, r.stdout
        assert "log.txt:2:" in r.stdout and "b.txt:2:" in r.stdout, r.stdout


def test_system_profiles_and_placeholders_are_not_people():
    for text in (WIN_USERS + "Public\\Documents", WIN_USERS + "Default\\AppData", WIN_USERS + "All Users\\x",
                 WIN_USERS + "<you>\\.claude", WIN_USERS + "%USERNAME%\\.claude", WIN_USERS + "$env\\x",
                 "%USERPROFILE%\\.claude", "~/.claude", "C:" + "\\Data\\someone\\.claude"):
        rc, out = check({"a.txt": text + "\n"})
        assert rc == 0, (text, out)


def test_vendored_binary_and_git_files_are_left_alone():
    rc, out = check({"skills/vendor/x/LICENSE": POSIX_HOME + "alice/\n", ".git/config": POSIX_HOME + "alice/\n"})
    assert rc == 0, out
    with tempfile.TemporaryDirectory() as tree:
        with open(os.path.join(tree, "font.ttf"), "wb") as fh:
            fh.write(b"\x00\x01" + POSIX_HOME.encode() + b"alice/\x00")
        r = subprocess.run([sys.executable, CHECK, tree], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_this_repository_is_clean():
    r = subprocess.run([sys.executable, CHECK, ROOT], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
