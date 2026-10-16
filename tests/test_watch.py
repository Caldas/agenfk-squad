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


def run_proc(h, event, sid, transcript, extra=None, env=None):
    p = {"hook_event_name": event, "session_id": sid, "transcript_path": transcript,
         "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": h}
    p.update(extra or {})
    e = dict(os.environ, HOME=h)
    for key in list(e):
        if key.startswith("SQUAD_") or key.startswith("HERDR_"):
            del e[key]
    e.update(env or {})
    return subprocess.run([sys.executable, HOOK], input=json.dumps(p), capture_output=True,
                          text=True, env=e)


def run(h, event, sid, transcript, extra=None, env=None):
    return run_proc(h, event, sid, transcript, extra, env).stdout.strip()


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


def compact_handoff(h, sid):
    return os.path.join(h, ".claude", "squad", "handoffs", f"{sid}-compact.md")


def dirty_repo(h):
    repo = os.path.join(h, "repo")
    subprocess.run(["git", "init", "-q", "-b", "feat/compact", repo], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        git(repo, "config", key, value)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "first commit of the card")
    with open(os.path.join(repo, "half-done.py"), "w") as fh:
        fh.write("x = 1\n")
    return repo


def test_compaction_writes_the_handoff_before_the_conversation_is_summarized():
    """A /compact, or an auto-compact, used to run with nothing on disk: the
    decisions were summarized away and git, the owner's request and the denied
    briefs were not written anywhere."""
    for trigger, instructions in (("manual", "keep the merge plan"), ("auto", None)):
        h = home()
        sid = f"c0c0c0c0-{trigger}"
        repo = dirty_repo(h)
        tr = session(h, sid, 300_000, 0.9)
        run(h, "UserPromptSubmit", sid, tr, {"prompt": "deliver card ABC-2", "cwd": repo})
        briefs = os.path.join(h, ".claude", "squad", "handoffs", f"{sid}-dispatches.md")
        os.makedirs(os.path.dirname(briefs), exist_ok=True)
        with open(briefs, "w") as fh:
            fh.write("## brief\n")
        r = run_proc(h, "PreCompact", sid, tr, {"trigger": trigger, "custom_instructions": instructions,
                                                "cwd": repo})
        assert r.returncode == 0 and r.stdout.strip() == "", r      # never blocks the compaction
        with open(compact_handoff(h, sid)) as fh:
            body = fh.read()
        assert "written by squad-watch" in body and f"compacted ({trigger})" in body, body
        assert "stopped without writing" not in body, body           # the header says why it was written
        assert "Branch: feat/compact" in body and "?? half-done.py" in body, body
        assert "first commit of the card" in body and "deliver card ABC-2" in body, body
        assert briefs in body and "\n## Next step\n" in body, body
        if instructions:                                             # what the owner typed after /compact
            assert f"Compact instructions:** {instructions}" in body, body
        else:
            assert "Compact instructions" not in body, body
        assert not os.path.exists(os.path.join(h, ".claude", "squad", "handoffs", f"{sid}-watch.md"))


def test_compaction_of_a_sub_session_writes_nothing():
    h = home()
    sid = "c0c0c0c0-0002"
    r = run_proc(h, "PreCompact", sid, session(h, sid, 300_000, 0.9),
                 {"trigger": "auto", "custom_instructions": None, "agent_id": "agent-1"})
    assert r.returncode == 0 and r.stdout.strip() == "", r
    assert not os.path.exists(os.path.join(h, ".claude", "squad", "handoffs")), os.listdir(h)


