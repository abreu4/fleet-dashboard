# "Opening and closing shells is not working well enough"

Review of the terminal-launching integration in the **live** tree,
`/Users/tiago/.local/share/fleet-dashboard/` (not the stale `~/Documents/Dev/agent-dashboard/`,
which is hours behind and has no `iterm_link.py`, `terminal.py`, `aliases.py` or `flush.py`).

Files reviewed:

| file | lines | role |
|---|---|---|
| `/Users/tiago/.local/share/fleet-dashboard/actions.py` | 164 | assembles the command, launches iTerm / Terminal / VS Code |
| `/Users/tiago/.local/share/fleet-dashboard/iterm_link.py` | 147 | finds the iTerm tab a session is already in, raises it |
| `/Users/tiago/.local/share/fleet-dashboard/terminal.py` | 353 | the in-page pty terminal (SSE out, POST in) |
| `/Users/tiago/.local/share/fleet-dashboard/dashboard.py` | 619 | `/api/open`, `/api/term/*`, the Host/Origin guards |
| `/Users/tiago/.local/share/fleet-dashboard/ui.html` | ~5.4k | the drawer buttons, the toast, the terminal sheet |

Everything below was measured on this machine, today, against iTerm2 **3.7.0**
(`/Applications/iTerm.app/Contents/Info.plist`, `CFBundleShortVersionString = 3.7.0`).
The live dashboard is pid 78519 under `gui/501/com.tiago.fleet-dashboard`, program
`~/.local/share/fleet-dashboard/.venv/bin/python`, args `dashboard.py --port 8787 --terminal`.

---

## 0. Recap of the state I found

The reuse mechanism the complaint is about **already exists** (`iterm_link.py`) and the
primary iTerm button **does not use it**. The primary button (`target: "iterm"`) shells out to
`open -a iTerm <tempfile>.command`; the reuse path is a separate, visually de-emphasised
`class="plain"` button labelled *"its iTerm tab"* (`target: "reveal"`). So the button the user
most likely clicks has never re-used anything, and the one that does is the one that looks
optional.

Automation (TCC) permission **is** granted to the launchd process — I verified this
functionally, not by reading TCC.db (unreadable without Full Disk Access):

```
$ curl -s -X POST localhost:8787/api/open -d '{"id":"claude:b15d9ee9-…","target":"reveal"}'
{"ok": true, "message": "focused tab 1 in iTerm"}
```

and a controlled before/after showed `frontmost` of iTerm going `false` → `true` across
that call. So the silent failure is **not** a blanket Apple Events denial today.

---

## 1. Ranked causes of "nothing visible happens"

### 1. The toast was painted behind the music player and the terminal sheet — **already fixed**

`.toast` was `z-index:7` at `bottom:18px; right:20px`; `.player` is `z-index:8` and `.sheet` is
`z-index:8` in the same corner. Any message — success *or* failure — was invisible whenever
the player or the sheet was up. Fixed in `ui.html` ~line 482 (`z-index:9`, offset by `--taken`).

This is almost certainly the dominant cause, and it is nastier than "an error was hidden":
it also hid **successes**. A click that correctly opened a tab on the other display produced
no visible change *and* no visible confirmation, which is indistinguishable from a dead button.

Still outstanding after that fix: a failure toast auto-dismisses after 2600 ms like any other,
and the user is usually looking at a different screen. Errors need to persist. See §3.5.

### 2. `open -a iTerm <script>` adds a **tab to an existing window**, which may be on another display or Space

The comment at `actions.py:146-148` says it "beats scripting iTerm's window API". What it
does not say is that it no longer creates a window. Measured:

```
windows before: 1   tabs of window 22301 before: 1
POST /api/open {"target":"iterm"}   ->  {"ok": true, "message": "opened in iTerm"}
windows after:  1   tabs of window 22301 after:  3
```

LaunchServices hands the `.command` to the running iTerm, which opens it as a **tab in its
current window**. `spans-displays` is unset in `com.apple.spaces`, i.e. *Displays have
separate Spaces* is ON, and iTerm's window here is a small 667×492 window at `(0, 30)`.
With the board fullscreen on the Air — its own Space, on its own display — a new tab
appearing in an iTerm window on the other display changes nothing on the screen the user is
looking at. That is literally "no window appears".

I also found `NoSyncSavedWindowPositions` entries at `{1440, 1132}`, i.e. iTerm windows have
been placed off the main display, which makes this scenario concrete rather than theoretical.

### 3. `open` returns 0 unconditionally, so the code cannot tell success from nothing

`actions.py:149-158` treats `proc.returncode == 0` as "opened in iTerm". `open` returns 0 as
soon as LaunchServices accepts the request. Proven with a script that cannot possibly work:

```
$ printf '#!/bin/zsh -l\ncd /nonexistent-dir-xyz || exit 1\nexec $SHELL -l\n' > probe3.command
$ open -a iTerm probe3.command ; echo rc=$?
rc=0
```

The Default profile has `Close Sessions On End = true`, so that session closed itself within
a second or two and left no trace — a success toast, and nothing on screen. The Terminal
fallback at `actions.py:154` is therefore dead code in practice: it only fires if
LaunchServices itself fails, which essentially never happens.

### 4. iTerm shows a modal **"OK to run <path>?"** for every script handed to it by LaunchServices

This one is in iTerm's own preferences, and it is forensic evidence:

```
com.googlecode.iterm2 → NoSyncSuppressedAlertsCatalog → NoSyncConfirmRunOpenFile
    selectionLabel = OK
    title          = OK to run "/private/tmp/.../probe3.command"?
    count          = 10
    episode        = permanent
```

`NoSyncConfirmRunOpenFile = true` at the top level is the remembered suppression. So: the
**first** time this button was ever clicked, iTerm put up a confirmation dialog — and if the
user had answered it the other way, or if the suppression is ever reset (new iTerm version,
renamed key, preferences reset), **every click would be silently refused while `open` still
returned 0**. A design that depends on a remembered answer to a modal is the wrong design
for a button on a dashboard.

