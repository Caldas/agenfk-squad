#!/usr/bin/env python3
"""The watcher cuts the main session between 50% and 80% of the window, and only by arithmetic.

Self-checking: the exit code is the verdict. Runs in a throwaway HOME, with a
fake herdr, and never touches ~/.claude.

    python3 tests/test_watch.py
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "squad-watch.py")
sys.path.insert(0, os.path.join(ROOT, "skills", "session-context", "scripts"))
import session_context as cx  # noqa: E402

M = 1_000_000


def home():
    return tempfile.mkdtemp(prefix="watch-")


def run(h, event, sid, transcript, extra=None, env=None):
    p = {"hook_event_name": event, "session_id": sid, "transcript_path": transcript,
         "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": h}
    p.update(extra or {})
    e = dict(os.environ, HOME=h)
    for key in list(e):
        if key.startswith("SQUAD_") or key.startswith("HERDR_"):
            del e[key]
    e.update(env or {})
    return subprocess.run([sys.executable, HOOK], input=json.dumps(p), capture_output=True,
                          text=True, env=e).stdout.strip()


def session(h, sid, ctx, share, burn=60):
    """Main-session transcript with this context, this reread share and this
    burn (% of the session budget)."""
    path = os.path.join(h, f"{sid}.jsonl")
    if share <= 0:           # everything written now, nothing reread
        recs = [{"cache_creation_input_tokens": ctx}]
    else:                    # 10 turns rereading ctx; the new work makes the share add up
        n = max(10, round(share * burn / 100 * cx.BUDGET / (ctx * 0.1)))
        reread = n * ctx * 0.1
        new = reread * (1 - share) / share
        recs = [{"cache_read_input_tokens": ctx, "output_tokens": int(new / n / 5)} for _ in range(n)]
    with open(path, "w") as fh:
        for i, usage in enumerate(recs):
            fh.write(json.dumps({"type": "assistant", "isSidechain": False, "requestId": f"r{i}",
                                 "message": {"usage": usage}}) + "\n")
    return path


def said(out):
    if not out:
        return "nothing"
    data = json.loads(out)
    if data.get("decision") == "block":
        return "block: " + data["reason"]
    hso = data.get("hookSpecificOutput") or {}
    return hso.get("additionalContext") or hso.get("permissionDecisionReason") or ""


def kind(text):
    # the most specific first: the notice and the cancellation mention "PROACTIVE HANDOFF" in their text
    for word in ("ALERT CANCELLED", "Informational only", "Handoff out of turn",
                 "stopped without writing the handoff", "DISPATCH DENIED", "PROACTIVE HANDOFF"):
        if word in text:
            return word
    return text


def state(h, sid):
    with open(os.path.join(h, ".claude", "squad", "watch", f"{sid}.main.json")) as fh:
        return json.load(fh)


def write_handoff(h, transcript, name="h1.md"):
    folder = os.path.join(h, "proj", ".claude", "handoffs")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    body = "# handoff\nNext step: X\n"
    with open(path, "w") as fh:
        fh.write(body)
    with open(transcript, "a") as fh:
        fh.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": path, "content": body}}]}}) + "\n")
    return path


def test_the_math_is_fixed():
    def due(share, ctx, window, burn=60):
        reread = share * burn / 100 * cx.BUDGET
        return cx.handoff_math(int(reread * (1 - share) / share), 0, int(reread / 0.1), 0, ctx, window)["due"]
    assert cx.REREAD_SHARE == 0.60 and cx.REREAD_FLOOR_PCT == 50 and cx.HANDOFF_NOW == 80
    assert not due(0.95, 150_000, M)        # the case that used to cut sessions at 15%
    assert not due(0.95, 499_000, M)
    assert due(0.60, 500_000, M)
    assert not due(0.59, 790_000, M)
    assert due(0.61, 90_000, 0)             # sub-session: floor 2*CTX_BASE
    assert due(0.61, 90_000, 0, burn=1)     # ...and with no window the burn does not move the floor
    # the floor weighs the burn: 80% of the window with zero burn, 50% with burn at 50% of the budget
    assert cx.BUDGET == 20_000_000 and cx.BURN_FULL_PCT == 50
    assert not due(0.90, 500_000, M, burn=10)   # context 50%, burn 10%: not the time
    assert not due(0.90, 730_000, M, burn=10) and due(0.90, 740_000, M, burn=10)
    assert not due(0.90, 640_000, M, burn=25) and due(0.90, 650_000, M, burn=25)
    assert due(0.90, 500_000, M, burn=80)


def test_cut_between_50_and_80_percent():
    cases = [  # context, reread, what the watcher says
        (100_000, 0.90, "nothing"), (150_000, 0.90, "nothing"), (300_000, 0.90, "nothing"),
        (490_000, 0.90, "nothing"),
        (500_000, 0.60, "PROACTIVE HANDOFF"), (520_000, 0.90, "PROACTIVE HANDOFF"),
        (520_000, 0.00, "Informational only"), (700_000, 0.50, "Informational only"),
        (790_000, 0.00, "Informational only"),
        (800_000, 0.00, "PROACTIVE HANDOFF"), (900_000, 0.30, "PROACTIVE HANDOFF"),
    ]
    h = home()
    for i, (ctx, share, expected) in enumerate(cases):
        sid = f"aaaaaaaa-{i:04d}"
        got = kind(said(run(h, "PostToolUse", sid, session(h, sid, ctx, share))))
        assert got == expected, (ctx, share, got)
        assert state(h, sid)["ctx_level"] == {"nothing": 0, "Informational only": 1,
                                              "PROACTIVE HANDOFF": 2}[expected]


def test_context_at_50_with_low_burn_is_not_handoff_time():
    h = home()
    cases = [(500_000, 10, "Informational only"), (700_000, 10, "Informational only"),
             (760_000, 10, "PROACTIVE HANDOFF"), (600_000, 25, "Informational only"),
             (660_000, 25, "PROACTIVE HANDOFF"), (500_000, 60, "PROACTIVE HANDOFF")]
    for i, (ctx, burn, expected) in enumerate(cases):
        sid = f"aaaabbbb-{i:04d}"
        text = said(run(h, "PostToolUse", sid, session(h, sid, ctx, 0.9, burn)))
        assert kind(text) == expected and f"burn {burn}% of the budget" in text, (ctx, burn, text)


def test_default_window_is_1m_even_if_the_cockpit_recorded_200k():
    h = home()
    sid = "bbbbbbbb-0001"
    cache = os.path.join(h, ".claude", "cache", "session-tokens")
    os.makedirs(cache)
    with open(os.path.join(cache, f"{sid}.json"), "w") as fh:
        json.dump({"window": 200_000}, fh)
    assert said(run(h, "PostToolUse", sid, session(h, sid, 170_000, 0.9))) == "nothing"


def test_alert_from_the_old_rule_is_cancelled_in_writing():
    h = home()
    sid = "cccccccc-0001"
    folder = os.path.join(h, ".claude", "squad", "watch")
    os.makedirs(folder)
    with open(os.path.join(folder, f"{sid}.main.json"), "w") as fh:
        json.dump({"ctx_level": 2, "alert_ts": time.time() - 600, "nudges": 1}, fh)
    tr = session(h, sid, 160_000, 0.9)
    assert kind(said(run(h, "PostToolUse", sid, tr))) == "ALERT CANCELLED"
    st = state(h, sid)
    assert st["ctx_level"] == 0 and "alert_ts" not in st
    assert said(run(h, "Stop", sid, tr)) == "nothing"       # no longer demands the handoff


def test_handoff_on_the_agents_opinion_sends_the_work_back():
    h = home()
    sid = "dddddddd-0001"
    tr = session(h, sid, 200_000, 0.9)
    run(h, "UserPromptSubmit", sid, tr, {"prompt": "continue the merchant journey"})
    run(h, "PostToolUse", sid, tr)
    write_handoff(h, tr)
    assert kind(said(run(h, "Stop", sid, tr))) == "Handoff out of turn"
    assert said(run(h, "Stop", sid, tr, {"stop_hook_active": True})) == "nothing"   # once per request
    # when it was the owner who asked, the watcher stays out of it (in Portuguese or in English)
    for i, asked in enumerate(("faca o handoff, vamos encerrar por hoje",
                               "write the handoff, let's wrap up for today")):
        run(h, "UserPromptSubmit", sid, tr, {"prompt": asked})
        assert state(h, sid)["asked_stop"] is True, asked
        os.utime(write_handoff(h, tr, f"h{i + 2}.md"))
        assert said(run(h, "Stop", sid, tr)) == "nothing", asked


def test_mistyped_threshold_does_not_turn_the_watcher_off():
    """The hook fails open: if an invalid value broke the import, the whole
    brake (handoff, loop, sub-session cut) would vanish silently."""
    for bad in ({"SQUAD_REREAD": "sixty"}, {"SQUAD_REREAD": "100"}, {"SQUAD_REREAD": "0"},
                {"SQUAD_REREAD_FLOOR": "x"}, {"SQUAD_CTX_PCT": "abc"}, {"SQUAD_CTX_PCT": "0"},
                {"SQUAD_CTX_BASE": "40k"}):
        h = home()
        sid = "99999999-0001"
        got = kind(said(run(h, "PostToolUse", sid, session(h, sid, 850_000, 0.9), env=bad)))
        assert got == "PROACTIVE HANDOFF", (bad, got)
        sid = "99999999-0002"                     # and no value makes the cut early
        assert said(run(h, "PostToolUse", sid, session(h, sid, 60_000, 0.9), env=bad)) == "nothing", bad
        assert not os.path.exists(os.path.join(h, ".claude", "squad", "watch-errors.log")), bad


def test_handoff_level_with_no_handoff_written_repeats_the_order():
    h = home()
    sid = "eeeeeeee-0001"
    tr = session(h, sid, 550_000, 0.9)
    assert kind(said(run(h, "PostToolUse", sid, tr))) == "PROACTIVE HANDOFF"
    assert kind(said(run(h, "Stop", sid, tr))) == "stopped without writing the handoff"


def fake_herdr(h, sid):
    """Fake herdr: `agent get` returns the pane's session, `/clear` switches the session."""
    cur, sent = os.path.join(h, "pane-session"), os.path.join(h, "pane-prompts")
    with open(cur, "w") as fh:
        fh.write(sid)
    path = os.path.join(h, "herdr")
    with open(path, "w") as fh:
        fh.write(f"""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["agent", "get"]:
    print(json.dumps({{"result": {{"agent": {{"agent_session": {{"value": open({cur!r}).read()}},
                                           "agent_status": "idle"}}}}}}))
elif a[:2] == ["agent", "prompt"]:
    open({sent!r}, "a").write(a[3] + "\\n")
    if a[3] == "/clear":
        open({cur!r}, "w").write("ffffffff-9999")
""")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path, sent