def test_compaction_at_handoff_level_never_switches_the_session():
    h = home()
    sid = "c0c0c0c0-0003"
    herdr, sent = fake_herdr(h, sid)
    env = {"HERDR_PANE_ID": "w1:p1", "HERDR_BIN_PATH": herdr}
    tr = session(h, sid, 550_000, 0.9)
    assert kind(said(run(h, "PostToolUse", sid, tr, env=env))) == "PROACTIVE HANDOFF"
    for trigger in ("manual", "auto"):
        r = run_proc(h, "PreCompact", sid, tr, {"trigger": trigger, "custom_instructions": None}, env)
        assert r.returncode == 0 and r.stdout.strip() == "", r
    assert os.path.exists(compact_handoff(h, sid))
    log = os.path.join(h, ".claude", "squad", "switches.log")
    for _ in range(16):                    # a switch runs detached and waits 3 s before its first step
        assert not os.path.exists(log) and not os.path.exists(sent), "PreCompact launched the switch"
        time.sleep(0.5)
    assert not state(h, sid).get("switched")


def test_compaction_handler_error_fails_open_and_is_logged():
    h = home()
    sid = "c0c0c0c0-0004"
    os.makedirs(os.path.join(h, ".claude", "squad", "watch"))
    with open(os.path.join(h, ".claude", "squad", "watch", f"{sid}.main.json"), "w") as fh:
        json.dump({"ctx": "not a number"}, fh)            # a corrupt state makes the handoff raise
    r = run_proc(h, "PreCompact", sid, os.path.join(h, "t.jsonl"), {"trigger": "auto", "custom_instructions": None})
    assert r.returncode == 0 and r.stdout.strip() == "" and r.stderr.strip() == "", r
    with open(os.path.join(h, ".claude", "squad", "watch-errors.log")) as fh:
        assert "TypeError" in fh.read()


def test_compaction_handoff_off_with_squad_watch_0():
    h = home()
    sid = "c0c0c0c0-0005"
    r = run_proc(h, "PreCompact", sid, session(h, sid, 300_000, 0.9),
                 {"trigger": "manual", "custom_instructions": None}, {"SQUAD_WATCH": "0"})
    assert r.returncode == 0 and r.stdout.strip() == "", r
    assert not os.path.exists(compact_handoff(h, sid))


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
    """Contract since the short turn: one session merges at a time, but only for
    the merge call itself; the next one goes as soon as that call returns, with
    no queue, no MERGE TURN call and no sync denial."""
    h = home()
    repo, env, state_file = repo_with_gh(h)
    a, b = "aaaa1111-0001", "bbbb2222-0001"
    assert bash(h, "PreToolUse", a, repo, "gh pr merge 10 --squash", env) == "nothing"   # turn free: passes
    assert queue(h)[0]["holder"]["session"] == a
    out = bash(h, "PreToolUse", b, repo, "cd x && gh pr merge 11 --squash", env)
    assert "MERGE QUEUE" in out and "is merging" in out and "PR #10" in out, out
    assert "queue" not in queue(h)[0] and queue(h)[0]["intents"] == []                    # nobody waits in line
    assert bash(h, "PreToolUse", b, repo, "git fetch origin && git merge origin/main", env) == "nothing"
    assert bash(h, "PreToolUse", a, repo, "git merge origin/main", env) == "nothing"
    assert bash(h, "PostToolUse", a, repo, "gh pr merge 10 --squash", env) == "nothing"   # the call returned
    d, _ = queue(h)
    assert d["holder"] is None and d["last"]["session"] == a and d["last"]["why"] == "done"
    assert bash(h, "PreToolUse", b, repo, "gh pr merge 11 --squash", env) == "nothing"    # the next one goes
    assert queue(h)[0]["holder"]["session"] == b
    assert "MERGE QUEUE" in bash(h, "PreToolUse", a, repo, "gh pr merge 12", env)


