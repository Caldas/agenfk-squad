#!/usr/bin/env python3
"""session_context reads oh-my-pi (omp) sessions: same pi-family JSONL, but the
model rides on `model` and the DGX checkpoint has a known window.

Self-checking: the exit code is the verdict. Patches HOME to a throwaway dir and
never touches the real one.

    python3 tests/test_session_context_omp.py
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "session-context", "scripts"))
import session_context as cx  # noqa: E402

MODEL = "dgx-spark/GLM-5.3-Flash-EXL3"


def write_session(home, name="-proj", sid="01a136ef-1111-2222-3333-444455556666", model=MODEL):
    d = os.path.join(home, ".omp", "agent", "sessions", name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"2026-10-13T20-23-43-134Z_{sid}.jsonl")
    recs = [
        {"type": "session", "id": sid, "timestamp": "2026-10-13T20:23:43.134Z", "cwd": "/work/proj"},
        {"type": "model_change", "timestamp": "2026-10-13T20:23:44.360Z", "model": model},
        {"type": "message", "timestamp": "2026-10-13T20:23:45.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "message", "timestamp": "2026-10-13T20:23:46.000Z",
         "message": {"role": "assistant", "model": model.split("/")[-1], "provider": "dgx-spark",
                     "usage": {"input": 8483, "output": 36, "cacheRead": 100, "cacheWrite": 200},
                     "content": [{"type": "toolCall", "id": "c1", "name": "read",
                                  "arguments": {"path": "/work/proj/a.py"}}]}},
    ]
    with open(path, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    return path, sid


def test_omp_sessions_finds_the_file_and_does_not_cross_with_pi():
    with tempfile.TemporaryDirectory() as home:
        old, cx.HOME = cx.HOME, home
        try:
            path, sid = write_session(home)
            found = cx.omp_sessions(6)
            assert found == [("omp", sid, path, "")], found
            assert cx.pi_sessions(6) == []
        finally:
            cx.HOME = old


def test_scan_omp_reads_usage_the_model_and_the_dgx_window():
    with tempfile.TemporaryDirectory() as home:
        old, cx.HOME = cx.HOME, home
        try:
            path, _ = write_session(home)
            st = cx.blank()
            cx.scan_omp(path, st)
            assert st["cwd"] == "/work/proj", st["cwd"]
            assert st["model"] == MODEL, st["model"]
            assert st["window"] == 262_144, st["window"]
            assert st["req"] == 1 and st["inp"] == 8483 and st["out"] == 36, st
            assert st["rd"] == 100 and st["wr"] == 200, st
            assert st["ctx"] == 8483 + 100 + 200, st["ctx"]
            assert st["tools"]["read"] == 1, st["tools"]
            assert st["reads"]["/work/proj/a.py"] == 1, st["reads"]
        finally:
            cx.HOME = old


def test_scan_omp_leaves_an_unknown_model_without_a_window():
    with tempfile.TemporaryDirectory() as home:
        old, cx.HOME = cx.HOME, home
        try:
            path, _ = write_session(home, model="openrouter/z-ai/glm-5.3-flash")
            st = cx.blank()
            cx.scan_omp(path, st)
            assert st["window"] is None, st["window"]
        finally:
            cx.HOME = old


def test_analyse_reports_an_omp_session_with_the_real_model():
    with tempfile.TemporaryDirectory() as home:
        old, cx.HOME = cx.HOME, home
        try:
            path, sid = write_session(home)
            row = cx.analyse("omp", sid, path, "", time.time())
            assert row is not None
            assert row["client"] == "omp" and row["session"] == sid
            assert row["model"] == MODEL
            assert row["window"] == 262_144 and row["window_inferred"] is False
            assert row["cwd"] == "/work/proj"
            assert row["requests"] == 1
            assert row["verdict"] in ("CONTINUE", "COMPACT", "HANDOFF", "LOOP", "IDLE"), row["verdict"]
        finally:
            cx.HOME = old


def test_scan_pi_still_reads_modelId():
    with tempfile.TemporaryDirectory() as home:
        old, cx.HOME = cx.HOME, home
        try:
            d = os.path.join(home, ".pi", "agent", "sessions", "-p")
            os.makedirs(d)
            path = os.path.join(d, "s_abc123.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps({"type": "model_change", "modelId": "qwen38-flashnext"}) + "\n")
                fh.write(json.dumps({"type": "message", "message": {"role": "assistant",
                                                                    "usage": {"input": 10}}}))
            st = cx.blank()
            cx.scan_pi(path, st)
            assert st["model"] == "qwen38-flashnext", st["model"]
            assert st["req"] == 1
        finally:
            cx.HOME = old


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
