# fleet-dashboard — CPU / memory review

Tree reviewed: `/Users/tiago/.local/share/fleet-dashboard/` (the live install, pid 78519,
port 8787, under `com.tiago.fleet-dashboard`). The stale copies in `~/Documents/Dev/`
were not profiled or quoted.

All timings were taken on this machine, against these modules, with harnesses in
`/private/tmp/claude-501/.../scratchpad/` (`spawns.py`, `rusage.py`, `childcpu.py`,
`transcripts.py`, `lsof.py`). Nothing was installed. No project file was edited and no
process was signalled by me.

**Two measurement regimes appear below**, because the 15 stray instances were killed
mid-review by the orchestrator:

- *contended* — 16 dashboards live, ~898 processes on the machine
- *clean* — one dashboard, after the cleanup

The difference is itself a finding, so both are kept.

---

## 1. Headline

The single most important number in this report is not a percentage, it is a ratio.

> **One instance truly costs 11.7% of one core. `ps` and `top` report it as 1.4%.
> 88% of its CPU is spent in short-lived child processes that no process monitor
> attributes to `dashboard.py`.**

Measured with `resource.getrusage(RUSAGE_SELF)` vs `RUSAGE_CHILDREN` across 10 rebuilds
on the clean machine. This is why the live instance looked like the cheapest thing on
the board at 0.1–1.0% while the machine felt slow: the cost is real, it is just
invisible to the tool everyone reaches for. Every `ps`-derived figure about this
dashboard — including the 27.8% aggregate that opened this review — is an **~8x
undercount**.

The mechanism is spawn churn, not computation:

| per instance, clean machine | measured |
|---|---|
| subprocess spawns per rebuild | **9.2** |
| subprocess spawns per minute (2s loop) | **275** |
| share of rebuild wall time spent in subprocesses | **90%** |
| child minor page faults per rebuild | **~9,700** |
| child minor page faults per minute | **~291,000** |
| child involuntary context switches per 10 rebuilds | 4,876 (contended: 23,853) |

At 16 instances that was ~4,400 spawns/minute and ~4.7M page faults/minute. That is
the "machine gets slower" sensation: scheduler and VM churn, not a CPU number.

---

## 2. Measured numbers

### 2a. The rebuild loop

| what | clean | contended (16 procs) | README claim | verdict |
|---|---|---|---|---|
| `Snapshot._build()` typical pass | **166–168 ms** (med 168) | 394–640 ms | ~165 ms | **claim is accurate — on an uncontended machine** |
| `_build()` on a roster-refresh pass | **480 ms** | up to 1,876 ms | not stated | every 3rd pass costs 3x |
| live instance's own `buildMs` field, 8 samples over 20 s | 142, **348**, 162, 153, 164, 148, 163, 142 | — | ~165 ms | matches; the 348 is a roster pass |
| `claude agents --json` (wall) | **262 ms** | 730–1,170 ms | ~350 ms | accurate clean; 3–4x worse under load |
| `claude agents --json` (child CPU) | **186 ms** | — | — | 12,301 minor faults per launch |
| everything except the roster | **~90 ms** child CPU | — | "~90ms for everything else" | **claim is accurate** |

The README's performance budget is **honest**. It was measured on a quiet machine and
it holds on a quiet machine. What it does not say is that the budget is ~90% subprocess
time, so it degrades superlinearly the moment anything else competes — which is exactly
what 15 copies of itself did.

### 2b. Where the subprocess time goes (clean, child CPU)

| component | spawns/min | child CPU per call | child CPU per rebuild | minor faults/call |
|---|---|---|---|---|
| `ps -Ao pid=,rss=,pcpu=,args=` (metrics) | 30 | **42.2 ms** | 42.2 ms | 1,309 |
| `ps -Ao pid=,etime=,args=` (collectors) | 30 | **38.9 ms** | 38.9 ms | 1,308 |
| `lsof -a -p <pid> -d cwd` | **60** | 12.2 ms | 24.4 ms | 264 |
| `pmset -g batt` | 30 | 6.4 ms | 6.4 ms | 452 |
| `sysctl hw.memsize` + `vm_stat` | 60 | 3.5 ms | 3.5 ms | 487 |
| `sysctl kern.boottime` | 30 | 2.1 ms | 2.1 ms | 255 |
| `sysctl vm.swapusage` | 30 | 1.8 ms | 1.8 ms | 244 |
| `memory_pressure -Q` (15 s cache) | 2.5 | 3.5 ms | 0.3 ms | — |
| `claude agents --json` (6 s clock) | 10 | 186.3 ms | 31.1 ms amortised | 12,301 |
| **fixed cost every pass** | | | **~89 ms** | ~4,000 |
| **total incl. amortised node** | **275** | | **~120 ms** | ~9,700 |
| self CPU in the Python process | | | 28 ms | |

Duty cycle: `3 x 89 + 186 + 3 x 28 = 537 ms of CPU per 6 seconds = 9.0% of one core`,
which agrees with the 11.7% from rusage (that run refreshed the roster slightly more
often). Call it **~10% of one core, steady state, forever.**

### 2c. Three concrete defects in the hot path

**(i) `_cwd_cache` never caches — an int/str key mismatch purges it every pass.**
`collectors.py:856` stores under a **string** pid; `collectors.py:918-921` purges using a
set of **ints**:

```python
found.append({"pid": int(pid), "cwd": _process_cwd(pid), ...})   # _process_cwd gets a str
...
alive = {p["pid"] for p in found}        # ints
for pid in list(_cwd_cache):             # str keys
    if pid not in alive:                 # always True
        _cwd_cache.pop(pid, None)        # -> cache emptied every single pass
```

Proven (`lsof.py`): three consecutive passes, same pid 14649, cwd resolved correctly to
`/Users/tiago` every time, `lsof` spawned **3 times**, and `_cwd_cache` is `{}` at the
end. Cost: **60 `lsof` spawns/minute, 24.4 ms child CPU per rebuild** — and it scales
with the number of running `codex`/`agy` processes, so a busy fleet pays multiples of
this. A second, independent bug sits next to it: `_process_cwd` does not cache a
negative result either, so any pid whose cwd `lsof` cannot read is re-spawned forever.

**(ii) Two full process-table walks per rebuild.** `metrics.processes()` runs
`ps -Ao pid=,rss=,pcpu=,args=` and `collectors._ps()` runs `ps -Ao pid=,etime=,args=`.
The README celebrates collapsing three `ps` calls into one inside the collectors; the
telemetry module was never folded in. Combined: **81 ms child CPU and 2,617 page faults
per rebuild, 60 spawns/minute**, for data one invocation supplies. This also has a
feedback loop: `ps -A` cost rises with the process count, so instance leakage made every
instance's `ps` slower.

**(iii) Constants are re-read as if they were telemetry.** `kern.boottime` cannot change
while the process lives, and `hw.memsize` cannot change at all; both are spawned **30
times a minute**. `pmset -g batt` is polled at 2 s for a reading that moves on a scale of
minutes, while the genuinely useful `memory_pressure` is correctly cached at 15 s.

### 2d. Incremental transcript reading — the README claim holds

| measured | result |
|---|---|
| cold read of the 44.8 MB transcript | **915 ms** (49 MB/s) |
| warm re-read, no new bytes | **0.003 ms** (a single `stat`, no `read`) |
| `path_for` cache hit | 0.005 ms |
| `path_for` miss (`glob` over 94 project dirs) | 0.6 ms |
| files `stat`'d per warm pass | one per roster entry (2 today), not 240 |

Incremental reading genuinely works: `Transcripts.read` stats, compares `st_size` to the
stored offset, and returns immediately when nothing was appended. Two caveats:

- **A cold read blocks the rebuild thread.** The first time a session with a large
  transcript enters the roster, the loop stalls for up to ~900 ms (45 MB at 49 MB/s).
  The archive already holds a 44.8 MB file, and `~/.claude/projects` is 805 MB over 240
  files, so this is not hypothetical. The board freezes for a second when a big session
  appears.
- **The offset dictionary is unbounded.** `_entries` is keyed by path and never evicted;
  one entry pickles to **21.3 KB** (it holds the compact summary, first prompt, last two
  assistant turns). 240 transcripts would be ~5 MB. Not today's problem — the live
  instance is at 22 MB RSS — but it only ever grows.

### 2e. The request path and SSE — genuinely cheap, no re-serialisation

| measured | result |
|---|---|
| `GET /api/state`, mean of 10 | **1.2 ms**, 36,842 byte payload |
| `GET /` (222 KB `ui.html`) | **1.6–2.4 ms** |
| snapshot re-serialised per request? | **no** |

`Snapshot._build()` ends with `json.dumps(...).encode()` and stores the **bytes**;
`get()` returns that object and `_send` writes it. One serialisation per 2 s however
many clients poll. This part of the design is exactly as advertised.

The SSE terminal stream costs one thread blocked on `outbox.get(timeout=1.0)` per client
— one wakeup/second, plus a ping every 15 s when idle. With no pty open, `attached` is
empty and nothing is copied. Negligible.

One observation rather than a defect: the live payload is **36.8 KB** and the page fetches
it **every second** while the server only rebuilds every two, so half of all polls
re-transfer and re-`JSON.parse` a snapshot the page already has. The page does guard the
expensive half — `tick()` compares `d.generatedAt` to `renderedSnapshotAt` and skips
`render()` — and `render()` guards again on a signature of `d.lanes` + UI state + a
5-second clock bucket (`ui.html:2843-2847`), so DOM work is correctly rare. The waste is
~36 KB/s of loopback traffic and a parse, not layout. An `If-None-Match`/304 on
`generatedAt` would remove it, but it is not where the money is.

### 2f. Memory

| measured | result |
|---|---|
| live instance RSS, 20 min uptime | **22.7 MB** |
| `~/Library/Logs/fleet-dashboard.log` | **4.6 KB** after 8 h — no accumulation |
| `self._history` | bounded, `450` samples, confirmed at cap via `/api/state` |
| `Transcripts._entries` | **unbounded**, 21.3 KB/entry |
| `Transcripts._paths` | unbounded, tiny |
| `collectors._agy_cache` | bounded by conversation count (74 `.db` files today) |
| `music._cache` | **unbounded** — `_cached("q:"+query, 600, ...)` keys on every search string and never evicts expired entries |
| `metrics._slow_cache` | bounded, 3 keys |
| `collectors._cwd_cache` | bounded (and, per 2c(i), always empty) |