def test_merge_queue_stalled_turn_passes_on_and_can_be_requested_and_released():
    h = home()
    repo, env, _ = repo_with_gh(h)
    a, b, c = "aaaa1111-0002", "bbbb2222-0002", "cccc3333-0002"
    assert bash(h, "PreToolUse", a, repo, "squad-turn request 20", env) == "nothing"
    assert bash(h, "PreToolUse", b, repo, "squad-turn request 21", env) == "nothing"
    d, _ = queue(h)
    assert d.get("holder") is None and [(e["session"], e["pr"]) for e in d["intents"]] == [(a, "20"), (b, "21")]
    assert bash(h, "PreToolUse", c, repo, "git push origin HEAD:main", env) == "nothing"   # an intent blocks nobody
    d, path = queue(h)
    d["holder"]["since"] -= 1000                      # C's merge call never came back
    with open(path, "w") as fh:
        json.dump(d, fh)
    assert bash(h, "PreToolUse", a, repo, "gh pr merge", env) == "nothing"        # the stalled turn passes on
    d, _ = queue(h)
    assert d["holder"]["session"] == a and d["holder"]["pr"] == "77" and d["last"]["why"] == "expired"
    assert [e["session"] for e in d["intents"]] == [b]                            # merging consumed A's intent
    assert "expired" in bash(h, "PostToolUse", c, repo, "ls", env)               # C finds out
    bash(h, "PreToolUse", a, repo, "squad-turn release", env)
    assert queue(h)[0]["holder"] is None
    bash(h, "PreToolUse", b, repo, "squad-turn release", env)
    assert queue(h)[0]["intents"] == []
    # text that is provably data does not take the turn; neither does a branch with "main" in its name
    for cmd in ("git push origin feat/main-menu", "git commit -m 'explain gh pr merge'", "echo squad-turn request"):
        assert bash(h, "PreToolUse", a, repo, cmd, env) == "nothing", cmd
    assert queue(h)[0]["holder"] is None
    # fail closed (contract change): code fed to an interpreter counts as a merge, even through a heredoc
    bash(h, "PreToolUse", a, repo, "python3 - <<'E'\npat = 'gh pr merge|git merge origin/main'\nE", env)
    assert queue(h)[0]["holder"]["session"] == a
    bash(h, "PreToolUse", a, repo, "squad-turn release", env)
    assert bash(h, "PreToolUse", a, repo, "gh pr merge 30", {"SQUAD_TURN": "0", **env}) == "nothing"
    assert queue(h)[0]["holder"] is None


def holder(h):
    """Who holds the merge turn, or None (also when no merge was ever seen)."""
    folder = os.path.join(h, ".claude", "squad", "turn")
    if not os.path.isdir(folder) or not any(n.endswith(".json") for n in os.listdir(folder)):
        return None
    return queue(h)[0].get("holder")


GM = "gh pr " + "merge"


