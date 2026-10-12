#!/usr/bin/env python3
"""Session switch without the owner: clears the pane and calls the pickup.

Called by squad-watch (Stop event) when the main session stopped after writing
the handoff. Runs detached, outside the session:

    squad-switch.py <herdr-pane> <session-id> <handoff-file> <sha256>

  1. waits for the pane's agent to be idle;
  2. checks that the pane still hosts the SAME session (if the owner switched
     sessions or is typing something else, it gives up);
  3. sends `/clear` and checks that the pane's session changed;
  4. sends `/clear-pickup pickup <copy>`: a read-only copy, checked by sha256,
     of the handoff the session itself wrote (never "the most recent one in
     the folder", never the original, which may change after the check); the
     pickup verifies it against the repo and continues from Next step.

Every step goes to ~/.claude/squad/switches.log. Any doubt = give up: the
handoff is already written and the owner does the switch by hand.
"""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time

HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
LOG = os.path.join(os.path.expanduser("~"), ".claude", "squad", "switches.log")
PICKUP = os.environ.get("SQUAD_SWITCH_PROMPT") or "/clear-pickup pickup"   # the variable exists for tests


def log(pane, msg):
    os.umask(0o077)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {pane} {msg}\n")


def herdr(*args, timeout=90):
    try:
        r = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def agent(pane):
    rc, out = herdr("agent", "get", pane, timeout=15)
    try:
        a = json.loads(out)["result"]["agent"]
        return (a.get("agent_session") or {}).get("value") or "", a.get("agent_status") or ""
    except (ValueError, KeyError, TypeError):
        return "", ""


COPIES = os.path.join(os.path.expanduser("~"), ".claude", "squad", "handoffs")


def read_checked(path, digest):
    """Bytes of the file if it is a regular file owned by the user with this
    sha256. Opens without following symlinks and checks type and owner on the
    open descriptor itself."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return None
            data = fh.read(2_000_000)
    except OSError:
        return None
    return data if hashlib.sha256(data).hexdigest() == digest else None


def sealed_copy(path, digest, session):
    """Reads the handoff ONCE, checks the sha256 over those same bytes and
    writes a read-only copy of them to ~/.claude/squad/handoffs (0700). The
    pickup receives the copy: what the new session reads is exactly what was
    checked, with no window between check and use. Same rule squad-watch
    applies to the original (lstat, regular file owned by the user, no symlink
    following)."""
    data = read_checked(path, digest)
    if data is None:
        return None
    try:
        os.umask(0o077)
        os.makedirs(COPIES, exist_ok=True)
        os.chmod(COPIES, 0o700)
        copy = os.path.join(COPIES, f"{session}-{digest[:12]}.md")
        tmp = f"{copy}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, copy)
        return copy
    except OSError:
        return None


def main():
    if len(sys.argv) != 5:
        return 2
    pane, session, handoff, digest = sys.argv[1:5]
    if (not re.fullmatch(r"/[A-Za-z0-9_./-]+/handoffs/[A-Za-z0-9_.-]+\.md", handoff)
            or ".." in handoff.split("/") or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        return 2
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,40}", pane) or not re.fullmatch(r"[0-9a-f-]{8,64}", session):
        return 2
    time.sleep(3)                                   # let the Stop really finish
    herdr("agent", "wait", pane, "--until", "idle", "--until", "done", "--timeout", "60000")
    sid, status = agent(pane)
    if sid != session or status in ("working", "blocked"):
        log(pane, f"gave up: pane hosts session {sid[:8] or '?'} in state {status or '?'}, expected {session[:8]} idle")
        return 1
    copy = sealed_copy(handoff, digest, session)
    if not copy:
        log(pane, "gave up: the handoff changed since the session wrote it")
        return 1
    rc, _ = herdr("agent", "prompt", pane, "/clear", timeout=20)
    if rc != 0:
        log(pane, "gave up: /clear was not accepted")
        return 1
    new = session
    for _ in range(15):                             # the pane only changes session after the /clear
        time.sleep(1)
        new, _status = agent(pane)
        if new and new != session:
            break
    if not new or new == session:
        log(pane, f"gave up: session {session[:8]} did not change after the /clear")
        return 1
    if read_checked(copy, digest) is None:          # the copy is rechecked right before sending
        log(pane, f"{session[:8]} -> {new[:8]} CLEARED, but the handoff copy does not match: pickup NOT sent; original at {handoff}")
        return 1
    rc, _ = herdr("agent", "prompt", pane, f"{PICKUP} {copy}" if PICKUP.startswith("/") else PICKUP, timeout=20)
    log(pane, f"{session[:8]} -> {new[:8]} " + ("pickup sent" if rc == 0 else "CLEARED, but the pickup was not accepted: run /clear-pickup pickup"))
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        try:
            log(sys.argv[1] if len(sys.argv) > 1 else "?", f"error {type(exc).__name__}")
        except Exception:
            pass
        sys.exit(1)