def test_ordered_handoff_switches_session_and_calls_the_pickup():
    h = home()
    sid = "abcdef12-0001"
    herdr, sent = fake_herdr(h, sid)
    env = {"HERDR_PANE_ID": "w1:p1", "HERDR_BIN_PATH": herdr}
    tr = session(h, sid, 550_000, 0.9)
    text = said(run(h, "PostToolUse", sid, tr, env=env))
    assert "PROACTIVE HANDOFF" in text and "calls the pickup on its own" in text, text
    handoff = write_handoff(h, tr)
    assert said(run(h, "Stop", sid, tr, env=env)) == "nothing"
    log = os.path.join(h, ".claude", "squad", "switches.log")
    for _ in range(40):                                  # the switch runs detached, outside the session
        if os.path.exists(log):
            break
        time.sleep(0.5)
    with open(log) as fh:
        line = fh.read()
    assert "abcdef12 -> ffffffff pickup sent" in line, line
    with open(sent) as fh:
        prompts = fh.read().splitlines()
    assert prompts[0] == "/clear" and prompts[1].startswith("/clear-pickup pickup "), prompts
    with open(prompts[1].split()[-1]) as fh, open(handoff) as orig:
        assert fh.read() == orig.read()                  # the new session reads this session's handoff
    assert state(h, sid)["switched"] is True


