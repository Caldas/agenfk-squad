#!/usr/bin/env python3
"""oh-my-pi (omp) -> squad-watch adapter.

omp has no Claude Code hook protocol. This reads one omp event as JSON on
stdin, writes the payload hooks/squad-watch.py expects (with `client: omp`, so
the watcher reads the omp transcript instead of a Claude one), runs it, and
translates its verdict into the shape the omp extension consumes:

    {"block": true, "reason": "..."}   refuse the call
    {"context": "..."}                 notes to inject after the call
    {}                                 nothing to do

The arithmetic stays in hooks/squad-watch.py; this only translates. A failure
here prints nothing, so the host is never brought down by a defect in the
adapter.

Event mapping:
    tool_call              -> PreToolUse
    before_subagent_spawn  -> PreToolUse with the Task tool (pre_dispatch)
    tool_result            -> PostToolUse
    session_stop           -> Stop
    prompt                 -> UserPromptSubmit
"""
import json
import os
import subprocess
import sys

EVENTS = {
    "tool_call": "PreToolUse",
    "before_subagent_spawn": "PreToolUse",
    "tool_result": "PostToolUse",
    "session_stop": "Stop",
    "prompt": "UserPromptSubmit",
}

# omp tool names are lowercase; the watcher's brakes are keyed on the Claude
# dialect (MUTATING, DISPATCH, turn_kind's "Bash", the post-cut git escape).
# Translate once, here, so the watcher keeps one vocabulary.
TOOL_NAMES = {
    "bash": "Bash", "read": "Read", "edit": "Edit", "write": "Write",
    "ast_edit": "Edit", "apply_patch": "Edit", "multiedit": "MultiEdit",
    "notebook": "NotebookEdit", "grep": "Grep", "glob": "Glob",
    "task": "Task", "webfetch": "WebFetch", "websearch": "WebSearch",
}


def claude_tool(name):
    """The Claude-dialect name the watcher keys on, or the name unchanged."""
    name = str(name or "")
    return TOOL_NAMES.get(name.lower(), name)


def payload(event):
    """The Claude Code hook payload squad-watch.py reads, from one omp event."""
    kind = str(event.get("event") or "")
    hook = EVENTS.get(kind)
    if not hook:
        return None
    p = {
        "hook_event_name": hook,
        "client": "omp",
        "session_id": event.get("session_id") or "",
        "transcript_path": event.get("transcript_path") or "",
        "cwd": event.get("cwd") or "",
    }
    for src, dst in (("agent_id", "agent_id"), ("agent_type", "agent_type"),
                     ("agent_transcript_path", "agent_transcript_path")):
        if event.get(src):
            p[dst] = event[src]
    if kind == "before_subagent_spawn":
        # The watcher's dispatch brake is the PreToolUse of the Task tool. omp's
        # spawn event carries the agent name, not always the brief; an empty
        # prompt only costs the brief copy, not the ceiling.
        p["tool_name"] = "Task"
        p["tool_input"] = {
            "prompt": event.get("prompt") or event.get("context") or "",
            "description": event.get("description") or "",
            "subagent_type": event.get("agent") or event.get("subagent_type") or "",
        }
    else:
        p["tool_name"] = claude_tool(event.get("tool_name"))
        p["tool_input"] = event.get("tool_input") or {}
    return p


def verdict(stdout):
    """The extension verdict from the watcher's stdout."""
    text = (stdout or "").strip()
    if not text:
        return {}
    data = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                pass
    if isinstance(data, dict):
        hso = data.get("hookSpecificOutput") or {}
        if hso.get("permissionDecision") == "deny" or data.get("decision") == "block":
            reason = hso.get("permissionDecisionReason") or data.get("reason") or "denied by squad-watch"
            return {"block": True, "reason": reason}
        context = hso.get("additionalContext")
        return {"context": context} if context else {}
    return {"context": text}       # UserPromptSubmit prints raw text


def main():
    watcher = os.environ.get("SQUAD_WATCH_HOOK") or \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "squad-watch.py")
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    p = payload(event)
    if not p or not p["session_id"]:
        return 0
    try:
        r = subprocess.run([sys.executable, watcher], input=json.dumps(p),
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return 0
    out = verdict(r.stdout)
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
