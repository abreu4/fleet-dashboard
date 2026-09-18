"""The usage ledger: what the fleet has written, and when.

Every agent that can tell us leaves a usage record in its own transcript --
Claude Code on each assistant row, Codex as a running total on each
`token_count` event; Antigravity leaves nothing readable. This module tails
those files the same way the collectors do (append-only, so each pass reads
only the bytes that arrived since the last) and keeps what it finds in
one-minute buckets, so the board can answer, with its window stated:

    how fast is the fleet writing right now     tokens/min over the last 5
    how much has it written today               since local midnight
    how much in the open 5-hour Claude window   and when that window resets
    per session: written, context in use, model, effort

"Tokens" on this board has always meant OUTPUT tokens -- what the model
wrote, thinking included. The job file's `tokens` is exactly the deduplicated
output sum of the transcript, so a live session's count lands on the number
the job will eventually stamp. Input is kept too (almost all of it cache
reads, tens of millions per session) but never headlines: it says how big
the context is, not how much work was done.

The 5-hour window is Anthropic's usage-limit period: it opens on the first
message and closes five hours later, and the next message after that opens
another. Chaining that forward from the last gap of five quiet hours (which
guarantees a fresh start) gives the open window's start and reset time from
local data alone. It sees only this machine's Claude Code sessions -- claude.ai
chats count against the same limit and are invisible here -- so it is an
estimate, and labelled as one.
"""

import collections
import glob
import json
import os
import re
import time

HOME = os.path.expanduser("~")
CLAUDE_PROJECTS = os.path.join(HOME, ".claude", "projects")
CODEX_SESSIONS = os.path.join(HOME, ".codex", "sessions")

MINUTE_MS = 60_000
WINDOW_MINUTES = 5 * 60                 # Anthropic's usage-limit period
HORIZON_MINUTES = 30 * 60               # buckets kept; must exceed a day plus a window
RATE_MINUTES = 5                        # tokens/min is averaged over this many
RESCAN_SECONDS = 10                     # how often new files are looked for
CONTEXT_SHORT = 200_000                 # Haiku 4.5 and the pre-4.6 generation
CONTEXT_LONG = 1_000_000                # every Claude model since Opus/Sonnet 4.6


def context_window(model_id):
    """The context ceiling a model id implies.

    Claude Code tags a session's model in a `model` attachment row, sometimes
    with a `[1m]` suffix; that suffix is confirmation, not the rule. Opus 5,
    Fable 5.1, Sonnet 5 and the 4.6+ family are 1M regardless (a plain
    `claude-opus-5` session here has reached 550k), and only Haiku 4.5 and
    the 4.5-and-older generation are 200k. A session that outgrows the
    ceiling this returns is bumped to 1M by the caller.
    """
    name = (model_id or "").lower()
    if "[1m]" in name:
        return CONTEXT_LONG
    if "haiku" in name:
        return CONTEXT_SHORT
    # "claude-opus-4-5", "claude-sonnet-5", "claude-3-7-sonnet-20250219".
    generation = (re.search(r"(?:opus|sonnet|haiku|fable|mythos)-(\d{1,2})(?:-(\d{1,2}))?(?!\d)", name)
                  or re.search(r"claude-(\d)-(\d)-", name))
    if generation:
        version = (int(generation.group(1)), int(generation.group(2) or 0))
        if version < (4, 6):
            return CONTEXT_SHORT
    return CONTEXT_LONG


def _floor_minute(ms):
    return int(ms // MINUTE_MS)


def _epoch_ms(stamp):
    """ISO-8601 with a trailing Z, the way both CLIs write it."""
    if not stamp:
        return None
    try:
        from datetime import datetime, timezone
        text = stamp.replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).astimezone(timezone.utc).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def local_midnight_ms(now_ms=None):
    now = (now_ms or time.time() * 1000) / 1000
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return int(midnight * 1000)


