#!/usr/bin/env python3
"""A one-screen live board for every agent session on this machine.

    python3 ~/Documents/Dev/agent-dashboard/dashboard.py     # then http://localhost:8080

Stdlib only, read-only, and it never holds a transcript in memory: the page is
static and pulls a small JSON snapshot, which is rebuilt at most once every few
seconds no matter how many tabs are watching.
"""

import argparse
import base64
import json
import os
import secrets
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import actions
import aliases
import flush as flushmod
import instance
import sunset
import collectors
import metrics
import notes
import music
import usage

HERE = os.path.dirname(os.path.abspath(__file__))
# A rebuild costs about 90ms once the Claude roster is off the hot path
# (see collectors.claude_agents), so the board can afford to move at walking
# pace. The tok/min trace is not sampled here: it is drawn from the usage
# ledger's minute buckets, which come from the transcripts' own timestamps
# and so survive a restart of this process. The host trace is: cpu, gpu,
# memory and the agents' footprint have no file to be read back from, so
# they are kept as a ring of light samples. HISTORY_SAMPLES is written as a
# duration: the ring covers a quarter of an hour whatever the refresh is.
REFRESH_SECONDS = 2.0
HISTORY_SAMPLES = max(60, int(900 / REFRESH_SECONDS))

# Order and identity of the three lanes. The mark is drawn as inline SVG in the
# page, never as an emoji: emoji fonts are the reason the old board showed tofu.
PROVIDERS = [
    {"key": "claude", "label": "Claude Code"},
    {"key": "antigravity", "label": "Antigravity"},
    {"key": "codex", "label": "Codex"},
]

# A session that has stopped and wants you sorts with the ones that need
# attention, not with the ones quietly getting on with it.
# A session that says it is running but has written nothing for this long is
# not running. Providers report their own state and are routinely wrong about
# it: a Claude job that never exited cleanly leaves state.json saying
# "running" forever, and an idle `agy` sitting at a prompt still counts as a
# live process. What is on disk is evidence; what a provider claims is not.
# Ten minutes is deliberately generous -- a long build or test run can be
# genuinely quiet for several -- so anything past it is not a close call.
STALE_RUNNING_SECONDS = 600

# This board's own session -> chosen name map. Nothing else on the machine
# reads or writes it, and it never reaches an agent's store: a rename changes
# what THIS board calls a session, and the agent goes on calling it whatever
# it called it.
ALIASES = aliases.Aliases()

# Tiles the user has flushed off the board. Dismissal only, never a kill:
# nothing here signals a process or deletes an agent's state.
DISMISSED = flushmod.Dismissed()

STATE_ORDER = {"blocked": 0, "waiting": 1, "running": 2, "idle": 3,
               "done": 4, "unknown": 5}