def test_dispatch_denied_at_the_ceiling_arms_the_switch():
    h = home()
    sid = "12345678-0001"
    tr = session(h, sid, 620_000, 0.0)                   # 62%, low reread: only a notice...
    assert kind(said(run(h, "PostToolUse", sid, tr))) == "Informational only"
    out = run(h, "PreToolUse", sid, tr, {"tool_name": "Agent",
                                         "tool_input": {"subagent_type": "developer", "prompt": "x"}})
    assert "DISPATCH DENIED" in out, out                 # ...but dispatching from here means handoff
    st = state(h, sid)
    assert st["ctx_level"] == 2 and st["ordered"] is True
    path = os.path.join(h, ".claude", "squad", "watch", f"{sid}.main.json")
    st["checked"] = 0                                    # forces a new measurement of the transcript
    with open(path, "w") as fh:
        json.dump(st, fh)
    run(h, "PostToolUse", sid, tr)
    assert state(h, sid)["ctx_level"] == 2               # the next measurement does not disarm
    # below the ceiling the dispatch passes
    sid2 = "12345678-0002"
    tr2 = session(h, sid2, 450_000, 0.9)
    run(h, "PostToolUse", sid2, tr2)
    assert "DISPATCH DENIED" not in run(h, "PreToolUse", sid2, tr2, {
        "tool_name": "Agent", "tool_input": {"subagent_type": "developer", "prompt": "x"}})


