#!/usr/bin/env python3
"""The watcher reads an oh-my-pi (omp) transcript, not only a Claude one.

Self-checking: the exit code is the verdict. Runs in a throwaway HOME and never
touches ~/.claude.

    python3 tests/test_watch_omp.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "squad-watch.py")

_spec = importlib.util.spec_from_file_location("squad_watch", HOOK)
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)

MODEL = "dgx-spark/GLM-5.3-Flash-EXL3"


def omp_session(home, sid="01a136aa-1111-2222-3333-444455556666"):
    d = os.path.join(home, ".omp", "agent", "sessions", "-work-proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"2026-10-13T20-00-00-000Z_{sid}.jsonl")
    recs = [
        {"type": "session", "id": sid, "cwd": "/work/proj"},
        {"type": "model_change", "model": MODEL},
        {"type": "message", "id": "m1", "message": {"role": "user", "content": []}},
        {"type": "message", "id": "m2", "message": {"role": "assistant",
                                                    "usage": {"input": 5000, "output": 40,
                                                              "cacheRead": 0, "cacheWrite": 0},
                                                    "content": [{"type": "toolCall", "name": "read",
                                                                 "arguments": {"path": "a.py"}}]}},
    ]
    with open(path, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    return path, sid


def run(home, payload):
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    for key in list(env):
        if key.startswith("SQUAD_") or key.startswith("HERDR_"):
            del env[key]
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def state(home, sid):
    with open(os.path.join(home, ".claude", "squad", "watch", f"{sid}.main.json")) as fh:
        return json.load(fh)


def test_harness_payload_then_path():
    assert sw.harness({"client": "omp"}) == "omp"
    assert sw.harness({"client": "PI"}) == "pi"
    assert sw.harness({"transcript_path": "/tmp/u/.omp/agent/sessions/p/s.jsonl"}) == "omp"
    assert sw.harness({"transcript_path": "/tmp/u/.pi/agent/sessions/p/s.jsonl"}) == "pi"
    assert sw.harness({"transcript_path": "/tmp/u/.claude/projects/p/s.jsonl"}) == "claude"
    assert sw.harness({}) == "claude"


def test_fold_reads_the_pi_family_fields():
    with tempfile.TemporaryDirectory() as home:
        path, _ = omp_session(home)
        tok = sw.fold(path, {}, "omp")
        assert tok["req"] == 1, tok
        assert tok["inp"] == 5000 and tok["out"] == 40, tok
        assert tok["ctx"] == 5000, tok
        assert tok["model"] == MODEL, tok
        # a second read finds nothing new
        assert sw.fold(path, tok, "omp")["req"] == 1


def test_fold_still_reads_claude():
    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "session.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "requestId": "r1",
                                 "message": {"usage": {"input_tokens": 10,
                                                       "cache_creation_input_tokens": 2,
                                                       "cache_read_input_tokens": 3,
                                                       "output_tokens": 4}}}) + "\n")
        tok = sw.fold(path, {})
        assert tok["req"] == 1 and tok["inp"] == 10 and tok["wr"] == 2, tok
        assert tok["rd"] == 3 and tok["out"] == 4 and tok["ctx"] == 15, tok


def test_measure_reads_the_omp_session():
    with tempfile.TemporaryDirectory() as home:
        path, _ = omp_session(home)
        m = sw.measure(path, "omp")
        assert m is not None and m["ctx"] == 5000 and m["model"] == MODEL, m


def test_post_tool_measures_an_omp_session_end_to_end():
    with tempfile.TemporaryDirectory() as home:
        path, sid = omp_session(home)
        p = {"hook_event_name": "PostToolUse", "client": "omp", "session_id": sid,
             "transcript_path": path, "cwd": "/work/proj",
             "tool_name": "read", "tool_input": {"path": "a.py"}}
        r = run(home, p)
        assert r.returncode == 0, r.stderr
        assert state(home, sid)["ctx"] == 5000, state(home, sid)
        # the model's real window is used, not claude's 1M
        assert sw.main_window(sid, "omp") == 262_144


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