class Snapshot:
    """Rebuilds the board state on its own thread.

    A rebuild costs a couple of hundred milliseconds — mostly waiting on
    `claude agents` — so requests are never made to wait for one. They are
    served the most recent snapshot, which is at most one refresh old.
    """

    def __init__(self):
        self._transcripts = collectors.Transcripts()
        self._codex_transcripts = collectors.CodexTranscripts()
        self._payload = None
        self._history = []          # ring of host samples, for the host trace
        self._index = {}            # session id -> session, for /api/open
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="snapshot").start()

    def _loop(self):
        while True:
            started = time.monotonic()
            try:
                self._payload = self._build()
                self._ready.set()
            except Exception as exc:
                print("snapshot failed: %s: %s" % (type(exc).__name__, exc))
            # Sleep the remainder, not the whole interval: a build that took
            # 400ms should not push the next one 400ms further out.
            time.sleep(max(0.4, REFRESH_SECONDS - (time.monotonic() - started)))

    def get(self):
        if self._payload is None:
            self._ready.wait(timeout=25)
        return self._payload or b'{"total":0,"tally":{},"lanes":[]}'

    def session(self, session_id):
        return self._index.get(session_id)

    def sessions(self):
        return list(self._index.values())

    def _build(self):
        started = time.time()
        # The ledger tails every transcript touched in the last thirty hours,
        # roster or not, so the day's total counts sessions that have already
        # finished and gone; the collectors then read their own session's
        # numbers off the same records.
        try:
            usage.LEDGER.scan()
        except Exception as exc:
            print("usage ledger failed: %s: %s" % (type(exc).__name__, exc))
        sessions = []
        for collect in (
            lambda: collectors.collect_claude(self._transcripts),
            collectors.collect_antigravity,
            lambda: collectors.collect_codex(self._codex_transcripts),
        ):
            try:
                sessions.extend(collect())
            except Exception as exc:                      # a broken lane must
                sessions.append({                         # not blank the board
                    "id": "error", "provider": "claude", "name": "collector error",
                    "project": "dashboard", "place": "", "kind": "", "state": "blocked",
                    "brief": "A collector raised %s" % type(exc).__name__,
                    "now": str(exc)[:200], "needs": "", "links": [],
                    "tokens": None, "started": None, "updated": None,
                })

        # A note is the one thing an agent volunteers rather than leaks.
        try:
            notes.attach(sessions)
        except Exception:
            pass          # a bad note must never cost you the board

        # Demote stale claims before anything sorts or counts them, so the
        # tally, the lane weighting and the "live" gauge all agree. "waiting"
        # is left alone: a session that wants you still wants you, however
        # long it has been asking.
        now_ms = time.time() * 1000
        for session in sessions:
            updated = session.get("updated")
            if session.get("state") == "running" and updated:
                if (now_ms - updated) / 1000 > STALE_RUNNING_SECONDS:
                    session["state"] = "idle"
                    session["stale"] = True

        # What got finished today, counted before a flush can hide it: a done
        # tile waved off the board still happened. The MRs are the links the
        # jobs themselves reported, deduplicated by URL.
        midnight = usage.local_midnight_ms()
        try:
            jobs = usage.finished(midnight)
        except Exception:
            jobs = {"count": 0, "mrs": 0, "ids": []}
        # Sessions on the roster that ended today and are not jobs (a Codex
        # thread, an interactive Claude session) add to the jobs' own count.
        job_ids = set(jobs["ids"])
        extra = [s for s in sessions
                 if s.get("state") == "done" and (s.get("updated") or 0) >= midnight
                 and not (s.get("jobId") in job_ids)]
        done = {"today": jobs["count"] + len(extra), "mrs": jobs["mrs"], "since": midnight}

        # The chosen names go on last, over whatever the collectors read, so a
        # rename survives the collector changing its mind about a session.
        ALIASES.apply(sessions)
        # Finished work the user has waved away. A flushed session reappears
        # the moment it writes something newer than when it was flushed.
        sessions = DISMISSED.apply(sessions)

        lanes = []
        for provider in PROVIDERS:
            mine = [s for s in sessions if s["provider"] == provider["key"]]
            projects = {}
            for session in mine:
                projects.setdefault(session["project"], []).append(session)
            for group in projects.values():
                group.sort(key=lambda s: (STATE_ORDER.get(s["state"], 9), s["name"]))
            lanes.append({
                "key": provider["key"],
                "label": provider["label"],
                "count": len(mine),
                "projects": [
                    {"name": name, "count": len(group), "sessions": group}
                    for name, group in sorted(
                        projects.items(), key=lambda kv: (-len(kv[1]), kv[0]))
                ],
            })

        self._index = {s["id"]: s for s in sessions}

        # The terminal sheet names its tabs after what runs in them, from the
        # same sessions and the same process table this pass just read.
        if TERMINAL is not None:
            try:
                TERMINAL.adopt(sessions, metrics.parents())
            except Exception as exc:
                print("terminal adopt failed: %s: %s" % (type(exc).__name__, exc))

        tally = {}
        tokens = 0
        for session in sessions:
            tally[session["state"]] = tally.get(session["state"], 0) + 1
            tokens += session.get("tokens") or 0

        try:
            host = metrics.snapshot()
        except Exception:
            host = {}
        try:
            fleet_usage = usage.LEDGER.summary()
        except Exception as exc:
            print("usage summary failed: %s: %s" % (type(exc).__name__, exc))
            fleet_usage = None

        self._history.append({
            "t": int(time.time() * 1000),
            "cpu": host.get("cpu", {}).get("pct", 0),
            "gpu": host.get("gpu", {}).get("pct"),
            "mem": host.get("memory", {}).get("pct", 0),
            "rss": host.get("agentRssMb", 0),
        })
        del self._history[:-HISTORY_SAMPLES]

        # The fullest context on the board: the session nearest a compaction.
        fullest = max((s for s in sessions if (s.get("usage") or {}).get("ctxMax")),
                      key=lambda s: s["usage"]["ctxPct"], default=None)
        context = ({"id": fullest["id"], "name": fullest["name"],
                    "pct": fullest["usage"]["ctxPct"], "used": fullest["usage"]["ctx"],
                    "max": fullest["usage"]["ctxMax"]} if fullest else None)

        return json.dumps({
            "generatedAt": int(time.time() * 1000),
            "buildMs": int((time.time() - started) * 1000),
            "total": len(sessions),
            "tally": tally,
            "tokens": tokens,
            "usage": fleet_usage,
            "context": context,
            "done": done,
            "lanes": lanes,
            "host": host,
            "history": self._history,
            "targets": actions.available(),
        }).encode("utf-8")