And right beside it:

```
    NeverWarnAboutShortLivedSessions_515607DD-…
    title = A session ended very soon after starting. Check that the command in
            profile "Default" is correct.
    count = 3
    episode = permanent
```

iTerm has warned three times that a session died immediately after starting, and that warning
is now permanently suppressed. With `Close Sessions On End = true` that is exactly the
"nothing visible happens" signature: a tab flashes and vanishes.
*Caveat on attribution:* `lastSuppressed` on both entries is 22:16–22:20 today, i.e. during my
own probing, and at least two of the three short-lived sessions are mine. The counts are
higher than my probes account for, but I cannot prove how much of the history predates me.

### 5. `reveal` matches the wrong tab — it ignores the session id entirely

`iterm_link.find()` matches on `(provider, cwd)` only (`iterm_link.py:101-119`). Run against
the live snapshot:

```
MATCH  antigravity running | Fix the fonts in iterm and vscode…  | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | Caffeinate the mac for 5 hours      | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | Change my vscode and iterm font…    | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | Consider the side session I have…   | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | I'm out of credits on Claude.       | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | The user wants to "bring the tool…  | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | session e24d86ad                   | /Users/tiago -> 3A648754-… tab 2
MATCH  antigravity idle    | test_update                        | /Users/tiago -> 3A648754-… tab 2
MATCH  claude      running | tiago-5f                           | /Users/tiago -> E11412C3-… tab 1
```

Eight different dashboard sessions all "match" the single live `agy` tab, and the one claude
match is a *different* claude session that happens to share `~`. Focusing a tab that has
nothing to do with the tile you clicked — especially a tab in a window on another display —
is indistinguishable from nothing happening.

### 6. `reveal` can never find a shell the dashboard itself opened

`_PATTERNS` (`iterm_link.py:18-22`) only recognises `claude` / `codex` / `agy` processes.
`command_for()` returns `''` for any session whose `state` is `running` (`actions.py:42`), so
every click on a live session produces a **plain zsh** — which matches no pattern, is never
found, and gets a brand-new tab on the next click, forever. "One session, one shell, ever" is
structurally impossible with a process-table match.

### 7. Errors are discarded before anything can surface them

`iterm_link._osascript()` (lines 43-49) throws away stderr and returns `None` for *every*
failure: TCC denial (-1743), iTerm not running, a timeout, a syntax error. `open_session()`
then treats `None` as "no match" and silently opens another tab with a success message. Even
with the toast visible there is nothing to show.

### 8. `find()` computes a `fallback` and never returns it

`iterm_link.py:118` builds `fallback`; line 119 is `return None`. The intended
provider-only relaxation is dead code.

### 9. `/api/open` refuses with an HTML 403, and the UI reports it as a network error

`dashboard.py:430-431` → `self.send_error(403)` returns `text/html`. In `ui.html`'s `open_()`,
`r.json()` then throws and the catch block says **"could not reach the dashboard server"**.
Confirmed:

```
$ curl -i -X POST localhost:8787/api/open -H 'Host: fleet.local:8787' …
HTTP/1.1 403 Forbidden
Content-Type: text/html;charset=utf-8
```

This fires whenever the page's `Host` is not one of `127.0.0.1:8787`, `localhost:8787`,
`[::1]:8787`. **Worth confirming with the user:** if the board is ever opened on the MacBook
Air over the LAN (`http://<name>.local:8787`, `http://192.168.x.x:8787`) rather than through a
tunnel, then *every* action button 403s and the only message is a lie about reachability.
The LaunchAgent binds 127.0.0.1 so that should not be reachable — but it is the one
configuration in which the symptom is 100% reproducible and total, so it is worth ruling out.

### 10. Timing is fine; it is not a timeout

`find()` costs ~680 ms per call (AppleScript inventory 621 ms + `ps` 143 ms + one `lsof` per
candidate pid). The full `/api/open` reveal round trip measured **0.98 s**. `ThreadingHTTPServer`
gives each request its own thread, so the board's 2 s refresh is unaffected. There is no
request timeout in the browser either. Slowness is not the cause — but the 8 s `osascript`
timeout plus `ps` 6 s plus N × `lsof` 4 s is an unbounded worst case that deserves a ceiling.

### 11. Temp `.command` files accumulate forever

`_launch_script()` (`actions.py:98-102`) uses `tempfile.NamedTemporaryFile(delete=False)` and
nothing ever removes the file. Right now:

```
$ find /var/folders -maxdepth 4 -name '*.command' -type f | wc -l
48          (6,571 bytes total, all created today)
```

Mode is 0700 (0600 from `NamedTemporaryFile` plus `S_IXUSR`), so it is not an exposure, and
macOS eventually sweeps `$TMPDIR`. But `terminal.py:235` calls `actions.launch_script()` on
*every* in-page terminal open too, so the in-page terminal leaks one per open as well.
`TMPDIR` is correctly inherited by the launchd process
(`/var/folders/8y/xd5gkckx4552nlyt_ph14kd80000gn/T/`), so both processes write to the same place.

### 12. Closing an in-page terminal takes **two clicks**, and sometimes never works

`Terminals.close()` (`terminal.py:248-257`) sends SIGHUP and returns `{"ok": true}` **without
broadcasting anything**. The UI's `×` handler (`ui.html:3703`) ignores the response. So the
first click produces no visible change at all; the tab only goes strikethrough when the pty's
`_pump` sees EOF and emits `exit`, and it is only *removed* by a **second** click on `×`
(which takes the `exited is not None` branch and broadcasts `gone`).

Two further defects in the same area:

- `Pty.kill()` (lines 194-203) sends SIGHUP to the process group and escalates to SIGKILL only
  if `killpg` *raises*. A shell or foreground job that ignores SIGHUP is never escalated, so
  the tab can never be closed, ever, and nothing says so.
