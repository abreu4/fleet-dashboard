"""Closing a session from the board.

A tile is a conversation, and behind a live conversation there is a CLI
process sitting in some terminal. Closing it means ending that process the
way closing its terminal tab would, and nothing more: the transcript stays on
disk, so a session closed here is still one `--resume <id>` away. Nothing is
ever deleted.

Claude's roster gives the cleanest route: `claude stop <job>` ends a
background session by its own id and keeps the conversation attachable. When
that does not apply -- an interactive Claude session, Codex, Antigravity, a
bare process tile -- the signal goes to the process GROUP, not the pid alone:
an interactive shell gives each job its own group, so the group is the CLI
plus whatever it was running (a shell tool mid-command, a build), and none of
that should be orphaned to keep running headless. SIGTERM first, which all
three CLIs handle by shutting down cleanly; SIGKILL only if it is still there
after the grace period.

Which process? Claude's roster names the pid outright. Antigravity and Codex
are matched the way the collectors match them -- one process per working
directory -- and when that is ambiguous the board says so instead of guessing.
"""

import os
import shutil
import signal
import subprocess
import time

from collectors import live_processes

GRACE_S = 3.0


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_for(session):
    """(pid, reason). pid is None when there is nothing to signal."""
    pid = session.get("pid")
    try:
        pid = int(pid) if pid else None
    except (TypeError, ValueError):
        pid = None
    if pid and _alive(pid):
        return pid, ""
    if pid:
        return None, "its process is already gone"
    provider = session.get("provider") or ""
    cwd = (session.get("cwd") or "").rstrip("/")
    matches = [p for p in live_processes(provider)
               if (p.get("cwd") or "").rstrip("/") == cwd]
    if len(matches) == 1:
        return int(matches[0]["pid"]), ""
    if not matches:
        return None, "no running process behind it"
    return None, ("%d %s processes in that folder; close it from its own "
                  "terminal" % (len(matches), provider))


def _signal(pid, sig):
    """Signal the job's process group, falling back to the pid alone."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return False
    if pgid == os.getpgid(0):          # never our own group
        return False
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return False
    return True


def _claude_stop(session):
    """`claude stop <job>` for a session the roster knows. (done, message)."""
    job = session.get("jobId") or ""
    binary = shutil.which("claude")
    if not job or not binary:
        return False, ""
    try:
        proc = subprocess.run([binary, "stop", job], capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:120]
    if proc.returncode == 0:
        return True, "stopped %s; `claude attach %s` brings it back" % (
            session.get("name") or job, job)
    return False, (proc.stderr or proc.stdout or "").strip()[:160]


def close_session(session):
    """Returns (closed, message). closed is True when the session is gone
    afterwards, whether it stopped politely or had to be forced."""
    name = session.get("name") or "session"
    pid, why = pid_for(session)
    if session.get("provider") == "claude" and session.get("jobId"):
        done, message = _claude_stop(session)
        if done:
            # `stop` returns as soon as the request is accepted; give the
            # process a moment so the tile does not come straight back.
            deadline = time.time() + GRACE_S
            while pid and time.time() < deadline and _alive(pid):
                time.sleep(0.1)
            return True, message
    if not pid:
        return False, why
    if pid == os.getpid():
        return False, "that is the dashboard itself"
    if not _signal(pid, signal.SIGTERM):
        return not _alive(pid), "%s was already gone" % name
    deadline = time.time() + GRACE_S
    while time.time() < deadline:
        if not _alive(pid):
            return True, "closed %s" % name
        time.sleep(0.1)
    _signal(pid, signal.SIGKILL)
    time.sleep(0.2)
    if _alive(pid):
        return False, "%s would not close (pid %d)" % (name, pid)
    return True, "closed %s (it had to be forced)" % name