SNAPSHOT = Snapshot()

# ---------------------------------------------------------------------------
# The embedded terminal. Everything below is inert unless --terminal was
# passed: TERMINAL stays None, the routes 404, and the page never sees a token.
#
# This is the one feature that lets a browser reach a shell, so it is opt-in,
# loopback-only, and guarded by three independent things -- a Host allowlist
# (DNS rebinding), an Origin allowlist (CSRF), and a per-process token the
# page can only get by being served the HTML itself (cross-origin reads of
# which are what the same-origin policy exists to stop).
# ---------------------------------------------------------------------------
TERMINAL = None                 # the terminal.Terminals instance, or None
TERMINAL_TOKEN = ""
# One id per process, stamped on every response. The terminal token is also
# per-process, so a page loaded before a restart holds a token the new process
# has never seen and every terminal call it makes is refused -- silently, from
# where the user sits. The board restarts often while it is being worked on
# (launchd counted ten today), and a tab kept open for hours had no way to know.
# It reads this header on each poll and reloads itself the moment it changes.
BOOT_ID = secrets.token_hex(6)
ALLOWED_HOSTS = frozenset()
ALLOWED_ORIGINS = frozenset()
LOOPBACK = ("127.0.0.1", "::1", "localhost")
VENDOR = {"/vendor/xterm.js": "application/javascript",
          "/vendor/xterm.css": "text/css",
          "/vendor/xterm-addon-fit.js": "application/javascript",
          "/vendor/fleet-sounds.js": "application/javascript"}


# The same Host/Origin pair the terminal enforces, minus the token, for the
# routes that act on this machine but predate the terminal and must keep
# working with --terminal off. Set unconditionally at startup.
SAFE_HOSTS = frozenset()
SAFE_ORIGINS = frozenset()


def set_safe_origins(port):
    global SAFE_HOSTS, SAFE_ORIGINS
    names = ["127.0.0.1:%d" % port, "localhost:%d" % port, "[::1]:%d" % port]
    SAFE_HOSTS = frozenset(names)
    SAFE_ORIGINS = frozenset("http://%s" % n for n in names)


