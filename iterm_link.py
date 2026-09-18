"""Find the terminal tab a session is *already* running in, and bring it forward.

The board's open-in-iTerm and open-in-Terminal buttons used to open a *new*
window every time, even when the session they point at is a live agent sitting
in a tab you already have -- a second window that, for an interactive session,
cannot even attach. iTerm and Terminal each expose the tty of every tab over
AppleScript, and `ps` says which tty each process is on, so the session's pid
leads straight to its tab without asking either app for anything but a read.

Matching is by pid, not by folder: two sessions in one repo are the rule on
this machine, not the exception, and a folder match would bring forward
whichever tab AppleScript listed first.

This runs on a click, never on the snapshot loop: an inventory costs a few
hundred milliseconds of Apple Events, several times a whole board rebuild.
Only apps that are running are asked -- `tell application` would launch one
that is not, and nobody clicking "iTerm" wants Terminal to open.
"""

import subprocess

# Each app's inventory returns one tab per line: window id, tab index, the
# app's own handle for the tab (iTerm's session id; Terminal has none and
# is addressed by tty), the tty, and the tab's name.
_INVENTORY = {
    "iterm": """
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
""",
    "terminal": """
tell application "Terminal"
  set out to ""
  repeat with w in windows
    set ti to 0
    repeat with t in tabs of w
      set ti to ti + 1
      set out to out & (id of w as text) & "\t" & (ti as text) & "\t" & ¬
        "" & "\t" & (tty of t) & "\t" & (custom title of t) & linefeed
    end repeat
  end repeat
  return out
end tell
""",
}

# Reading 3 done the only way it works: select session, tab, window, in that
# order, then activate. Terminal's tab is addressed by its tty.
_FOCUS = {
    "iterm": """
tell application "iTerm"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if (id of s) is "%s" then
          select s
          select t
          select w
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
  return "gone"
end tell
""",
    "terminal": """
tell application "Terminal"
  repeat with w in windows
    repeat with t in tabs of w
      if (tty of t) is "%s" then
        set selected of t to true
        set index of w to 1
        activate
        return "ok"
      end if
    end repeat
  end repeat
  return "gone"
end tell
""",
}

# What each app's process is called in the process table.
_PROCESS = {"iterm": "iTerm2", "terminal": "Terminal"}
LABEL = {"iterm": "iTerm", "terminal": "Terminal"}


def _osascript(source, timeout=8):
    try:
        proc = subprocess.run(["osascript", "-"], input=source, capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _ps(columns):
    try:
        return subprocess.run(["ps", "-Ao", columns], capture_output=True,
                              text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def running_apps(ps_out=None):
    """Which of the two terminal apps are open right now."""
    names = {line.strip().rsplit("/", 1)[-1] for line in (ps_out or _ps("comm=")).splitlines()}
    return [app for app, proc in _PROCESS.items() if proc in names]


def inventory(app):
    """Every open tab of one app: window id, tab index, handle, tty, name."""
    out = _osascript(_INVENTORY[app])
    if not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            rows.append({"app": app, "window": parts[0], "tab": parts[1],
                         "session": parts[2], "tty": parts[3], "name": parts[4]})
    return rows


def tty_of(pid, ps_out=None):
    """The controlling tty of one process, as a /dev path, or None."""
    for line in (ps_out or _ps("pid=,tty=")).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(pid):
            return None if parts[1] in ("??", "-") else "/dev/" + parts[1]
    return None


def match(tty, rows):
    """The tab on this tty among the inventoried rows, if any."""
    for row in rows:
        if row["tty"] == tty:
            return row
    return None


def find(session):
    """The open tab running this session's process, if there is one.

    A session with no live pid is running nowhere, so there is nothing to
    reveal. One whose pid is on a tty no app claims -- a daemon's background
    job, or a pty the board itself opened -- is not in a window either.
    """
    try:
        pid = int(session.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if not pid:
        return None
    tty = tty_of(pid)
    if not tty:
        return None
    for app in running_apps():
        hit = match(tty, inventory(app))
        if hit:
            return dict(hit, pid=pid)
    return None


def focus(hit):
    """Bring an existing tab forward."""
    handle = hit["session"] if hit["app"] == "iterm" else hit["tty"]
    out = _osascript(_FOCUS[hit["app"]] % handle.replace('"', ""))
    return bool(out) and out.strip() == "ok"
