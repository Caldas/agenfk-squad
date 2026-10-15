#!/usr/bin/env python3
"""The heavy review exits 0 only when another model said SHIP on its last line.

Self-checking: the exit code is the verdict. Each test builds a real git
repository with a linked worktree, and a PATH holding only git, python3 and
fake `agenfk` / `codex` binaries: no network, no real model.

    python3 tests/test_review.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "hooks", "squad-review.py")
CARD = "c0ffee00-0000-4000-8000-000000000001"
CRITERION = "the widget answers 42"

FAKE_AGENFK = f"""#!/usr/bin/env python3
import json, os, sys
if os.environ.get("FAKE_AGENFK_RC"):
    sys.exit(int(os.environ["FAKE_AGENFK_RC"]))
assert sys.argv[1:] == ["get", {CARD!r}, "--json"], sys.argv
print(json.dumps({{"id": {CARD!r}, "title": "Widget answers", "status": "IN_PROGRESS",
                  "description": "Acceptance: {CRITERION}.",
                  "comments": [{{"content": "Target: the widget module."}}]}}))
"""

# Records its argv and stdin, then answers FAKE_REPLY (with \\n escapes) and exits FAKE_RC.
# As codex it writes the answer to --output-last-message and prints noise on stdout.
FAKE_REVIEWER = """#!/usr/bin/env python3
import json, os, sys, time
log = os.environ["FAKE_LOG"]
with open(log, "w") as fh:
    json.dump({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd()}, fh)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
reply = os.environ.get("FAKE_REPLY", "").replace("\\\\n", "\\n")
if "--output-last-message" in sys.argv:
    with open(sys.argv[sys.argv.index("--output-last-message") + 1], "w") as fh:
        fh.write(reply)
    print("codex event noise, VERDICT: SHIP")
else:
    print(reply)
sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""