def enable_terminal(host, port):
    """Turn the terminal on, or refuse loudly. Never silently degrade."""
    global TERMINAL, TERMINAL_TOKEN, ALLOWED_HOSTS, ALLOWED_ORIGINS
    if host not in LOOPBACK:
        raise SystemExit(
            "refusing --terminal on %s: the terminal serves a shell and is "
            "loopback-only. Bind 127.0.0.1 or drop --terminal." % host)
    import terminal                                    # noqa: E402  (opt-in only)
    TERMINAL = terminal.TERMINALS
    TERMINAL_TOKEN = secrets.token_urlsafe(32)
    names = ["127.0.0.1:%d" % port, "localhost:%d" % port, "[::1]:%d" % port]
    ALLOWED_HOSTS = frozenset(names)
    ALLOWED_ORIGINS = frozenset("http://%s" % n for n in names)
    return terminal


def page_bytes():
    """ui.html with the terminal's per-process token spliced in.

    The token rides inside the document rather than in a script of its own: a
    page on another origin can execute our script tags and read whatever they
    define, but it cannot read our HTML.
    """
    with open(os.path.join(HERE, "ui.html"), "rb") as handle:
        html = handle.read()
    config = json.dumps({"enabled": bool(TERMINAL),
                         "token": TERMINAL_TOKEN,
                         "iterm": actions.available().get("iterm", False)})
    inject = ("<script>window.FLEET_TERM=%s;</script>\n" % config).encode("utf-8")
    marker = b"<script>"
    at = html.find(marker)
    if at == -1:
        at = html.rfind(b"</body>")
        return html[:at] + inject + html[at:] if at != -1 else html + inject
    return html[:at] + inject + html[at:]



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, body, content_type):
        self.send_response(200)
        # charset is not optional: without it the browser guesses latin-1 and
        # every accented name and every glyph comes out as mojibake.
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("X-Fleet-Boot", BOOT_ID)
        # ui.html is read from disk per request, so an edit lands on the next
        # load -- but a tab kept open for days never loads. Stamp the file's
        # mtime and let the page reload itself when it moves.
        self.send_header("X-Fleet-UI", _ui_version())
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload):
        self._send(json.dumps(payload).encode("utf-8"), "application/json")

    def _acting_ok(self):
        """Host and Origin for the routes that act on the machine.

        No token here: /api/open and the music routes predate the terminal and
        have to keep working with --terminal off. But they do act -- open a
        shell window, drive the music tab -- so a page on another origin must
        not be able to POST to them. Host stops DNS rebinding. Origin stops
        CSRF: a browser always sends it on a cross-origin POST, so refusing a
        foreign one is enough, while an absent Origin (curl, a script) is not a
        browser being tricked and is allowed.
        """
        if (self.headers.get("Host") or "") not in SAFE_HOSTS:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in SAFE_ORIGINS

    # ---- terminal guards --------------------------------------------------
    def _terminal_ok(self, need_origin):
        """Host, Origin and token, all three, or nothing.

        Host: a DNS-rebinding attacker resolves their own name to 127.0.0.1,
        so the browser sends `Host: evil.example:8787` -- rejected here.
        Origin: present on every cross-origin POST, including a plain form
        POST, so an allowlist is what stops CSRF.
        Token: fresh per process, only ever handed to a page that was served
        this document, and carried in a custom header, which forces a preflight
        that this server never answers.
        """
        if TERMINAL is None:
            return False
        if (self.headers.get("Host") or "") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return False
        # Origin is checked when present but no longer required: Firefox-family
        # browsers with the privacy setting that strips it (Zen ships it) send
        # same-origin POSTs with no Origin at all, which made every terminal call
        # from that browser fail. The token is the gate -- it never leaves the
        # served page, so a cross-origin form cannot carry it. `need_origin` is
        # kept in the signature so the call sites still read as intended.
        del need_origin
        token = self.headers.get("X-Fleet-Token") or ""
        return bool(TERMINAL_TOKEN) and secrets.compare_digest(token, TERMINAL_TOKEN)

    def _stream_terminal(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        broken = []

        def frame(event, payload):
            if broken:
                raise BrokenPipeError()
            self.wfile.write(("event: %s\ndata: %s\n\n"
                              % (event, json.dumps(payload))).encode("utf-8"))
            self.wfile.flush()

        try:
            TERMINAL.stream(frame, lambda: not broken)
        except (BrokenPipeError, ConnectionResetError, OSError):
            broken.append(True)

    def do_GET(self):
        global LAST_POLL
        path = self.path.split("?")[0]
        if path == "/api/state":
            LAST_POLL = time.time()
            self._send(SNAPSHOT.get(), "application/json")
            return
        if path == "/api/term/stream":
            # No Origin is normal on a same-origin GET, so this one leans on
            # Host + the custom-header token instead.
            if not self._terminal_ok(need_origin=False):
                self.send_error(404)
                return
            self._stream_terminal()
            return
        # Allowlisted static files. Not gated on the terminal: the sound bank
        # is in here too, and a board run without --terminal was getting a 404
        # for it and going silent.
        if path in VENDOR:
            name = os.path.basename(path)          # allowlisted, never joined raw
            with open(os.path.join(HERE, "vendor", name), "rb") as handle:
                self._send(handle.read(), VENDOR[path])
            return
        # The themes' faces, self-hosted so a world looks like itself on a
        # kiosk with no network. Basename only, .woff2 only, from one folder.
        if path.startswith("/vendor/fonts/"):
            name = os.path.basename(path)
            full = os.path.join(HERE, "vendor", "fonts", name)
            if name.endswith(".woff2") and os.path.isfile(full):
                with open(full, "rb") as handle:
                    body = handle.read()
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("X-Fleet-Boot", BOOT_ID)
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)
            return
        # Music reads are network-bound and far slower than anything else
        # here, which is exactly why they are their own endpoints and never
        # part of the snapshot: the board keeps its two-second budget, and
        # the threaded server means a slow YouTube call blocks only itself.
        if path.startswith("/api/music/"):
            query = parse_qs(urlparse(self.path).query)
            one = lambda k: (query.get(k) or [""])[0]
            try:
                if path == "/api/music/state":
                    self._json(music.state())
                elif path == "/api/music/playlist":
                    self._json(music.playlist(one("id")))
                elif path == "/api/music/search":
                    self._json({"tracks": music.search(one("q"))})
                elif path == "/api/music/now":
                    # Polled far more often than the rest of the music API, and
                    # cheap: one AppleScript round trip, cached for a beat.
                    self._json(music.now())
                else:
                    self.send_error(404)
            except Exception as exc:
                self._json({"error": "%s: %s"
                            % (type(exc).__name__, str(exc)[:200])})
            return
        if path in ("/", "/index.html"):
            self._send(page_bytes(), "text/html")
            return
        self.send_error(404)

    def _json_body(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size > 1 << 20:                     # a paste, not a novel
                return None
            return json.loads(self.rfile.read(size) or b"{}")
        except (TypeError, ValueError):
            return None

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/term/"):
            self._terminal_post(path)
            return
        if path not in ("/api/open", "/api/music/auth", "/api/music/forget",
                        "/api/music/play", "/api/music/cmd",
                        "/api/music/seek", "/api/name", "/api/flush",
                        "/api/close"):
            self.send_error(404)
            return
        # Opening a shell window and driving the music tab are both actions on
        # this machine; neither should be reachable from another origin.
        if not self._acting_ok():
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}")
        except (TypeError, ValueError):
            self._send(b'{"ok":false,"message":"bad request"}', "application/json")
            return

        # The one thing the browser may post that is not an id: the header
        # block copied out of the user's own YouTube Music tab. It is written
        # to a 0600 file and read back only by ytmusicapi -- it is never
        # echoed to any endpoint, and it never reaches a shell, so the
        # property that matters here still holds.
        if path == "/api/music/auth":
            try:
                music.configure(body.get("headers") or "")
                self._json({"ok": True, "message": "signed in to YouTube Music"})
            except Exception as exc:
                self._json({"ok": False, "message": "%s: %s"
                            % (type(exc).__name__, str(exc)[:200])})
            return
        if path == "/api/music/forget":
            music.forget()
            self._json({"ok": True, "message": "signed out"})
            return

        # Playback drives the music.youtube.com tab you already have open. As
        # with /api/open, the browser sends an id or one of three fixed words
        # and never a command: music.py rejects anything that is not the shape
        # of a YouTube id before it goes anywhere near AppleScript.
        if path == "/api/music/play":
            ok, message = music.play(str(body.get("id") or ""),
                                     str(body.get("list") or ""))
            self._json({"ok": ok, "message": message})
            return
        if path == "/api/music/cmd":
            ok, message = music.command(str(body.get("cmd") or ""))
            self._json({"ok": ok, "message": message})
            return
        if path == "/api/music/seek":
            ok, message = music.seek(body.get("to"))
            self._json({"ok": ok, "message": message})
            return

        # Flush is about the board, not about any one session, so it is
        # handled before the per-session lookup below.
        if path == "/api/flush":
            if body.get("undo"):
                back = DISMISSED.restore()
                self._json({"ok": True, "restored": back,
                            "message": "brought back %d session%s"
                                       % (back, "" if back == 1 else "s")})
                return
            gone = DISMISSED.flush(SNAPSHOT.sessions())
            self._json({"ok": True, "flushed": gone,
                        "message": ("nothing to flush" if not gone else
                                    "flushed %d finished session%s"
                                    % (gone, "" if gone == 1 else "s"))})
            return

        session = SNAPSHOT.session(body.get("id"))
        # Closing ends a process on this machine, so it carries the terminal's
        # per-page token on top of the Host/Origin gate whenever one is minted
        # (it always is under --terminal). The page sends it through termPost.
        if path == "/api/close":
            # Ending a process is the one action here that is not undoable, so
            # it needs the per-page token, full stop: with no token minted
            # (no --terminal) it is refused rather than left on Host+Origin.
            if not TERMINAL_TOKEN or not self._terminal_ok(need_origin=False):
                self.send_error(403)
                return
            if not session:
                self._json({"ok": False, "message": "unknown session"})
                return
            try:
                ok, message = sunset.close_session(session)
            except Exception as exc:
                ok, message = False, "%s: %s" % (type(exc).__name__, str(exc)[:160])
            if ok:
                DISMISSED.dismiss(session)     # off the board now, not next flush
            self._json({"ok": ok, "message": message})
            return
        if path == "/api/name":
            if not session:
                self._json({"ok": False, "message": "unknown session"})
                return
            self._rename(session, body.get("name"))
            return
        target = body.get("target")
        if not session or target not in ("iterm", "terminal", "vscode", "reveal"):
            self._send(b'{"ok":false,"message":"unknown session or target"}',
                       "application/json")
            return
        try:
            ok, message = actions.open_session(session, target)
        except Exception as exc:
            ok, message = False, "%s: %s" % (type(exc).__name__, exc)
        self._send(json.dumps({"ok": ok, "message": message}).encode("utf-8"),
                   "application/json")

    def _terminal_post(self, path):
        if not self._terminal_ok(need_origin=True):
            self.send_error(404)
            return
        # A cross-origin form POST cannot set this, and a cross-origin fetch
        # that does is preflighted -- one more thing between a stray tab and a
        # pty's stdin.
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self.send_error(404)
            return
        body = self._json_body()
        if body is None:
            self._send(b'{"ok":false,"message":"bad request"}', "application/json")
            return
        reply = {"ok": False, "message": "unknown terminal"}

        if path == "/api/term/open":
            # The page names a session, or a folder plus an agent key. It never
            # names a command: what the pty execs comes out of actions, from
            # the snapshot or from the FRESH table.
            rows = _bounded(body.get("rows"), 4, 200, 24)
            cols = _bounded(body.get("cols"), 20, 500, 80)
            if body.get("agent"):
                term, why = TERMINAL.open_at(str(body.get("cwd") or ""),
                                             str(body.get("agent")), rows=rows, cols=cols)
            else:
                session = SNAPSHOT.session(body.get("id")) or {}
                title = session.get("name") or "shell"
                term, why = TERMINAL.open(session, title, rows=rows, cols=cols)
            reply = ({"ok": True, "terminal": term.meta()} if term
                     else {"ok": False, "message": why})

        elif path == "/api/term/in":
            term = TERMINAL.get(body.get("tid"))
            if term:
                try:
                    data = base64.b64decode(body.get("b64") or "", validate=True)
                except (ValueError, TypeError):
                    data = b""
                reply = {"ok": term.write(data)}

        elif path == "/api/term/resize":
            term = TERMINAL.get(body.get("tid"))
            if term:
                term.resize(_bounded(body.get("rows"), 4, 200, 24),
                            _bounded(body.get("cols"), 20, 500, 80))
                reply = {"ok": True}

        elif path == "/api/term/close":
            reply = {"ok": TERMINAL.close(body.get("tid"))}

        else:
            self.send_error(404)
            return
        self._send(json.dumps(reply).encode("utf-8"), "application/json")

    def _rename(self, session, name):
        """Name a session on this board. Nothing is written to the agent.

        An empty or missing name resets the tile to whatever the collector
        detected, which is the same code path as clearing the alias.
        """
        if name is not None and not isinstance(name, str):
            self._json({"ok": False, "message": "name must be text"})
            return
        try:
            ok, message, shown = ALIASES.set(session, name or "")
        except OSError as exc:
            ok, message, shown = False, "could not save: %s" % exc, None
        self._json({"ok": ok, "message": message, "name": shown,
                    "detected": session.get("detectedName") or session.get("name"),
                    "aliased": bool(ok and shown
                                    and shown != session.get("detectedName"))})

    def log_message(self, *args):
        pass