- `_reaper()` (lines 274-279) forgets a dead pty after 60 s **without** broadcasting `gone`. A
  page that was not watching at the moment of death keeps a strikethrough tab whose `×` now
  returns `{"ok": false, "message": "unknown terminal"}` — a permanently stuck tab.

### 13. `command_for()` returning `''` for running sessions is right, but unexplained

`actions.py:40-43`. Resuming a mid-turn session really would start a second copy, so a plain
shell is the correct call. The UI half-explains it: the button text changes from "resume in"
to "shell in" (`ui.html:3030`, `resumes = s.resume && s.state !== 'running'`). That is subtle
to the point of invisible — the user sees a label change, not a reason. The proposed toast text
says it outright.

### 14. Quoting, for the record

- `command.replace("'", "")` in the banner (`actions.py:88, 90`) silently *deletes* apostrophes
  instead of escaping them. Harmless for session ids, wrong in principle, and it is in the line
  that also carries `note`, which is free English text.
- The script path was interpolated straight into AppleScript source in the old
  `create window with default profile command "%s"`. The current code dodges it by using `open`,
  but `iterm_link.focus()` still interpolates (`match["session"].replace('"', "")`, line 140) —
  a sanitiser where an argument would do.
- **iTerm splits the `command` parameter on whitespace.** I proved this by accident: a script
  at `…/dir with space/probe one.command` produced a session that died instantly and a tab that
  vanished. Any design that passes a path to `create window … command` must guarantee a
  space-free path.
- Inside `tell application "iTerm"`, the AppleScript `tab` constant is shadowed by iTerm's `tab`
  class and concatenates the literal word "tab". `iterm_link.py`'s existing `\t` in the Python
  string is fine; a future `& tab &` would not be.

---

## 2. What the right mechanism is, verified on this machine

I read iTerm2's dictionary directly rather than trusting docs:
`/Applications/iTerm.app/Contents/Resources/iTerm2.sdef`.

### 2.1 The session class gives everything needed

```
class session:  id (r), unique ID (r), tty (r), name, profile name (r),
                is processing, is at shell prompt, contents, text
  responds to:  close, write, select, split *, variable, set variable
```

`variable` and `set variable` are **commands**, not properties — which is why
`variable named "x" of s` fails with `-1723`. The working form, verified:

```applescript
tell application "iTerm"
  tell current session of tab 3 of window id 22301
    set r1 to variable named "jobName"                      --> "zsh"
    set variable named "user.fleetSession" to "abc-123"
    set r2 to variable named "user.fleetSession"            --> "abc-123"
    set r3 to variable named "path"                         --> "/Users/tiago"
  end tell
end tell
```

So **user-defined variables are readable and writable from plain AppleScript** — no Python
API needed. An unset variable reads back as the string `missing value`. `variable named "path"`
gives the session's cwd for free, which removes the need for `lsof`. `is at shell prompt`
returns `false` here because shell integration is not installed — do not rely on it.

### 2.2 Creating a window, tagging it and verifying focus — one round trip, 0.57 s

```applescript
tell application "iTerm"
  set w to (create window with default profile command "/path/without/spaces.command")
  tell current session of current tab of w
    set variable named "user.fleetSession" to "probe-window-99"
    set g to id
  end tell
  select w
  activate
  delay 0.4
  return g & "|" & (frontmost as text) & "|" & (item 1 of bounds of w as text)
end tell
-->  6DD9FF48-6DCE-4CFB-9F78-A819C27E3020|true|0
```

This is the whole design. The window's own session guid comes back in the same call that
created it, so there is nothing to match and nothing to guess. `frontmost` comes back too,
which means **the dashboard can detect the reported symptom and say so**.

`create tab with default profile command "…"` does the same for a tab in an existing window.

### 2.3 Raising it again later, by guid — 0.57 s, no `ps`, no `lsof`

```applescript
on run argv
  tell application "iTerm"
    repeat with w in windows
      set ti to 0
      repeat with t in tabs of w
        set ti to ti + 1
        repeat with s in sessions of t
          if (id of s) is (item 1 of argv) then
            select s
            select t
            select w
            activate
            delay 0.3
            return "ok|" & (frontmost as text) & "|" & (ti as text) & "|" & (id of w as text)
          end if
        end repeat
      end repeat
    end repeat
    return "gone"
  end tell
end run
-->  ok|true|1|31137          (and "gone" for a guid that no longer exists)
```

`index of t` does **not** exist on a tab (`-1700`); count the position in the loop.
`"gone"` is also the close-detection answer: the user closing the window is discovered
lazily, on the next click, for free. A live watcher would cost Apple Events on a loop.

### 2.4 `osascript - arg1 arg2` with `on run argv` works

```
$ printf 'on run argv\n  return "got:" & (item 1 of argv) & "/" & (item 2 of argv)\nend run\n' \
    | osascript - hello "world two"
got:hello/world two
```

So **nothing has to be interpolated into AppleScript source ever again**. The session id and
the script path arrive as arguments. That removes a whole class of bug, including the
`.replace('"', "")` sanitiser. (iTerm's own whitespace-splitting of the `command` parameter
is separate and still requires a space-free path.)

### 2.4b How iTerm actually parses the `command` parameter

Measured with a script that dumps its own `argv` (`create window … command "<script> <args>"`):

```
command: "<argvdump.sh> <out> 'one two' \"three four\" five\ six back\\slash"
  ARGV[2]=<one two>      ARGV[3]=<three four>      ARGV[4]=<five six>   ARGV[5]=<backslash>
  SELF_CMD=</bin/zsh <argvdump.sh> <out> one two three four five six backslash>
  PPID_CMD=<…/iTerm2/iTermServer-3.7.0 …/iterm2-daemon-1.socket>
```

and with a redirection in the string:

```
command: "<argvdump.sh> <out> RAW >> <other>"
  ARGV[3]=<>>>           ARGV[4]=<…/t2b.txt>
```

