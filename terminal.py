"""A real terminal in the page, off unless it is asked for.

This is the one place in the dashboard where something typed in a browser
reaches a shell, and it does so only through a pty's stdin -- there is no
endpoint anywhere that takes a command string and runs it. What the pty runs
is still assembled server-side by `actions`, from the snapshot, out of a
session id: the browser picks *which* session, never *what to run*.

Transport is a single Server-Sent Events stream carrying every open terminal
(multiplexed, so a page with four terminals still holds one connection) and a
POST per burst of typing. Both are stdlib. A websocket would save about a
millisecond of the round trip and cost either a dependency or 130 lines of
RFC 6455 framing; the measurement is in DELIVERY.md.
"""

import base64
import errno
import fcntl
import os
import pty
import queue
import re
import select
import signal
import struct
import termios
import threading
import time

import actions

MAX_TERMINALS = 30
# What a reattaching page gets replayed. 256KB of a 200-column screen is a few
# hundred lines of scrollback, which is what a reload should feel like.
REPLAY_BYTES = 256 * 1024
READ_CHUNK = 65536
# The kernel hands a pty back in tiny pieces -- measured at an 18-byte average,
# 7,017 reads for the 129KB that `seq 1 20000` produces. One frame per read
# meant 7,000 JSON+base64+flush round trips and 3.8 seconds for output a bare
# pty delivers in 32ms. So a read is followed by a drain: take everything
# already queued, and once a burst is under way allow a couple of milliseconds
# for the rest of it. The first drain pass waits zero, so a lone keystroke echo
# pays nothing for this.
COALESCE_BYTES = 128 * 1024
COALESCE_GRACE = 0.002
# A pty with nobody watching it and nothing happening in it for this long is a
# leak, not scrollback. "Nothing happening" has to include output, not just
# attention: a `claude --resume` left running while the dashboard window is
# closed is exactly the thing that must NOT be hung up, and it is producing
# output the whole time. Only a genuinely abandoned idle shell reaches this.
IDLE_KILL_SECONDS = 2 * 60 * 60
# A tab opened for a session is not stripped of it before its launch script
# has had time to start the agent: the resume takes a moment to become a
# child of the shell, and a Claude one a few seconds more to reach the roster.
LINK_GRACE_SECONDS = 20
DEFAULT_SHELL = os.environ.get("SHELL") or "/bin/zsh"

# Sequences that ask the terminal a question. They matter because replay is not
# a recording: xterm.js parses the bytes it is given, so a page that reloads and
# is handed the scrollback would *answer* every question in it -- posting stale
# device attributes and background colours back into the shell's stdin, where
# they land on the command line as garbage. Live output keeps them (that round
# trip is real and takes ~3ms); replayed output has them cut out. Nothing
# visible is lost: none of these draw anything.
_QUERIES = re.compile(
    rb"\x1b\[[0-9;?>]*[cn]"                    # DA1 / DA2 / DSR
    rb"|\x1b\][0-9;]*;\?(?:\x07|\x1b\\)"       # OSC colour queries
    rb"|\x1b\[>[0-9;]*q"                       # XTVERSION
    rb"|\x1bP\+q[0-9a-fA-F;]*\x1b\\"           # XTGETTCAP
)


def strip_queries(data):
    return _QUERIES.sub(b"", data)


def _set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def tab_title(path, agent):
    """The tab is named after the folder the way a prompt would show it: the
    home directory is "~", a folder in it is "~/name", and only deeper ones
    go by their last component. Naming home by its basename put the login
    name on every tab opened from the + button. This is what a tab is called
    while nothing but a shell runs in it; see Terminals.adopt for the rest."""
    real = os.path.realpath(path).rstrip(os.sep) or os.sep
    home = os.path.realpath(os.path.expanduser("~")).rstrip(os.sep)
    if real == home:
        name = "~"
    elif real.startswith(home + os.sep) and real.count(os.sep) == home.count(os.sep) + 1:
        name = "~/" + os.path.basename(real)
    else:
        name = os.path.basename(real) or "/"
    return name if agent == "shell" else "%s · %s" % (name, {"antigravity": "agy"}.get(agent, agent))