def _ui_version():
    try:
        return str(int(os.stat(os.path.join(HERE, "ui.html")).st_mtime))
    except OSError:
        return "0"


# Set by the one route a browser cannot avoid calling. The terminal POSTs and
# the SSE stream are deliberately NOT counted: a page that has gone away can
# leave a socket half-open, and a pty still printing is covered by the
# live-terminal test in _idle_watch.
LAST_POLL = time.time()


def _idle_watch(seconds, server, stop):
    """Exit an unwatched instance. Never the kiosk: --kiosk sets seconds to 0.

    An instance exists to be looked at. If nothing has asked for /api/state in
    half an hour, nobody is looking, and the only thing it is still doing is
    spawning a few hundred processes a minute. Fifteen of these, started from
    agents' shells and never told to stop, once took 28% of the machine. The
    exemptions are the kiosk, excluded before this thread starts, and a live
    pty -- hanging up on somebody's `claude --resume` to save a tenth of a
    core is not a trade worth making.
    """
    while not stop.wait(30):
        if time.time() - LAST_POLL < seconds:
            continue
        if TERMINAL is not None and any(p.exited is None for p in TERMINAL._ptys.values()):
            continue
        print("no browser for %.0f min and no live terminal -- exiting" % (seconds / 60))
        threading.Thread(target=server.shutdown, daemon=True).start()
        return