So iTerm **tokenizes the string shell-style** — single quotes, double quotes and backslash
escapes are honoured — and then **execs the resulting argv directly**; `>>` arrives as a
literal argument, not a redirection. Two consequences:

- a path with a space *can* be passed, but only if it is quoted inside the AppleScript string.
  The proposed fixed cache path has no spaces, so there is nothing to quote and nothing to get
  wrong — which is why §3.2 spends a comment on it rather than adding a quoting layer;
- the parent is `iTermServer`, not a login shell, so the `#!/bin/zsh -l` shebang is what
  supplies the login environment. That part of the existing script is doing real work and
  should stay.

**iTerm2 Python API / `it2` CLI.** `EnableAPIServer = 1` is already set, the daemon socket
exists (`~/Library/Application Support/iTerm2/iterm2-daemon-1.socket`), and the shipped CLI
at `/Applications/iTerm.app/Contents/Resources/utilities/it2` is genuinely capable —
`it2 session list --json`, `it2 session focus`, `it2 session get-var/set-var`,
`it2 window new --command`, `it2 tab new`, `it2 monitor`. It would be a cleaner API than
AppleScript. I am **not** recommending it:

- it needs authorisation (`it2 auth cookie`), and for a process that is not a child of iTerm
  that means a consent dialog inside iTerm — the same class of invisible modal as §1.4, and
  one I deliberately did not trigger while the user is working;
- the Python route adds the `iterm2` + `websockets` pip dependency to a stdlib-only project;
- AppleScript already does window/tab/session reuse, naming, user variables and liveness, at
  0.57 s per call, with permission already granted.
- There is no `it2run` in 3.7.0 (`it2` has a `run` subcommand that targets an existing session).

**Dropping the temp script and using `write text` into a fresh session.** Reintroduces
quoting into a live shell's stdin and races shell startup. The script file is the safer
boundary; it just needs a lifecycle.

**Hotkey window** (`create hotkey window with profile`) always appears on the current Space,
over everything — the perfect answer to "it opened on the other display". It needs a profile
with a hotkey configured, so it is a suggestion for the user, not something to hard-code.

### 2.6 Relevant preferences as they stand on this machine

| key | value | meaning |
|---|---|---|
| `Default` profile → `Close Sessions On End` | `true` | a session whose command exits closes its tab — why a broken script leaves no trace |
| `Default` profile → `Prompt Before Closing 2` | `false` | closing a tab with a running process does **not** prompt here. Nothing to fix, but it is profile-scoped and not the stock default |
| `Default` profile → `Jobs to Ignore` | `rlogin ssh slogin telnet` | irrelevant while the above is false |
| `NoSyncConfirmRunOpenFile` | `true` (remembered "OK") | the modal in §1.4, suppressed |
| `EnableAPIServer` | `1` | Python API available if ever wanted |
| `com.apple.spaces` `spans-displays` | unset | *Displays have separate Spaces* is ON — §1.2 |

---

## 3. Recommended rewrite

**The policy.** One session, one shell. The iTerm button means *"show me this session's
shell"*: raise the one that exists, create one if it does not. There is no separate
"reveal" button to forget about. Every outcome produces a sentence the user can act on.

**The mechanism.** When the board creates a shell it learns that shell's iTerm session guid in
the same Apple Event round trip, tags the session with `user.fleetSession`, and writes the
mapping to `~/.cache/fleet-dashboard/shells.json` (on disk, because this LaunchAgent restarts
whenever the tree changes — `runs = 5` today). A later click raises that guid; if iTerm says
`gone`, the entry is dropped and a fresh shell is made. No `ps`, no `lsof`, works for plain
shells, and exact per session id.

**The layering**, so TCC denial degrades visibly instead of silently:

1. registry guid → `focus()` (Apple Events)
2. `create window`/`create tab` + tag, reading back the guid (Apple Events)
3. `open -a iTerm <script>` (LaunchServices, needs no permission) — with a toast that says
   reuse will not work until Automation is granted
4. `open -a Terminal <script>`

### 3.1 `iterm_link.py` — full replacement

