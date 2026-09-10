"""Find the iTerm2 tab a session is *already* running in, and bring it forward.

The board's open-in-iTerm button has always opened a *new* window, even when
the session it points at is a live agent sitting in a tab you already have.
iTerm exposes each session's tty over AppleScript, and `ps` says which tty each
agent process is attached to, so the two can be matched without asking iTerm
for anything but a read.

This runs on a click, never on the snapshot loop: the inventory costs about
780ms of Apple Events, which is four times a whole board rebuild.
"""

import os
import re
import subprocess

# What a running session of each provider looks like in the process table.
_PATTERNS = {
    "claude": re.compile(r"(^|/)claude(\s|$)"),
    "codex": re.compile(r"(^|/)codex(\s|$)"),
    "antigravity": re.compile(r"(^|/)(agy|antigravity)(\s|$)"),
}
_NOT_SESSION = re.compile(r"--mcp|mcp-server|language-server|\.vscode|Helper")

_INVENTORY = """
tell application "iTerm"
  set out to ""
  repeat with w in windows
    set ti to 0
    repeat with t in tabs of w
      set ti to ti + 1
      repeat with s in sessions of t
        set out to out & (id of w as text) & "\t" & (ti as text) & "\t" & ¬
          (id of s) & "\t" & (tty of s) & "\t" & (name of s) & linefeed
      end repeat
    end repeat
  end repeat
  return out
end tell
"""


def _osascript(source, timeout=8):
    try:
        proc = subprocess.run(["osascript", "-"], input=source, capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def inventory():
    """Every open iTerm session: window id, tab index, session id, tty, name."""
    out = _osascript(_INVENTORY)
    if not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            rows.append({"window": parts[0], "tab": parts[1], "session": parts[2],
                         "tty": parts[3], "name": parts[4]})
    return rows


def _agent_ttys():
    """tty path -> list of (provider, pid) for agent processes on that tty."""
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,tty=,args="], capture_output=True,
                             text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, tty, args = parts
        if tty in ("??", "-") or _NOT_SESSION.search(args):
            continue
        head = args.split()[0]
        for provider, pattern in _PATTERNS.items():
            if pattern.search(head) or pattern.search(args.split(" ")[0]):
                found.setdefault("/dev/" + tty, []).append((provider, int(pid)))
                break
    return found


def _cwd(pid):
    try:
        proc = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                              capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in proc.stdout.splitlines():
        if line.startswith("n/"):
            return line[1:]
    return ""


def find(session):
    """The open iTerm session running this dashboard session, if there is one."""
    want_cwd = (session.get("cwd") or "").rstrip("/")
    want_provider = session.get("provider")
    if not want_cwd:
        return None
    by_tty = _agent_ttys()
    if not by_tty:
        return None
    rows = inventory()
    fallback = None
    for row in rows:
        for provider, pid in by_tty.get(row["tty"], []):
            if provider != want_provider:
                continue
            if _cwd(pid).rstrip("/") == want_cwd:
                return dict(row, pid=pid, provider=provider)
            fallback = fallback or dict(row, pid=pid, provider=provider)
    return None


def focus(match):
    """Bring an existing tab forward. Reading 3 done the only way it works."""
    source = (
        'tell application "iTerm"\n'
        '  repeat with w in windows\n'
        '    repeat with t in tabs of w\n'
        '      repeat with s in sessions of t\n'
        '        if (id of s) is "%s" then\n'
        '          select s\n'
        '          select t\n'
        '          select w\n'
        '          activate\n'
        '          return "ok"\n'
        '        end if\n'
        '      end repeat\n'
        '    end repeat\n'
        '  end repeat\n'
        '  return "gone"\n'
        'end tell\n' % match["session"].replace('"', "")
    )
    out = _osascript(source)
    return bool(out) and out.strip() == "ok"


def available():
    return os.path.isdir("/Applications/iTerm.app")
