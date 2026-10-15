#!/usr/bin/env python3
"""The seal: squad-seal records a SHIP verdict for one exact commit, and with the
seal on, squad-watch lets a merge through only for a sealed SHA.

Self-checking: the exit code is the verdict. Runs in a throwaway HOME and never
touches ~/.claude.

    python3 tests/test_seal.py
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAL = os.path.join(ROOT, "hooks", "squad-seal.py")
WATCH = os.path.join(ROOT, "hooks", "squad-watch.py")
GM = "gh pr " + "merge"


def env(h, **kw):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "HERDR_"))}
    e.update(HOME=h, **kw)
    return e


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def setup():
    """HOME, a worktree with one commit on branch feat, an evidence file and a fake gh."""
    h = tempfile.mkdtemp(prefix="seal-")
    repo = os.path.join(h, "repo")
    subprocess.run(["git", "init", "-q", "-b", "feat", repo], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "a")
    ev = report(h, git(repo, "rev-parse", "HEAD"))
    head = os.path.join(h, "pr-head")
    gh = os.path.join(h, "gh")
    with open(gh, "w") as fh:
        fh.write(f"""#!/usr/bin/env python3
import json, sys
print(json.dumps({{"number": 5, "baseRefName": "main", "headRefName": "feat",
                  "headRefOid": open({head!r}).read().strip()}}))
""")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
    point(head, git(repo, "rev-parse", "HEAD"))
    return h, repo, ev, head, gh


def report(h, sha):
    """The verifier's report of this commit, named after it."""
    path = os.path.join(h, f"{sha}.md")
    with open(path, "w") as fh:
        fh.write("SHIP\n")
    return path


def point(head, sha):
    with open(head, "w") as fh:
        fh.write(sha)


def seal(h, repo, *args):
    return subprocess.run([sys.executable, SEAL, *args], cwd=repo, capture_output=True, text=True, env=env(h))


def record(h, repo, ev, verdict="SHIP"):
    return seal(h, repo, "record", "--card", "card-1", "--model", "m1", "--verdict", verdict, "--evidence", ev)