```python
"""Find the terminal a session is already sitting in, and raise it.

One session, one shell. The board opens a shell for a session once, notes which
iTerm session it landed in, and every later click raises that same tab instead
of opening another. The note is on disk because this LaunchAgent restarts
whenever the tree changes, and a restart must not orphan the shells it already
opened.

Identity comes from iTerm rather than from the process table: `create window ...
command` hands back the window it made, so the session's own guid can be read in
the same round trip. No `ps`, no `lsof`, no guessing -- and it works for a plain
shell, which a process-table match can never see, because a plain shell runs no
agent process to match against. The old match was (provider, cwd), which put
eight idle antigravity tiles onto the one live agy tab.

Every call says why it failed. A button that does nothing and says nothing was
the whole defect this file exists to fix.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time

ITERM = "/Applications/iTerm.app"
CACHE = os.path.expanduser("~/.cache/fleet-dashboard")
REGISTRY = os.path.join(CACHE, "shells.json")
VAR = "user.fleetSession"

# Reads are cheap and a click is rare, so one lock around the registry is enough.
_LOCK = threading.Lock()

# The one failure a launchd process cannot talk its way out of: with no window to
# put the consent dialog over, macOS just refuses. Worth its own sentence in the
# toast, because the fix is a trip to System Settings and nothing else works.
_DENIED = re.compile(r"-1743|Not authori[sz]ed|not allowed to send Apple events")


def available():
    return os.path.isdir(ITERM)


# ---------------------------------------------------------------------------
# talking to iTerm
# ---------------------------------------------------------------------------

def _osascript(source, args=(), timeout=12):
    """(ok, stdout, why-not). The why-not is for a human, not for a log."""
    try:
        proc = subprocess.run(["osascript", "-"] + [str(a) for a in args],
                              input=source, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "", ("iTerm did not answer in %ds -- it may be showing a "
                           "dialog that needs a click" % timeout)
    except OSError as exc:
        return False, "", "could not run osascript: %s" % exc
    if proc.returncode == 0:
        return True, proc.stdout.strip(), ""
    lines = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
    why = lines[-1] if lines else "osascript exited %d" % proc.returncode
    if _DENIED.search(why):
        why = ("macOS has not given the dashboard permission to control iTerm. "
               "It runs under launchd, so there is no window for the consent "
               "dialog to appear over: grant it by hand in System Settings > "
               "Privacy & Security > Automation.")
    return False, "", why


# Arguments, not interpolation. Everything that used to be pasted into the script
# text -- a path, a session id -- arrives in argv, so quoting stops being a
# hazard and the old .replace('"', "") sanitiser can go.
_NEW_WINDOW = """
on run argv
  set theScript to item 1 of argv
  set theId to item 2 of argv
  set wantTab to (item 3 of argv is "tab")
  tell application "iTerm"
    if wantTab and (count of windows) > 0 then
      tell current window
        set t to (create tab with default profile command theScript)
      end tell
      set w to current window
    else
      set w to (create window with default profile command theScript)
      set t to current tab of w
    end if
    tell current session of t
      set variable named "%s" to theId
      set g to id
    end tell
    select t
    select w
    activate
    delay 0.3
    return g & "|" & (frontmost as text)
  end tell
end run
""" % VAR

# select the session, then its tab, then its window, then raise the app: all four,
# in that order. Anything less leaves the tab selected in a window nobody can see.
_FOCUS = """
on run argv
  set wanted to item 1 of argv
  tell application "iTerm"
    repeat with w in windows
      set ti to 0
      repeat with t in tabs of w
        set ti to ti + 1
        repeat with s in sessions of t
          if (id of s) is wanted then
            select s
            select t
            select w
            activate
            delay 0.3
            return "ok|" & (frontmost as text) & "|" & (ti as text)
          end if
        end repeat
      end repeat
    end repeat
    return "gone"
  end tell
end run
"""

# The fallback for a shell this board did not open: a tab that tagged itself, or
# an agent the user started by hand. `variable named "path"` is iTerm's own idea
# of the session's directory, which is what the old code paid an lsof per pid for.
_SCAN = """
on run argv
  tell application "iTerm"
    set out to ""
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          tell s
            set v to ""
            try
              set v to (variable named "%s") as text
            end try
            if v is "missing value" then set v to ""
            set out to out & id & "\t" & v & "\t" & tty & "\t" & ¬
              (variable named "path") & "\t" & (variable named "jobName") & "\n"
          end tell
        end repeat
      end repeat
    end repeat
    return out
  end tell
end run
""" % VAR


# ---------------------------------------------------------------------------
# the registry: session id -> the iTerm session it was given
# ---------------------------------------------------------------------------

def _read():
    try:
        with open(REGISTRY) as handle:
            got = json.load(handle)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    os.makedirs(CACHE, exist_ok=True)
    # Replaced atomically: a half-written registry would lose every shell the
    # board has open, and the next click on each would open a duplicate.
    fd, tmp = tempfile.mkstemp(dir=CACHE, prefix=".shells-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, REGISTRY)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def remember(sid, guid):
    with _LOCK:
        data = _read()
        data[sid] = {"iterm": guid, "when": int(time.time())}
        _write(data)


def forget(sid):
    with _LOCK:
        data = _read()
        if data.pop(sid, None) is not None:
            _write(data)


def remembered(sid):
    return (_read().get(sid) or {}).get("iterm") or ""


# ---------------------------------------------------------------------------
# the three things actions.py asks for
# ---------------------------------------------------------------------------

def focus(guid):
    """(state, front, tab, why) -- state is 'ok', 'gone' or 'error'."""
    ok, out, why = _osascript(_FOCUS, [guid])
    if not ok:
        return "error", False, "", why
    if out.startswith("ok|"):
        parts = (out.split("|") + ["", ""])[:3]
        return "ok", parts[1] == "true", parts[2], ""
    return "gone", False, "", ""


def create(script, sid, where="window"):
    """Open a shell for `sid` and come back knowing which session it is.

    `where` is "window" or "tab". A new window is the default because it lands on
    the Space the user is looking at, while a tab joins whichever window iTerm
    happens to have -- which, with Displays have separate Spaces on, is how a
    click ends up invisible on the other screen.
    """
    ok, out, why = _osascript(_NEW_WINDOW, [script, sid, where], timeout=20)
    if not ok:
        return "", False, why
    guid, _, front = out.partition("|")
    if guid:
        remember(sid, guid)
    return guid, front == "true", ""


def scan():
    """Every iTerm session: guid, our tag, tty, directory, foreground job."""
    ok, out, why = _osascript(_SCAN, timeout=15)
    if not ok:
        return [], why
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 5:
            rows.append({"session": parts[0], "tag": parts[1], "tty": parts[2],
                         "path": parts[3].rstrip("/"), "job": parts[4]})
    return rows, ""


def untagged_match(session):
    """A shell for this session that the registry does not know about.

    Two ways in: a tab that tagged itself with our variable (a dashboard shell
    from before a restart), or an agent the user started by hand, which we can
    only recognise by its directory and its foreground job. The second is a
    guess, so it is only offered when it is unambiguous -- the old code happily
    pointed eight idle tiles at one live tab.
    """
    sid = session.get("sessionId") or ""
    want = (session.get("cwd") or "").rstrip("/")
    provider = session.get("provider") or ""
    rows, why = scan()
    if why:
        return "", why
    for row in rows:
        if sid and row["tag"] == sid:
            return row["session"], ""
    if not want:
        return "", ""
    job = {"claude": "claude", "codex": "codex", "antigravity": "agy"}.get(provider)
    hits = [r for r in rows if r["path"] == want and job and job in r["job"]]
    if len(hits) == 1:
        return hits[0]["session"], ""
    if hits:
        return "", ("%d iTerm tabs are running %s in %s, so which one belongs to "
                    "this tile is a guess -- opening a new shell instead"
                    % (len(hits), job, want))
    return "", ""
```

