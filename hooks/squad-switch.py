#!/usr/bin/env python3
"""Session switch without the owner: clears the pane and calls the pickup.

Called by squad-watch (Stop event) when the main session stopped after writing
the handoff. Runs detached, outside the session:

    squad-switch.py <herdr-pane> <session-id> <handoff-file> <sha256> [note]

  1. waits for the pane's agent to be idle;
  2. checks that the pane still hosts the SAME session (if the owner switched
     sessions or is typing something else, it gives up);
  3. sends `/clear` and checks that the pane's session changed;
  4. sends `/clear-pickup pickup <copy>`: a read-only copy, checked by sha256,
     of the handoff the session itself wrote (never "the most recent one in
     the folder", never the original, which may change after the check); the
     pickup verifies it against the repo and continues from Next step.

  note: a file written by the watcher and appended to the end of the copy
  (background tasks that were still running at the switch).

    squad-switch.py wait <herdr-pane> <session-id> <transcript> <cwd> <seconds>

  The session stopped at handoff level with a background task still running.
  Keeps watch until the deadline: if another switch already went out (claim)
  or the pane changed session, it leaves; once the deadline passes with the
  pane idle, it hands squad-watch a synthetic Stop (squad_wait_expired) and the
  watcher launches the real switch. A herdr that never answers again counts as
  transient only up to SQUAD_SWITCH_BUSY seconds after the deadline (1800).

One switch per session: the first process to create
~/.claude/squad/switches/<session>.claim sends the /clear; the second gives up.
A /clear that does not switch the session (a dialog open) gets an Escape, so the
pane is not left stuck, unless the session is working. Giving up before the
/clear rearms the watcher (synthetic Stop with squad_rearm): it decides again
on the session's next Stop, with the handoff and the owner's request of then.

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


def sealed_copy(path, digest, session, extra=b""):
    """Reads the handoff ONCE, checks the sha256 over those same bytes and
    writes a read-only copy of them (plus the watcher's note, if any) to
    ~/.claude/squad/handoffs (0700). The pickup receives the copy: what the new
    session reads is exactly what was checked, with no window between check
    and use. Same rule squad-watch applies to the original (lstat, regular file
    owned by the user, no symlink following). Returns the copy and its own
    sha256, which is what gets rechecked before the pickup."""
    data = read_checked(path, digest)
    if data is None:
        return None
    data += extra
    digest = hashlib.sha256(data).hexdigest()
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
        return copy, digest
    except OSError:
        return None


CLAIMS = os.path.join(os.path.expanduser("~"), ".claude", "squad", "switches")
WATCH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "squad-watch.py")
STATE = os.path.join(os.path.expanduser("~"), ".claude", "squad", "watch")


def claim_path(session):
    return os.path.join(CLAIMS, f"{session}.claim")


def claim(session):
    """True for the first process that is going to clear this session; the others give up."""
    try:
        os.umask(0o077)
        os.makedirs(CLAIMS, exist_ok=True)
        os.close(os.open(claim_path(session), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except OSError:
        return False


def read_note(path):
    """The watcher's note: only a regular file owned by the user, inside the watcher's state."""
    if not path:
        return b""
    if not re.fullmatch(re.escape(STATE) + r"/[A-Za-z0-9_-]+\.switch-note\.md", path):
        return b""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return b""
            return fh.read(20_000)
    except OSError:
        return b""


def wait(pane, session, transcript, cwd, secs):
    """Scheduled switch: waits for the background task to come back (the session
    stops again and the watcher switches) or for the deadline to pass with the
    pane idle."""
    deadline = time.time() + secs
    hard = deadline + int(os.environ.get("SQUAD_SWITCH_BUSY") or 1800)   # session busy or herdr silent past the deadline
    while True:
        time.sleep(15 if secs >= 60 else 1)
        if os.path.exists(claim_path(session)):
            return 0                            # the switch already went out another way
        sid, status = agent(pane)
        if not sid:                             # herdr did not answer: transient up to the limit, not another session
            if time.time() >= hard:
                log(pane, f"wait undone: herdr silent until {int((hard - deadline) / 60)} min past the deadline")
                return 1
            continue
        if sid != session:
            log(pane, f"wait undone: pane hosts session {sid[:8]}, expected {session[:8]}")
            return 1
        now = time.time()
        if now >= deadline and status not in ("working", "blocked"):
            break
        if now >= hard:
            log(pane, f"wait undone: {session[:8]} still busy {int((hard - deadline) / 60)} min past the deadline")
            return 1
    log(pane, f"{session[:8]} deadline of {secs // 60} min passed with a background task: switch launched")
    if not watch(pane, {"session_id": session, "transcript_path": transcript, "cwd": cwd,
                        "squad_wait_expired": True}):
        log(pane, "gave up: the watcher did not answer at the end of the wait")
        return 1
    return 0


def watch(pane, fields):
    """Synthetic Stop handed to squad-watch (it decides with its own state and lock)."""
    payload = {"hook_event_name": "Stop", "background_tasks": [], **fields}
    try:
        subprocess.run([sys.executable, WATCH], input=json.dumps(payload), text=True, timeout=30,
                       capture_output=True, env=dict(os.environ, HERDR_PANE_ID=pane))
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def rearm(pane, session, why):
    """Giving up before the /clear must not leave the session without a switch:
    the watcher decides again on its next Stop, with the handoff and the
    owner's request of then."""
    watch(pane, {"session_id": session, "squad_rearm": True})
    log(pane, f"gave up: {why}; switch rearmed for the next Stop")
    return 1


def main():
    if len(sys.argv) == 7 and sys.argv[1] == "wait":
        pane, session, transcript, cwd, secs = sys.argv[2:7]
        if (not re.fullmatch(r"[A-Za-z0-9:_-]{1,40}", pane) or not re.fullmatch(r"[0-9a-f-]{8,64}", session)
                or not secs.isdigit() or not transcript.endswith(".jsonl")):
            return 2
        return wait(pane, session, transcript, cwd, int(secs))
    if len(sys.argv) not in (5, 6):
        return 2
    pane, session, handoff, digest = sys.argv[1:5]
    note = read_note(sys.argv[5] if len(sys.argv) == 6 else "")
    if (not re.fullmatch(r"/[A-Za-z0-9_./-]+/handoffs/[A-Za-z0-9_.-]+\.md", handoff)
            or ".." in handoff.split("/") or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        return 2
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,40}", pane) or not re.fullmatch(r"[0-9a-f-]{8,64}", session):
        return 2
    time.sleep(3)                                   # let the Stop really finish
    herdr("agent", "wait", pane, "--until", "idle", "--until", "done", "--timeout", "60000")
    sid, status = agent(pane)
    if sid != session or status in ("working", "blocked"):
        # Session woken after the Stop (owner's request, a task coming back): the
        # handoff pinned here may be stale. Do not clear; the watcher decides on the next Stop.
        return rearm(pane, session, f"pane hosts session {sid[:8] or '?'} in state {status or '?'}, "
                                    f"expected {session[:8]} idle")
    sealed = sealed_copy(handoff, digest, session, note)
    if not sealed:
        return rearm(pane, session, "the handoff changed since the session wrote it")
    copy, copy_digest = sealed
    if agent(pane) != (session, status):            # rechecked right before the /clear
        return rearm(pane, session, "the session changed state before the /clear")
    if not claim(session):
        log(pane, f"gave up: another switch of {session[:8]} is already under way")
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
        if agent(pane)[1] != "working":             # a dialog opened by the /clear; never interrupts a turn
            herdr("agent", "send-keys", pane, "esc", timeout=10)
            log(pane, f"gave up: session {session[:8]} did not change after the /clear (Escape sent)")
        else:
            log(pane, f"gave up: session {session[:8]} did not change after the /clear and is working (no Escape)")
        return 1
    if read_checked(copy, copy_digest) is None:     # the copy is rechecked right before sending
        log(pane, f"{session[:8]} -> {new[:8]} CLEARED, but the handoff copy does not match: pickup NOT sent; original at {handoff}")
        return 1
    rc, _ = herdr("agent", "prompt", pane, f"{PICKUP} {copy}" if PICKUP.startswith("/") else PICKUP, timeout=20)
    log(pane, f"{session[:8]} -> {new[:8]} " + ("pickup sent" if rc == 0 else "CLEARED, but the pickup was not accepted: run /clear-pickup pickup")
        + (" (with a note on background tasks)" if note else ""))
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