class _File:
    """One tailed transcript and the totals read off it so far."""

    __slots__ = ("path", "provider", "ino", "offset", "pending", "seen", "recent",
                 "out", "inp", "cacheRead", "cacheWrite", "requests",
                 "ctx", "ctxPeak", "model", "modelId", "effort", "lastAt",
                 "codexTotal", "ctxMax")

    def __init__(self, path, provider):
        self.path, self.provider = path, provider
        self.ino, self.offset, self.pending = None, 0, b""
        # A streamed reply is written as one row per content block, every row
        # repeating the request's usage. The last few request ids are enough
        # to fold them: rows of one request are consecutive.
        self.seen, self.recent = set(), collections.deque(maxlen=64)
        self.out = self.inp = self.cacheRead = self.cacheWrite = self.requests = 0
        self.ctx = self.ctxPeak = 0
        self.model = self.modelId = self.effort = None
        self.lastAt = None
        self.codexTotal = None
        self.ctxMax = None

    def summary(self):
        if not self.requests:
            return None
        ctx_max = self.ctxMax or context_window(self.modelId or self.model)
        if self.ctxPeak > ctx_max:
            ctx_max = CONTEXT_LONG
        return {
            "out": self.out, "in": self.inp,
            "cacheRead": self.cacheRead, "cacheWrite": self.cacheWrite,
            "requests": self.requests,
            "ctx": self.ctx, "ctxMax": ctx_max,
            "ctxPct": round(100.0 * self.ctx / ctx_max, 1) if ctx_max else 0,
            "model": self.modelId or self.model, "effort": self.effort,
            "lastAt": self.lastAt,
        }