def test_merge_text_is_data_only_where_it_provably_does_not_run():
    """October 2026: `agenfk create ... -d "... (gh pr merge, ...)"` took the merge
    turn. Text is data only as the value of -m/-d/--body/--title/--description/
    --evidence or an echo/printf argument, on a line of inert commands; any other
    form counts as a merge (fail closed) and goes through the turn and the seal."""
    h = home()
    repo, env, _ = repo_with_gh(h)
    sid = "dddd4444-0001"
    for cmd in (f'agenfk create story x -d "The turn covers the merge ({GM}, push to main, merge_pull_request)"',
                f"git commit -m 'explain {GM}'", f'gh pr create --title "x" --body "run {GM} 5 after"',
                f"echo \\; {GM} 6", f'cd x && agenfk create --description="{GM} 5" 2>&1'):
        assert bash(h, "PreToolUse", sid, repo, cmd, env) == "nothing", cmd
        assert holder(h) is None, cmd
    for cmd in (f'bash -c "{GM} 5"', f"sh -c '{GM} 5'", 'eval "git push origin main"', f'ssh host "{GM} 5"',
                f"echo 5 | xargs {GM}", f'env FOO=1 sh -c "{GM} 5"', f'echo "$({GM} 5)"', f"echo `{GM} 5`",
                f"watch -n 5 {GM} 5", f"timeout 60 {GM} 5", f"nohup {GM} 5", "git -C . push origin HEAD:main",
                "git push origin +HEAD:refs/heads/main", "gh api -X PUT repos/o/r/pulls/5/merge",
                f'echo "{GM} 5" | sh', 'gh pr "mer""ge" 5', f"cat > n.md <<EOF\n{GM} 9\nEOF"):
        assert bash(h, "PreToolUse", sid, repo, cmd, env) == "nothing", cmd     # seal off: takes the turn
        assert holder(h)["session"] == sid, cmd
        bash(h, "PostToolUse", sid, repo, cmd, env)                            # and gives it back
        assert holder(h) is None, cmd
        out = bash(h, "PreToolUse", sid, repo, cmd, {**env, "SQUAD_SEAL": "1"})
        assert "MERGE SEAL" in out and "squad-seal record" in out, (cmd, out)
        assert holder(h) is None, cmd                                          # a denial releases at once
    out = bash(h, "PreToolUse", sid, repo, f'agenfk comment 1 "see {GM} 3" && {GM} 12', env)
    assert "more than one merge" in out and "#3" in out and "#12" in out, out


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def origin_repo(h):
    """A clone of a bare origin with a fake gh that reads PRs from prs.json."""
    bare, repo = os.path.join(h, "origin.git"), os.path.join(h, "repo")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    subprocess.run(["git", "clone", "-q", bare, repo], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        git(repo, "config", k, v)
    for f in ("a.txt", "b.txt", "c.txt"):
        with open(os.path.join(repo, f), "w") as fh:
            fh.write("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    git(repo, "push", "-q", "origin", "HEAD:main")
    prs = os.path.join(h, "prs.json")
    gh = os.path.join(h, "gh")
    with open(gh, "w") as fh:
        fh.write(f"""#!/usr/bin/env python3
import json, sys
prs = json.load(open({prs!r}))
n = next((a for a in sys.argv[3:] if a.isdigit()), "")
pr = prs.get(n) or {{}}
print(json.dumps(pr) if "-q" not in sys.argv else pr.get(sys.argv[-1][1:], ""))
""")
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR)
    return repo, {"SQUAD_GH": gh}, prs


def branch(repo, name, path, text):
    git(repo, "checkout", "-q", "-b", name, "origin/main")
    with open(os.path.join(repo, path), "w") as fh:
        fh.write(text)
    git(repo, "commit", "-qam", name)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--detach")
    return sha


def set_prs(prs, **kw):
    with open(prs, "w") as fh:
        json.dump({n: {"number": int(n), "baseRefName": "main", "headRefName": b, "headRefOid": s}
                   for n, (b, s) in kw.items()}, fh)


def test_merge_turn_two_sessions_disjoint_prs_merge_without_waiting():
    h = home()
    repo, env, prs = origin_repo(h)
    set_prs(prs, **{"1": ("feat-a", branch(repo, "feat-a", "a.txt", "A\n")),
                    "2": ("feat-b", branch(repo, "feat-b", "b.txt", "B\n"))})
    a, b = "aaaa5555-0001", "bbbb6666-0001"
    assert bash(h, "PreToolUse", a, repo, f"{GM} 1 --squash", env) == "nothing"
    out = bash(h, "PreToolUse", b, repo, f"{GM} 2 --squash", env)          # only while A's call is running
    assert "MERGE QUEUE" in out and "is merging" in out and "a few seconds" in out and "PR #1" in out, out
    assert bash(h, "PreToolUse", b, repo, "git fetch origin && git merge origin/main", env) == "nothing"  # sync: never
    bash(h, "PostToolUse", a, repo, f"{GM} 1 --squash", env)                 # A's call came back: turn released
    assert holder(h) is None and queue(h)[0]["last"]["why"] == "done"
    assert bash(h, "PreToolUse", b, repo, f"{GM} 2 --squash", env) == "nothing"   # B: no queue, no wait
    bash(h, "PostToolUse", b, repo, f"{GM} 2 --squash", env)
    assert holder(h) is None
    # a failed merge call gives the turn back as well
    assert bash(h, "PreToolUse", a, repo, f"{GM} 1", env) == "nothing"
    run(h, "PostToolUseFailure", a, os.path.join(h, "t.jsonl"), {"tool_input": {"command": f"{GM} 1"}, "cwd": repo}, env)
    assert holder(h) is None


def test_merge_turn_held_too_long_expires():
    h = home()
    repo, env, _ = repo_with_gh(h)
    a, b = "aaaa7777-0001", "bbbb8888-0001"
    assert bash(h, "PreToolUse", a, repo, f"{GM} 10", env) == "nothing"
    d, path = queue(h)
    d["holder"]["since"] -= 100
    with open(path, "w") as fh:
        json.dump(d, fh)
    assert "is merging" in bash(h, "PreToolUse", b, repo, f"{GM} 11", env)       # 100 s: still A's
    d, path = queue(h)
    d["holder"]["since"] -= 21
    with open(path, "w") as fh:
        json.dump(d, fh)
    assert bash(h, "PreToolUse", b, repo, f"{GM} 11", env) == "nothing"          # 121 s: expired
    d, _ = queue(h)
    assert d["holder"]["session"] == b and d["last"]["why"] == "expired" and d["last"]["session"] == a
    assert "expired" in bash(h, "PostToolUse", a, repo, "ls", env)              # A finds out


def test_merge_conflict_with_main_is_denied_with_the_files():
    h = home()
    repo, env, prs = origin_repo(h)
    head = branch(repo, "feat-c", "a.txt", "C\n")
    with open(os.path.join(repo, "b.txt"), "w") as fh:                         # a second, clean file on the PR
        fh.write("C\n")
    git(repo, "checkout", "-q", "feat-c")
    git(repo, "commit", "-qam", "b")
    head = git(repo, "rev-parse", "HEAD")
    set_prs(prs, **{"3": ("feat-c", head)})
    other = os.path.join(h, "other")                                           # main moves elsewhere: no local ref yet
    subprocess.run(["git", "clone", "-q", os.path.join(h, "origin.git"), other], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        git(other, "config", k, v)
    with open(os.path.join(other, "a.txt"), "w") as fh:
        fh.write("MAIN\n")
    git(other, "commit", "-qam", "main moves")
    git(other, "push", "-q", "origin", "HEAD:main")
    sid = "cccc9999-0001"
    out = bash(h, "PreToolUse", sid, repo, f"{GM} 3", env)
    assert "MERGE CONFLICT" in out and "Conflict in: a.txt." in out and "b.txt" not in out, out
    assert "git merge origin/main" in out and "AgenFK" in out, out
    assert holder(h) is None                                                   # the turn was released
    git(repo, "merge", "-q", "-X", "theirs", "origin/main", "-m", "sync")      # resolved: passes, no suite asked
    set_prs(prs, **{"3": ("feat-c", git(repo, "rev-parse", "HEAD"))})
    assert bash(h, "PreToolUse", sid, repo, f"{GM} 3", env) == "nothing"


def test_turn_status_shows_who_is_merging_and_the_intents():
    h = home()
    repo, env, _ = repo_with_gh(h)
    assert bash(h, "PreToolUse", "eeee1111-0001", repo, "squad-turn request 40", env) == "nothing"
    assert bash(h, "PreToolUse", "ffff2222-0001", repo, f"{GM} 41", env) == "nothing"
    e = dict(os.environ, HOME=h)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "squad-turn.py"), "status"], cwd=repo,
                         capture_output=True, text=True, env=e).stdout
    assert "merging now: session ffff2222 (PR #41)" in out and "eeee1111 (PR #40)" in out, out