Nothing is leaking at a rate that matters today. The log is clean because
`Handler.log_message` is a no-op — good. Two unbounded dicts are worth a cap on
principle, not urgency.

---

## 3. Part 1 — why instances leak, and how to make it impossible

### 3a. What actually started and orphaned them — proven, not inferred

Each dev tree carries its own copy of the tooling and, decisively, a **zero-byte
`server.log`** whose mtime matches its orphan's start time to the minute:

| tree | `server.log` mtime | orphan | started |
|---|---|---|---|
| `/private/tmp/theme-b` | 13:37 | 89262, port 8802 | 13:37:32 |
| `/private/tmp/agentio` | 13:54 | 44775, port 8804 | 13:54:29 |
| `/private/tmp/idpass-3` | 14:06 | 96902, port 8813 | 14:06:55 |
| `/private/tmp/marks` | 14:14 | 47745, port 8816 | 14:14:50 |

That file is a shell redirect: something ran, from an agent's Bash tool,

```
python3 dashboard.py --port 88NN > server.log 2>&1 &
```

The tool call's shell exits, the child is reparented to pid 1, and **nothing in
`dashboard.py` ever makes it stop.** `KeepAlive` on the LaunchAgent is a red herring — it
governs only pid 78519. These were never launchd jobs.

Two corroborating details:

- **All 15 died on plain SIGTERM.** They were responsive, not wedged. They were simply
  never told to exit.
- **Every `server.log` is empty**, even though `main()` prints two startup lines. Python
  block-buffers stdout when it is a file rather than a tty, so those lines sat in an 8 KB
  buffer until SIGTERM discarded them. A leaked instance was therefore *undiagnosable
  from its own log*. Fix with `python3 -u` or `sys.stdout.reconfigure(line_buffering=True)`.

And the code confirms the absence: `grep -n 'signal|atexit|SIGTERM|pidfile|lock|getppid|setsid'`
over `dashboard.py` returns **no matches**. No pidfile, no lock, no signal handler, no
parent-death check, no idle timeout. `serve_forever()` runs until KeyboardInterrupt;
every worker thread is a daemon, so nothing else even holds the process open. An instance
is immortal by construction.

One thing that *does* already work: **`SO_REUSEADDR` does not let two listeners share a
port on macOS.** I verified a second bind to 8787 fails with `EADDRINUSE`. So "one per
port" is already enforced by the kernel. The leak was never two-on-one-port; it was
fifteen on fifteen *different* ports, each invisible to the next. **The missing piece is
not mutual exclusion — it is a registry, and an expiry.**

This also means the dev copies were not the problem in themselves: all three
`collectors.py` I compared (`theme-b`, `marks`, live) carry the same `ROSTER_SECONDS` and
`_ps_cache` optimisations. Fifteen *correct* instances were enough.

### 3b. The guard — actual code

Design constraints, in order:

1. `--port` must stay variable; two deliberate instances on two ports must still work.
2. The kiosk on 8787 must never exit and must never be killable by the stray-sweeper.
3. A guard that relies on a pid written to a file goes stale on SIGKILL. `flock` does
   not — the kernel drops it when the process dies, however it dies. Use the lock for
   liveness and the file only for description.
4. Nothing may signal a pty's children out from under a running `claude --resume`.

New module, `instance.py`:

```python
"""One registry entry per running dashboard, and an expiry for the ones nobody watches.

The kernel already enforces one listener per port (SO_REUSEADDR does not share a
listening socket on macOS: a second bind gets EADDRINUSE). What it does not give you is a
way to FIND the instance you started an hour ago on a port you have forgotten. That is
what this is for.

Liveness comes from flock, not from the pid in the file: the kernel releases a flock when
the holder dies, whatever kills it, so a lock that can be taken is proof the previous
holder is gone. The JSON beside it is description only, and is allowed to be stale.
"""

import errno
import fcntl
import json
import os
import signal
import sys
import time

RUN_DIR = os.path.join(os.path.expanduser("~"), ".config", "fleet", "run")


def _paths(port):
    return (os.path.join(RUN_DIR, "%d.lock" % port),
            os.path.join(RUN_DIR, "%d.json" % port))


class Claim:
    """An exclusive, self-releasing claim on one port."""

    def __init__(self, port, kiosk=False):
        self.port = port
        self.kiosk = kiosk
        self._fd = None

    def take(self, replace=False):
        os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)
        lock, desc = _paths(self.port)
        self._fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        for attempt in range(40):                      # up to 4s when replacing
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                held = read(self.port)
                if not replace:
                    # Loud, never silent, and never a different port.
                    raise SystemExit(
                        "port %d is already served by fleet pid %s (started %s, cwd %s).\n"
                        "  take it over:   --replace\n"
                        "  look around:    --list\n"
                        "  clear the rest:  --stop-strays"
                        % (self.port, (held or {}).get("pid", "?"),
                           time.strftime("%H:%M:%S",
                                         time.localtime((held or {}).get("started", 0))),
                           (held or {}).get("cwd", "?")))
                if held and held.get("kiosk"):
                    raise SystemExit(
                        "refusing --replace on the kiosk instance (pid %s, port %d). "
                        "Stop it with launchctl if you really mean to."
                        % (held.get("pid"), self.port))
                if attempt == 0 and held and held.get("pid"):
                    os.kill(int(held["pid"]), signal.SIGTERM)
                time.sleep(0.1)
        else:
            raise SystemExit("port %d is still held after 4s; not replacing" % self.port)

        os.ftruncate(self._fd, 0)
        os.write(self._fd, b"%d\n" % os.getpid())
        tmp = desc + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "port": self.port, "kiosk": self.kiosk,
                       "cwd": os.getcwd(), "argv": sys.argv,
                       "started": int(time.time())}, handle)
        os.replace(tmp, desc)
        return self

    def release(self):
        if self._fd is None:
            return
        _, desc = _paths(self.port)
        try:
            os.unlink(desc)
        except OSError:
            pass
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None


def read(port):
    _, desc = _paths(port)
    try:
        with open(desc, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _alive(port):
    """True only if the lock cannot be taken -- i.e. a live process holds it."""
    lock, _ = _paths(port)
    try:
        fd = os.open(lock, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False                       # we took it, so nobody holds it
    except OSError:
        return True
    finally:
        os.close(fd)


def running():
    """Every live instance, newest last. Stale descriptions are swept as we go."""
    out = []
    try:
        names = sorted(os.listdir(RUN_DIR))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            port = int(name[:-5])
        except ValueError:
            continue
        entry = read(port) or {}
        if _alive(port):
            entry["port"] = port
            out.append(entry)
        else:
            for path in _paths(port):      # nobody holds it: the files are litter
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return sorted(out, key=lambda e: e.get("started", 0))


def stop_strays(keep_port, dry_run=False):
    """SIGTERM every instance except the kiosk. Two independent safeties.

    An instance is spared if it declared itself the kiosk, OR if it is on the port we
    were told to keep. Either alone is enough, so a missing/corrupt description cannot
    cost you the board.
    """
    killed, spared = [], []
    for entry in running():
        port, pid = entry.get("port"), entry.get("pid")
        if entry.get("kiosk") or port == keep_port or pid in (None, os.getpid()):
            spared.append(entry)
            continue
        if not dry_run:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                continue
        killed.append(entry)
    return killed, spared
```

Wiring in `dashboard.py`. Note that **the bind comes first**: `EADDRINUSE` is the
authoritative answer about the port, and failing there means we never write a registry
entry for an instance that was not going to start.

```python
# --- main(), replacing the current body ---
parser.add_argument("--kiosk", action="store_true",
                    help="this is the always-on board: never idle-exit, and "
                         "--stop-strays will refuse to touch it")
parser.add_argument("--replace", action="store_true",
                    help="SIGTERM whatever holds this port, then take it")
parser.add_argument("--idle-exit", type=float, default=None, metavar="MINUTES",
                    help="exit after MINUTES with no browser poll and no live "
                         "terminal (default 30; 0 disables; --kiosk implies 0)")
parser.add_argument("--list", action="store_true", help="show running instances and exit")
parser.add_argument("--stop-strays", action="store_true",
                    help="SIGTERM every instance except the kiosk, and exit")
args = parser.parse_args()

import instance
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

# Line-buffer stdout: a leaked instance whose log is empty because the startup
# lines never left an 8KB buffer is a leak you cannot diagnose.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass

set_safe_origins(args.port)
module = enable_terminal(args.host, args.port) if args.terminal else None

SNAPSHOT.start()
# Bind first: EADDRINUSE from the kernel is the authoritative answer on the port,
# and a claim written for an instance that then fails to bind is worse than none.
try:
    server = ThreadingHTTPServer((args.host, args.port), Handler)
except OSError as exc:
    held = instance.read(args.port) or {}
    raise SystemExit("cannot bind %s:%d (%s)%s"
                     % (args.host, args.port, exc,
                        "" if not held.get("pid")
                        else " -- fleet pid %s is there; --replace to take it over"
                             % held["pid"]))
claim = instance.Claim(args.port, kiosk=args.kiosk).take(replace=args.replace)

idle = 0.0 if args.kiosk else (30.0 if args.idle_exit is None else args.idle_exit)
stop = threading.Event()
if idle > 0:
    threading.Thread(target=_idle_watch, args=(idle * 60, server, stop),
                     daemon=True, name="idle-exit").start()

# SIGTERM must run the same shutdown path as Ctrl-C, or a killed instance leaves its
# pty children orphaned exactly the way the instances themselves were orphaned.
def _bye(signum, frame):
    stop.set()
    threading.Thread(target=server.shutdown, daemon=True).start()
for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
    signal.signal(sig, _bye)

print("agent dashboard  ->  http://%s:%d%s"
      % (args.host, args.port, "  (kiosk)" if args.kiosk else ""))
try:
    server.serve_forever()
finally:
    if module:
        module.TERMINALS.shutdown()
    claim.release()
```

and the idle watch, alongside `Snapshot`:

```python
# Set by the one route a browser cannot avoid calling. The terminal POSTs and the SSE
# stream are deliberately NOT counted: a page that has gone away can leave a socket
# half-open, and a pty still printing is covered by the live-terminal test below.
LAST_POLL = time.time()


def _idle_watch(seconds, server, stop):
    """Exit an unwatched instance. Never the kiosk: --kiosk sets seconds to 0.

    An instance exists to be looked at. If nothing has asked for /api/state in half an
    hour, nobody is looking, and the only thing it is still doing is spawning ~275
    processes a minute. The two exemptions are the kiosk, which is excluded before this
    thread is ever started, and a live pty -- hanging up on somebody's `claude --resume`
    to save 10% of a core is not a trade worth making.
    """
    while not stop.wait(30):
        if time.time() - LAST_POLL < seconds:
            continue
        if TERMINAL is not None and any(p.exited is None for p in TERMINAL._ptys.values()):
            continue
        print("no browser for %.0f min and no live terminal -- exiting" % (seconds / 60))
        threading.Thread(target=server.shutdown, daemon=True).start()
        return
```

with one line added to `do_GET`:

```python
if path == "/api/state":
    global LAST_POLL
    LAST_POLL = time.time()
    self._send(SNAPSHOT.get(), "application/json")
    return
```

and the LaunchAgent gains one argument — **this is the change that makes idle-exit safe**,
and it must land in `install.sh`'s heredoc as well as the installed plist:

```xml
<string>--port</string><string>8787</string>
<string>--terminal</string>
<string>--kiosk</string>
```

### 3c. Should idle-exit be the default? Yes — and opt-out, not opt-in.

The argument for opt-out: the failure we actually suffered was fifteen instances that
nobody could see and nobody had a way to find. Any guard that must be *remembered* at
launch would have been forgotten in exactly the same Bash tool calls that created the
leak — an agent writing `python3 dashboard.py --port 8802 &` will not also write
`--idle-exit 30`. The default has to protect the case where nobody thought about it.

The kiosk is the one instance anyone ever *does* think about: it is installed once, by
`install.sh`, into a plist. Putting the opt-out there is cheap, explicit, and reviewable
— and it is belt-and-braces, because `KeepAlive` would restart the kiosk within seconds
even if the flag were ever lost. A dev instance has no such safety net, which is the
asymmetry that settles the direction of the default.

30 minutes, not 5: a dev instance routinely sits unwatched while its author reads code,
and being killed mid-review is the kind of annoyance that gets the feature disabled
wholesale. 30 minutes bounds the damage to one instance-hour of churn while never
surprising anyone in a working session.

The live-pty exemption matters more than the timeout value. `terminal.py` can be hosting
a `claude --resume`, and `IDLE_KILL_SECONDS` is 2 hours precisely because that session
must not be hung up on. Idle-exit must respect the same rule or it becomes a way to lose
work.

### 3d. `flush.py` is not this — and it is not broken either

`flush.py` is **tile dismissal**, not process reaping. It writes
`~/.config/fleet/dismissed.json` recording "I have seen this session at this `updated`
timestamp, stop drawing it", and `Dismissed.apply()` drops those sessions from the
snapshot. Its own docstring is unambiguous: *"It never signals, kills or deletes
anything."* The name collision with "flush the strays" is unfortunate, nothing more.

As tile dismissal it is **correct**, and better built than it needs to be: writes go
through `NamedTemporaryFile` + `os.replace` so a crash cannot leave a half-parsed file;
`_load()` stats before parsing and keys the cache on `(st_mtime, st_size)` so hand-editing
lands within a refresh; a corrupt file degrades to one lost flush rather than a blank
board; `FLUSHABLE` excludes `running`/`blocked`/`waiting` so live work can never be
dismissed; and an entry self-expires when the session writes anything newer. The one
thing it lacks is any bound on the dict — dismissals accumulate for sessions whose
transcripts have been deleted and which will therefore never revive to clear themselves.
A mtime-based sweep (drop entries older than `STALE_MS`) would close that.

It is worth keeping the two ideas separately named. I would add `--stop-strays` to
`dashboard.py` (above) and leave `flush.py` alone.

### 3e. Can `--terminal` leak child shells the same way? Yes — and only partly reaped.

What works:

- `Terminals._reaper` runs every 60 s and `kill()`s any pty with **no subscribers** idle
  past `IDLE_KILL_SECONDS` (2 h), and forgets dead ones 60 s after exit.
- `Pty._pump` ends in `_reap()`, which `waitpid`s the child, so a shell that exits
  normally is not left a zombie.
- `stream()`'s `finally` detaches the sink, so a browser that goes away stops counting as
  a subscriber within ~15 s (the ping interval is what makes the write fail).
- `kill()` uses `os.killpg(os.getpgid(pid), SIGHUP)`, so it takes the whole process group
  — a shell's own children go with it. `pty.fork()` makes the child a session leader,
  which is what makes that group correct.

What does not:

- **`TERMINALS.shutdown()` only runs on a clean exit.** It is in `main()`'s `finally`,
  reachable from `KeyboardInterrupt` or a normal return. On SIGTERM — the default, and
  how all 15 strays died — the process terminates without unwinding, and every pty child
  is reparented to pid 1 with no reaper. **A leaked dashboard with `--terminal` leaks
  shells too.** Note that one of the 15 strays (pid 53671, port 8805) *was* running
  `--terminal`. The `_bye` handler in 3b fixes this: it routes SIGTERM/SIGHUP through
  `server.shutdown()` so the `finally` runs.