def merge(h, repo, gh, cmd=f"{GM} 5", **kw):
    p = {"hook_event_name": "PreToolUse", "session_id": "abab1212-0001", "transcript_path": os.path.join(h, "t.jsonl"),
         "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": repo}
    out = subprocess.run([sys.executable, WATCH], input=json.dumps(p), capture_output=True, text=True,
                         env=env(h, SQUAD_GH=gh, **kw)).stdout.strip()
    if not out:
        return "nothing"
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def test_record_writes_a_private_seal_of_head_and_show_reads_it():
    h, repo, ev, _, _ = setup()
    r = record(h, repo, ev)
    assert r.returncode == 0, r.stderr
    sha = git(repo, "rev-parse", "HEAD")
    folder = os.path.join(h, ".claude", "squad", "seals")
    (sub,) = os.listdir(folder)
    path = os.path.join(folder, sub, f"{sha}.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with open(path) as fh:
        d = json.load(fh)
    assert set(d) == {"repo", "branch", "sha", "card", "at", "model", "verdict", "evidence"}, d
    assert (d["sha"], d["branch"], d["card"], d["model"], d["verdict"]) == (sha, "feat", "card-1", "m1", "SHIP")
    assert d["repo"] == os.path.realpath(os.path.join(repo, ".git")) and d["evidence"] == os.path.realpath(ev)
    assert json.loads(seal(h, repo, "show").stdout)["sha"] == sha
    assert json.loads(seal(h, repo, "show", sha).stdout)["sha"] == sha
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("b\n")
    git(repo, "commit", "-qam", "b")
    assert seal(h, repo, "show").returncode == 1                       # the new HEAD has no seal


def test_record_refuses_dirty_worktree_and_a_verdict_other_than_ship():
    h, repo, ev, _, _ = setup()
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("dirty\n")
    r = record(h, repo, ev)
    assert r.returncode == 1 and "dirty" in r.stderr and "a.txt" in r.stderr, r.stderr
    git(repo, "checkout", "--", "a.txt")
    with open(os.path.join(repo, "new.txt"), "w") as fh:
        fh.write("untracked\n")
    assert record(h, repo, ev).returncode == 1                         # untracked counts as dirty too
    os.remove(os.path.join(repo, "new.txt"))
    for verdict in ("FIX_FIRST", "REJECT", "ship"):
        r = record(h, repo, ev, verdict)
        assert r.returncode == 1 and "only SHIP" in r.stderr, (verdict, r.stderr)
    assert not os.path.exists(os.path.join(h, ".claude", "squad", "seals"))
    assert record(h, repo, ev).returncode == 0


def test_seal_on_merge_needs_a_seal_of_the_pr_head():
    h, repo, ev, head, gh = setup()
    assert merge(h, repo, gh) == "nothing"                             # seal off: no seal needed
    git(repo, "config", "squad.seal", "true")
    out = merge(h, repo, gh)
    assert "MERGE SEAL" in out and "no seal for that SHA" in out and "squad-seal record --card" in out, out
    assert record(h, repo, ev).returncode == 0
    assert merge(h, repo, gh) == "nothing"                             # sealed head: passes
    sealed = git(repo, "rev-parse", "HEAD")
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("after the review\n")
    git(repo, "commit", "-qam", "after")
    point(head, git(repo, "rev-parse", "HEAD"))
    assert record(h, repo, ev).returncode == 1                         # the old report does not cover the new HEAD
    out = merge(h, repo, gh)                                           # a seal of another SHA does not count
    assert "MERGE SEAL" in out and f"is for {sealed[:12]}" in out and "moved after the verification" in out, out
    assert merge(h, repo, gh, SQUAD_SEAL="0") == "nothing"
    git(repo, "config", "squad.seal", "false")
    assert "MERGE SEAL" in merge(h, repo, gh, SQUAD_SEAL="1")          # the variable turns it on too


def test_seal_on_push_to_trunk_needs_a_seal_of_the_pushed_sha():
    h, repo, ev, _, gh = setup()
    git(repo, "config", "squad.seal", "true")
    out = merge(h, repo, gh, "git push origin HEAD:main")
    assert "MERGE SEAL" in out and "push to the trunk" in out, out
    assert "MERGE SEAL" in merge(h, repo, gh, "git push origin +HEAD:refs/heads/main")
    assert record(h, repo, ev).returncode == 0
    assert merge(h, repo, gh, "git push origin HEAD:main") == "nothing"
    assert merge(h, repo, gh, "git push origin feat") == "nothing"     # not the trunk: no seal needed


def test_record_refuses_evidence_that_is_not_the_report_of_head():
    h, repo, ev, _, _ = setup()
    other = os.path.join(h, "notes.md")
    with open(other, "w") as fh:
        fh.write("SHIP\n")
    for bad in (other, os.path.join(h, "0" * 40 + ".md"), os.path.join(h, "missing", os.path.basename(ev))):
        r = record(h, repo, bad)
        assert r.returncode == 1 and "report of this very commit" in r.stderr, (bad, r.stderr)
    eleven = os.path.join(h, os.path.basename(ev)[:11] + ".md")
    os.rename(ev, eleven)
    r = record(h, repo, eleven)
    assert r.returncode == 1 and "at least 12 characters" in r.stderr, r.stderr   # 11 is too short
    short = os.path.join(h, os.path.basename(ev)[:12] + ".md")
    os.rename(eleven, short)
    assert record(h, repo, short).returncode == 0                      # a 12-character prefix is enough


def test_a_seal_file_whose_verdict_is_not_ship_does_not_count():
    """The watcher reads the verdict, not only the SHA: a seal file edited, or
    written by something else, with another verdict is no seal."""
    h, repo, ev, _, gh = setup()
    git(repo, "config", "squad.seal", "true")
    assert record(h, repo, ev).returncode == 0 and merge(h, repo, gh) == "nothing"
    folder = os.path.join(h, ".claude", "squad", "seals")
    (sub,) = os.listdir(folder)
    (name,) = os.listdir(os.path.join(folder, sub))
    path = os.path.join(folder, sub, name)
    with open(path) as fh:
        d = json.load(fh)
    for verdict in ("FIX_FIRST", "REJECT", "ship", None):
        with open(path, "w") as fh:
            json.dump({**d, "verdict": verdict}, fh)
        out = merge(h, repo, gh)
        assert "MERGE SEAL" in out and "no seal for that SHA" in out, (verdict, out)
        out = merge(h, repo, gh, "git push origin HEAD:main")
        assert "MERGE SEAL" in out, (verdict, out)


def test_seal_is_on_when_git_cannot_answer_the_setting():
    """Fail closed: when `git config squad.seal` cannot run (git missing or timed
    out), the seal counts as on; a plain "not set" leaves it off."""
    spec = importlib.util.spec_from_file_location("squad_watch", WATCH)
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    saved = os.environ.pop("SQUAD_SEAL", None)
    try:
        for answer, on in (((-1, ""), True), ((1, ""), False), ((0, "true"), True), ((0, "false"), False)):
            watch.git_rc = lambda *a, answer=answer, **k: answer
            assert watch.seal_on("/nowhere") is on, (answer, on)
    finally:
        if saved is not None:
            os.environ["SQUAD_SEAL"] = saved


def fake_gh(h, body, code=0):
    gh = os.path.join(h, "gh-broken")
    with open(gh, "w") as fh:
        fh.write(f"#!/usr/bin/env python3\nimport sys\nprint({body!r})\nsys.exit({code})\n")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
    return gh


def test_seal_on_any_failed_check_denies_the_merge():
    h, repo, ev, head, gh = setup()
    git(repo, "config", "squad.seal", "true")
    assert record(h, repo, ev).returncode == 0 and merge(h, repo, gh) == "nothing"
    assert "MERGE SEAL" in merge(h, repo, fake_gh(h, "boom", 1))                     # gh fails
    assert "MERGE SEAL" in merge(h, repo, fake_gh(h, '{"number": 5}'))               # no PR head SHA
    assert "MERGE SEAL" in merge(h, repo, gh, "git push origin no-such-ref:main")    # git cannot resolve
    folder = os.path.join(h, ".claude", "squad", "seals")
    (sub,) = os.listdir(folder)
    (name,) = os.listdir(os.path.join(folder, sub))
    with open(os.path.join(folder, sub, name), "w") as fh:
        fh.write("{not json")
    assert "MERGE SEAL" in merge(h, repo, gh)                                        # unreadable seal
    turn = os.path.join(h, ".claude", "squad", "turn")
    subprocess.run(["rm", "-rf", turn], check=True)
    with open(turn, "w") as fh:                                                      # the check raises
        fh.write("not a directory")
    out = merge(h, repo, gh)
    assert "MERGE SEAL" in out and "check failed" in out, out
    os.remove(turn)
    assert "MERGE SEAL" in merge(h, h, gh, SQUAD_SEAL="1")                           # outside any repository


def gh_by_target(h, prs):
    """A fake gh that answers `gh pr view [<target>] [--repo R]` from prs, keyed by
    "<target>" or "<R> <target>" ("" is the current branch's PR), and logs every argv."""
    table, log, gh = os.path.join(h, "prs-by-target.json"), os.path.join(h, "gh.log"), os.path.join(h, "gh-target")
    with open(table, "w") as fh:
        json.dump(prs, fh)
    with open(gh, "w") as fh:
        fh.write(f"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
open({log!r}, "a").write(json.dumps(a) + "\\n")
t = a[2] if a[:2] == ["pr", "view"] and len(a) > 2 and not a[2].startswith("-") else ""
key = (a[a.index("--repo") + 1] + " " + t) if "--repo" in a else t
pr = json.load(open({table!r})).get(key)
if pr is None:
    sys.exit(1)
print(json.dumps(pr) if "-q" not in a else pr.get(a[-1][1:], ""))
""")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
    return gh, log


def test_seal_checks_the_pr_the_merge_names_not_the_current_branch():
    """Review of the seal: `gh pr merge -t 'T' 7`, `-R o/r 7` and `gh pr merge
    other-branch` checked the seal of the current branch's PR, because gh pr view
    was called without the target. The target and --repo now reach gh pr view;
    with the seal on, a merge whose target cannot be read is denied."""
    h, repo, ev, _, _ = setup()
    assert record(h, repo, ev).returncode == 0                                       # the current branch is sealed
    sealed = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "other-branch")
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("other\n")
    git(repo, "commit", "-qam", "other")
    other = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "feat")

    def pr(n, branch, sha):
        return {"number": n, "baseRefName": "main", "headRefName": branch, "headRefOid": sha}
    url = "https://github.com/o/r/pull/7"
    gh, log = gh_by_target(h, {"": pr(3, "feat", sealed), "7": pr(7, "other-branch", other),
                               "5": pr(5, "other-branch", other), "o/r 7": pr(7, "other-branch", other),
                               "o/r 5": pr(5, "other-branch", other), "other-branch": pr(9, "other-branch", other),
                               url: pr(7, "other-branch", other)})
    git(repo, "config", "squad.seal", "true")
    assert merge(h, repo, gh, GM) == "nothing"                                       # no target: the current PR
    for cmd, argv in ((f"{GM} -t 'T' 7", ["7"]), (f"{GM} -R o/r 7", ["7", "--repo", "o/r"]),
                      (f"{GM} --repo o/r 5", ["5", "--repo", "o/r"]), (f"{GM} --body x 5", ["5"]),
                      (f"{GM} other-branch", ["other-branch"]), (f"{GM} {url}", [url]),
                      (f"{GM} --repo=o/r -st T '#7' -d", ["7", "--repo", "o/r"]), (f"{GM} -m 7", ["7"]),
                      (f"{GM} -sRo/r --match-head-commit {other} -- 7", ["7", "--repo", "o/r"]),
                      (f"cd {repo} && {GM} -b 'x y' -A a@b -F - 7 --auto 2>&1", ["7"])):
        os.remove(log) if os.path.exists(log) else None
        out = merge(h, repo, gh, cmd)
        assert "MERGE SEAL" in out and f"is at {other[:12]}" in out, (cmd, out)
        with open(log) as fh:
            calls = [json.loads(line) for line in fh]
        assert ["pr", "view", *argv] == calls[0][:2 + len(argv)] and calls[0][2 + len(argv)] == "--json", (cmd, calls)
    for cmd in (f"{GM} --frobnicate 7", f"{GM} 7 8", f"{GM} 7 -t", f"{GM} --repo o/r", f'{GM} "$PR"',
                f"timeout 60 {GM} 7", f"{GM} 'x;y'", f"{GM} -R 'o r' 7"):
        out = merge(h, repo, gh, cmd)
        assert "cannot tell which PR" in out and "squad-seal record" in out, (cmd, out)
        assert merge(h, repo, gh, cmd, SQUAD_SEAL="0") == "nothing", cmd               # seal off: the turn only
    p = {"hook_event_name": "PreToolUse", "session_id": "abab1212-0001", "transcript_path": os.path.join(h, "t.jsonl"),
         "tool_name": "mcp__github__merge_pull_request", "tool_input": {"owner": "o", "repo": "r", "pullNumber": 7},
         "cwd": repo}
    out = subprocess.run([sys.executable, WATCH], input=json.dumps(p), capture_output=True, text=True,
                         env=env(h, SQUAD_GH=gh)).stdout
    assert "MERGE SEAL" in out and f"is at {other[:12]}" in out, out                # the MCP tool names its repo too
    git(repo, "checkout", "-q", "other-branch")
    assert record(h, repo, report(h, other)).returncode == 0
    assert merge(h, repo, gh, f"{GM} -t 'T' -R o/r 7") == "nothing"                  # the named PR is sealed: passes


def test_install_links_squad_seal_like_squad_turn():
    h = tempfile.mkdtemp(prefix="install-")
    e = env(h, CLAUDE_CONFIG_DIR=os.path.join(h, "claude"), PATH="/usr/bin:/bin")
    subprocess.run(["bash", os.path.join(ROOT, "install.sh")], capture_output=True, text=True, env=e)
    for link in (os.path.join(h, "claude", "hooks", "squad-seal.py"), os.path.join(h, ".local", "bin", "squad-seal")):
        assert os.path.islink(link) and os.path.realpath(link) == os.path.realpath(SEAL), link


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