def beta_origin(h):
    """origin_repo whose default branch is beta (origin/HEAD -> origin/beta)."""
    repo, env, prs = origin_repo(h)
    git(repo, "push", "-q", "origin", "HEAD:beta")
    git(repo, "fetch", "-q", "origin")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/beta")
    git(repo, "checkout", "-q", "-b", "feat", "origin/beta")
    return repo, env, prs


def test_push_to_the_remote_default_branch_is_a_push_to_the_trunk():
    """Review of October 2026: with beta as the default branch, `git push origin
    HEAD:beta` went past the turn and the seal, which only knew main/master."""
    h = home()
    repo, env, _ = beta_origin(h)
    sid = "abab1111-0001"
    for cmd in ("git push origin HEAD:beta", "git push origin feat:beta", "git push origin +feat:refs/heads/beta"):
        assert bash(h, "PreToolUse", sid, repo, cmd, env) == "nothing", cmd          # seal off: takes the turn
        assert holder(h)["session"] == sid, cmd
        bash(h, "PostToolUse", sid, repo, cmd, env)
        out = bash(h, "PreToolUse", sid, repo, cmd, {**env, "SQUAD_SEAL": "1"})
        assert "MERGE SEAL" in out and "push to the trunk" in out, (cmd, out)
    for cmd in ("git push origin feat", "git push origin HEAD:feat-2", "git push -u origin feat:beta-notes"):
        assert bash(h, "PreToolUse", sid, repo, cmd, {**env, "SQUAD_SEAL": "1"}) == "nothing", cmd
        assert holder(h) is None, cmd