- Independently, the machine already holds orphaned long-lived shells from other tooling
  (`11812`, `11934` — `/bin/zsh .../servir.sh ... while :; do sleep 5; done`, reparented
  to pid 1, up 2 days). Same class of bug, different owner; out of scope, but it shows the
  pattern is not unique to this tree.

---

## 4. Part 3 — the browser side

### 4a. The page is not being viewed in Chrome

`lsof -nP -iTCP:8787` shows the two established connections to the server coming from
**`zen` (pid 43996)** — Zen Browser, a Firefox fork — not Chrome. Two sockets is exactly
right for one dashboard tab: the 1 Hz `/api/state` poll and the persistent
`/api/term/stream` SSE.

Measured on the clean machine with `top -l 4` (instantaneous, last sample):

| process | %CPU (one core) | MEM |
|---|---|---|
| **`Zen GPU Helper`** | **27.8%** | 919 MB |
| **`zen`** (parent) | **13.9%** | 838 MB |
| `WindowServer` | 17.0% | 612 MB |
| `dashboard.py` (pid 78519) | 0.3% apparent / **~10% true** | 22.7 MB |

**The browser side costs roughly 3–4x the Python server.** Caveat, stated plainly: `zen`
and its GPU helper are shared across every tab the user has open, and I could not isolate
the dashboard tab without disrupting the session. What makes the attribution more than a
guess is the *shape* of it — a GPU helper sustained at 27.8% with `WindowServer` at 17%
on an otherwise quiet machine is continuous compositing, and the only thing on this
machine that is always on screen and always animating is this kiosk.

Separately: **Chrome is leaked too** — 37 processes, **923 MB RSS**, and at the earlier
census seven distinct browser processes, four started within the same second (08:32:40),
several with a GPU process, network service and storage service but **no renderer at all**
— browser shells with no content. `fleet.command` uses `open -na "Google Chrome" --args
--app=...`, and `-n` forces a *new instance* every invocation. Run it four times and you
get four Chromes. That is a second, independent leak in the same family as Part 1, and it
costs about a gigabyte. (`open -a` without `-n`, or reusing a named `--user-data-dir`,
would reuse the existing instance.)

### 4b. What is forcing continuous paint

Two full-viewport `position:fixed` overlay layers exist in **every** theme, independent of
theme choice:

- `body::before` (`ui.html:100`) — `position:fixed; inset:0`, a 3 px-pitch
  `repeating-linear-gradient` scanline plus an 1100x640 `radial-gradient` halo.
- `.wrap::after` (`ui.html:578`) — `position:fixed; inset:0; z-index:2`, a radial vignette.

Specific themes add a third and fourth (`body::after`, `.wrap::before`). At the Air's
2x DPI a full-viewport layer is ~16 MB of texture, so the steady state is **2–4 full-screen
composited layers, always resident**, before any theme decoration.

On the grain: the `feTurbulence` data URIs (20 of them, up to a 320x320 tile with four
chained filters) are `background-image`s, so Gecko and Blink rasterise each **once per
(tile size, zoom)** into the image cache and reuse it. They are a startup and
theme-switch cost, not a per-frame one — **with one exception**, which is the real defect:

> **`background-attachment: fixed` appears 6 times** (`ui.html:1493, 1498, 1525, 1608, 1613,
> 1643` — the `vellum` and `hoarstone` themes), applied to `.bubble`, `.project`, `.lane`,
> `.panel`, `.stat`, `.chip`. A fixed-attachment background cannot be scrolled as a
> composited layer: the element must be re-rasterised against viewport coordinates on
> every scroll and on every layer change. Applying it to *every tile* makes the grain the
> most expensive thing on the page in those two themes.

Animations, corrected — the brief's worry about an always-on `drift` is **already moot**:

| keyframe | target | scope | cost |
|---|---|---|---|
| `drift` 7s | `[data-theme=cyber] body::after` | **dead** — overridden to `animation:none` at `ui.html:690` | none |
| `pulse` 2.2s | `.bubble[data-state=blocked]::before` | **always on when any session is blocked** | `opacity` — composited, cheap per frame, but it pins the compositor at 60 fps forever |
| `sig-tear` 11s | `[data-theme=signal] .wrap::after` | that theme only | `transform` — composited |
| `vhs-roll` 5.5s | `[data-theme=miami86] .wrap::after` | that theme only | `transform` — composited |
| `hillroll` 1.15s | `[data-theme=chequer] .project>header::after` | **hover only** | animates `background-position` — **not** composited, repaints every frame; scoped tightly enough to forgive |

`prefers-reduced-motion: reduce` covers **all five** (`ui.html:112, 290, 973-976, 1269, 1680`).
That is genuinely good coverage — and it means **enabling System Settings → Accessibility
→ Display → Reduce motion is a zero-code fix that stops every animation on the board.**
What it will not do is remove the static full-screen overlay layers, which is where the
compositing cost actually lives.

Also absent, and all cheap to add: **no `will-change` anywhere, no `content-visibility`,
no `contain`, and no `visibilityState` handling at all.** The 1 Hz clock `setInterval`
(`ui.html:3186`), the 400 ms music seek-bar repaint (`ui.html:3315`), the 2 s `localStorage`
write (`ui.html:3357`) and the 1 Hz poll all keep running when the window is occluded.
Browsers throttle timers in *hidden* tabs, but a fullscreen kiosk window is never hidden —
so on the Air this never kicks in.