def executable(path, body):
    with open(path, "w") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def setup(codex=True, change=True):
    """(worktree, env, log path). A repo with origin/main, and a worktree on the card's branch."""
    h = tempfile.mkdtemp(prefix="review-")
    repo, wt, bin_dir = os.path.join(h, "repo"), os.path.join(h, "wt-card"), os.path.join(h, "bin")
    os.makedirs(repo)
    os.makedirs(bin_dir)
    for tool, target in (("git", shutil.which("git")), ("python3", sys.executable)):
        os.symlink(target, os.path.join(bin_dir, tool))
    executable(os.path.join(bin_dir, "agenfk"), FAKE_AGENFK)
    executable(os.path.join(h, "reviewer"), FAKE_REVIEWER)
    if codex:
        os.symlink(os.path.join(h, "reviewer"), os.path.join(bin_dir, "codex"))
    git(h, "init", "-q", "-b", "main", repo)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    with open(os.path.join(repo, "widget.py"), "w") as fh:
        fh.write("def answer():\n    return 41\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "worktree", "add", "-q", "-b", "feat/widget", wt)
    if change:
        with open(os.path.join(wt, "widget.py"), "w") as fh:
            fh.write("def answer():\n    return 42\n")
        git(wt, "commit", "-q", "-am", "widget answers 42")
    env = {"PATH": bin_dir, "HOME": h, "FAKE_LOG": os.path.join(h, "reviewer.json"),
           "GIT_CONFIG_NOSYSTEM": "1", "LANG": "C.UTF-8"}
    return wt, env, env["FAKE_LOG"]


def review(wt, env, *extra, **fake):
    e = dict(env)
    e.update({f"FAKE_{k.upper()}": str(v) for k, v in fake.items()})
    r = subprocess.run([sys.executable, SCRIPT, "--card", CARD, *extra], cwd=wt, env=e,
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def reports(wt):
    folder = os.path.join(git(wt, "rev-parse", "--absolute-git-dir"), "squad-review")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def called(log):
    if not os.path.exists(log):
        return None
    with open(log) as fh:
        return json.load(fh)


def test_ship_exits_zero_and_writes_the_report_in_the_worktree_git_dir():
    wt, env, log = setup()
    head = git(wt, "rev-parse", "HEAD")
    rc, out, err = review(wt, env, reply="Looks right.\\nVERDICT: SHIP")
    assert rc == 0, (rc, out, err)
    assert out.rstrip().splitlines()[-1] == "VERDICT: SHIP", out
    assert reports(wt) == [f"{head}.md"]
    gitdir = git(wt, "rev-parse", "--absolute-git-dir")
    assert "worktrees" in gitdir                      # the worktree's own git dir, not the main repo's
    with open(os.path.join(gitdir, "squad-review", f"{head}.md")) as fh:
        report = fh.read()
    assert CARD in report and "codex exec --sandbox read-only" in report, report
    assert report.rstrip().endswith("VERDICT: SHIP"), report
    assert git(wt, "status", "--short") == ""        # the report stays out of git status
    seen = called(log)
    a = seen["argv"]
    assert a[0] == "exec" and a[a.index("--sandbox") + 1] == "read-only", a
    assert a[-1] == "-", a                            # prompt on stdin
    assert os.path.realpath(seen["cwd"]) == os.path.realpath(wt)
    for needle in (CRITERION, "Target: the widget module.", "+    return 42", "-    return 41",
                   "widget answers 42", "VERDICT: SHIP\nVERDICT: FIX_FIRST\nVERDICT: REJECT"):
        assert needle in seen["stdin"], needle


def test_fix_first_and_reject_exit_non_zero_and_send_the_card_back():
    for word in ("FIX_FIRST", "REJECT"):
        wt, env, _ = setup()
        rc, out, err = review(wt, env, reply=f"widget.py:2 is wrong.\\n**VERDICT: {word}**")
        assert rc == 1, (word, rc, out, err)
        assert out.rstrip().splitlines()[-1] == f"VERDICT: {word}", out
        assert "Back to IMPLEMENT" in out
        assert reports(wt) == [git(wt, "rev-parse", "HEAD") + ".md"]


def test_no_reviewer_is_an_error_that_says_how_to_continue():
    wt, env, log = setup(codex=False)
    rc, out, err = review(wt, env, reply="VERDICT: SHIP")
    assert rc == 2, (rc, out, err)
    assert "SQUAD_REVIEWER" in err and "codex" in err, err
    assert "VERDICT: SHIP" not in out and reports(wt) == []
    rc, out, err = review(wt, dict(env, SQUAD_REVIEWER="not-a-real-reviewer --model x"), reply="VERDICT: SHIP")
    assert rc == 2 and "not-a-real-reviewer" in err, (rc, err)
    assert called(log) is None


def test_an_answer_without_a_verdict_on_its_last_line_is_never_ship():
    for reply in ("Looks fine to me.",
                  "VERDICT: SHIP\\nOn second thought, the tests are missing.",
                  "VERDICT: SHIP|FIX_FIRST|REJECT",
                  "Final VERDICT: SHIP",
                  ""):
        wt, env, _ = setup()
        head = git(wt, "rev-parse", "HEAD")
        rc, out, err = review(wt, env, reply=reply)
        assert rc == 2, (reply, rc, out, err)
        assert "does not end with" in err, err
        assert out == "", out
        assert reports(wt) == [f"{head}.invalid.md"], reports(wt)   # kept for reading, never as evidence


def test_a_reviewer_that_fails_or_hangs_gives_no_verdict():
    wt, env, _ = setup()
    rc, out, err = review(wt, env, reply="VERDICT: SHIP", rc=3)
    assert rc == 2 and "reviewer failed" in err and out == "", (rc, out, err)
    rc, out, err = review(wt, dict(env, SQUAD_REVIEW_TIMEOUT="1"), reply="VERDICT: SHIP", sleep=5)
    assert rc == 2 and "within 1 s" in err and out == "", (rc, out, err)
    assert not any(n.endswith(".md") and not n.endswith(".invalid.md") for n in reports(wt))


def test_squad_reviewer_takes_the_prompt_on_stdin_and_is_named_in_the_report():
    wt, env, log = setup(codex=False)
    reviewer = os.path.join(os.path.dirname(wt), "reviewer")
    rc, out, err = review(wt, dict(env, SQUAD_REVIEWER=f"{reviewer} -p --model other-model"),
                          reply="All criteria met.\\nVERDICT: SHIP")
    assert rc == 0, (rc, out, err)
    seen = called(log)
    assert seen["argv"] == ["-p", "--model", "other-model"], seen["argv"]
    assert CRITERION in seen["stdin"]
    with open(os.path.join(git(wt, "rev-parse", "--absolute-git-dir"), "squad-review",
                           git(wt, "rev-parse", "HEAD") + ".md")) as fh:
        assert "--model other-model" in fh.read()


def test_empty_diff_does_not_call_the_reviewer():
    wt, env, log = setup(change=False)
    rc, out, err = review(wt, env, reply="VERDICT: SHIP")
    assert rc == 2 and "nothing to review" in err, (rc, out, err)
    assert called(log) is None and reports(wt) == []


def test_unreadable_card_or_missing_base_stops_before_the_reviewer():
    wt, env, log = setup()
    rc, out, err = review(wt, env, reply="VERDICT: SHIP", agenfk_rc=1)
    assert rc == 2 and "could not read card" in err, (rc, err)
    rc, out, err = review(wt, env, "--base", "origin/nope", reply="VERDICT: SHIP")
    assert rc == 2 and "origin/nope" in err and "--base" in err, (rc, err)
    assert called(log) is None and reports(wt) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