class Pty:
    """One pseudo-terminal, its output ring, and everyone watching it."""

    def __init__(self, tid, session_id, title, cwd, rows, cols, script):
        self.id = tid
        self.session_id = session_id
        self.title = title
        # Where the tab's name comes from once the agent inside it exits (or
        # never starts): the folder, the way a prompt would show it.
        self.fallback = tab_title(cwd, "shell")
        # The session it was opened to resume or attach to, if any. adopt()
        # keeps that link as long as something is running in the tab, since
        # `claude attach` is a different process from the session's own.
        self.opened_for = session_id
        self.cwd = cwd
        self.rows, self.cols = rows, cols
        self.started = time.time()
        self.exited = None
        self.last_seen = time.time()
        self._ring = bytearray()
        self._lock = threading.Lock()
        self._subs = set()

        # pty.fork rather than openpty+Popen: a shell needs to be a session
        # leader with this tty as its *controlling* terminal or Ctrl-C never
        # becomes SIGINT, and pty.fork is the only stdlib call that arranges
        # that. The child does nothing between fork and exec but chdir.
        self.pid, self.fd = pty.fork()
        if self.pid == 0:                                   # child
            try:
                os.chdir(cwd)
            except OSError:
                pass
            env = dict(os.environ)
            env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor",
                        "FLEET_TERMINAL": "1"})
            env.pop("FLEET_TERMINAL_TOKEN", None)   # never hand the token to a shell
            try:
                os.execve(script, [script], env)
            except Exception:
                os._exit(127)
        _set_winsize(self.fd, rows, cols)
        threading.Thread(target=self._pump, daemon=True,
                         name="pty-%s" % tid).start()

    # ---- output -----------------------------------------------------------
    def _pump(self):
        while True:
            try:
                select.select([self.fd], [], [], 30)
                data = os.read(self.fd, READ_CHUNK)
                grace = 0.0
                while data and len(data) < COALESCE_BYTES:
                    ready, _, _ = select.select([self.fd], [], [], grace)
                    if not ready:
                        break
                    more = os.read(self.fd, READ_CHUNK)
                    if not more:
                        break
                    data += more
                    grace = COALESCE_GRACE
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                data = b""                       # EIO: the child hung up
            except ValueError:
                data = b""
            if not data:
                break
            self.last_seen = time.time()     # output counts as being alive
            with self._lock:
                self._ring += data
                del self._ring[:-REPLAY_BYTES]
                subs = list(self._subs)
            for sub in subs:
                sub(self.id, data)
        self._reap()

    def _reap(self):
        try:
            _, status = os.waitpid(self.pid, 0)
            self.exited = status
        except OSError:
            self.exited = -1
        try:
            os.close(self.fd)
        except OSError:
            pass
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            sub(self.id, None)

    def attach(self, sink):
        """Replay the ring and start following, without a gap between the two."""
        with self._lock:
            backlog = strip_queries(bytes(self._ring))
            self._subs.add(sink)
        self.last_seen = time.time()
        return backlog

    def detach(self, sink):
        with self._lock:
            self._subs.discard(sink)
        self.last_seen = time.time()

    # ---- input ------------------------------------------------------------
    def write(self, data):
        self.last_seen = time.time()
        if self.exited is not None:
            return False
        try:
            os.write(self.fd, data)
            return True
        except OSError:
            return False

    def resize(self, rows, cols):
        self.rows, self.cols = rows, cols
        _set_winsize(self.fd, rows, cols)

    def kill(self):
        if self.exited is not None:
            return
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGHUP)
        except OSError:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass

    def meta(self):
        return {"id": self.id, "session_id": self.session_id,
                "title": self.title, "cwd": self.cwd,
                "rows": self.rows, "cols": self.cols,
                "started": int(self.started * 1000),
                "alive": self.exited is None}