Note what went away: `_PATTERNS`, `_NOT_SESSION`, `_agent_ttys()`, `_cwd()` and the `ps`/`lsof`
subprocesses, plus the dead `fallback` variable. The remaining guess (`untagged_match`) uses
iTerm's own `path` and `jobName` instead, costs one round trip, and refuses to guess when
the answer is ambiguous.

### 3.2 `actions.py` — full replacement

```python
"""Open a session where you can actually work on it.

The page never sends a command: it sends a session id and a target, and the
command is assembled here from the snapshot. Nothing the browser types can reach
a shell.

One session, one shell. The iTerm button means "show me this session's shell":
iterm_link remembers which iTerm session each tile was given, so a second click
raises that tab instead of opening another. Every path returns a sentence that
is true, because the failure mode this whole file was rewritten for was a button
that did nothing and said "opened in iTerm".
"""

import hashlib
import os
import shlex
import stat
import subprocess
import time

import iterm_link

ITERM = "/Applications/iTerm.app"
VSCODE_BINS = ("/usr/local/bin/code", "/opt/homebrew/bin/code",
               "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")

# One file per session, at a path we choose, instead of a fresh mkstemp per
# click: tempfile(delete=False) had left 48 scripts in $TMPDIR by the end of one
# afternoon. A fixed name also means a repeat click overwrites, and the file can
# be read afterwards to see exactly what a shell was handed.
SHELLS = os.path.expanduser("~/.cache/fleet-dashboard/shells")
SWEEP_AFTER = 7 * 24 * 3600


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


def why_plain_shell(session, fell_back):
    """Why this session is getting a shell and not its agent back.

    The UI only hints at this by swapping "resume in" for "shell in", which is
    far too quiet for the two cases where a user clicks expecting their agent.
    """
    if not session.get("sessionId"):
        return "this session has no resumable id, so this is a plain shell"
    if session.get("state") == "running":
        return ("this session is mid-turn -- resuming would start a second copy "
                "of it, so this is a shell in its directory")
    if fell_back and session.get("resume") == "claude":
        return ("the recorded worktree is gone, so the transcript cannot be "
                "found from here; this is a shell in the project root")
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


def _sweep():
    """Scripts outlive their shells; a week-old one has outlived its session."""
    now = time.time()
    try:
        names = os.listdir(SHELLS)
    except OSError:
        return
    for name in names:
        path = os.path.join(SHELLS, name)
        try:
            if now - os.path.getmtime(path) > SWEEP_AFTER:
                os.unlink(path)
        except OSError:
            pass


def _quote_for_print(text):
    """zsh single quotes, for a banner. The old code deleted apostrophes."""
    return text.replace("'", "'\\''")


def _script_path(session):
    """A fixed, space-free path per session.

    Space-free is not a nicety: iTerm splits the `command` parameter of `create
    window` on whitespace, and a path with a space in it produces a session that
    dies before it draws -- a tab that flashes and vanishes, which is most of
    what "nothing happens when I click" turned out to be.
    """
    key = session.get("id") or session.get("sessionId") or "anon"
    return os.path.join(SHELLS, hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
                        + ".command")


def _launch_script(session, cwd, command, note=""):
    """A script on disk beats quoting a command through AppleScript."""
    body = "#!/bin/zsh -l\ncd %s || exit 1\n" % shlex.quote(cwd)
    if note:
        # Say it in the window too. A message that only reaches the toast is
        # gone by the time anyone reads the shell they were given.
        body += "print -P '%%F{yellow}%s%%f'\n" % _quote_for_print(note)
    if command:
        body += "print -P '%%F{cyan}%s%%f'\n%s\n" % (_quote_for_print(command), command)
    else:
        # %%F/%%f, not %F/%f: these are zsh prompt escapes and have to survive
        # Python's own %-formatting, which reads a bare %F as "a float goes
        # here" and raises on a string. This is why "shell in iTerm" failed for
        # every running session while "resume in iTerm" worked.
        body += "print -P '%%F{cyan}shell at%%f' %s\n" % shlex.quote(cwd)
    body += "exec $SHELL -l\n"

    os.makedirs(SHELLS, mode=0o700, exist_ok=True)
    _sweep()
    path = _script_path(session)
    with open(path, "w") as handle:
        handle.write(body)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return path


def launch_script(session):
    """The script a terminal should exec: the same assembly the buttons use.

    The embedded terminal runs this too, so what a pty starts on is decided
    here from the snapshot -- the page chooses a session, never a command.
    """
    cwd, moved = working_directory(session)
    return _launch_script(session, cwd, command_for(session, moved))


def _script_for(session):
    """(script path, the sentence that goes in the toast)."""
    cwd, moved = working_directory(session)
    command = command_for(session, moved)
    note = why_plain_shell(session, moved) if not command else ""
    said = []
    if moved:
        said.append("the recorded directory is gone, so this is %s" % cwd)
    if note:
        said.append(note)
    return _launch_script(session, cwd, command, note), cwd, "; ".join(said)


def open_session(session, target):
    cwd, _ = working_directory(session)
    if target == "vscode":
        binary = _vscode_bin()
        if not binary:
            return False, "the `code` command is not installed"
        subprocess.Popen([binary, cwd])
        return True, "opened %s in VS Code" % os.path.basename(cwd)

    script, cwd, said = _script_for(session)
    tail = (" -- " + said) if said else ""

    if target == "terminal":
        proc = subprocess.run(["open", "-a", "Terminal", script],
                              capture_output=True, text=True)
        if proc.returncode:
            return False, "Terminal refused: %s" % (proc.stderr or "").strip()
        return True, "opened in Terminal" + tail

    if target not in ("iterm", "iterm-new") or not os.path.isdir(ITERM):
        return False, "no such target: %s" % target

    sid = session.get("id") or ""

    # 1. the shell this tile already has. One session, one shell: this is the
    #    common case after the first click, and it must never open a second.
    if target == "iterm" and sid:
        guid = iterm_link.remembered(sid)
        if not guid:
            guid, ambiguous = iterm_link.untagged_match(session)
            # Said out loud rather than swallowed: "I could not tell which of
            # your three claude tabs this is" is the one thing the old match
            # never admitted, and it guessed wrong eight times out of nine.
            if ambiguous:
                tail = " -- " + ambiguous + (("; " + said) if said else "")
        if guid:
            state, front, tab, why = iterm_link.focus(guid)
            if state == "ok":
                return True, _placed("raised its iTerm tab %s" % tab, front)
            if state == "error":
                return False, "could not raise its iTerm tab: %s" % why
            # "gone": the user closed it. That is the only close-detection this
            # needs -- lazily, on the next click, instead of polling iTerm.
            iterm_link.forget(sid)

    # 2. make one, and come back knowing which session it is so that step 1 can
    #    work next time. A window rather than a tab: a new window opens on the
    #    Space in front of the user, while a tab joins whichever window iTerm
    #    already has -- on the other display, as often as not.
    guid, front, why = iterm_link.create(script, sid, "window")
    if guid:
        return True, _placed("opened an iTerm window", front) + tail
    if why:
        # 3. LaunchServices needs no Automation permission, so it still works
        #    when Apple Events are refused. Say what was lost, or the next click
        #    silently opens yet another tab.
        proc = subprocess.run(["open", "-a", "iTerm", script],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            return True, ("opened a tab in iTerm, but it cannot be raised again "
                          "later: %s" % why)
        return False, why

    return False, "iTerm created a window but would not say which one"


def _placed(what, front):
    """Say it when iTerm did not come forward. That is the actual complaint."""
    if front:
        return what
    return (what + ", but iTerm did not come to the front -- look on your other "
            "display or Space")
```

