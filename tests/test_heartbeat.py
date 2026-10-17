#!/usr/bin/env python3
"""The board heartbeat prints nothing when nothing is stuck, and one line per stuck thing.

Self-checking: the exit code is the verdict. Runs in a throwaway HOME, with a
fake `agenfk` and a fake `gh` on a PATH that holds only them and `git`, and
never touches ~/.claude or the network.

    python3 tests/test_heartbeat.py
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "board-heartbeat", "scripts", "heartbeat.py")
DAY = 86400
PROJECT = "11111111-2222-3333-4444-555555555555"


def iso(seconds_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def git(*args, cwd=None, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(when)} +0000"
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


class World:
    """A HOME, a repository with a GitHub remote, a board and a PR list, all fresh."""

    def __init__(self, tools=("agenfk", "gh")):
        self.root = tempfile.mkdtemp(prefix="heartbeat-")
        self.home = os.path.join(self.root, "home")
        self.bin = os.path.join(self.root, "bin")
        self.fix = os.path.join(self.root, "fixtures")
        self.repo = os.path.join(self.root, "demo")
        for d in (self.home, self.bin, self.fix, self.repo):
            os.makedirs(d)
        os.symlink(shutil.which("git"), os.path.join(self.bin, "git"))
        for tool in tools:
            self.fake(tool)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "start", cwd=self.repo)
        git("remote", "add", "origin", "https://github.com/example/demo.git", cwd=self.repo)
        self.projects = [{"id": PROJECT, "name": "demo-board", "projectRoot": self.repo}]
        self.items = [{"id": "aaaaaaaa-0000-0000-0000-000000000001", "projectId": PROJECT, "status": "IN_PROGRESS",
                       "title": "fresh card", "updatedAt": iso(3600), "createdAt": iso(5 * DAY)}]
        self.prs = [{"number": 7, "title": "fresh PR", "isDraft": False, "createdAt": iso(3600), "latestReviews": []}]
        self.save()

    def fake(self, tool, body=None):
        """A stand-in CLI: answers the command line it is asked from a fixture file."""
        path = os.path.join(self.bin, tool)
        body = body or (
            "import sys, os\n"
            f"fix = {self.fix!r}\n"
            "a = sys.argv[1:]\n"
            "name = {('list-projects',): 'projects', ('list',): 'items', ('pr',): 'prs'}.get(tuple(a[:1]))\n"
            "if name is None:\n"
            "    sys.exit('unexpected: ' + ' '.join(a))\n"
            "sys.stdout.write(open(os.path.join(fix, name + '.json')).read())\n")
        with open(path, "w") as fh:
            fh.write(f"#!{sys.executable}\n{body}")
        os.chmod(path, 0o755)

    def save(self):
        for name in ("projects", "items", "prs"):
            with open(os.path.join(self.fix, name + ".json"), "w") as fh:
                json.dump(getattr(self, name), fh)

    def run(self, *args, env=None):
        e = {"HOME": self.home, "PATH": self.bin, "LANG": "C.UTF-8"}
        e.update(env or {})
        r = subprocess.run([sys.executable, SCRIPT, *args], cwd=self.root, capture_output=True, text=True,
                           env=e, timeout=60)
        assert "Traceback" not in r.stderr, r.stderr
        assert r.returncode == 0, (r.returncode, r.stderr)
        return [ln for ln in r.stdout.splitlines() if ln.strip()], r.stdout

    def worktree(self, name, age_days):
        path = os.path.join(self.root, name)
        when = time.time() - age_days * DAY
        git("worktree", "add", "-q", "-b", name, path, cwd=self.repo, when=when)
        gd = os.path.join(self.repo, ".git", "worktrees", name)
        for f in ("index", "HEAD"):
            os.utime(os.path.join(gd, f), (when, when))
        os.utime(os.path.join(gd, "logs", "HEAD"))          # a `git gc` rewrote the reflog today
        return path

    def turn(self, holder_age, queue=()):
        d = os.path.join(self.home, ".claude", "squad", "turn")
        os.makedirs(d, exist_ok=True)
        repo = os.path.realpath(os.path.join(self.repo, ".git"))
        now = time.time()
        holder = None if holder_age is None else {
            "session": "abcdef12-3456", "pr": "7", "branch": "feat/x", "since": now - holder_age,
            "seen": now - holder_age, "asked": now - holder_age}
        state = {"repo": repo, "holder": holder,
                 "queue": [{"session": s, "pr": "", "branch": "", "since": now, "seen": now, "asked": now - 60}
                           for s in queue]}
        with open(os.path.join(d, hashlib.sha1(repo.encode()).hexdigest()[:16] + ".json"), "w") as fh:
            json.dump(state, fh)

    def handoff(self, where, age_days):
        os.makedirs(where, exist_ok=True)
        path = os.path.join(where, f"20260101-000000-note-{age_days}.md")
        with open(path, "w") as fh:
            fh.write("# handoff\n")
        when = time.time() - age_days * DAY
        os.utime(path, (when, when))
        return path

    def fresh_everything(self):
        self.worktree("fresh-wt", 0)
        self.turn(60, queue=["bbbbbbbb-0001"])
        self.handoff(os.path.join(self.home, ".claude", "handoffs"), 1)
        self.handoff(os.path.join(self.home, ".claude", "squad", "handoffs"), 1)
        self.handoff(os.path.join(self.repo, ".claude", "handoffs"), 1)


def only(lines, check):
    assert len(lines) == 1, lines
    assert lines[0].startswith(check + " "), lines
    assert "Next: " in lines[0], lines
    return lines[0]


def test_nothing_stuck_prints_nothing():
    w = World()
    w.fresh_everything()
    w.items += [{"id": "aaaaaaaa-0000-0000-0000-000000000002", "projectId": PROJECT, "status": s,
                 "title": "waiting on purpose", "updatedAt": iso(40 * DAY)} for s in ("TODO", "DONE", "BLOCKED")]
    w.prs += [{"number": 8, "title": "draft", "isDraft": True, "createdAt": iso(9 * DAY), "latestReviews": []},
              {"number": 9, "title": "reviewed", "isDraft": False, "createdAt": iso(9 * DAY),
               "latestReviews": [{"state": "COMMENTED"}]}]
    w.save()
    lines, out = w.run()
    assert out == "", out


def test_stale_card_is_one_line_per_project_naming_the_oldest():
    w = World()
    w.fresh_everything()
    w.items += [{"id": f"cccccccc-0000-0000-0000-00000000000{i}", "projectId": PROJECT, "status": "REVIEW",
                 "title": f"stuck {i}", "updatedAt": iso(d * DAY)} for i, d in ((1, 5), (2, 9))]
    w.save()
    line = only(w.run()[0], "stale-card")
    assert "demo-board" in line and "2 card(s)" in line and "agenfk get cccccccc" in line and "stuck 2" in line, line
    assert w.run("--card-days", "10")[0] == []


def test_pr_with_no_review_is_one_line_with_the_verifier():
    w = World()
    w.fresh_everything()
    w.prs.append({"number": 12, "title": "nobody looked", "isDraft": False, "createdAt": iso(3 * DAY),
                  "latestReviews": []})
    w.save()
    line = only(w.run()[0], "pr-no-review")
    assert "demo" in line and "#12" in line and "verifier" in line and "gh pr view 12" in line, line


def test_pr_check_runs_only_where_there_is_a_github_remote():
    w = World()
    w.fresh_everything()
    w.prs.append({"number": 12, "title": "nobody looked", "isDraft": False, "createdAt": iso(3 * DAY),
                  "latestReviews": []})
    w.save()
    git("remote", "set-url", "origin", "https://git.example.invalid/demo.git", cwd=w.repo)
    assert w.run()[0] == []
    os.remove(os.path.join(w.bin, "gh"))           # no GitHub repository: a missing gh is not news either
    assert w.run()[0] == []


def test_merge_turn_held_past_the_max_reads_the_watchers_directory():
    w = World()
    w.fresh_everything()
    w.turn(3700, queue=["bbbbbbbb-0001", "bbbbbbbb-0002"])
    line = only(w.run()[0], "merge-turn")
    assert "abcdef12" in line and "PR #7" in line and "2 waiting" in line and "squad-turn status" in line, line
    assert w.run(env={"SQUAD_TURN_MAX": "7200"})[0] == []           # the watcher's own variable moves the bar
    assert len(w.run(env={"SQUAD_TURN_MAX": "bad"})[0]) == 1        # a bad value falls back to 3600


def test_merge_queue_with_nobody_holding_the_turn():
    w = World()
    w.fresh_everything()
    w.turn(None, queue=["bbbbbbbb-0001"])
    line = only(w.run()[0], "merge-turn")
    assert "nobody holds the turn" in line and "1 session(s)" in line, line


def test_idle_worktree_is_judged_by_the_reflog_entry_not_its_mtime():
    w = World()
    w.fresh_everything()
    old = w.worktree("old-wt", 12)
    line = only(w.run()[0], "idle-worktree")
    assert "1 worktree(s)" in line and old in line and f"git worktree remove {old}" in line, line
    assert "github agent" in line, line


def test_worktree_missing_on_disk_says_prune():
    w = World()
    w.fresh_everything()
    shutil.rmtree(w.worktree("gone-wt", 0))
    line = only(w.run()[0], "idle-worktree")
    assert "missing on disk" in line and "worktree prune" in line, line


def test_old_handoff_is_one_line_per_directory_with_the_context_agent():
    w = World()
    w.fresh_everything()
    where = os.path.join(w.home, ".claude", "squad", "handoffs")
    w.handoff(where, 10)
    line = only(w.run()[0], "old-handoff")
    assert "~/.claude/squad/handoffs" in line and "1 handoff(s)" in line and "context agent" in line, line
    assert w.handoff(os.path.join(w.repo, ".claude", "handoffs"), 20)
    assert [ln.split(":")[0] for ln in w.run()[0]] == ["old-handoff ~/.claude/squad/handoffs",
                                                         f"old-handoff {w.repo}/.claude/handoffs"]


def test_missing_cli_skips_the_check_with_one_line_never_a_traceback():
    w = World(tools=())
    w.fresh_everything()
    lines, _ = w.run("--repo", w.repo)
    assert len(lines) == 2, lines
    assert lines[0].startswith("skipped stale-card: agenfk not found"), lines
    assert lines[1].startswith("skipped pr-no-review: gh not found"), lines


def test_failing_cli_skips_with_the_reason():
    w = World()
    w.fresh_everything()
    w.fake("agenfk", "import sys\nsys.stderr.write('connect ECONNREFUSED 127.0.0.1\\n')\nsys.exit(1)\n")
    w.fake("gh", "print('not json')\n")
    lines, _ = w.run("--repo", w.repo)
    assert len(lines) == 2, lines
    assert lines[0].startswith("skipped stale-card") and "ECONNREFUSED" in lines[0] and "agenfk health" in lines[0]
    assert lines[1].startswith("skipped pr-no-review demo") and "gh auth status" in lines[1], lines


def test_outside_active_hours_prints_nothing_even_with_findings():
    w = World()
    w.fresh_everything()
    w.handoff(os.path.join(w.home, ".claude", "handoffs"), 30)
    h = datetime.datetime.now().hour
    assert len(w.run("--hours", f"{h}-{h + 1}")[0]) == 1
    assert w.run("--hours", f"{(h + 1) % 24}-{(h + 2) % 24 or 24}")[0] == []


def test_help_and_bad_hours():
    r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--hours" in r.stdout and "nothing" in r.stdout, r.stdout
    r = subprocess.run([sys.executable, SCRIPT, "--hours", "late"], capture_output=True, text=True)
    assert r.returncode == 2 and "Traceback" not in r.stderr and "9-19" in r.stderr, r.stderr


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
