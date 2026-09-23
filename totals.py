"""The long record: one row per day the fleet worked, kept after the evidence goes.

The usage ledger (`usage.py`) answers "how much today" and forgets everything
older than thirty hours. The transcripts it reads are not forever either:
Claude Code deletes a session file thirty days after it was last written, so
every day that passes, the oldest day's evidence goes with it. Anything that is
going to remember what the fleet has spent has to write it down before the
transcripts are gone. This module is that notebook.

The file is `~/.config/fleet/totals.json` (music's and aliases' directory;
`FLEET_TOTALS` moves it, which the tests and a side server use), one row per
local day:

    out, in, cacheRead, cacheWrite, requests     tokens, as the ledger counts them
    byProvider                                   the same five, per agent
    started, startedBy                           sessions whose first row is that day
    sessions                                     session files that wrote that day
    byModel, byProject                           output, by model id and by project
    hours                                        output per local hour, 24 buckets
    peak                                         the day's busiest minute and when
    first, last                                  the day's first and last write

Two definitions are settled and worth saying once. *A session counts on the
day it was started* -- the first timestamped row of its transcript -- not on
every day it wrote, so a session resumed three weeks later still counts on the
day it was opened. Subagent transcripts (`<project>/<session>/subagents/`) are
not sessions: their tokens count, they do not. *Output is the word for
tokens*: cache reads are kept in the rows because they cost nothing to store,
but at 6.9 billion against 29 million written they would be the biggest and
least meaningful number on the panel, so nothing here reports them.

How the rows are made. At every start a walker reads every transcript still on
disk from its first byte -- the same byte-needle prefilter and the same row
readers as the ledger, by subclassing it, so a token is counted here exactly
as it is counted on the HUD -- then re-reads only what was appended, once a
minute. That walk is also what folds today in: today's row is simply the
walker's today. About 2.5 s for a gigabyte of transcripts, on a thread of its
own, so neither the server's start nor the /api/state poll waits for it.

A day once closed is sealed and never recomputed. The walker would happily
recount it, but its transcripts are being deleted from the oldest end, so a
recount would slowly shrink the past. A sealed row in the file therefore wins
over whatever a later walk finds; an unsealed one (today, or a day nobody has
walked since it ended) is replaced. A day seals an hour after local midnight,
so a reply that began at 23:58 and landed at 00:02 is not shut out. Sealed
rows are computed from the transcripts alone, never from anything local to a
process, so two boards writing the same file write the same past; the write is
whole-file and atomic. Bumping VERSION throws every sealed row away, which is
the escape hatch if a counting rule ever changes.

Antigravity writes no usage anywhere readable, so `agy` sessions are not in
here at all -- the summary says so rather than quietly under-reporting.
"""

import json
import os
import tempfile
import threading
import time

import usage

DEFAULT_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "fleet", "totals.json")

VERSION = 1
REWALK_SECONDS = 60             # how often appended bytes are folded in
START_DELAY_SECONDS = 3         # let the server bind and the board paint first
SEAL_GRACE_SECONDS = 3600       # a day seals this long after it ends
HEAD_LINES = 200                # how far into a file its first row is looked for
HEAD_BYTES = 4 << 20
SUBAGENTS = usage.SUBAGENTS
NOT_COUNTED = ["antigravity"]   # writes no usage anywhere this can read


