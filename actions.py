"""Open a session where you can actually work on it.

The page never sends a command: it sends a session id and a target, and the
command is assembled here from the snapshot. Nothing the browser types can
reach a shell.
"""

import os
import shlex
import stat
import subprocess
import tempfile

import iterm_link

ITERM = "/Applications/iTerm.app"
VSCODE_BINS = ("/usr/local/bin/code", "/opt/homebrew/bin/code",
               "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")


def available():
    return {
        "iterm": os.path.isdir(ITERM),
        "terminal": True,
        "vscode": any(os.path.exists(p) for p in VSCODE_BINS),
    }


def _vscode_bin():
    for path in VSCODE_BINS:
        if os.path.exists(path):
            return path
    return None


def command_for(session, fell_back=False):
    """The shell line a terminal should land on, or '' for a plain shell."""
    kind = session.get("resume")
    sid = session.get("sessionId") or ""
    # Resuming a session that is mid-turn would start a second copy of it, so
    # a live session only ever gets a shell in the right directory.
    if session.get("state") == "running" or not sid:
        return ""
    # Claude scopes a transcript by the directory it ran in: the session lives
    # at ~/.claude/projects/<encoded cwd>/<id>.jsonl. Once the recorded cwd is
    # gone and we have landed somewhere else, `claude --resume <id>` looks under
    # the NEW directory's encoding and cannot find it -- verified against
    # base-remota, whose transcript sits under the worktree encoding and is
    # absent from the project root's. Offering the command anyway is exactly
    # what made a tile click report success and then fail inside the window.
    if fell_back and kind == "claude":
        return ""
    if kind == "claude":
        return "claude --resume %s" % shlex.quote(sid)
    if kind == "codex":
        return "codex resume %s" % shlex.quote(sid)
    return ""


def working_directory(session):
    """Return a useful existing directory, even after a worktree was removed."""
    requested = session.get("cwd") or os.path.expanduser("~")
    if os.path.isdir(requested):
        return requested, False

    # A completed Claude worker commonly outlives its disposable worktree. Its
    # project checkout is a better landing point than ~/.claude/worktrees.
    marker = os.sep + ".claude" + os.sep + "worktrees" + os.sep
    if marker in requested:
        project = requested.split(marker, 1)[0]
        if os.path.isdir(project):
            return project, True

    candidate = os.path.dirname(requested)
    while candidate and candidate != os.path.dirname(candidate):
        if os.path.isdir(candidate):
            return candidate, True
        candidate = os.path.dirname(candidate)
    return os.path.expanduser("~"), True


def _launch_script(cwd, command, note=""):
    """A throwaway script beats quoting a command through AppleScript."""
    body = "#!/bin/zsh -l\ncd %s || exit 1\n" % shlex.quote(cwd)
    if note:
        # Say it in the window too. A message that only reaches the toast is
        # gone by the time anyone reads the shell they were given.
        body += "print -P '%%F{yellow}%s%%f'\n" % note.replace("'", "")
    if command:
        body += "print -P '%%F{cyan}%s%%f'\n%s\n" % (command.replace("'", ""), command)
    else:
        # %%F/%%f, not %F/%f: these are zsh prompt escapes and have to survive
        # Python's own %-formatting, which reads a bare %F as "a float goes
        # here" and raises on a string. This is why "shell in iTerm" failed for
        # every running session while "resume in iTerm" worked.
        body += "print -P '%%F{cyan}shell at%%f' %s\n" % shlex.quote(cwd)
    body += "exec $SHELL -l\n"
    handle = tempfile.NamedTemporaryFile("w", suffix=".command", delete=False)
    handle.write(body)
    handle.close()
    os.chmod(handle.name, os.stat(handle.name).st_mode | stat.S_IXUSR)
    return handle.name


def launch_script(session):
    """The script a terminal should exec: the same assembly the buttons use.

    The embedded terminal runs this too, so what a pty starts on is decided
    here from the snapshot -- the page chooses a session, never a command.
    Rebuilt against working_directory()/command_for(session, moved), which the
    live tree moved to after this patch was written.
    """
    cwd, moved = working_directory(session)
    return _launch_script(cwd, command_for(session, moved))


def open_session(session, target):
    cwd, moved = working_directory(session)
    where = " (worktree gone; using %s)" % cwd if moved else ""

    if target == "reveal":
        # The tab this session is already living in, if it has one. Falls
        # through to opening a new window when it does not.
        match = iterm_link.find(session)
        if match and iterm_link.focus(match):
            return True, "focused tab %s in iTerm" % match["tab"]
        target = "iterm"

    if target == "vscode":
        binary = _vscode_bin()
        if not binary:
            return False, "the `code` command is not installed"
        subprocess.Popen([binary, cwd])
        return True, "opened %s in VS Code%s" % (os.path.basename(cwd), where)

    command = command_for(session, moved)
    note = ""
    if moved and not command and session.get("resume") == "claude" \
            and session.get("sessionId") and session.get("state") != "running":
        note = ("the recorded worktree is gone, so this session cannot be "
                "resumed from here; this is a shell in the project root")
        where += "; cannot resume, worktree removed"
    script = _launch_script(cwd, command, note)
    if target == "iterm" and os.path.isdir(ITERM):
        # Opening a .command file through LaunchServices is both simpler and
        # more reliable than scripting iTerm's window API. It also avoids the
        # per-process macOS Automation permission that made browser clicks look
        # successful while no usable window appeared.
        proc = subprocess.run(["open", "-a", "iTerm", script],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            return True, "opened in iTerm%s" % where
        # If LaunchServices cannot hand the file to iTerm, keep the action useful.
        fallback = subprocess.run(["open", "-a", "Terminal", script],
                                  capture_output=True, text=True)
        if fallback.returncode == 0:
            return True, "iTerm refused; opened Terminal instead%s" % where
        return False, "could not open iTerm or Terminal"

    proc = subprocess.run(["open", "-a", "Terminal", script],
                          capture_output=True, text=True)
    return (proc.returncode == 0,
            ("opened in Terminal%s" % where) if proc.returncode == 0
            else "could not open Terminal")