def orchestrators(h, n):
    """n other sessions with a live sub-session right now."""
    folder = os.path.join(h, ".claude", "squad", "watch")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if name.startswith("other"):
            os.remove(os.path.join(folder, name))
    for i in range(n):
        with open(os.path.join(folder, f"other{i}.sub{i}.json"), "w") as fh:
            fh.write("{}")


def dispatch(h, sid, tr, agent_type="developer", env=None):
    return said(run(h, "PreToolUse", sid, tr, {
        "tool_name": "Agent", "tool_input": {"subagent_type": agent_type, "prompt": "card ABC-1"}}, env))


def test_no_slot_heavy_session_becomes_handoff_with_plan_and_switch():
    h = home()
    sid = "12345678-0003"
    tr = session(h, sid, 300_000, 0.0)                   # 30%: no context alert at all
    assert said(run(h, "PostToolUse", sid, tr)) == "nothing"
    orchestrators(h, 3)
    out = dispatch(h, sid, tr)
    assert "DISPATCH DENIED" in out and "PLAN of the denied dispatch" in out, out
    assert "without dispatching an agent" in out and "/clear-pickup pickup <file>" in out, out
    st = state(h, sid)
    assert st["ctx_level"] == 2 and st["ordered"] is True
    briefs = os.path.join(h, ".claude", "squad", "handoffs", f"{sid}-dispatches.md")
    assert briefs in out, out                            # the denied plan is kept in full
    with open(briefs) as fh:
        assert fh.read().count("card ABC-1") == 1
    assert "pickup on its own" in dispatch(h, sid, tr, env={"HERDR_PANE_ID": "w1:p1"})
    with open(briefs) as fh:
        assert fh.read().count("card ABC-1") == 1        # the same brief does not go in twice
    assert "already been ordered" in dispatch(h, sid, tr)   # insisting does not change the answer
    # stopping without the handoff sends the order back; with the handoff written, no more complaints
    assert kind(said(run(h, "Stop", sid, tr))) == "stopped without writing the handoff"
    write_handoff(h, tr)
    assert said(run(h, "Stop", sid, tr)) == "nothing"


def test_no_slot_light_session_implements_here():
    h = home()
    sid = "12345678-0004"
    tr = session(h, sid, 60_000, 0.0)                    # the session that has just done the pickup
    run(h, "PostToolUse", sid, tr)
    orchestrators(h, 3)
    out = dispatch(h, sid, tr)
    assert "RIGHT HERE" in out and "no handoff" in out, out
    st = state(h, sid)
    assert not st.get("ordered") and st.get("ctx_level", 0) == 0 and st["wait_slot"] is True
    assert said(run(h, "PostToolUse", sid, tr)) == "nothing"   # still no slot: silence
    orchestrators(h, 2)
    assert "SLOT FREE" in said(run(h, "PostToolUse", sid, tr))
    assert said(run(h, "PostToolUse", sid, tr)) == "nothing"   # announces once
    assert "DISPATCH DENIED" not in dispatch(h, sid, tr)


def test_no_slot_reviewer_waits_for_the_slot_without_handoff():
    h = home()
    sid = "12345678-0005"
    tr = session(h, sid, 300_000, 0.0)
    run(h, "PostToolUse", sid, tr)
    orchestrators(h, 3)
    out = dispatch(h, sid, tr, "verifier")
    assert "whoever writes does not approve" in out and "SLOT FREE" in out, out
    st = state(h, sid)
    assert not st.get("ordered") and st["wait_slot"] is True