class Ledger:
    def __init__(self, claude_root=CLAUDE_PROJECTS, codex_root=CODEX_SESSIONS):
        self.claude_root, self.codex_root = claude_root, codex_root
        self._files = {}                    # path -> _File
        self._buckets = {}                  # minute -> provider -> counters
        self._rescanned = 0.0
        self._peak = (0, None)              # (out in a minute, minute) today

    # ---------------------------------------------------------------- files

    def _discover(self, now_ms):
        """Files touched inside the horizon, from both stores."""
        oldest = now_ms / 1000 - HORIZON_MINUTES * 60
        found = []
        try:
            for project in os.scandir(self.claude_root):
                if not project.is_dir():
                    continue
                try:
                    for entry in os.scandir(project.path):
                        if entry.name.endswith(".jsonl") and entry.stat().st_mtime >= oldest:
                            found.append((entry.path, "claude"))
                except OSError:
                    continue
        except OSError:
            pass
        # Codex files sit under sessions/YYYY/MM/DD; the horizon spans at most
        # two of those days, so only they are walked.
        for days_back in (0, 1, 2):
            lt = time.localtime(now_ms / 1000 - days_back * 86400)
            day = os.path.join(self.codex_root, "%04d" % lt.tm_year,
                               "%02d" % lt.tm_mon, "%02d" % lt.tm_mday)
            for path in glob.glob(os.path.join(day, "*.jsonl")):
                try:
                    if os.path.getmtime(path) >= oldest:
                        found.append((path, "codex"))
                except OSError:
                    pass
        return found

    def track(self, path, provider):
        path = os.path.realpath(path)
        rec = self._files.get(path)
        if rec is None:
            rec = self._files[path] = _File(path, provider)
        return rec

    def scan(self, now_ms=None):
        now_ms = now_ms or int(time.time() * 1000)
        if time.time() - self._rescanned >= RESCAN_SECONDS:
            self._rescanned = time.time()
            for path, provider in self._discover(now_ms):
                self.track(path, provider)
        for rec in list(self._files.values()):
            self._tail(rec)
        self._prune(now_ms)

    def _tail(self, rec):
        try:
            stat = os.stat(rec.path)
        except OSError:
            return
        if rec.ino != stat.st_ino or stat.st_size < rec.offset:
            # Rotated or rewritten: everything counted from it stands (the
            # buckets are history), but the running totals start again.
            rec.ino, rec.offset, rec.pending = stat.st_ino, 0, b""
            rec.seen.clear(); rec.recent.clear()
            rec.out = rec.inp = rec.cacheRead = rec.cacheWrite = rec.requests = 0
            rec.codexTotal = None
        if stat.st_size == rec.offset:
            return
        try:
            with open(rec.path, "rb") as handle:
                handle.seek(rec.offset)
                chunk = handle.read(stat.st_size - rec.offset)
        except OSError:
            return
        rec.offset = stat.st_size
        buffer = rec.pending + chunk
        lines = buffer.split(b"\n")
        rec.pending = lines.pop()
        absorb = self._claude_row if rec.provider == "claude" else self._codex_row
        # A cheap byte test before the parse: only one row in three carries
        # usage, and none of the others need decoding.
        needles = ((b'"usage"', b'"modelId"') if rec.provider == "claude"
                   else (b'"token_count"',))
        for raw in lines:
            if not any(needle in raw for needle in needles):
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            absorb(rec, row)

    # ----------------------------------------------------------------- rows

    def _claude_row(self, rec, row):
        if row.get("type") == "attachment":
            # The CLI names the model it is talking to once at the start (and
            # again after /model); the id carries the context window.
            attachment = row.get("attachment") or {}
            if attachment.get("type") == "model":
                identity = attachment.get("identity") or {}
                rec.modelId = identity.get("modelId") or rec.modelId
            return
        if row.get("type") != "assistant":
            return
        message = row.get("message") or {}
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return
        rid = row.get("requestId") or message.get("id")
        if rid:
            if rid in rec.seen:
                return
            if len(rec.recent) == rec.recent.maxlen:
                rec.seen.discard(rec.recent[0])
            rec.recent.append(rid); rec.seen.add(rid)
        out = int(usage.get("output_tokens") or 0)
        inp = int(usage.get("input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        at = _epoch_ms(row.get("timestamp"))
        rec.out += out; rec.inp += inp
        rec.cacheRead += cache_read; rec.cacheWrite += cache_write
        rec.requests += 1
        # The context the model saw on this request is everything it was
        # given: fresh input plus what came back from the cache.
        rec.ctx = inp + cache_read + cache_write
        rec.ctxPeak = max(rec.ctxPeak, rec.ctx)
        rec.model = message.get("model") or rec.model
        rec.effort = row.get("effort") or rec.effort
        rec.lastAt = at or rec.lastAt
        self._credit(at, "claude", rec.path, out, inp, cache_read, cache_write)

    def _codex_row(self, rec, row):
        payload = row.get("payload") or {}
        if payload.get("type") != "token_count":
            return
        info = payload.get("info") or {}
        total = info.get("total_token_usage") or {}
        last = info.get("last_token_usage") or {}
        if not total:
            return
        previous = rec.codexTotal or {}
        delta = {k: max(0, int(total.get(k) or 0) - int(previous.get(k) or 0))
                 for k in ("output_tokens", "input_tokens",
                           "cached_input_tokens", "cache_write_input_tokens")}
        rec.codexTotal = total
        if not any(delta.values()):
            return
        at = _epoch_ms(row.get("timestamp"))
        rec.out += delta["output_tokens"]
        # Codex counts cached tokens inside input_tokens; keep the same split
        # as Claude so the two read alike: fresh input, cache read, cache write.
        fresh = max(0, delta["input_tokens"] - delta["cached_input_tokens"])
        rec.inp += fresh
        rec.cacheRead += delta["cached_input_tokens"]
        rec.cacheWrite += delta["cache_write_input_tokens"]
        rec.requests += 1
        rec.ctx = int(last.get("input_tokens") or 0) + int(last.get("output_tokens") or 0)
        rec.ctxPeak = max(rec.ctxPeak, rec.ctx)
        rec.ctxMax = int(info.get("model_context_window") or 0) or rec.ctxMax
        rec.lastAt = at or rec.lastAt
        self._credit(at, "codex", rec.path, delta["output_tokens"], fresh,
                     delta["cached_input_tokens"], delta["cache_write_input_tokens"])

    def _credit(self, at, provider, path, out, inp, cache_read, cache_write):
        if not at:
            return
        minute = _floor_minute(at)
        slot = self._buckets.setdefault(minute, {})
        cell = slot.get(provider)
        if cell is None:
            cell = slot[provider] = {"out": 0, "in": 0, "cacheRead": 0,
                                     "cacheWrite": 0, "requests": 0, "files": set()}
        cell["out"] += out; cell["in"] += inp
        cell["cacheRead"] += cache_read; cell["cacheWrite"] += cache_write
        cell["requests"] += 1
        cell["files"].add(path)

    def _prune(self, now_ms):
        floor = _floor_minute(now_ms) - HORIZON_MINUTES
        for minute in [m for m in self._buckets if m < floor]:
            del self._buckets[minute]

    # -------------------------------------------------------------- queries

    def session(self, path, provider="claude"):
        """Per-session numbers, tailing the file if the sweep has not."""
        if not path:
            return None
        rec = self.track(path, provider)
        self._tail(rec)
        return rec.summary()

    def _minute_out(self, minute, providers=None):
        slot = self._buckets.get(minute)
        if not slot:
            return 0
        return sum(cell["out"] for key, cell in slot.items()
                   if providers is None or key in providers)

    def _minute_files(self, minute):
        slot = self._buckets.get(minute)
        if not slot:
            return 0
        files = set()
        for cell in slot.values():
            files |= cell["files"]
        return len(files)

    def window(self, now_ms=None):
        """The open 5-hour Claude window: (start_ms, end_ms, out) or None."""
        now_ms = now_ms or int(time.time() * 1000)
        now_minute = _floor_minute(now_ms)
        minutes = sorted(m for m, slot in self._buckets.items()
                         if "claude" in slot and m <= now_minute)
        if not minutes:
            return None
        # Any five silent hours guarantee the next message opened a window;
        # walk forward from the last such gap (or from the oldest we hold).
        anchor = minutes[0]
        for before, after in zip(minutes, minutes[1:]):
            if after - before >= WINDOW_MINUTES:
                anchor = after
        start = anchor
        while now_minute >= start + WINDOW_MINUTES:
            later = [m for m in minutes if m >= start + WINDOW_MINUTES]
            if not later:
                return None                        # expired; nothing since
            start = later[0]
        end = start + WINDOW_MINUTES
        out = sum(self._minute_out(m, ("claude",)) for m in minutes if m >= start)
        return start * MINUTE_MS, end * MINUTE_MS, out

    def summary(self, now_ms=None, trace_minutes=360):
        now_ms = now_ms or int(time.time() * 1000)
        now_minute = _floor_minute(now_ms)
        midnight = _floor_minute(local_midnight_ms(now_ms))

        # tokens/min: the last RATE_MINUTES whole minutes, the current one
        # excluded -- it is always part-full and would read as a slump.
        recent = range(now_minute - RATE_MINUTES, now_minute)
        rate = sum(self._minute_out(m) for m in recent) / float(RATE_MINUTES)

        today = {"out": 0, "in": 0, "cacheRead": 0, "cacheWrite": 0, "requests": 0}
        files_today = set()
        peak_out, peak_at = 0, None
        by_provider = {}
        for minute, slot in self._buckets.items():
            if minute < midnight or minute > now_minute:
                continue
            minute_out = 0
            for provider, cell in slot.items():
                for key in today:
                    today[key] += cell[key]
                files_today |= cell["files"]
                minute_out += cell["out"]
                by_provider[provider] = by_provider.get(provider, 0) + cell["out"]
            if minute_out > peak_out:
                peak_out, peak_at = minute_out, minute
        today["sessions"] = len(files_today)
        today["since"] = midnight * MINUTE_MS
        today["byProvider"] = by_provider

        first = now_minute - trace_minutes + 1
        span = range(first, now_minute + 1)
        trace = {
            "from": first * MINUTE_MS, "step": MINUTE_MS,
            "out": [self._minute_out(m) for m in span],
            "sessions": [self._minute_files(m) for m in span],
        }
        # The same minutes split by provider, so the bars can stack when
        # more than one agent was writing. Only providers that wrote inside
        # the span are listed: with one, the board draws the plain bars.
        writers = {p for m in span for p in (self._buckets.get(m) or {})}
        if len(writers) > 1:
            trace["by"] = {p: [self._minute_out(m, (p,)) for m in span]
                           for p in sorted(writers)}

        window = self.window(now_ms)
        block = None
        if window:
            start, end, out = window
            block = {"start": start, "end": end, "out": out,
                     "elapsedPct": round(100.0 * (now_ms - start) / (end - start), 1)}

        return {
            "asOf": now_ms,
            "rate": {"perMin": int(round(rate)), "minutes": RATE_MINUTES,
                     "peakPerMin": peak_out,
                     "peakAt": peak_at * MINUTE_MS if peak_at else None},
            "today": today,
            "window": block,
            "trace": trace,
        }


# ---------------------------------------------------------------------------
# What got finished. A job that reached `done` leaves state.json saying so,
# with the moment it ended and the merge requests it opened, long after the
# roster has stopped listing it -- so the day's score is read from there and
# a tile flushed off the board still counts.
# ---------------------------------------------------------------------------

CLAUDE_JOBS = os.path.join(HOME, ".claude", "jobs")
_jobs_cache = {}


def finished(since_ms):
    """Jobs done since `since_ms`: {"count": n, "mrs": m, "ids": [...]}."""
    done, links = [], set()
    try:
        entries = list(os.scandir(CLAUDE_JOBS))
    except OSError:
        entries = []
    for entry in entries:
        path = os.path.join(entry.path, "state.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        hit = _jobs_cache.get(path)
        if not hit or hit[0] != mtime:
            try:
                with open(path, encoding="utf-8") as handle:
                    job = json.load(handle)
            except (OSError, ValueError):
                job = {}
            ended = _epoch_ms(job.get("lastTerminalAt") or job.get("updatedAt"))
            hrefs = [c.get("href") for c in (job.get("children") or [])
                     if isinstance(c, dict) and c.get("kind") == "pr" and c.get("href")]
            hit = (mtime, job.get("state"), ended, hrefs)
            _jobs_cache[path] = hit
        _, state, ended, hrefs = hit
        if state == "done" and ended and ended >= since_ms:
            done.append(entry.name)
            links.update(hrefs)
    return {"count": len(done), "mrs": len(links), "ids": done}


LEDGER = Ledger()
