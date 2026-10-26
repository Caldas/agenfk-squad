#!/usr/bin/env python3
"""The omp bridge translates an omp event into the watcher's payload, and its
verdict back. All the arithmetic stays in hooks/squad-watch.py.

Self-checking: the exit code is the verdict. Runs in a throwaway HOME and never
touches ~/.claude.

    python3 tests/test_watch_omp_bridge.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "hooks", "squad-watch-omp.py")
WATCH = os.path.join(ROOT, "hooks", "squad-watch.py")

_spec = importlib.util.spec_from_file_location("squad_watch_omp", BRIDGE)
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)

_wspec = importlib.util.spec_from_file_location("squad_watch", WATCH)
sw = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(sw)

MODEL = "dgx-spark/GLM-5.3-Flash-EXL3"
SID = "01a136aa-1111-2222-3333-444455556666"


def omp_session(home, sid=SID):
    d = os.path.join(home, ".omp", "agent", "sessions", "-work-proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"2026-10-13T20-00-00-000Z_{sid}.jsonl")
    recs = [
        {"type": "session", "id": sid, "cwd": "/work/proj"},
        {"type": "model_change", "model": MODEL},
        {"type": "message", "id": "m1", "message": {"role": "assistant",
                                                    "usage": {"input": 5000, "output": 40,
                                                              "cacheRead": 0, "cacheWrite": 0}}},
    ]
    with open(path, "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    return path


def run(home, event):
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    for key in list(env):
        if key.startswith("SQUAD_") or key.startswith("HERDR_"):
            del env[key]
    return subprocess.run([sys.executable, BRIDGE], input=json.dumps(event),
                          capture_output=True, text=True, env=env)


def state(home, sid=SID):
    with open(os.path.join(home, ".claude", "squad", "watch", f"{sid}.main.json")) as fh:
        return json.load(fh)


def test_payload_maps_every_event():
    base = {"session_id": SID, "transcript_path": "/t.jsonl", "cwd": "/work"}
    assert br.payload({**base, "event": "tool_call", "tool_name": "write",
                       "tool_input": {"path": "a.ts"}})["hook_event_name"] == "PreToolUse"
    spawn = br.payload({**base, "event": "before_subagent_spawn", "agent": "verifier"})
    assert spawn["hook_event_name"] == "PreToolUse" and spawn["tool_name"] == "Task"
    assert spawn["tool_input"]["subagent_type"] == "verifier"
    assert br.payload({**base, "event": "tool_result"})["hook_event_name"] == "PostToolUse"
    assert br.payload({**base, "event": "session_stop"})["hook_event_name"] == "Stop"
    assert br.payload({**base, "event": "prompt"})["hook_event_name"] == "UserPromptSubmit"
    assert br.payload({**base, "event": "nonsense"}) is None
    assert br.payload(base) is None


def test_omp_tool_names_reach_the_watcher_brakes_in_its_dialect():
    base = {"event": "tool_call", "session_id": SID, "transcript_path": "/t.jsonl"}
    for omp_name, claude_name in (("bash", "Bash"), ("edit", "Edit"), ("write", "Write"),
                                  ("ast_edit", "Edit"), ("apply_patch", "Edit"),
                                  ("notebook", "NotebookEdit"), ("task", "Task"),
                                  ("read", "Read")):
        assert br.payload({**base, "tool_name": omp_name, "tool_input": {}})["tool_name"] == claude_name, omp_name
    assert br.payload({**base, "tool_name": "weird", "tool_input": {}})["tool_name"] == "weird"

    # the translation is what the watcher's brakes key on
    assert "Write" in sw.MUTATING and "Edit" in sw.MUTATING
    merge = br.payload({**base, "tool_name": "bash", "tool_input": {"command": "gh pr merge 99"}})
    assert sw.turn_kind(merge) == ("merge", "99"), sw.turn_kind(merge)


def test_payload_carries_client_omp_and_the_agent():
    p = br.payload({"event": "tool_call", "session_id": SID, "agent_id": "a1",
                    "agent_transcript_path": "/sub.jsonl", "agent_type": "developer"})
    assert p["client"] == "omp"
    assert p["agent_id"] == "a1" and p["agent_transcript_path"] == "/sub.jsonl"
    assert p["agent_type"] == "developer"


def test_verdict_reads_deny_block_and_context():
    deny = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": "LOOP"}})
    assert br.verdict(deny) == {"block": True, "reason": "LOOP"}
    stop = json.dumps({"decision": "block", "reason": "write the handoff"})
    assert br.verdict(stop) == {"block": True, "reason": "write the handoff"}
    note = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": "ctx 600k"}})
    assert br.verdict(note) == {"context": "ctx 600k"}
    assert br.verdict("a plain note") == {"context": "a plain note"}
    assert br.verdict("") == {}


def test_own_handoff_reads_an_omp_transcript():
    import hashlib
    with tempfile.TemporaryDirectory() as home:
        d = os.path.join(home, "proj", ".claude", "handoffs")
        os.makedirs(d)
        written = os.path.join(d, "20261013-000000-x.md")
        content = "# Handoff\n\nreal content\n"
        with open(written, "w", newline="") as fh:
            fh.write(content)
        transcript = os.path.join(home, "s.jsonl")
        rec = {"type": "message", "id": "m9", "message": {
            "role": "assistant",
            "content": [{"type": "toolCall", "name": "write",
                         "arguments": {"path": written, "content": content}}]}}
        with open(transcript, "w") as fh:
            fh.write(json.dumps(rec) + "\n")
        assert sw.own_handoff(transcript, 0, "omp") == \
            (written, hashlib.sha256(content.encode()).hexdigest())
        # the claude parser does not read the same record
        assert sw.own_handoff(transcript, 0, "claude") is None


def test_a_translated_write_clears_the_loop_counter_like_a_mutation():
    """The behavioural guard for the tool-name translation: the watcher only
    clears the loop counter when it sees a MUTATING name, so an omp `write`
    that reaches it untranslated would keep the counter and false-fire LOOP."""
    with tempfile.TemporaryDirectory() as home:
        path = omp_session(home)
        watch = os.path.join(home, ".claude", "squad", "watch")
        os.makedirs(watch)
        state_file = os.path.join(watch, f"{SID}.main.json")
        base = {"event": "tool_result", "session_id": SID, "transcript_path": path,
                "cwd": "/work/proj"}

        with open(state_file, "w") as fh:
            json.dump({"calls": ["stale-hash"]}, fh)
        r = run(home, {**base, "tool_name": "write", "tool_input": {"path": "a.py"}})
        assert r.returncode == 0, r.stderr
        assert state(home)["calls"] == [], state(home)

        # a read is not mutating: the entry survives and the call is appended
        with open(state_file, "w") as fh:
            json.dump({"calls": ["stale-hash"]}, fh)
        r = run(home, {**base, "tool_name": "read", "tool_input": {"path": "a.py"}})
        assert r.returncode == 0, r.stderr
        calls = state(home)["calls"]
        assert calls and calls[0] == "stale-hash" and len(calls) == 2, calls


def test_post_tool_reaches_the_watcher_and_writes_state():
    with tempfile.TemporaryDirectory() as home:
        path = omp_session(home)
        r = run(home, {"event": "tool_result", "session_id": SID, "transcript_path": path,
                       "cwd": "/work/proj", "tool_name": "read", "tool_input": {"path": "a.py"}})
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "", r.stdout
        assert state(home)["ctx"] == 5000, state(home)


def test_an_over_ceiling_dispatch_is_denied_and_the_brief_is_kept():
    with tempfile.TemporaryDirectory() as home:
        path = omp_session(home)
        watch = os.path.join(home, ".claude", "squad", "watch")
        os.makedirs(watch)
        with open(os.path.join(watch, f"{SID}.main.json"), "w") as fh:
            json.dump({"ctx": 700_000}, fh)          # above MAIN_CEIL (600k)
        r = run(home, {"event": "before_subagent_spawn", "session_id": SID,
                       "transcript_path": path, "cwd": "/work/proj", "agent": "verifier",
                       "prompt": "Review card e3351732 on the branch feat/x."})
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["block"] is True and "DISPATCH DENIED" in out["reason"], out
        kept = os.path.join(home, ".claude", "squad", "handoffs", f"{SID}-dispatches.md")
        assert "Review card e3351732" in open(kept).read()


def test_unknown_event_and_missing_session_are_quiet():
    with tempfile.TemporaryDirectory() as home:
        assert run(home, {"event": "nonsense"}).stdout.strip() == ""
        assert run(home, {"event": "tool_result"}).stdout.strip() == ""


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