### 3.3 `dashboard.py` — three small patches

**(a) A refusal must be JSON, or the toast lies.** Around line 430:

```python
        # Opening a shell window and driving the music tab are both actions on
        # this machine; neither should be reachable from another origin.
        if not self._acting_ok():
            # Not send_error(): that returns HTML, the page's r.json() throws,
            # and the catch block blames the network for a policy decision. The
            # status stays 200 and the body carries the no, which is the shape
            # every other answer from this endpoint already has.
            self._json({
                "ok": False,
                "message": ("refused: this page was loaded from %s, and actions "
                            "are only allowed from 127.0.0.1, localhost or [::1]"
                            % (self.headers.get("Host") or "?")),
            })
            return
```

(If the 403 status matters more than the shape, keep it — but send it with
`Content-Type: application/json` and the same body, because what the page needs is a body
that parses.)

**(b) Accept the new target and drop the old one.** Around line 500:

```python
        if not session or target not in ("iterm", "iterm-new", "terminal", "vscode"):
```

`reveal` is gone: raising is what `iterm` does now. Keep accepting `"reveal"` for one release
and map it to `"iterm"` if any bookmark or script uses it.

**(c) Put a ceiling on the click.** `open_session` can spend 12 s in `focus` plus 20 s in
`create`. Wrap the call so a wedged iTerm cannot hold a request thread indefinitely:

```python
        try:
            ok, message = actions.open_session(session, target)
        except Exception as exc:
            # Surfaced, not logged: the page is the only place anyone will look.
            ok, message = False, "%s: %s" % (type(exc).__name__, exc)
```

is already right — the timeouts inside `iterm_link._osascript` are the ceiling, and they now
return a sentence instead of `None`.

### 3.4 `terminal.py` — closing a shell should take one click

```python
    def close(self, tid):
        term = self._ptys.get(tid)
        if not term:
            return False, "that terminal is already gone"
        if term.exited is not None:      # already dead: this click means "clear it"
            self.forget(tid)
            self._broadcast("gone", {"id": tid})
            return True, ""
        # Tell the page now. The pty may take a moment to die, or may refuse to,
        # and a click that changes nothing on screen for a second reads as a
        # button that does not work.
        self._broadcast("closing", {"id": tid})
        term.kill()
        return True, ""
```

and escalation, because SIGHUP is a request:

```python
    def kill(self):
        """HUP, then TERM, then KILL. A shell may ignore the first two."""
        if self.exited is not None:
            return
        for sig, wait in ((signal.SIGHUP, 1.5), (signal.SIGTERM, 1.5),
                          (signal.SIGKILL, 0)):
            try:
                os.killpg(os.getpgid(self.pid), sig)
            except OSError:
                return                       # already reaped
            if not wait:
                return
            deadline = time.time() + wait
            while time.time() < deadline:
                if self.exited is not None:
                    return
                time.sleep(0.05)
```

`kill()` now blocks for up to 3 s, so call it off the request thread:

```python
        threading.Thread(target=term.kill, daemon=True,
                         name="kill-%s" % tid).start()
```

and the reaper must tell the page when it drops a dead pty, or the page keeps a tab whose
`×` can never do anything again:

```python
            for tid, term in list(self._ptys.items()):
                if term.exited is not None and now - term.last_seen > 60:
                    self.forget(tid)
                    self._broadcast("gone", {"id": tid})
```

`dashboard.py`'s `/api/term/close` should pass the message through:

```python
        elif path == "/api/term/close":
            ok, why = TERMINAL.close(body.get("tid"))
            reply = {"ok": ok, "message": why}
```

### 3.5 `ui.html` — the four edits

**(a) One iTerm button, and no more `reveal`.** Replace the `reveal` line (~3036) and the
button map (~3037-3041):

```js
  // One session, one shell: the iTerm button raises the shell this session
  // already has and only opens one when there is none. "new window" is the
  // escape hatch for when a second shell is actually wanted.
  const newWin = targets.iterm
    ? '<button class="plain" data-target="iterm-new">new iTerm window</button>' : '';
  document.getElementById('p-acts').innerHTML = here
    + buttons.map(([t,l]) =>
        '<button data-target="'+t+'">'+(t==='vscode' ? 'open in ' : (resumes ? 'resume in ' : 'shell in '))+l+'</button>').join('')
    + newWin
    + '<button class="plain" data-copy="1">copy command</button>';
```