def test_trunk_from_gh_when_origin_head_is_missing_and_from_squad_trunk():
    h = home()
    repo, env, prs = beta_origin(h)
    git(repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    sealed = {**env, "SQUAD_SEAL": "1"}
    assert bash(h, "PreToolUse", "abab2222-0001", repo, "git push origin HEAD:beta", sealed) == "nothing"
    with open(prs, "w") as fh:
        json.dump({"": {"defaultBranchRef.name": "beta"}}, fh)       # what `gh repo view` answers
    assert "MERGE SEAL" in bash(h, "PreToolUse", "abab2222-0001", repo, "git push origin HEAD:beta", sealed)
    git(repo, "config", "squad.trunk", "release, stable")
    for dst in ("release", "stable"):
        out = bash(h, "PreToolUse", "abab2222-0001", repo, f"git push origin HEAD:{dst}", sealed)
        assert "MERGE SEAL" in out, (dst, out)


def test_push_with_no_refspec_to_a_trunk_upstream_is_a_push_to_the_trunk():
    """A branch that tracks origin/beta with push.default=upstream sends `git push`
    to beta: the watcher reads the push target, not the branch name."""
    h = home()
    repo, env, _ = beta_origin(h)
    sealed = {**env, "SQUAD_SEAL": "1"}
    assert bash(h, "PreToolUse", "abab3333-0001", repo, "git push", sealed) == "nothing"   # simple: feat -> feat
    git(repo, "branch", "-q", "--set-upstream-to", "origin/beta")
    git(repo, "config", "push.default", "upstream")
    for cmd in ("git push", "git push origin"):
        assert "MERGE SEAL" in bash(h, "PreToolUse", "abab3333-0001", repo, cmd, sealed), cmd


def test_turn_status_compares_against_the_remote_default_branch():
    h = home()
    repo, env, _ = beta_origin(h)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("feat\n")
    git(repo, "commit", "-qam", "feat")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "squad-turn.py"), "status"], cwd=repo,
                         capture_output=True, text=True, env=dict(os.environ, HOME=h, **env)).stdout
    assert "feat x origin/beta" in out and "merges without conflict" in out, out


def seal_head(h, repo):
    """Records a SHIP seal of the repository's HEAD with squad-seal."""
    sha = git(repo, "rev-parse", "HEAD")
    ev = os.path.join(h, f"{sha}.md")
    with open(ev, "w") as fh:
        fh.write("SHIP\n")
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SQUAD_", "HERDR_"))}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "squad-seal.py"), "record", "--card", "c-1",
                        "--model", "m", "--verdict", "SHIP", "--evidence", ev], cwd=repo, capture_output=True,
                       text=True, env=dict(e, HOME=h))
    assert r.returncode == 0, r.stderr
    return sha