def _bind(args):
    """The listener, or a loud exit. With --replace, SIGTERM the fleet
    instance holding the port (never the kiosk) and wait up to 4s for it."""
    for attempt in range(40):
        try:
            return ThreadingHTTPServer((args.host, args.port), Handler)
        except OSError as exc:
            held = instance.read(args.port) or {}
            if not args.replace or not held.get("pid"):
                raise SystemExit("cannot bind %s:%d (%s)%s"
                                 % (args.host, args.port, exc,
                                    "" if not held.get("pid")
                                    else " -- fleet pid %s is there; --replace to take it over"
                                         % held["pid"]))
            if held.get("kiosk"):
                raise SystemExit("refusing --replace on the kiosk instance (pid %s, port %d). "
                                 "Stop it with launchctl if you really mean to."
                                 % (held["pid"], args.port))
            if attempt == 0:
                try:
                    os.kill(int(held["pid"]), signal.SIGTERM)
                except OSError:
                    pass
            time.sleep(0.1)
    raise SystemExit("port %d is still held after 4s; not replacing" % args.port)


def _bounded(value, low, high, fallback):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--terminal", action="store_true",
                        help="serve a real terminal in the page (loopback only; "
                             "this is the one thing here that lets a browser "
                             "reach a shell, so it is off unless asked for)")
    parser.add_argument("--kiosk", action="store_true",
                        help="this is the always-on board: never idle-exit, and "
                             "--stop-strays will refuse to touch it")
    parser.add_argument("--replace", action="store_true",
                        help="SIGTERM whatever holds this port, then take it")
    parser.add_argument("--idle-exit", type=float, default=None, metavar="MINUTES",
                        help="exit after MINUTES with no browser poll and no live "
                             "terminal (default 30; 0 disables; --kiosk implies 0)")
    parser.add_argument("--list", action="store_true",
                        help="show running instances and exit")
    parser.add_argument("--stop-strays", action="store_true",
                        help="SIGTERM every instance except the kiosk (and this "
                             "port), and exit")
    args = parser.parse_args()

    if args.list:
        for e in instance.running():
            print("port %-5s pid %-7s %s  started %s  %s"
                  % (e.get("port"), e.get("pid"), "KIOSK" if e.get("kiosk") else "     ",
                     time.strftime("%H:%M:%S", time.localtime(e.get("started", 0))),
                     e.get("cwd")))
        raise SystemExit(0)
    if args.stop_strays:
        killed, spared = instance.stop_strays(keep_port=args.port)
        for e in spared:
            print("kept    port %s pid %s%s" % (e.get("port"), e.get("pid"),
                                                " (kiosk)" if e.get("kiosk") else ""))
        for e in killed:
            print("stopped port %s pid %s  %s" % (e.get("port"), e.get("pid"), e.get("cwd")))
        print("%d stopped, %d kept" % (len(killed), len(spared)))
        raise SystemExit(0)

    # Line-buffer stdout: a leaked instance whose log is empty because the
    # startup lines never left an 8KB buffer is a leak you cannot diagnose.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    set_safe_origins(args.port)
    module = enable_terminal(args.host, args.port) if args.terminal else None

    SNAPSHOT.start()
    # Bind first: EADDRINUSE from the kernel is the authoritative answer on the
    # port, and a claim written for an instance that then fails to bind is
    # worse than none.
    server = _bind(args)
    claim = instance.Claim(args.port, kiosk=args.kiosk).take(replace=args.replace)

    idle = 0.0 if args.kiosk else (30.0 if args.idle_exit is None else args.idle_exit)
    stop = threading.Event()
    if idle > 0:
        threading.Thread(target=_idle_watch, args=(idle * 60, server, stop),
                         daemon=True, name="idle-exit").start()

    # SIGTERM must run the same shutdown path as Ctrl-C, or a killed instance
    # leaves its pty children orphaned exactly the way the instances
    # themselves were orphaned.
    def _bye(signum, frame):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _bye)

    print("agent dashboard  ->  http://%s:%d%s"
          % (args.host, args.port, "  (kiosk)" if args.kiosk else
             "  (exits after %g idle min)" % idle if idle else ""))
    if module:
        print("terminal         ->  on, loopback only, %d max" % module.MAX_TERMINALS)
    try:
        server.serve_forever()
    finally:
        if module:
            module.TERMINALS.shutdown()
        claim.release()
        print("bye")


if __name__ == "__main__":
    main()