def test_notice_ahead_of_the_brake_only_for_whoever_orchestrates():
    h = home()
    sid = "12345678-0006"
    tr = session(h, sid, 300_000, 0.0)
    orchestrators(h, 3)
    assert said(run(h, "PostToolUse", sid, tr)) == "nothing"     # never dispatched: not its concern
    path = os.path.join(h, ".claude", "squad", "watch", f"{sid}.main.json")
    def remeasure():
        st = state(h, sid)
        st.update(checked=0, subs=2, calls=[])
        with open(path, "w") as fh:
            json.dump(st, fh)
        return said(run(h, "PostToolUse", sid, tr))
    out = remeasure()
    assert "DISPATCH NOTICE" in out and "finish the task in progress" in out, out
    assert not state(h, sid).get("ordered")                      # a notice arms nothing
    again = remeasure()
    assert again == "nothing", again                             # one notice per episode
    orchestrators(h, 0)
    remeasure()
    orchestrators(h, 3)
    assert "DISPATCH NOTICE" in remeasure()                      # the slot came back and went away again


def test_sub_agent_return_is_not_the_owner_asking_to_stop():
    """One session in October 2026: a sub-agent's notification mentioned
    "handoff", the watcher read it as the owner's request and let the session
    die with a handoff out of turn."""
    h = home()
    sid = "12345678-0007"
    tr = session(h, sid, 200_000, 0.9)
    run(h, "UserPromptSubmit", sid, tr, {"prompt": "redo the When block"})
    run(h, "UserPromptSubmit", sid, tr, {
        "prompt": "<task-notification>\n<result>Stopped on the squad-watch HANDOFF order</result>"})
    assert state(h, sid)["asked_stop"] is False
    run(h, "PostToolUse", sid, tr)
    write_handoff(h, tr)
    assert kind(said(run(h, "Stop", sid, tr))) == "Handoff out of turn"
    for resume in ("/clear-pickup pickup /x/handoffs/h.md", "retome o handoff de ontem",
                   "resume from yesterday's handoff", "pick up the handoff where we left off"):
        run(h, "UserPromptSubmit", sid, tr, {"prompt": resume})
        assert state(h, sid)["asked_stop"] is False, resume      # resuming is not stopping


def test_session_that_does_not_write_the_handoff_the_watcher_takes_over_and_switches():
    h = home()
    sid = "abcdef12-0002"
    herdr, sent = fake_herdr(h, sid)
    env = {"HERDR_PANE_ID": "w1:p1", "HERDR_BIN_PATH": herdr}
    tr = session(h, sid, 300_000, 0.0)
    run(h, "UserPromptSubmit", sid, tr, {"prompt": "deliver card ABC-1"}, env)
    run(h, "PostToolUse", sid, tr, env=env)
    orchestrators(h, 3)
    assert "DISPATCH DENIED" in dispatch(h, sid, tr, env=env)
    assert kind(said(run(h, "Stop", sid, tr, env=env))) == "stopped without writing the handoff"
    assert said(run(h, "Stop", sid, tr, {"stop_hook_active": True}, env)) == "nothing"
    log = os.path.join(h, ".claude", "squad", "switches.log")
    for _ in range(40):
        if os.path.exists(log):
            break
        time.sleep(0.5)
    with open(log) as fh:
        assert "abcdef12 -> ffffffff pickup sent" in fh.read()
    with open(sent) as fh:
        prompts = fh.read().splitlines()
    with open(prompts[1].split()[-1]) as fh:
        body = fh.read()
    assert "written by squad-watch" in body and "deliver card ABC-1" in body, body
    assert f"{sid}-dispatches.md" in body and "UNKNOWN" in body, body
    assert "\n## Next step\n" in body, body