def test_push_of_head_from_the_trunk_is_a_push_to_the_trunk():
    """Round 2 review: `git push origin HEAD` with the trunk checked out passed,
    because `origin` counted as the refspec and the current branch was never read."""
    h = home()
    repo, env, _ = beta_origin(h)
    sealed = {**env, "SQUAD_SEAL": "1"}
    sid = "acac1111-0001"
    for cmd in ("git push origin HEAD", "git push -u origin HEAD", "git push origin @", "git push origin feat"):
        assert bash(h, "PreToolUse", sid, repo, cmd, sealed) == "nothing", cmd          # feat is not the trunk
    out = bash(h, "PreToolUse", sid, repo, "git push --all origin", sealed)
    assert "MERGE SEAL" in out and "push to the trunk" in out, out                     # --all pushes the trunk
    git(repo, "checkout", "-q", "-B", "beta", "origin/beta")
    for cmd in ("git push origin HEAD", "git push -u origin HEAD", "git push origin @"):
        out = bash(h, "PreToolUse", sid, repo, cmd, sealed)
        assert "MERGE SEAL" in out and "push to the trunk" in out, (cmd, out)
    git(repo, "checkout", "-q", "-b", "master")                                        # no upstream, no push target
    out = bash(h, "PreToolUse", sid, repo, "git push", sealed)
    assert "MERGE SEAL" in out and "push to the trunk" in out, out                     # the current branch is master


def test_merge_and_push_are_checked_where_the_command_runs():
    """Round 2 review: from a cwd outside the repository, `cd <repo> && <merge>`
    passed unchecked; `cd ../wt-x && git push origin HEAD:beta` checked the HEAD of
    the session's cwd, sealed, instead of the unsealed HEAD of wt-x."""
    h = home()
    repo, env, prs = beta_origin(h)
    git(repo, "config", "squad.seal", "true")
    sid = "acac2222-0001"
    outside = os.path.join(h, "outside")
    os.makedirs(outside)
    set_prs(prs, **{"5": ("feat", git(repo, "rev-parse", "HEAD"))})
    for cmd in (f"cd {repo} && git push origin HEAD:beta", f"cd {repo} && {GM} 5", f"cd {repo}; {GM} 5"):
        out = bash(h, "PreToolUse", sid, outside, cmd, env)
        assert "MERGE SEAL" in out and "no seal for that SHA" in out, (cmd, out)
    for cmd in ('git -C "$WT" push origin HEAD:beta', f'cd "$WT" && {GM} 5', f"cd - && {GM} 5",
                f"(cd {repo} && true) && {GM} 5", f"GIT_DIR={repo}/.git git push origin HEAD:beta"):
        out = bash(h, "PreToolUse", sid, outside, cmd, env)
        assert "MERGE SEAL" in out and "literal path" in out, (cmd, out)
        assert holder(h) is None, cmd
    seal_head(h, repo)
    wt = os.path.join(h, "wt-x")
    git(repo, "worktree", "add", "-q", "-b", "other", wt, "origin/beta")
    with open(os.path.join(wt, "a.txt"), "w") as fh:
        fh.write("not reviewed\n")
    git(wt, "commit", "-qam", "unsealed")
    assert bash(h, "PreToolUse", sid, repo, "git push origin HEAD:beta", env) == "nothing"   # sealed here
    bash(h, "PostToolUse", sid, repo, "git push origin HEAD:beta", env)
    for cmd in ("cd ../wt-x && git push origin HEAD:beta", "git -C ../wt-x push origin HEAD:beta",
                f"cd {wt} && git push origin HEAD:beta"):
        out = bash(h, "PreToolUse", sid, repo, cmd, env)
        assert "MERGE SEAL" in out and "no seal for that SHA" in out, (cmd, out)
    out = bash(h, "PreToolUse", sid, repo, 'cd "$WT" && git push origin HEAD:beta', {**env, "SQUAD_SEAL": "0"})
    assert out == "nothing", out                                                           # seal off: no denial


def test_turn_status_uses_squad_trunk_first():
    h = home()
    repo, env, _ = beta_origin(h)
    git(repo, "push", "-q", "origin", "origin/beta:refs/heads/release")
    git(repo, "fetch", "-q", "origin")
    git(repo, "config", "squad.trunk", "release")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "squad-turn.py"), "status"], cwd=repo,
                         capture_output=True, text=True, env=dict(os.environ, HOME=h, **env)).stdout
    assert "feat x origin/release" in out, out