def day_key(ms):
    """The local calendar day a moment falls on, as YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))


def _day_end_ms(day):
    """Local midnight at the end of `day`."""
    y, m, d = (int(p) for p in day.split("-"))
    return int(time.mktime((y, m, d + 1, 0, 0, 0, 0, 0, -1)) * 1000)


def _project(cwd):
    """The board's project name for a working directory.

    The same rule the collectors use, so a worktree's work lands on its repo
    and the list reads like the board's lanes. Copied rather than imported:
    collectors pulls in the whole roster machinery for four lines.
    """
    if not cwd:
        return None
    if "/.claude/worktrees/" in cwd:
        return os.path.basename(cwd.split("/.claude/worktrees/", 1)[0])
    if cwd.rstrip("/") == usage.HOME.rstrip("/"):
        return "home"
    return os.path.basename(cwd.rstrip("/")) or None


def _blank():
    return {"out": 0, "in": 0, "cacheRead": 0, "cacheWrite": 0, "requests": 0,
            "started": 0, "startedBy": {}, "sessions": 0, "byProvider": {},
            "byModel": {}, "byProject": {}, "hours": [0] * 24,
            "peak": {"out": 0, "at": None}, "first": None, "last": None}


class _Head:
    __slots__ = ("start", "project", "subagent")

    def __init__(self, start, project, subagent):
        self.start, self.project, self.subagent = start, project, subagent


class Walker(usage.Ledger):
    """The ledger's reader pointed at everything on disk, crediting days.

    Only `_credit` is replaced: the ledger's row readers call it once per
    request with the moment, the provider, the file and the four token
    counts, and here that lands in a day row instead of a minute bucket.
    Buckets are kept per minute as well (only minutes that wrote, a few
    thousand a month) because a day's peak minute sums every file.
    """

    def __init__(self, claude_root=usage.CLAUDE_PROJECTS, codex_root=usage.CODEX_SESSIONS):
        super().__init__(claude_root=claude_root, codex_root=codex_root)
        self._heads = {}                    # path -> _Head, once the first row is found
        self._dirs = {}                     # project dir -> project, for files with no cwd
        self._days = {}                     # day -> row, with sets where the file has counts
        self._minutes = {}                  # minute -> out

    def _discover_all(self):
        """Every transcript on disk: Claude's sessions and their subagents,
        and Codex's sessions under any date."""
        found = []
        try:
            projects = list(os.scandir(self.claude_root))
        except OSError:
            projects = []
        for project in projects:
            try:
                if not project.is_dir():
                    continue
                entries = list(os.scandir(project.path))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.name.endswith(".jsonl") and entry.is_file():
                        found.append((entry.path, "claude"))
                    elif entry.is_dir():
                        sub = os.path.join(entry.path, "subagents")
                        for inner in os.scandir(sub):
                            if inner.name.endswith(".jsonl"):
                                found.append((inner.path, "claude"))
                except OSError:
                    continue
        for folder, _dirs, files in os.walk(self.codex_root):
            for name in files:
                if name.endswith(".jsonl"):
                    found.append((os.path.join(folder, name), "codex"))
        return found

    def _read_head(self, path, provider):
        """The first timestamped row's moment and the first cwd, or None.

        Read line by line: a Codex file opens with a session_meta row that
        carries the whole system prompt, so a fixed-size peek can cut it.
        """
        start, cwd = None, None
        try:
            with open(path, "rb") as handle:
                read = 0
                for _ in range(HEAD_LINES):
                    raw = handle.readline()
                    if not raw or read > HEAD_BYTES:
                        break
                    read += len(raw)
                    if b'"timestamp"' not in raw and b'"cwd"' not in raw:
                        continue
                    try:
                        row = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if start is None:
                        start = usage._epoch_ms(row.get("timestamp"))
                    if not cwd:
                        # Claude puts it on the row, Codex in session_meta's payload.
                        payload = row.get("payload")
                        cwd = row.get("cwd") or (payload.get("cwd") if isinstance(payload, dict) else None)
                    if start is not None and cwd:
                        break
        except OSError:
            return None
        if start is None:
            return None
        return start, cwd

    def _head(self, path, provider):
        head = self._heads.get(path)
        if head is not None:
            return head
        read = self._read_head(path, provider)
        if read is None:
            return None
        start, cwd = read
        subagent = SUBAGENTS in path
        # A session dir's subagents sit one level deeper than its transcript.
        home = os.path.dirname(os.path.dirname(os.path.dirname(path))) if subagent \
            else os.path.dirname(path)
        project = _project(cwd)
        if project and provider == "claude":
            self._dirs.setdefault(home, project)
        head = self._heads[path] = _Head(start, project or self._dirs.get(home) or "unknown",
                                         subagent)
        if not subagent:
            row = self._day(day_key(start))
            row["started"] += 1
            row["startedBy"][provider] = row["startedBy"].get(provider, 0) + 1
        return head

    def _day(self, day):
        row = self._days.get(day)
        if row is None:
            row = self._days[day] = _blank()
            row["sessions"] = set()
        return row

    def walk(self):
        """Fold in everything on disk that has not been read yet."""
        for path, provider in self._discover_all():
            rec = self.track(path, provider)
            if self._head(rec.path, provider) is None:
                continue                    # nothing timestamped yet; next pass
            self._tail(rec)

    def _turn(self, at, provider):
        # The live ledger counts finished turns into its minute buckets; the
        # walker keeps none of those, and never prunes, so a turn lands nowhere.
        pass

    def _credit(self, at, provider, path, out, inp, cache_read, cache_write):
        if not at:
            return
        head = self._heads.get(path)
        row = self._day(day_key(at))
        cell = row["byProvider"].setdefault(
            provider, {"out": 0, "in": 0, "cacheRead": 0, "cacheWrite": 0, "requests": 0})
        for target in (row, cell):
            target["out"] += out; target["in"] += inp
            target["cacheRead"] += cache_read; target["cacheWrite"] += cache_write
            target["requests"] += 1
        if head is None or not head.subagent:
            row["sessions"].add(path)
        row["first"] = at if row["first"] is None else min(row["first"], at)
        row["last"] = at if row["last"] is None else max(row["last"], at)
        if not out:
            return
        rec = self._files.get(path)
        # Codex's token_count rows do not name the model; the agent is the
        # most this can say about them.
        model = (rec.model if rec is not None and provider == "claude" else None) or provider
        row["byModel"][model] = row["byModel"].get(model, 0) + out
        project = head.project if head is not None else "unknown"
        row["byProject"][project] = row["byProject"].get(project, 0) + out
        row["hours"][time.localtime(at / 1000).tm_hour] += out
        minute = usage._floor_minute(at)
        self._minutes[minute] = self._minutes.get(minute, 0) + out

    def rows(self):
        """Every day walked, as plain rows."""
        peaks = {}
        for minute, out in self._minutes.items():
            at = minute * usage.MINUTE_MS
            day = day_key(at)
            best = peaks.get(day)
            if best is None or out > best[0] or (out == best[0] and at < best[1]):
                peaks[day] = (out, at)
        rows = {}
        for day, live in self._days.items():
            row = dict(live)
            row["sessions"] = len(live["sessions"])
            row["startedBy"] = dict(live["startedBy"])
            row["byProvider"] = {k: dict(v) for k, v in live["byProvider"].items()}
            row["byModel"] = dict(live["byModel"])
            row["byProject"] = dict(live["byProject"])
            row["hours"] = list(live["hours"])
            out, at = peaks.get(day, (0, None))
            row["peak"] = {"out": out, "at": at}
            rows[day] = row
        return rows


