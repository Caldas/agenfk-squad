#!/usr/bin/env python3
"""The omp extension routes events to the bridge and applies the verdict.

Runs the real TypeScript extension under `node` (Node 24 strips the types) with
a fake bridge, so the routing, the session id and the verdict handling are all
exercised. Throwaway dir; never touches ~/.omp.

    python3 tests/test_squad_watch_omp_ts.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extensions", "squad-watch-omp.ts")

FAKE_BRIDGE = '''#!/usr/bin/env python3
import json, os, sys
event = json.load(sys.stdin)
with open(os.environ["RECEIVED"], "a") as fh:
    fh.write(json.dumps(event) + "\\n")
kind = event.get("event")
if kind == "tool_call":
    print(json.dumps({"block": True, "reason": "loop"}))
elif kind == "before_subagent_spawn":
    print(json.dumps({"block": True, "reason": "dispatch denied"}))
elif kind == "session_stop":
    print(json.dumps({"block": True, "reason": "write the handoff"}))
elif kind == "tool_result":
    print(json.dumps({"context": "ctx note"}))
elif kind == "prompt":
    print(json.dumps({"context": "pending note"}))
'''

DRIVER = '''(async () => {
  const mod = await import("__EXT__");
  const activate = mod.default;
  const handlers = {};
  const sent = [];
  const pi = {
    on: (e, h) => { handlers[e] = h; },
    sendMessage: (m, o) => sent.push({ message: m, options: o }),
  };
  activate(pi);
  const sm = {
    getSessionFile: () => process.env.FAKE_SM_FILE,
    getSessionId: () => process.env.FAKE_SM_ID,
  };
  const main = { agent: { kind: "main", id: "m", name: "main" }, sessionManager: sm };
  const sub = { agent: { kind: "sub", id: "a1", name: "developer", depth: 1 }, sessionManager: sm };
  const noSm = { agent: { kind: "main", id: "m", name: "main" } };
  const out = {};
  out.sid = mod.sessionIdFrom(process.env.PI_SESSION_FILE);
  out.toolCall = await handlers["tool_call"]({ toolName: "write", input: { path: "a.ts" } }, main);
  out.spawn = await handlers["before_subagent_spawn"]({ agent: "verifier", context: "brief" }, main);
  out.stop = await handlers["session_stop"]({}, main);
  out.result = await handlers["tool_result"]({ toolName: "read", input: { path: "a.py" } }, sub);
  out.prompt = await handlers["prompt"]({}, main);
  out.envOnly = await handlers["tool_call"]({ toolName: "glob", input: { path: "*" } }, noSm);
  out.sent = sent;
  console.log(JSON.stringify(out));
})();
'''


def run_driver(tmp):
    ext = EXT.replace("\\", "\\\\")
    driver = os.path.join(tmp, "driver.mjs")
    with open(driver, "w") as fh:
        fh.write(DRIVER.replace("__EXT__", "file://" + ext))
    env = dict(os.environ, HOME=tmp, RECEIVED=os.path.join(tmp, "received.jsonl"),
               SQUAD_WATCH_OMP_BRIDGE=os.path.join(tmp, "fake_bridge.py"),
               # the inherited pi session: the sessionManager must win over it
               PI_SESSION_FILE=os.path.join(tmp, "2026-10-13T20-00-00-000Z_sess-1.jsonl"),
               FAKE_SM_FILE=os.path.join(tmp, "2026-10-13T20-00-00-000Z_sess-mgr.jsonl"),
               FAKE_SM_ID="sess-mgr")
    r = subprocess.run(["node", driver], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    received = []
    with open(env["RECEIVED"]) as fh:
        received = [json.loads(line) for line in fh if line.strip()]
    return json.loads(r.stdout), received


def test_the_extension_routes_events_and_applies_verdicts():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "fake_bridge.py"), "w") as fh:
            fh.write(FAKE_BRIDGE)
        out, received = run_driver(tmp)

        assert out["sid"] == "sess-1", out["sid"]
        assert out["toolCall"] == {"block": True, "reason": "loop"}, out["toolCall"]
        assert out["spawn"] == {"block": True, "reason": "dispatch denied"}, out["spawn"]
        assert out["stop"] == {"decision": "block", "reason": "write the handoff"}, out["stop"]
        # JSON.stringify drops an undefined handler return, so the keys are absent
        assert out.get("result") is None and out.get("prompt") is None

        kinds = [e["event"] for e in received]
        assert kinds == ["tool_call", "before_subagent_spawn", "session_stop", "tool_result",
                         "prompt", "tool_call"], kinds
        # the sessionManager wins over the PI_SESSION_FILE inherited from pi
        assert all(e["session_id"] == "sess-mgr" for e in received[:5]), received
        assert all(e["transcript_path"].endswith("sess-mgr.jsonl") for e in received[:5])
        assert received[0]["tool_name"] == "write" and received[0]["tool_input"] == {"path": "a.ts"}
        assert received[1]["agent"] == "verifier" and received[1]["prompt"] == "brief"
        assert received[3]["agent_id"] == "a1" and received[3]["agent_type"] == "developer"
        assert received[3]["agent_transcript_path"].endswith("sess-mgr.jsonl")
        assert "agent_id" not in received[0]
        # with no session manager, the env is the fallback
        assert received[5]["session_id"] == "sess-1"
        assert received[5]["transcript_path"].endswith("sess-1.jsonl")

        notes = [s["message"]["content"] for s in out["sent"]]
        assert notes == ["ctx note", "pending note"], notes
        assert all(s["message"]["customType"] == "squad-watch" for s in out["sent"])


def test_a_missing_session_file_decides_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "fake_bridge.py"), "w") as fh:
            fh.write(FAKE_BRIDGE)
        ext = EXT.replace("\\", "\\\\")
        driver = os.path.join(tmp, "driver2.mjs")
        with open(driver, "w") as fh:
            fh.write('''(async () => {
  const mod = await import("file://__EXT__");
  const ran = [];
  const v = mod.decide({ event: "tool_call", session_id: null, transcript_path: "" },
                       (e) => { ran.push(e); return { block: true, reason: "should not run" }; });
  console.log(JSON.stringify({ v, ran }));
})();
'''.replace("__EXT__", ext))
        env = dict(os.environ, HOME=tmp, RECEIVED=os.path.join(tmp, "received.jsonl"))
        r = subprocess.run(["node", driver], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["v"] == {} and out["ran"] == [], out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
