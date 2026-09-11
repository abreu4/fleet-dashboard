"""Open a session where you can actually work on it.

The page never sends a command: it sends a session id and a target, and the
command is assembled here from the snapshot. Nothing the browser types can
reach a shell.
"""

import io
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import time

import iterm_link

ITERM = "/Applications/iTerm.app"
VSCODE_BINS = ("/usr/local/bin/code", "/opt/homebrew/bin/code",
               "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")

# How each agent comes back to a conversation. The first form targets one exact
# session; the second continues the most recent conversation in this directory,
# which is all that is left when the id cannot be used. Antigravity was missing
# from here entirely, so every `agy` tile opened a bare shell whatever its state.
# Adding a fourth agent is one line.
_RESUME = {
    "claude":      ("claude --resume %s",     "claude --continue"),
    "codex":       ("codex resume %s",         "codex resume --last"),
    "antigravity": ("agy --conversation %s",   "agy --continue"),
}

# A fresh conversation, by agent. The page picks a key from this table, never
# a string of its own; "shell" is a shell and nothing else.
FRESH = {"shell": "", "claude": "claude", "antigravity": "agy", "codex": "codex"}

# Every launch writes a script, and a script has to outlive the click, so
# nothing can delete it at the time. They went to $TMPDIR with delete=False and
# stayed there forever. One directory per launch under a root we own instead,
# swept on the way past the next one.
_LAUNCH_ROOT = os.path.join(tempfile.gettempdir(), "fleet-launch")


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
    forms = _RESUME.get(kind or "")
    return (forms[0] % shlex.quote(sid)) if forms else ""


def suggest_for(session, fell_back=False):
    """The command to leave sitting ON the prompt, unrun.

    command_for() refuses to start anything for a live session, because that
    would be a second copy of it, and it had nothing at all to say about
    Antigravity. Both cases still have exactly one obvious next move, and having
    to remember which of three CLIs spells it which way -- and type it -- is the
    actual complaint. Offering it unexecuted keeps the safety property intact:
    the decision is still a keypress, made by someone who can see the screen.
    """
    if command_for(session, fell_back):
        return ""                      # it is being run; nothing to suggest
    forms = _RESUME.get(session.get("resume") or "")
    if not forms:
        return ""
    sid = session.get("sessionId") or ""
    # A live session is mid-turn and a moved worktree cannot resolve its id, so
    # neither may target one: --continue picks up the most recent conversation
    # here, which is the one being looked at.
    if session.get("state") == "running" or not sid or fell_back:
        return forms[1]
    return forms[0] % shlex.quote(sid)


def _sweep_launches(keep_seconds=6 * 3600):
    """Drop launch dirs nothing can still be using.

    Sweeping on the way past the next launch, rather than at exit, is what keeps
    this safe: the shell a dir belongs to may still be open hours later, and
    pulling its ZDOTDIR out from under it would break its next new tab.
    """
    cutoff = time.time() - keep_seconds
    try:
        names = os.listdir(_LAUNCH_ROOT)
    except OSError:
        return
    for name in names:
        path = os.path.join(_LAUNCH_ROOT, name)
        try:
            if os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


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


def _launch_script(cwd, command, note="", suggest=""):
    """A throwaway script beats quoting a command through AppleScript."""
    _sweep_launches()
    os.makedirs(_LAUNCH_ROOT, exist_ok=True)
    home = tempfile.mkdtemp(prefix="l-", dir=_LAUNCH_ROOT)

    body = "#!/bin/zsh -l\ncd %s || exit 1\n" % shlex.quote(cwd)
    if note:
        # Say it in the window too. A message that only reaches the toast is
        # gone by the time anyone reads the shell they were given.
        body += "print -P '%%F{yellow}%s%%f'\n" % note.replace("'", "")
    if command:
        body += "print -P '%%F{cyan}%s%%f'\n%s\n" % (command.replace("'", ""), command)
        body += "exec $SHELL -l\n"
    elif suggest:
        # The command is left on the prompt rather than run. `print -z` pushes a
        # line into the editor buffer but cannot survive an exec, so the
        # interactive shell is started against a ZDOTDIR of our own that sources
        # the real dotfiles first and then pushes the line. One return runs it.
        with io.open(os.path.join(home, ".zshenv"), "w", encoding="utf8") as fh:
            fh.write('[ -f "$HOME/.zshenv" ] && source "$HOME/.zshenv"\n')
        with io.open(os.path.join(home, ".zshrc"), "w", encoding="utf8") as fh:
            fh.write('[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc"\n'
                     # so tabs opened off this shell are ordinary shells again
                     "unset ZDOTDIR\n"
                     "print -z %s\n" % shlex.quote(suggest))
        body += "print -P '%%F{cyan}press return to run:%%f' %s\n" % shlex.quote(suggest)
        body += "export ZDOTDIR=%s\nexec zsh -i\n" % shlex.quote(home)
    else:
        # %%F/%%f, not %F/%f: these are zsh prompt escapes and have to survive
        # Python's own %-formatting, which reads a bare %F as "a float goes
        # here" and raises on a string. This is why "shell in iTerm" failed for
        # every running session while "resume in iTerm" worked.
        body += "print -P '%%F{cyan}shell at%%f' %s\n" % shlex.quote(cwd)
        body += "exec $SHELL -l\n"

    path = os.path.join(home, "open.command")
    with io.open(path, "w", encoding="utf8") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def fresh_script(cwd, agent):
    """A new agent (or plain shell) in a directory the user picked.

    The directory must exist and sit inside $HOME; the agent must be a key of
    FRESH. Both are checked here, so the sheet's + button can offer any folder
    the board knows about without the page ever naming a command.
    """
    home = os.path.realpath(os.path.expanduser("~"))
    real = os.path.realpath(os.path.expanduser(cwd or home))
    if not os.path.isdir(real) or not (real == home or real.startswith(home + os.sep)):
        return None, "that folder is not under your home directory"
    if agent not in FRESH:
        return None, "unknown agent"
    return _launch_script(real, FRESH[agent]), real


def launch_script(session):
    """The script a terminal should exec: the same assembly the buttons use.

    The embedded terminal runs this too, so what a pty starts on is decided
    here from the snapshot -- the page chooses a session, never a command.
    Rebuilt against working_directory()/command_for(session, moved), which the
    live tree moved to after this patch was written.
    """
    cwd, moved = working_directory(session)
    return _launch_script(cwd, command_for(session, moved),
                          suggest=suggest_for(session, moved))


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
    script = _launch_script(cwd, command, note,
                            suggest=suggest_for(session, moved))
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