class Totals:
    """The file, the walker that feeds it, and the readings drawn from both."""

    def __init__(self, path=None, claude_root=usage.CLAUDE_PROJECTS,
                 codex_root=usage.CODEX_SESSIONS):
        self.path = path or os.environ.get("FLEET_TOTALS") or DEFAULT_PATH
        self.walker = Walker(claude_root=claude_root, codex_root=codex_root)
        self._lock = threading.Lock()
        self._sealed = {}                   # day -> row, never recomputed
        self._live = {}                     # day -> row, replaced by every walk
        self._walked = None                 # when the last walk finished
        self._walk_ms = None                # how long the first one took
        self._written = None                # the last body written, to skip no-op writes
        self._thread = None
        self._load()

    # ---------------------------------------------------------------- disk

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or data.get("version") != VERSION:
            return                          # an old counting rule: start the past again
        days = data.get("days")
        if not isinstance(days, dict):
            return
        for day, row in days.items():
            if not isinstance(row, dict):
                continue
            if row.get("sealed"):
                self._sealed[day] = row
            else:
                self._live[day] = row

    def _save(self, days):
        body = json.dumps({"version": VERSION, "days": days},
                          indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        if body == self._written:
            return
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, prefix=".totals-",
            suffix=".tmp", delete=False)
        try:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(handle.name, self.path)      # atomic within the dir
        except OSError:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        self._written = body

    # ---------------------------------------------------------------- walk

    def refresh(self, now_ms=None):
        """One pass: read what is new, seal what has closed, write the file."""
        began = time.time()
        self.walker.walk()
        now_ms = now_ms or int(time.time() * 1000)
        rows = self.walker.rows()
        with self._lock:
            live = {}
            for day, row in rows.items():
                if day in self._sealed:
                    continue
                if _day_end_ms(day) + SEAL_GRACE_SECONDS * 1000 <= now_ms:
                    row["sealed"] = True
                    self._sealed[day] = row
                else:
                    live[day] = row
            self._live = live
            if self._walked is None:
                self._walk_ms = int((time.time() - began) * 1000)
            self._walked = now_ms
            days = dict(self._live)
            days.update(self._sealed)
        try:
            self._save(days)
        except OSError:
            pass                            # the panel still reads from memory

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="totals")
            self._thread.start()

    def _loop(self):
        time.sleep(START_DELAY_SECONDS)
        while True:
            try:
                self.refresh()
            except Exception as exc:        # a bad file must not end the record
                print("totals: %s: %s" % (type(exc).__name__, exc))
            time.sleep(REWALK_SECONDS)

    # ------------------------------------------------------------- queries

    def days(self):
        with self._lock:
            merged = dict(self._live)
            merged.update(self._sealed)
        return merged

    def summary(self, now_ms=None, top=8):
        """Everything the panel prints, from whatever rows exist right now.

        Before the first walk that is the file as the last board left it (or
        nothing), and `ready` says so; the readings never pretend otherwise.
        """
        now_ms = now_ms or int(time.time() * 1000)
        today = day_key(now_ms)
        days = self.days()
        order = sorted(days)

        total = {"out": 0, "requests": 0, "started": 0}
        providers, started_by, models, projects = {}, {}, {}, {}
        biggest = most = peak = None
        worked = []
        for day in order:
            row = days[day]
            out = int(row.get("out") or 0)
            started = int(row.get("started") or 0)
            total["out"] += out
            total["requests"] += int(row.get("requests") or 0)
            total["started"] += started
            for key, cell in (row.get("byProvider") or {}).items():
                providers[key] = providers.get(key, 0) + int((cell or {}).get("out") or 0)
            for key, n in (row.get("startedBy") or {}).items():
                started_by[key] = started_by.get(key, 0) + int(n or 0)
            for key, n in (row.get("byModel") or {}).items():
                models[key] = models.get(key, 0) + int(n or 0)
            for key, n in (row.get("byProject") or {}).items():
                projects[key] = projects.get(key, 0) + int(n or 0)
            if out > 0:
                worked.append(day)
                if biggest is None or out > biggest["out"]:
                    biggest = {"day": day, "out": out}
            if started > 0 and (most is None or started > most["started"]):
                most = {"day": day, "started": started}
            p = row.get("peak") or {}
            if p.get("out") and (peak is None or p["out"] > peak["out"]):
                peak = {"out": int(p["out"]), "at": p.get("at")}

        run = best = None
        for day in worked:
            if run and _next_day(run["to"]) == day:
                run = {"from": run["from"], "to": day, "days": run["days"] + 1}
            else:
                run = {"from": day, "to": day, "days": 1}
            if best is None or run["days"] > best["days"]:
                best = dict(run)
        elapsed = _days_between(worked[0], today) + 1 if worked else 0

        def ranked(table):
            rows = sorted(table.items(), key=lambda kv: (-kv[1], kv[0]))
            return [{"name": k, "out": v} for k, v in rows[:top] if v > 0]

        with self._lock:
            walked, walk_ms = self._walked, self._walk_ms
        return {
            "available": True,
            "ready": walked is not None,
            "asOf": now_ms,
            "walkedAt": walked,
            "walkMs": walk_ms,
            "today": today,
            "since": {"tokens": worked[0] if worked else None,
                      "starts": next((d for d in order if (days[d].get("started") or 0) > 0), None)},
            "totals": {"out": total["out"], "requests": total["requests"],
                       "started": total["started"], "byProvider": providers,
                       "startedBy": started_by},
            "records": {
                "biggestDay": biggest,
                "mostStarted": most,
                "peakMinute": peak,
                "longestRun": best,
                "worked": {"days": len(worked), "elapsed": elapsed},
                "startDays": sum(1 for d in order if (days[d].get("started") or 0) > 0),
            },
            "days": [[d, int(days[d].get("out") or 0), int(days[d].get("started") or 0)]
                     for d in order],
            "projects": ranked(projects),
            "models": ranked(models),
            "notCounted": NOT_COUNTED,
        }


def _next_day(day):
    y, m, d = (int(p) for p in day.split("-"))
    return time.strftime("%Y-%m-%d", time.localtime(time.mktime((y, m, d + 1, 12, 0, 0, 0, 0, -1))))


def _days_between(a, b):
    """Whole calendar days from a to b, both YYYY-MM-DD."""
    def noon(day):
        y, m, d = (int(p) for p in day.split("-"))
        return time.mktime((y, m, d, 12, 0, 0, 0, 0, -1))
    return int(round((noon(b) - noon(a)) / 86400))


TOTALS = Totals()