def repo_with_gh(h):
    """A real git repository and a fake gh that answers the PR state."""
    repo = os.path.join(h, "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    state_file = os.path.join(h, "gh-state")
    with open(state_file, "w") as fh:
        fh.write("OPEN")
    gh = os.path.join(h, "gh")
    with open(gh, "w") as fh:
        fh.write(f"""#!/usr/bin/env python3
import sys
print("77" if "number" in sys.argv else open({state_file!r}).read())
""")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
    return repo, {"SQUAD_GH": gh}, state_file


def bash(h, event, sid, repo, cmd, env):
    return said(run(h, event, sid, os.path.join(h, "t.jsonl"),
                    {"tool_input": {"command": cmd}, "cwd": repo}, env))


def queue(h):
    folder = os.path.join(h, ".claude", "squad", "turn")
    name = next(n for n in os.listdir(folder) if n.endswith(".json"))
    with open(os.path.join(folder, name)) as fh:
        return json.load(fh), os.path.join(folder, name)


def test_merge_queue_one_session_at_a_time_and_the_next_is_called():
    h = home()
    repo, env, state_file = repo_with_gh(h)
    a, b = "aaaa1111-0001", "bbbb2222-0001"
    assert bash(h, "PreToolUse", a, repo, "gh pr merge 10 --squash", env) == "nothing"   # turn free: passes
    assert queue(h)[0]["holder"]["session"] == a
    out = bash(h, "PreToolUse", b, repo, "cd x && gh pr merge 11 --squash", env)
    assert "MERGE QUEUE" in out and "position 1" in out and "PR #10" in out, out
    assert "position 1" in bash(h, "PreToolUse", b, repo, "gh pr merge 11 --squash", env)  # no duplicate
    assert len(queue(h)[0]["queue"]) == 1
    # syncing with main while another session holds the turn: warned once, then it passes
    out = bash(h, "PreToolUse", b, repo, "git fetch origin && git merge origin/main", env)
    assert "main is about to move" in out and "repeat the command" in out, out
    assert bash(h, "PreToolUse", b, repo, "git fetch origin && git merge origin/main", env) == "nothing"
    assert bash(h, "PreToolUse", a, repo, "git merge origin/main", env) == "nothing"     # the turn holder syncs
    # A's merge has not landed yet: the turn is still A's, and A is told what to do
    out = bash(h, "PostToolUse", a, repo, "gh pr merge 10 --squash", env)
    assert "the turn in this repository is yours" in out and "ONCE" in out, out
    with open(state_file, "w") as fh:
        fh.write("MERGED")
    out = bash(h, "PostToolUse", a, repo, "gh pr merge 10 --squash", env)
    assert "PR #10 landed on main" in out and "bbbb2222" in out, out
    d, _ = queue(h)
    assert d["holder"]["session"] == b and d["queue"] == []
    with open(state_file, "w") as fh:
        fh.write("OPEN")
    out = bash(h, "PostToolUse", b, repo, "ls", env)                  # B is called in its own session
    assert "MERGE TURN: it is your turn" in out and "PR #11" in out, out
    assert bash(h, "PreToolUse", b, repo, "gh pr merge 11 --squash", env) == "nothing"
    assert "MERGE QUEUE" in bash(h, "PreToolUse", a, repo, "gh pr merge 12", env)


def test_merge_queue_stalled_turn_passes_on_and_can_be_requested_and_released():
    h = home()
    repo, env, _ = repo_with_gh(h)
    a, b, c = "aaaa1111-0002", "bbbb2222-0002", "cccc3333-0002"
    assert bash(h, "PreToolUse", a, repo, "squad-turn request 20", env) == "nothing"
    assert queue(h)[0]["holder"]["pr"] == "20"
    assert bash(h, "PreToolUse", b, repo, "squad-turn request 21", env) == "nothing"   # requesting only queues
    assert bash(h, "PreToolUse", c, repo, "git push origin HEAD:main", env) != "nothing"
    d, path = queue(h)
    assert [e["session"] for e in d["queue"]] == [b, c]
    d["holder"]["seen"] -= 1000                       # A vanished holding the turn
    with open(path, "w") as fh:
        json.dump(d, fh)
    bash(h, "PreToolUse", c, repo, "squad-turn status", env)
    d, path = queue(h)
    assert d["holder"]["session"] == b and d["last"]["why"] == "idle"
    assert "was released" in bash(h, "PostToolUse", a, repo, "ls", env)          # A finds out
    d["holder"]["since"] -= 400                       # B was called and did not show up within 5 min
    d["holder"]["seen"] = d["holder"]["since"]
    with open(path, "w") as fh:
        json.dump(d, fh)
    assert bash(h, "PreToolUse", c, repo, "gh pr merge", env) == "nothing"        # the turn reaches C
    d, _ = queue(h)
    assert d["holder"]["session"] == c and d["holder"]["pr"] == "77"             # the branch's PR, through gh
    bash(h, "PreToolUse", c, repo, "squad-turn release", env)
    assert queue(h)[0]["holder"] is None
    # text that only mentions the command does not join the queue; neither does a branch with "main" in its name
    for cmd in ("python3 - <<'E'\npat = 'gh pr merge|git merge origin/main'\nE", "git push origin feat/main-menu",
                "git commit -m 'explain gh pr merge'", "echo squad-turn request"):
        assert bash(h, "PreToolUse", a, repo, cmd, env) == "nothing", cmd
    assert queue(h)[0]["holder"] is None
    assert bash(h, "PreToolUse", a, repo, "gh pr merge 30", {"SQUAD_TURN": "0", **env}) == "nothing"
    assert queue(h)[0]["holder"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