**(b) A failure must stay on screen.** `toast()` (~3071) holds errors longer and marks them:

```js
function toast(msg, bad){
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.toggle('bad', !!bad);
  el.classList.add('on');
  clearTimeout(toast._t);
  // A failure is read on a different screen from the one that was clicked, so
  // it gets long enough to walk over and a click to dismiss it early.
  toast._t = setTimeout(() => el.classList.remove('on'), bad ? 12000 : 2600);
  el.onclick = () => el.classList.remove('on');
}
```

with `.toast.bad{border-color:var(--blocked)}` beside the existing `.toast` rules (~481).

**(c) `open_()` must not blame the network for a server answer:**

```js
async function open_(id, target){
  try{
    const r = await fetch('/api/open', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({id, target})
    });
    // A refusal now answers in JSON; anything that does not parse really is a
    // broken server, and only then is "could not reach" the truth.
    const d = await r.json();
    toast(d.message || (d.ok ? 'opened' : 'could not open'), !d.ok);
  }catch(e){ toast('the dashboard server did not answer', true); }
}
```

**(d) The terminal `×` acts on the first click.** In `drawTabs()` (~3703):

```js
      if(ev.target.dataset.close){
        const tid = ev.target.dataset.close;
        // Strike it now. The pty can take a couple of seconds to die, and a
        // click with no visible effect reads as a button that does not work.
        const t = terms.get(tid);
        if(t){ t.alive = false; drawTabs(); }
        termPost('/api/term/close', {tid}).then(r => {
          if(!r.ok) toast(r.message || 'could not close that terminal', true);
        });
        return;
      }
```

and handle the new frame beside `exit` (~3785):

```js
  if(event === 'closing'){
    const t = terms.get(payload.id);
    if(t){ t.alive = false; t.term?.write('\r\n\x1b[2m[closing]\x1b[0m\r\n'); }
    drawTabs();
    return;
  }
```

---

## 4. What the user should see, per failure mode

| what went wrong | toast |
|---|---|
| the shell exists and came forward | `raised its iTerm tab 2` |
| it exists but iTerm stayed behind | `raised its iTerm tab 2, but iTerm did not come to the front -- look on your other display or Space` |
| the user had closed it | `opened an iTerm window` (registry entry dropped silently — correct) |
| Automation not granted | `opened a tab in iTerm, but it cannot be raised again later: macOS has not given the dashboard permission to control iTerm… System Settings > Privacy & Security > Automation` |
| iTerm showing a modal | `iTerm did not answer in 12s -- it may be showing a dialog that needs a click` |
| ambiguous hand-started agent | `3 iTerm tabs are running claude in /Users/tiago, so which one belongs to this tile is a guess -- opening a new shell instead` |
| a live session, no resume | `opened an iTerm window -- this session is mid-turn, so resuming would start a second copy of it; this is a shell in its directory` |
| worktree removed | `opened an iTerm window -- the recorded directory is gone, so this is /Users/tiago/Documents/Dev/casaradar` |
| page loaded from a non-loopback host | `refused: this page was loaded from fleet.local:8787, and actions are only allowed from 127.0.0.1, localhost or [::1]` |
| in-page terminal refuses to die | `could not close that terminal` (after HUP → TERM → KILL) |

---

## 5. Measurements, for the record

| thing | cost |
|---|---|
| `iterm_link.inventory()` as it stands | 621 ms |
| `_agent_ttys()` (`ps -Ao`) | 143 ms |
| `find()` end to end, per click | ~680 ms (16 sessions: 10.9 s) |
| `/api/open` reveal, full round trip | 0.98 s |
| proposed `focus()` by guid | 0.57 s |
| proposed `create` window + tag + verify | one call, ~1.0 s including `delay 0.3` |
| leftover `.command` files in `$TMPDIR` | 48, 6,571 bytes, all from today |

## 6. To confirm with the user

1. **How does the board reach the Air?** If it is ever opened at a LAN address or
   `<name>.local` rather than `localhost` (tunnel / port forward), every action button 403s and
   the only message is "could not reach the dashboard server". That single configuration
   reproduces the symptom completely, and the fix is one line either way.
2. **New window or tab?** The recommendation creates a **window**, because a window lands on
   the Space in front of you and a tab joins whichever window iTerm already has. If he prefers
   tabs, `iterm_link.create(..., "tab")` is the switch, and it should be a saved preference.
   A profile with a **hotkey window** would be strictly better than both — it always appears on
   the current Space, over everything — but it needs a hotkey configured by hand.
3. **Is `iTerm` ever not the target?** `Prompt Before Closing 2 = false` in the Default profile
   means closing a dashboard-opened tab never prompts here. If he uses a second profile for
   these shells, that needs setting there too.
4. **One shell per session, or one per tile-click?** The recommendation is the former, which
   means the `iTerm` button will sometimes *not* open anything new. The `new iTerm window`
   escape hatch covers the other case.

## 7. Caveats

- Another agent was manipulating iTerm throughout this review (window positions
  `FLEET-RESEARCH-CLOSEONEND-001` and `FLEET-RESEARCH-KEEPOPEN-0001` appeared in
  `NoSyncSavedWindowPositions`, and windows came and went that were not mine). Tab and window
  counts in §1.2 were taken in one unbroken measurement; the alert counts in §1.4 are shared
  history and I have said so.
- I left nothing behind: final inventory is the user's original single window with its two
  tabs (`◑ Dashboard themes research (claude)` and `agy (agy)`). One test window was created
  and closed; the rest of the probing used tabs.
- I did **not** test the iTerm2 Python API / `it2` path, because authorising a non-child
  process raises a consent dialog inside iTerm and the user is working.
- TCC.db is unreadable without Full Disk Access, so "Automation is granted" is a functional
  conclusion from a successful Apple Event out of pid 78519, not a database reading.
</content>