class Terminals:
    """Every open pty, and the fan-out to the pages watching them."""

    def __init__(self):
        self._ptys = {}
        self._clients = set()      # each is a Queue of (event, payload)
        self._lock = threading.Lock()
        self._seq = 0
        threading.Thread(target=self._reaper, daemon=True, name="pty-reaper").start()

    # ---- lifecycle --------------------------------------------------------
    def open(self, session, title, rows=24, cols=80):
        with self._lock:
            live = [p for p in self._ptys.values() if p.exited is None]
            if len(live) >= MAX_TERMINALS:
                return None, "already running %d terminals" % MAX_TERMINALS
            self._seq += 1
            tid = "t%d" % self._seq
        cwd = (session or {}).get("cwd") or os.path.expanduser("~")
        if not os.path.isdir(cwd):
            cwd = os.path.expanduser("~")
        # The command is assembled here, from the snapshot, exactly the way the
        # iTerm and Terminal buttons assemble theirs. Nothing from the page.
        script = actions.launch_script(session or {})
        try:
            term = Pty(tid, (session or {}).get("id"), title, cwd, max(4, int(rows)), max(20, int(cols)), script)
        except OSError as exc:
            return None, "could not start a terminal: %s" % exc
        with self._lock:
            self._ptys[tid] = term
        self._broadcast("open", term.meta())
        return term, ""

    def open_at(self, cwd, agent, rows=24, cols=80):
        """The + button: a fresh agent or shell in a folder of the user's choosing."""
        script, real = actions.fresh_script(cwd, agent)
        if not script:
            return None, real
        with self._lock:
            live = [p for p in self._ptys.values() if p.exited is None]
            if len(live) >= MAX_TERMINALS:
                return None, "already running %d terminals" % MAX_TERMINALS
            self._seq += 1
            tid = "t%d" % self._seq
        title = tab_title(real, agent)
        try:
            term = Pty(tid, None, title, real, max(4, int(rows)), max(20, int(cols)), script)
        except OSError as exc:
            return None, "could not start a terminal: %s" % exc
        with self._lock:
            self._ptys[tid] = term
        self._broadcast("open", term.meta())
        return term, ""

    def adopt(self, sessions, parent_of):
        """Name every terminal after the session running inside it.

        A tab opened from the + button as a shell in ~ is called "~", and stayed
        that way after the user typed `claude` into it -- while the board
        listed the conversation under its own name. So once a snapshot, every
        live pty looks for an agent under its shell: the collectors put a pid
        on each session whose CLI is running (Claude from the roster, Codex and
        agy from the process table), and `parent_of` says whose child that is.
        The nearest one wins, since a Claude that runs `claude` in a tool call
        is a descendant too. The tab takes that session's name -- the board's
        name, so a rename reaches the tab -- and its id, so the tile's terminal
        button finds this tab instead of opening a second one.

        A tab opened *for* a session keeps that link while anything runs in
        it: `claude attach` is a client, not the session's own process, so it
        never matches by pid. A bare shell, opened for nothing or with its
        agent gone, goes back to its folder name. Runs on the snapshot thread;
        the writes are plain attributes, and only a change is broadcast.
        """
        with self._lock:
            live = [p for p in self._ptys.values() if p.exited is None]
        if not live:
            return
        by_id = {s.get("id"): s for s in sessions}
        shells = {p.pid: p for p in live}
        busy = set(parent_of.values())            # pids with a child
        nearest = {}                              # tid -> (depth, session)
        for session in sessions:
            try:
                pid = int(session.get("pid") or 0)
            except (TypeError, ValueError):
                continue
            depth = 0
            while pid and pid > 1 and depth < 32:
                pid = parent_of.get(pid)
                depth += 1
                term = shells.get(pid)
                if term is not None:
                    if term.id not in nearest or depth < nearest[term.id][0]:
                        nearest[term.id] = (depth, session)
                    break
        now = time.time()
        for term in live:
            hit = nearest.get(term.id)
            if hit:
                session = hit[1]
            elif term.opened_for and (term.pid in busy or now - term.started < LINK_GRACE_SECONDS):
                session = by_id.get(term.opened_for)
                if session is None:               # off the board, still running
                    continue
            else:
                session = None
                term.opened_for = None            # a shell now; the next agent typed into it is adopted by pid
            title = (session.get("name") or term.fallback) if session else term.fallback
            sid = session.get("id") if session else None
            if (title, sid) != (term.title, term.session_id):
                term.title, term.session_id = title, sid
                self._broadcast("meta", term.meta())

    def get(self, tid):
        return self._ptys.get(tid)

    def close(self, tid):
        term = self._ptys.get(tid)
        if not term:
            # The page can hold a tab for a terminal this side has already
            # forgotten. Answer the click anyway so the tab goes, and say yes:
            # from where the user sits, closing something gone is a success.
            self._broadcast("gone", {"id": tid})
            return True
        if term.exited is not None:      # already dead: this click means "clear it"
            self.forget(tid)
            self._broadcast("gone", {"id": tid})
            return True
        term.kill()
        return True

    def forget(self, tid):
        with self._lock:
            self._ptys.pop(tid, None)

    def list(self):
        return [p.meta() for p in sorted(self._ptys.values(), key=lambda p: p.started)]

    def shutdown(self):
        for term in list(self._ptys.values()):
            term.kill()

    def _reaper(self):
        while True:
            time.sleep(60)
            now = time.time()
            for tid, term in list(self._ptys.items()):
                if term.exited is not None and now - term.last_seen > 60:
                    # Forgetting without telling the page left a phantom tab
                    # whose close button then hit an unknown id and did nothing:
                    # the "shell I cannot close". The page hears about it now.
                    self.forget(tid)
                    self._broadcast("gone", {"id": tid})
                elif term.exited is None and not term._subs \
                        and now - term.last_seen > IDLE_KILL_SECONDS:
                    term.kill()

    # ---- fan-out ----------------------------------------------------------
    def _broadcast(self, event, payload):
        for client in list(self._clients):
            try:
                client.put_nowait((event, payload))
            except queue.Full:
                pass

    def stream(self, write_frame, alive):
        """Serve one SSE client until it goes away.

        One stream carries every terminal, so a page with four of them open
        still holds a single connection out of the browser's six per origin.
        """
        outbox = queue.Queue(maxsize=4096)

        def sink(tid, data):
            try:
                if data is None:
                    outbox.put_nowait(("exit", {"id": tid}))
                else:
                    outbox.put_nowait(("out", {"id": tid, "b64":
                                               base64.b64encode(data).decode("ascii")}))
            except queue.Full:
                pass

        with self._lock:
            self._clients.add(outbox)
        attached = []
        try:
            write_frame("hello", {"terminals": self.list()})
            for term in list(self._ptys.values()):
                backlog = term.attach(sink)
                attached.append(term)
                if backlog:
                    write_frame("out", {"id": term.id, "replay": True,
                                        "b64": base64.b64encode(backlog).decode("ascii")})
            last_ping = time.time()
            while alive():
                try:
                    event, payload = outbox.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_ping > 15:
                        last_ping = time.time()
                        write_frame("ping", {"t": int(last_ping)})
                    continue
                if event == "open":
                    term = self._ptys.get(payload["id"])
                    if term and term not in attached:
                        # The tab has to exist in the page before any bytes are
                        # sent for it, and the pty has usually printed its
                        # banner before this client got here -- so: frame,
                        # attach, then whatever it already said. attach() takes
                        # the ring and registers the sink under one lock, so
                        # nothing is lost between them and nothing arrives twice.
                        write_frame(event, payload)
                        backlog = term.attach(sink)
                        attached.append(term)
                        if backlog:
                            write_frame("out", {"id": term.id, "replay": True,
                                                "b64": base64.b64encode(backlog).decode("ascii")})
                        continue
                write_frame(event, payload)
                for term in attached:
                    term.last_seen = time.time()
        finally:
            with self._lock:
                self._clients.discard(outbox)
            for term in attached:
                term.detach(sink)


TERMINALS = Terminals()