### 4c. Cheap browser fixes that cost the themes nothing

1. **Delete `background-attachment: fixed` (6 sites).** The grain tiles at 140–420 px; on
   a tile-sized element a scrolling attachment is visually indistinguishable and removes a
   forced re-raster per scroll. Biggest single browser win, lowest risk.
2. **Merge `body::before` and `.wrap::after` into one fixed layer.** They are both
   full-viewport, both `pointer-events:none`, and differ only in `z-index` (0 vs 2).
   Where the z-order genuinely matters, keep two — but that is two layers, not the three
   or four some themes reach.
3. **`contain: paint` on `.bubble` and `.project`.** These are clipped boxes already
   (`overflow:hidden`); declaring it lets the engine skip descendants outside the clip and
   bounds invalidation to the tile when one session changes.
4. **`content-visibility: auto` + `contain-intrinsic-size` on `.project`** when a group
   scrolls (the README notes groups scroll below the legibility floor). Skips layout and
   paint for off-screen groups entirely.
5. **`will-change: transform` on the three animated `::after` overlays only** — and
   nowhere else. `will-change` is a promotion hint that costs a permanent texture, so
   sprinkling it is a pessimisation; on a layer that is *already* being transform-animated
   it just stops the promote/demote churn.
6. **Pause on `visibilitychange`** — one listener toggling a class that sets
   `animation-play-state: paused`, plus skipping `tick()` while hidden. Matters less for
   the kiosk than for the second window the user inevitably opens.
7. Consider `--glow: 0`-style discipline on the 83 `box-shadow` declarations: blur radii
   reach 60 px, and large-radius shadows are a real rasterisation cost. Nine declarations
   use >= 28 px. Lower value than 1–4, and it touches the look, so it belongs to whoever
   is auditing the aesthetics.

*(One visual bug noted in passing, not pursued: `drift` at `ui.html:109` is unreachable
because `ui.html:690` sets `animation:none` on the same selector. If neon film is meant to
have its scanline drift, it does not.)*

---

## 5. Ranked changes, by measured saving ÷ effort

Savings are per instance, as child CPU per rebuild on the clean machine, against a
measured baseline of ~89 ms fixed + 31 ms amortised node + 28 ms self.

| # | change | measured saving | effort | notes |
|---|---|---|---|---|
| **1** | **`--kiosk` + `instance.py` + SIGTERM handler + `--list`/`--stop-strays` + line-buffered stdout** | **everything a leaked instance would have cost: ~10% of one core and 275 spawns/min, each** | ~150 lines, one new module, one plist line | Not a micro-optimisation — it is the bug. The fifteen strays were 15x the entire rest of this list. |
| **2** | **Merge the two `ps -A` walks into one `ps -Ao pid=,rss=,pcpu=,etime=,args=`** | **38.9 ms/rebuild (44% of fixed cost), 30 spawns/min, ~1,300 page faults/rebuild** | ~20 lines: widen `collectors._ps`, pass its output into `metrics.processes(ps_output)` | Highest saving-per-line in the whole report. The README already did this *within* the collectors; telemetry was missed. |
| **3** | **Fix `_cwd_cache` int/str key mismatch (`collectors.py:918`) and cache negative lookups** | **24.4 ms/rebuild, 60 spawns/min** — and it scales with the number of live `codex`/`agy` processes | **one line** (`alive = {str(p["pid"]) for p in found}`) plus ~3 for the negative cache | Best ratio of anything here. A confirmed bug, not a tuning decision. |
| **4** | **Cache the constants**: read `hw.memsize` and `kern.boottime` once per process; `_cached("power", 30, ...)` on `pmset -g batt` | **~10 ms/rebuild, 75 of 275 spawns/min** | ~6 lines, the `_cached` helper already exists | `kern.boottime` cannot change while the process lives. |
| **5** | **Read the roster on evidence, not on a clock** — keep the 6 s floor but skip the Node spawn when the (now single) `ps` output shows no claude pid added or removed | **up to 186 ms per skipped refresh; ~31 ms/rebuild amortised on a quiet board** | ~25 lines | Strictly better than raising `ROSTER_SECONDS`: it keeps 6-second responsiveness and pays only when the roster might actually have changed. `claude agents --json` is 12,301 page faults a launch — the single worst page-cache offender. |
| **6** | **Read big transcripts off the rebuild thread** — cap the first read at a few MB, or hand a >5 MB cold read to a worker and serve the tile without its gist for one pass | removes a measured **915 ms** stall on the 44.8 MB transcript | ~20 lines | Fixes a visible one-second freeze, not average CPU. |
| **7** | **Browser: remove `background-attachment: fixed` (6 sites); merge the two always-on full-viewport overlays; `contain: paint` on `.bubble`/`.project`** | not isolated; the browser side measures **~42% of one core** vs the server's ~10%, so the upside is larger than anything above except #1 | ~15 CSS lines for the first two; the overlay merge needs care with `z-index` | I could not attribute a figure to the dashboard tab alone without disturbing the session. Ranked on measured *total* browser cost plus mechanism, and flagged as the least precisely quantified item here. |
| **8** | **`fleet.command`: drop `open -n`** so a second launch reuses the running Chrome | **923 MB RSS and 37 processes** currently idle | one word | Same leak family as #1, different process. |
| **9** | `prefers-reduced-motion` via System Settings → Accessibility → Reduce motion | stops all five keyframes | zero code, one toggle | A decision for the user, not a change. Worth trying first as a diagnostic. |
| **10** | Bound `Transcripts._entries` (LRU ~200) and sweep `music._cache`; sweep `flush.py` dismissals older than `STALE_MS` | ~5 MB ceiling | ~15 lines | Hygiene. Nothing is leaking at a rate that matters today. |
| **11** | `If-None-Match` on `generatedAt` for `/api/state` | ~36 KB/s of loopback and one parse per second | ~10 lines | Lowest value on the list; the server already serves pre-built bytes at 1.2 ms. |