def test_a_cd_that_may_not_run_leaves_the_directory_unknown():
    """Round 3 review: `false && cd <repo>; git push ...` was checked in <repo>,
    though the cd never ran and the push ran in the session's unsealed worktree."""
    h = home()
    repo, env, _ = beta_origin(h)
    git(repo, "config", "squad.seal", "true")
    sid = "adad1111-0001"
    seal_head(h, repo)
    wt = os.path.join(h, "wt-y")
    git(repo, "worktree", "add", "-q", "-b", "other", wt, "origin/beta")
    with open(os.path.join(wt, "a.txt"), "w") as fh:
        fh.write("not reviewed\n")
    git(wt, "commit", "-qam", "unsealed")
    assert bash(h, "PreToolUse", sid, wt, f"cd {repo}; git push origin HEAD:beta", env) == "nothing"   # sealed there
    bash(h, "PostToolUse", sid, wt, f"cd {repo}; git push origin HEAD:beta", env)
    for cmd in (f"false && cd {repo}; git push origin HEAD:beta", f"[ -d /nada ] && cd {repo}; git push origin HEAD:beta",
                f"cd {wt} || cd {repo}; git push origin HEAD:beta", f"cd {repo} | cat; git push origin HEAD:beta",
                f"cd {repo} & git push origin HEAD:beta", f"if true; then cd {repo}; fi; git push origin HEAD:beta"):
        out = bash(h, "PreToolUse", sid, wt, cmd, env)
        assert "MERGE SEAL" in out and "literal path" in out, (cmd, out)


def test_an_unknown_directory_counts_only_a_push_that_may_reach_the_trunk():
    """Round 3 review: with the directory unknown, every push counted as a push to
    the trunk, so `cd "$D" && git push -u origin feat/x` took the turn or was denied."""
    h = home()
    repo, env, _ = beta_origin(h)
    sid = "adad2222-0001"
    outside = os.path.join(h, "outside")
    os.makedirs(outside)
    for cmd in ('cd "$D" && git push -u origin feat/x', "cd /no/such/dir && git push origin feat/x:feat/x"):
        assert bash(h, "PreToolUse", sid, repo, cmd, env) == "nothing", cmd
        assert holder(h) is None, cmd
        out = bash(h, "PreToolUse", sid, outside, cmd, env)      # outside a repository: no trunk to compare with
        assert "MERGE SEAL" in out and "literal path" in out, (cmd, out)
    git(repo, "config", "squad.seal", "true")
    for cmd in ('cd "$D" && git push', 'cd "$D" && git push origin', 'cd "$D" && git push -u origin HEAD',
                'cd "$D" && git push origin @', 'cd "$D" && git push origin HEAD:beta', 'cd "$D" && git push origin main'):
        out = bash(h, "PreToolUse", sid, repo, cmd, env)
        assert "MERGE SEAL" in out and "literal path" in out, (cmd, out)


def test_turn_status_falls_back_to_master():
    """With no origin/HEAD, no squad.trunk, no origin/main and gh silent, the trunk is master."""
    h = home()
    repo, env, _ = origin_repo(h)
    git(repo, "push", "-q", "origin", "HEAD:master")
    subprocess.run(["git", "--git-dir", os.path.join(h, "origin.git"), "symbolic-ref", "HEAD", "refs/heads/master"],
                   check=True)
    git(repo, "push", "-q", "origin", ":main")
    git(repo, "fetch", "-q", "--prune", "origin")
    subprocess.run(["git", "-C", repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD"], capture_output=True)
    git(repo, "checkout", "-q", "-b", "feat", "origin/master")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "hooks", "squad-turn.py"), "status"], cwd=repo,
                         capture_output=True, text=True, env=dict(os.environ, HOME=h, **env)).stdout
    assert "feat x origin/master" in out, out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