**Compound effect of 2–5**, arithmetic on the measured components: fixed child CPU per
rebuild falls from **89 ms to ~16 ms** (-82%), spawns from 275/min to **~60/min** (-78%),
and one instance's true cost from **~10% of one core to ~3%**. None of those four changes
alters a single thing the board displays or how fast it updates.

---

## 6. Measured vs inferred

**Measured directly on this machine:**

- Every number in the tables of §2, via `resource.getrusage`, `time.perf_counter`, a
  monkeypatched `subprocess.run` counter, `curl -w`, `top -l N` (instantaneous), and
  `ps`. Harnesses are in the scratchpad and re-runnable.
- The self-vs-child CPU split (28 ms / 206 ms per rebuild) and therefore the ~8x `ps`
  undercount.
- The `_cwd_cache` bug: reproduced in `lsof.py` — three passes, same pid, three `lsof`
  spawns, empty cache.
- `EADDRINUSE` on a second bind to 8787: executed.
- Incremental transcript reads: 915 ms cold for 44.8 MB, 0.003 ms warm.
- `/api/state` at 1.2 ms and not re-serialised (read from the code, confirmed by timing).
- Live instance `buildMs` sampled 8 times over 20 s from its own `/api/state`.
- Zen and Chrome process CPU/RSS, and that `zen` holds both sockets to 8787.
- The orphan forensics: zero-byte `server.log` mtimes matched against each stray's start
  time; `grep` confirming no signal/lock/pidfile handling anywhere in `dashboard.py`;
  the three `collectors.py` copies carrying identical optimisations.

**Inferred, and why:**

- *Per-instance browser cost.* `Zen GPU Helper` at 27.8% and `zen` at 13.9% are measured,
  but they are shared across all tabs and I would have had to close the user's windows to
  isolate the dashboard. The attribution rests on mechanism (2–4 always-on full-viewport
  fixed layers, one perpetual `opacity` animation whenever a session is blocked) plus
  `WindowServer` at 17%. **Treat the ~42% as an upper bound on the page's cost.**
- *That `feTurbulence` is rasterised once rather than per frame.* Standard Gecko/Blink
  image-cache behaviour for `background-image` data URIs; not instrumented here. If the
  fixes in §4c underdeliver, this is the assumption to test first with Firefox's paint
  profiler.
- *That the strays came from `python3 dashboard.py --port N > server.log 2>&1 &` in an
  agent Bash call.* The zero-byte `server.log`s with matching mtimes, ppid 1, and the
  `/private/tmp/<slug>` working directories make this near-certain, but I did not recover
  the command line itself.
- *Compound savings of changes 2–5.* Arithmetic on individually measured components, not
  a measurement of the patched code — the brief ruled out editing project files.
- *That 16 instances cost ~188% of one core.* 11.7% measured once, multiplied by 16. The
  real figure was worse than linear: under contention a single rebuild measured 394–640 ms
  against 166–168 ms clean, because `ps -A` gets more expensive as the process table grows
  — a feedback loop the leak fed itself.

---

## 7. Needs the user's decision

1. **`--kiosk` in the LaunchAgent plist, and idle-exit on by default for everything else.**
   This is the one change that requires touching the installed plist and re-running
   `install.sh`. It is also the fix; nothing else here prevents recurrence.
2. **Default idle timeout: 30 minutes.** Argued in §3c. A shorter value is safe for the
   kiosk but will irritate dev use and get the feature switched off.
3. **`--stop-strays` semantics.** I have it sparing anything flagged `kiosk` *or* sitting
   on the kept port — two independent safeties, so a corrupt registry entry cannot cost
   the board. Confirm that is conservative enough, or require `--force` for anything at all.
4. **`fleet.command`'s `open -n`.** Dropping it reuses the running Chrome and reclaims
   ~923 MB, but it changes launch behaviour (a second board would reuse the first window).
5. **Whether to touch theme CSS at all.** Changes 7 and the `background-attachment` removal
   are performance edits to files another agent is auditing for aesthetics. Sequencing,
   not substance — but it needs deciding before anyone edits.
6. **The 805 MB / 240-file transcript archive** (including a 44.8 MB single file) is read
   by the dashboard but owned by Claude Code. Pruning it is the user's call; it would
   reduce cold-read stalls and `metrics.archive`'s `os.walk`.
