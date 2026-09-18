"""Read-only collectors that turn each agent CLI's on-disk state into sessions.

Every collector returns a list of dicts with the same shape:

    id        stable identifier
    provider  'claude' | 'antigravity' | 'codex'
    name      short display name
    project   grouping key (usually the repo directory name)
    place     where inside the project ('worktree: x', 'main', branch...)
    state     'running' | 'blocked' | 'idle' | 'done' | 'unknown'
    brief     what this session was asked to do (stable)
    now       where it has got to (changes)
    needs     what it is waiting on, when blocked
    links     [{'label': ..., 'href': ...}]
    tokens    int or None
    started   epoch ms or None
    updated   epoch ms or None

Nothing here writes, and nothing here holds a whole transcript in memory.
"""

import ctypes
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

import metrics

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
AGY_DIR = os.path.join(HOME, ".gemini", "antigravity-cli")
CODEX_DIR = os.path.join(HOME, ".codex")

# Sessions older than this stop being interesting on a live board.
STALE_MS = 3 * 24 * 60 * 60 * 1000
# A file touched this recently means the agent is mid-turn.
LIVE_S = 120


# --------------------------------------------------------------------------
# text
# --------------------------------------------------------------------------

_FENCE = re.compile(r"```.*?```", re.S)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s{0,6}(?:[-*+]|\d+[.)])\s+", re.M)
_EMPH = re.compile(r"(\*\*|__|~~|`)")
_TAG = re.compile(r"<[^>\n]{1,120}>")
_WS = re.compile(r"\s+")

# Claude Code wraps slash commands and hook output in these; they are not the
# user talking, so they must never become a session's brief.
_NOT_USER = (
    "<local-command",
    "<command-name>",
    "<command-message>",
    "<system-reminder>",
    "Caveat: The messages below",
    "[Request interrupted",
    "This session is being continued",
)

# Monitors, task notifications and hook output arrive as user turns with an
# opaque id in front, so a prefix test is not enough to spot them.
_INJECTED = re.compile(
    r"(monitor event:|task-notification|<task-|hook (?:output|feedback)|"
    r"tool_use_error|\[request interrupted)", re.I)


def flatten(text):
    """Markdown (or a stray HTML tag) in, one clean line out."""
    if not text:
        return ""
    t = _FENCE.sub(" ", text)
    t = _TABLE_ROW.sub(" ", t)
    t = _LINK.sub(r"\1", t)
    t = _HEADING.sub("", t)
    t = _BULLET.sub("", t)
    t = _EMPH.sub("", t)
    t = _TAG.sub(" ", t)
    t = t.replace("—", "-").replace("|", " ")
    return _WS.sub(" ", t).strip(" -–—:")


def clip(text, limit=220):
    """Trim to `limit`, preferring a sentence or word boundary."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    window = t[:limit]
    for stop in (". ", "; ", " - "):
        cut = window.rfind(stop)
        if cut > limit * 0.55:
            return window[:cut + 1].strip()
    cut = window.rfind(" ")
    return (window[:cut] if cut > limit * 0.5 else window).rstrip() + "…"


_ABS_PATH = re.compile(r"(?:/[\w.@+-]+){2,}/([\w.@+-]+)")
_API_ERR = re.compile(r"API Error:\s*(\d{3})[^.]*\.?.*", re.I)
_CONN_ERR = re.compile(r"API Error:\s*Connection refused.*", re.I)


def shorten_paths(text):
    """A brief that points at a file should name the file, not the path to it."""
    return _ABS_PATH.sub(r"\1", text or "")


def normalise_error(text):
    """Provider outages are the same three sentences every time; say it once."""
    t = text or ""
    t = _CONN_ERR.sub("API connection refused - retrying", t)
    t = _API_ERR.sub(lambda m: "API error %s - retrying" % m.group(1), t)
    return re.sub(r"(?:API (?:error|unavailable|connection)[^·]*·\s*)+", "", t).strip(" ·") or t


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")


def _epoch_ms(stamp):
    """Transcript timestamps are ISO-8601 UTC; epoch ms is what the board
    compares everywhere else. None when the stamp is missing or odd."""
    if not stamp or not isinstance(stamp, str):
        return None
    match = _ISO.match(stamp.strip())
    if not match:
        return None
    import calendar
    y, mo, d, h, mi, sec, frac, zone = match.groups()
    base = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(sec)))
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        digits = zone[1:].replace(":", "")
        base -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    millis = int((frac or "0")[:3].ljust(3, "0"))
    return base * 1000 + millis


def looks_like_user(text):
    t = (text or "").lstrip()
    if not t or t.startswith(_NOT_USER):
        return False
    return not _INJECTED.search(t[:160])


def message_text(message):
    """Pull the plain text out of a transcript message, tool calls excluded."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "\n".join(parts)


def compact_section(summary, *names):
    """Pull one named section out of a compact summary.

    A compact summary is a ~20KB document the model wrote about its own
    session, under a fixed set of section names ("Primary Request and Intent",
    "Current Work", "Optional Next Step"). Reading the section we want beats
    both the boilerplate preamble and any fresh summarising. Two layouts are in
    the wild: markdown headings, and bold numbered items.
    """
    if not summary:
        return ""
    for name in names:
        escaped = re.escape(name)
        for pattern, stop in (
            (r"^#{1,3}\s*\d*\.?\s*" + escaped + r":?\s*$", r"^#{1,3}\s"),
            (r"^\s*\d+\.\s*\*\*" + escaped + r":?\*\*:?\s*$", r"^\s*\d+\.\s*\*\*"),
        ):
            match = re.search(pattern + r"(.*?)(?=" + stop + r"|\Z)",
                              summary, re.M | re.S)
            if match:
                picked = _first_substance(match.group(1))
                if picked:
                    return picked
    return ""


def _first_substance(body):
    """Join paragraphs until there is a real statement, skipping the lead-in
    sentence that only introduces a list."""
    picked = []
    for para in body.split("\n\n"):
        line = flatten(para)
        if len(line) < 30:
            continue
        picked.append(line)
        joined = " ".join(picked)
        if len(joined) >= 120 and not para.rstrip().endswith(":"):
            return joined
    return " ".join(picked)


def intent_from_compact(summary):
    body = compact_section(summary, "Primary Request and Intent")
    if body:
        return body
    # Older/shorter summaries: skip the preamble, take the first real prose.
    tail = re.sub(r"^.*?Summary:\s*", "", summary or "", flags=re.S)
    return _first_substance(tail) or flatten(tail)


_MD_REF = re.compile(r"(/[^\s'\"]+\.md)")


def doc_brief(text):
    """A launch order that says "read brief_x.md" is a pointer, not a brief.
    If the document it names is still on disk, summarise that instead."""
    for path in reversed(_MD_REF.findall(text or "")):
        try:
            with open(path, encoding="utf-8") as handle:
                body = handle.read(8000)
        except OSError:
            continue
        head = re.search(r"^#\s+(.+?)\s*$", body, re.M)
        title = flatten(head.group(1)) if head else ""
        for para in body.split("\n\n")[1 if head else 0:]:
            line = flatten(para)
            if len(line) > 60:
                return ("%s — %s" % (title, line)) if title else line
        if title:
            return title
    return ""


def plan_brief(slug):
    """Sessions that went through plan mode left the plan on disk, named by the
    session's slug. Its title and opening paragraph are the model's own
    statement of the task."""
    if not slug:
        return ""
    path = os.path.join(CLAUDE_DIR, "plans", slug + ".md")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read(8000)
    except OSError:
        return ""
    title = ""
    head = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    if head:
        title = flatten(head.group(1)).replace(" - plan", "").replace(" — plan", "")
    for para in text.split("\n\n")[1:]:
        line = flatten(para)
        if len(line) > 60 and not line.lower().startswith(("context", "the question")):
            return ("%s — %s" % (title, line)) if title else line
    return title


# --------------------------------------------------------------------------
# transcripts, read once and then only from where we stopped
# --------------------------------------------------------------------------

class Transcripts:
    """Incremental reader over ~/.claude/projects/**/<session>.jsonl.

    A transcript is append-only, so after the first pass each refresh only
    reads the bytes that arrived since the last one.
    """

    def __init__(self):
        self._entries = {}
        self._paths = {}

    def path_for(self, session_id, cwd):
        if not session_id:
            return None
        cached = self._paths.get(session_id)
        if cached and os.path.exists(cached):
            return cached
        found = None
        if cwd:
            slug = re.sub(r"[^A-Za-z0-9]", "-", cwd)
            guess = os.path.join(CLAUDE_DIR, "projects", slug, session_id + ".jsonl")
            if os.path.exists(guess):
                found = guess
        if not found:
            matches = glob.glob(os.path.join(
                CLAUDE_DIR, "projects", "*", session_id + ".jsonl"))
            found = matches[0] if matches else None
        if found:
            self._paths[session_id] = found
        return found

    def read(self, path):
        if not path:
            return {}
        try:
            stat = os.stat(path)
        except OSError:
            return {}
        entry = self._entries.get(path)
        fresh = (entry is None
                 or entry["ino"] != stat.st_ino
                 or stat.st_size < entry["offset"])
        if fresh:
            entry = {"ino": stat.st_ino, "offset": 0, "pending": b"",
                     "first_prompt": None, "first_substantial": None, "compact": None,
                     "last_assistant": None, "last_prompt": None,
                     "turns": 0, "mtime": 0, "slug": None, "prev_assistant": None,
                     "started": None, "updated": None,
                     # Claude Code's own names for the session: the title the
                     # model wrote from the first prompt, and the one the user
                     # set with --name or /rename.
                     "ai_title": None, "custom_title": None,
                     # Row counter, so the newer of the last prompt and the last
                     # reply can be told apart without trusting timestamps.
                     "seq": 0, "prompt_seq": -1, "reply_seq": -1,
                     "prompt_at": None}
            self._entries[path] = entry
        elif stat.st_size == entry["offset"]:
            return entry
        try:
            with open(path, "rb") as handle:
                handle.seek(entry["offset"])
                chunk = handle.read(stat.st_size - entry["offset"])
        except OSError:
            return entry
        entry["offset"] = stat.st_size
        entry["mtime"] = int(stat.st_mtime * 1000)
        self._absorb(entry, chunk)
        return entry

    def _absorb(self, entry, chunk):
        buffer = entry["pending"] + chunk
        lines = buffer.split(b"\n")
        entry["pending"] = lines.pop()  # possibly a half-written line
        for raw in lines:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            self._absorb_row(entry, row)

    def _absorb_row(self, entry, row):
        kind = row.get("type")
        stamp = row.get("timestamp")
        entry["seq"] += 1
        if stamp:
            entry["updated"] = stamp
            if entry["started"] is None:
                entry["started"] = stamp

        if kind == "ai-title":
            entry["ai_title"] = (row.get("aiTitle") or "").strip() or entry["ai_title"]
            return
        if kind == "custom-title":
            entry["custom_title"] = ((row.get("customTitle") or "").strip()
                                     or entry["custom_title"])
            return

        if kind == "last-prompt":
            prompt = row.get("lastPrompt")
            if looks_like_user(prompt):
                entry["last_prompt"] = prompt
                entry["prompt_seq"] = entry["seq"]
            return

        if kind == "user":
            if row.get("isSidechain") or row.get("isMeta"):
                return
            text = message_text(row.get("message"))
            if row.get("isCompactSummary"):
                entry["compact"] = text
                return
            if not looks_like_user(text):
                return
            # The user row follows its last-prompt row and is the one with a
            # timestamp; both mark the same moment.
            entry["prompt_seq"] = entry["seq"]
            entry["prompt_at"] = _epoch_ms(stamp) or entry["prompt_at"]
            if entry["first_prompt"] is None:
                entry["first_prompt"] = text
            # "retry?" or "continue" is a nudge, not a brief; hold out for the
            # first prompt that actually states a task.
            if entry["first_substantial"] is None and len(flatten(text)) >= 60:
                entry["first_substantial"] = text
            return

        if row.get("slug"):
            entry["slug"] = row["slug"]

        if kind == "assistant" and not row.get("isSidechain"):
            entry["turns"] += 1
            text = message_text(row.get("message"))
            if text.strip():
                # "Acknowledged." as the closing line tells you nothing, so keep
                # the one before it to fall back on.
                if entry["last_assistant"] and len(flatten(entry["last_assistant"])) >= 60:
                    entry["prev_assistant"] = entry["last_assistant"]
                entry["last_assistant"] = text
                entry["reply_seq"] = entry["seq"]


# --------------------------------------------------------------------------
# claude code
# --------------------------------------------------------------------------

def _split_cwd(cwd):
    if not cwd:
        return "unknown", ""
    if "/.claude/worktrees/" in cwd:
        root, branch = cwd.split("/.claude/worktrees/", 1)
        return os.path.basename(root), "worktree: " + branch.split("/")[0]
    if cwd.rstrip("/") == HOME.rstrip("/"):
        return "home", "~"
    return os.path.basename(cwd.rstrip("/")), "main checkout"


def _job_state(job_id):
    path = os.path.join(CLAUDE_DIR, "jobs", job_id, "state.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _job_detail(job_id):
    """Last non-error status line the worker published to its timeline."""
    path = os.path.join(CLAUDE_DIR, "jobs", job_id, "timeline.jsonl")
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            back = min(handle.tell(), 64 * 1024)
            handle.seek(-back, os.SEEK_END)
            lines = handle.read().split(b"\n")
    except OSError:
        return None
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        detail = row.get("detail")
        if detail and "session limit" not in detail:
            return flatten(detail)
    return None


def _coerce_dict(value):
    """job state.json stores some fields as python-repr strings."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return json.loads(value.replace("'", '"'))
        except ValueError:
            return None
    return None


# launchd starts us with a bare PATH, so the CLI has to be found by hand. The
# symlink is re-pointed on every update, so resolve it per call, never cache it.
_CLI_DIRS = (os.path.join(HOME, ".local", "bin"), "/opt/homebrew/bin",
             "/usr/local/bin", "/usr/bin")


def claude_cli():
    found = shutil.which("claude")
    if found:
        return found
    for directory in _CLI_DIRS:
        candidate = os.path.join(directory, "claude")
        if os.access(candidate, os.X_OK):
            return candidate
    return None


_agents_roster = (0.0, [])
ROSTER_SECONDS = 6.0


def claude_agents(binary):
    """The `claude agents --json` roster, kept on a slower clock than the board.

    Spawning the Node CLI costs ~350ms; every other source in a rebuild costs
    ~90ms put together, so at a two-second refresh this one call would be the
    whole cost of the dashboard. The roster only changes when a session starts
    or ends, and the transcripts behind it -- which is where a tile's state,
    gist and age come from -- are re-read every pass regardless. So a new
    session appears within six seconds and everything about the ones already
    on screen stays live.
    """
    global _agents_roster
    stamp, cached = _agents_roster
    if time.time() - stamp < ROSTER_SECONDS:
        return cached
    try:
        proc = subprocess.run([binary, "agents", "--json"],
                              capture_output=True, text=True, timeout=15)
        agents = json.loads(proc.stdout) if proc.returncode == 0 else cached
    except (OSError, ValueError, subprocess.SubprocessError):
        agents = cached
    _agents_roster = (time.time(), agents)
    return agents


def collect_claude(transcripts):
    binary = claude_cli()
    if not binary:
        return []
    agents = claude_agents(binary)

    sessions = []
    for agent in agents:
        cwd = agent.get("cwd") or ""
        project, place = _split_cwd(cwd)
        state = (agent.get("state") or agent.get("status") or "unknown").lower()
        if state in ("busy", "working", "active"):
            state = "running"
        job_id = agent.get("id")
        session_id = agent.get("sessionId") or ""

        brief = now = needs = None
        links = []
        tokens = None
        turns = 0
        last_activity = None

        if job_id:
            job = _job_state(job_id)
            if job:
                raw_intent = job.get("intent") or ""
                brief = shorten_paths(flatten(raw_intent))
                # "Lê contrato.md e depois brief_x.md" says nothing on a tile.
                if re.match(r"^\s*(l[eê]|read|abre|open)\b", brief, re.I):
                    brief = doc_brief(raw_intent) or brief
                needs = normalise_error(flatten(job.get("needs") or ""))
                result = _coerce_dict(job.get("output")) or {}
                detail = flatten(job.get("detail") or "") or _job_detail(job_id)
                now = flatten(result.get("result") or "") if state == "done" else ""
                now = normalise_error(now or detail or "")
                try:
                    tokens = int(job.get("tokens"))
                except (TypeError, ValueError):
                    tokens = None
                for child in _coerce_dict(job.get("children")) or []:
                    if isinstance(child, dict) and child.get("href"):
                        label = child.get("kind", "link")
                        links.append({
                            "label": "%s #%s" % (label, child.get("id", "")),
                            "href": child["href"]})

        entry = transcripts.read(transcripts.path_for(session_id, cwd))
        nxt = ""
        handle = agent.get("name") or "unnamed"
        name = handle
        prompt_at = None
        if entry:
            # Claude Code names the session itself: the user's --name or
            # /rename first, else the title the model wrote from the opening
            # prompt. The roster's handle ("tiago-01") is what `claude attach`
            # takes, so it stays on the tile as the handle, not the name.
            name = entry.get("custom_title") or entry.get("ai_title") or handle
            prompt_at = entry.get("prompt_at")
            compact = entry.get("compact")
            # Everything below is a summary somebody already wrote — a compact
            # section, a plan document, a worker's own status line. None of it
            # is synthesised here.
            if compact:
                brief = intent_from_compact(compact) or brief
                nxt = compact_section(compact, "Optional Next Step", "Pending Tasks")
                current = compact_section(compact, "Current Work")
                if current:
                    now = now or current
            if not brief:
                brief = plan_brief(entry.get("slug"))
            if not brief:
                brief = flatten(entry.get("first_substantial")
                                or entry.get("first_prompt") or "")
            prompt = flatten(entry.get("last_prompt") or "")
            reply = flatten(entry.get("last_assistant") or "")
            if len(reply) < 60:
                reply = flatten(entry.get("prev_assistant") or "") or reply
            if not now:
                # Whichever of the two was said last is where the session is:
                # the reply once the agent has answered, the prompt while it is
                # still working on one. A one-turn session would otherwise
                # print the same sentence twice, so a prompt that is the brief
                # yields to the reply.
                prompt_is_newer = entry.get("prompt_seq", -1) > entry.get("reply_seq", -1)
                if prompt_is_newer and prompt and prompt != brief:
                    now = prompt
                else:
                    now = reply or (prompt if prompt != brief else "")
            turns = entry.get("turns") or 0
            last_activity = entry.get("mtime") or None

        sessions.append({
            # Roster entries can share a parent sessionId. The job id is the
            # tile identity; sessionId remains the command used for --resume.
            "id": "claude:%s:%s" % (
                job_id or session_id or "session",
                handle,
            ),
            "provider": "claude",
            "name": clip(name, 60),
            "handle": handle,
            "project": project,
            "place": place,
            "kind": agent.get("kind") or "",
            "state": state,
            "brief": clip(brief or "", 260),
            "now": clip(now or "", 220),
            "needs": clip(needs or "", 200) if (needs or "") != (now or "") else "",
            "next": clip(nxt or "", 220),
            "links": links,
            "tokens": tokens,
            "turns": turns,
            "cwd": cwd,
            "sessionId": session_id,
            "resume": "claude" if session_id else "",
            "started": agent.get("startedAt"),
            "updated": last_activity,
            # When the user last spoke: a fleet note older than this has been
            # overtaken by new instructions and stops leading the tile.
            "promptAt": prompt_at,
            # The roster's own handle on this session: `claude attach <jobId>`
            # joins it while it runs, `claude stop <jobId>` ends it, and the pid
            # is what /api/close signals when the CLI has no such handle.
            "jobId": job_id or "",
            "pid": agent.get("pid"),
        })
    return sessions


# --------------------------------------------------------------------------
# antigravity  (agy)
# --------------------------------------------------------------------------

_agy_titles_cache = (None, {})


def _agy_titles():
    """Antigravity's own name for each conversation, and when the user last
    spoke to it: {id: (title, last_user_input_ms)}.

    `conversation_summaries.db` is where the model writes a title for every
    conversation ("Confirm Automatic Data Ingestion"), so a tile can carry a
    name rather than a clipped prompt. The file is WAL-journaled: a read-only
    open needs the -shm file that only exists while agy is running, so when
    that fails the immutable open reads the main file alone. It may then lag
    the newest rows by a checkpoint, which is fine for a name.
    """
    global _agy_titles_cache
    path = os.path.join(AGY_DIR, "conversation_summaries.db")
    try:
        info = os.stat(path)
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        return {}
    if _agy_titles_cache[0] == stamp:
        return _agy_titles_cache[1]
    out = {}
    for uri in ("file:%s?mode=ro" % path, "file:%s?mode=ro&immutable=1" % path):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=1)
            rows = conn.execute(
                "select conversation_id, title, preview, last_user_input_time"
                "  from conversation_summaries").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for cid, title, preview, spoke in rows:
            out[cid] = ((title or preview or "").strip(), _agy_ms(spoke))
        break
    _agy_titles_cache = (stamp, out)
    return out


def _agy_ms(text):
    """'2026-09-15 09:28:16.732754+00:00' -> epoch ms, or None."""
    if not text:
        return None
    return _epoch_ms(str(text).strip().replace(" ", "T", 1))


# Antigravity writes its prompts to history.jsonl without a conversationId more
# often than with one, so the conversation databases are the only reliable
# source. Steps are protobuf blobs; the human text is the longest printable run
# that is not an id, a token or a tool-permission string.
_AGY_NOISE = re.compile(
    r"^\$?[0-9a-f]{8}-[0-9a-f-]{20,}$|^\$|^sessionID$|^[A-Za-z0-9+/=_-]{26,}$")
_AGY_PATH = re.compile(rb"/Users/[\w./ -]{2,90}")
AGY_USER_STEP = 14      # step_type of a user prompt
_agy_cache = {}


def _agy_text(blob):
    """Pull the human sentence out of a protobuf step.

    Length alone picks the wrong string: injected rules like
    `#timeout_long_running_search_command` are longer than "test_update". The
    prompt itself is stored in two fields of the same message, so a run that
    occurs twice is the prompt; everything else falls back to prose scoring.
    """
    runs = []
    for raw in re.findall(rb"[\x20-\x7e]{4,}", blob or b""):
        # The string is length-prefixed, and for 32..126 bytes that prefix
        # is itself a printable byte -- a 93-character prompt arrives as
        # "]Confirm this deployed repo...". The byte equals the length of
        # what follows, which is the test.
        if len(raw) >= 2 and raw[0] == len(raw) - 1:
            raw = raw[1:]
        text = raw.decode("ascii", "replace").strip().strip('"').strip()
        if not text or "(*)" in text or _AGY_NOISE.search(text):
            continue
        if text[0] in "+.-_/\\|=#" or "/Users/" in text or "://" in text:
            continue
        wordish = sum(1 for ch in text if ch.isalpha() or ch.isspace())
        if wordish < len(text) * 0.7:          # ids, hashes, serialised args
            continue
        runs.append(text)

    seen = {}
    for text in runs:
        seen[text] = seen.get(text, 0) + 1
    for text in runs:
        if seen[text] > 1:
            return text
    best, best_score = "", 0
    for text in runs:
        score = sum(1 for ch in text if ch.isalpha() or ch.isspace())
        score += 20 if " " in text else 0
        if score > best_score:
            best, best_score = text, score
    return best


def _agy_conversation(path):
    """(first prompt, latest text, steps, workspace) for one conversation."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    hit = _agy_cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1)
        steps = conn.execute("select count(*) from steps").fetchone()[0]
        first = conn.execute(
            "select step_payload from steps where step_type = ? order by idx limit 1",
            (AGY_USER_STEP,)).fetchone()
        if not first:
            first = conn.execute(
                "select step_payload from steps order by idx limit 1").fetchone()
        tail = conn.execute(
            "select step_payload from steps order by idx desc limit 3").fetchall()
        workspace = ""
        try:
            for row in conn.execute("select * from trajectory_metadata_blob limit 1"):
                for value in row:
                    if isinstance(value, bytes):
                        found = _AGY_PATH.search(value)
                        if found:
                            workspace = found.group(0).decode("utf-8", "replace")
                            break
        except sqlite3.Error:
            pass
        conn.close()
    except sqlite3.Error:
        return None

    opening = _agy_text(first[0]) if first else ""
    latest = ""
    for (blob,) in tail:
        latest = _agy_text(blob)
        # A tool step scrapes as its tool's name ("run_command"); only a run
        # with a space in it can be something the model or the user said.
        if latest and " " in latest and latest != opening:
            break
        latest = ""
    result = (opening, latest, steps, workspace)
    _agy_cache[path] = (stamp, result)
    return result


def _agy_workspaces():
    """history.jsonl still carries the workspace, even on rows with no id."""
    path = os.path.join(AGY_DIR, "history.jsonl")
    by_id, latest = {}, ""
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("workspace"):
                    latest = row["workspace"]
                    if row.get("conversationId"):
                        by_id[row["conversationId"]] = row["workspace"]
    except OSError:
        pass
    return by_id, latest


def collect_antigravity():
    if not os.path.isdir(AGY_DIR):
        return []
    by_id, fallback_ws = _agy_workspaces()
    titles = _agy_titles()
    now_ms = time.time() * 1000
    sessions = []

    for path in glob.glob(os.path.join(AGY_DIR, "conversations", "*.db")):
        cid = os.path.basename(path)[:-3]
        try:
            updated = os.path.getmtime(path) * 1000
        except OSError:
            continue
        if now_ms - updated > STALE_MS:
            continue
        read = _agy_conversation(path)
        if not read:
            continue
        opening, latest, steps, workspace = read

        lock = os.path.join(AGY_DIR, "presence", cid + ".lock")
        try:
            live = (now_ms - os.path.getmtime(lock) * 1000) < LIVE_S * 1000
        except OSError:
            live = False

        workspace = (workspace or by_id.get(cid) or HOME).rstrip("/")
        project = os.path.basename(workspace) or "home"
        if workspace == HOME.rstrip("/"):
            project = "home"

        title, spoke = titles.get(cid) or ("", None)
        sessions.append({
            "id": cid,
            "provider": "antigravity",
            "name": clip(flatten(title), 60) or clip(flatten(opening), 34)
                    or ("session " + cid[:8]),
            "project": project,
            "place": "cli",
            "kind": "interactive",
            "state": "running" if live else "idle",
            "brief": clip(shorten_paths(flatten(opening)), 260),
            "now": clip(flatten(latest), 220),
            "needs": "",
            "next": "",
            "links": [],
            "tokens": None,
            "turns": steps,
            "cwd": workspace or HOME,
            "sessionId": cid,
            "resume": "antigravity" if cid else "",   # agy --conversation <id>
            "started": None,
            "updated": int(updated),
            "promptAt": spoke,
            "jobId": "",
            "pid": None,
        })

    # A running `agy` with no fresh presence lock is still a live session: give
    # the processes to the most recently touched conversations before falling
    # back to a bare process tile.
    running = len(live_processes("antigravity"))
    for session in sorted(sessions, key=lambda s: -(s["updated"] or 0))[:running]:
        session["state"] = "running"
    # merge_live then matches those against the processes, so a live agy shows
    # as its conversation rather than as a bare pid.
    return merge_live(sessions, "antigravity", "agy")


# --------------------------------------------------------------------------
# codex
# --------------------------------------------------------------------------

_CODEX_USER_NOISE = re.compile(
    r"^(?:#\s*AGENTS\.md instructions\b|<environment_context>|"
    r"<user_shell_command>|<turn_aborted>)", re.I)
_CODEX_NUDGE = re.compile(
    r"^(?:continue|retry|go on|keep going|carry on|yes|yep|ok|okay|cool)[?!. ]*$",
    re.I)


def _codex_text(message):
    """Plain text from a Codex response_item message, excluding tool data."""
    if not isinstance(message, dict):
        return ""
    parts = []
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("input_text", "output_text", "text", "Text"):
            parts.append(block.get("text") or "")
    return "\n".join(parts)


def _looks_like_codex_user(text):
    clean = (text or "").lstrip()
    return (looks_like_user(clean) and not _CODEX_USER_NOISE.match(clean)
            and not _CODEX_NUDGE.match(flatten(clean)))


class CodexTranscripts:
    """Incrementally recover current work from append-only Codex rollouts.

    The SQLite preview is normally just the opening prompt. Rollouts contain
    the useful status commentary and final response, but can grow to several
    megabytes, so each refresh starts at the byte where the previous one ended.
    """

    def __init__(self):
        self._entries = {}

    def read(self, path):
        if not path:
            return {}
        try:
            stat = os.stat(path)
        except OSError:
            return {}
        entry = self._entries.get(path)
        fresh = (entry is None or entry["ino"] != stat.st_ino
                 or stat.st_size < entry["offset"])
        if fresh:
            entry = {
                "ino": stat.st_ino, "offset": 0, "pending": b"",
                "last_user": None, "last_user_ordinal": -1, "last_user_at": None,
                "last_assistant": None, "last_assistant_ordinal": -1,
                "prev_assistant": None, "turns": 0,
                "mtime": 0,
            }
            self._entries[path] = entry
        elif stat.st_size == entry["offset"]:
            entry["mtime"] = int(stat.st_mtime * 1000)
            return entry
        try:
            with open(path, "rb") as handle:
                handle.seek(entry["offset"])
                chunk = handle.read(stat.st_size - entry["offset"])
        except OSError:
            return entry
        entry["offset"] = stat.st_size
        entry["mtime"] = int(stat.st_mtime * 1000)
        buffer = entry["pending"] + chunk
        lines = buffer.split(b"\n")
        entry["pending"] = lines.pop()
        for raw in lines:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if row.get("type") != "response_item":
                continue
            message = row.get("payload") or {}
            if message.get("type") != "message":
                continue
            ordinal = row.get("ordinal")
            ordinal = ordinal if isinstance(ordinal, int) else -1
            text = _codex_text(message)
            role = message.get("role")
            if role == "user" and _looks_like_codex_user(text):
                entry["last_user"] = text
                entry["last_user_ordinal"] = ordinal
                entry["last_user_at"] = _epoch_ms(row.get("timestamp")) or entry["last_user_at"]
                entry["turns"] += 1
            elif role == "assistant" and text.strip():
                if (entry["last_assistant"]
                        and len(flatten(entry["last_assistant"])) >= 60):
                    entry["prev_assistant"] = entry["last_assistant"]
                entry["last_assistant"] = text
                entry["last_assistant_ordinal"] = ordinal
        return entry


def _codex_fallback_name(text):
    """Make old, unnamed Codex rows readable without pretending to summarise."""
    clean = flatten(text)
    clean = re.sub(
        r"^(?:please\s+|can you\s+|could you\s+|i need you to\s+|"
        r"i want you to\s+|let'?s\s+)", "", clean, flags=re.I)
    return clip(clean, 34)


def collect_codex(transcripts=None):
    path = os.path.join(CODEX_DIR, "state_5.sqlite")
    if not os.path.exists(path):
        return []
    transcripts = transcripts or CodexTranscripts()
    rows = []
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1)
        rows = conn.execute(
            "select id, name, agent_nickname, title, cwd, git_branch, tokens_used,"
            "       first_user_message, preview, rollout_path, created_at, updated_at"
            "  from threads where archived = 0"
            "  order by updated_at desc limit 40").fetchall()
        conn.close()
    except sqlite3.Error:
        return []

    now_ms = time.time() * 1000
    sessions = []
    rollout_of = {}
    for (tid, name, nickname, title, cwd, branch, tokens, first, preview,
         rollout, created, updated) in rows:
        updated_ms = (updated or 0) * 1000
        if now_ms - updated_ms > STALE_MS:
            continue
        if rollout:
            rollout_of[tid] = os.path.realpath(rollout)
        cwd = (cwd or "").rstrip("/")
        project = os.path.basename(cwd) or "home"
        if cwd == HOME.rstrip("/"):
            project = "home"
        brief = flatten(first or title or "")
        latest = flatten(preview or "")
        entry = transcripts.read(rollout)
        if entry:
            # SQLite's updated_at has lagged behind an actively appended
            # rollout in several Codex releases. The transcript is the better
            # evidence that the open session is alive.
            updated_ms = max(updated_ms, entry.get("mtime") or 0)
            prompt = flatten(entry.get("last_user") or "")
            reply = flatten(entry.get("last_assistant") or "")
            if len(reply) < 60:
                reply = flatten(entry.get("prev_assistant") or "") or reply
            if entry.get("last_user_ordinal", -1) > entry.get("last_assistant_ordinal", -1):
                latest = prompt or reply or latest
            else:
                latest = reply or prompt or latest
        display_name = flatten(name or nickname or "")
        if not display_name:
            display_name = _codex_fallback_name(title or first or tid)
        sessions.append({
            "id": tid,
            "provider": "codex",
            "name": clip(display_name, 34),
            "project": project,
            "place": ("branch: " + branch) if branch else "main checkout",
            "kind": "interactive",
            "state": "running" if (now_ms - updated_ms) < LIVE_S * 1000 else "idle",
            "brief": clip(brief, 260),
            "now": clip(latest if latest != brief else "", 220),
            "needs": "",
            "next": "",
            "links": [],
            "tokens": tokens or None,
            "turns": entry.get("turns", 0) if entry else 0,
            "cwd": cwd or HOME,
            "sessionId": tid,
            "resume": "codex",
            "started": (created or 0) * 1000 or None,
            "updated": updated_ms or None,
            "promptAt": entry.get("last_user_at") if entry else None,
        })
    # Codex holds its rollout open for as long as the session runs, which ties
    # a process to its thread exactly. Matching by folder alone could not tell
    # two sessions started from ~ apart: the first process took the freshest
    # thread, the second found nothing it was allowed to claim, and the tile
    # that idled out lost its × while its process sat there, unclosable.
    def by_rollout(proc, pool):
        held = _process_files(proc["pid"], CODEX_DIR)
        if not held:
            return None
        for session in pool:
            if rollout_of.get(session["id"]) in held:
                return session
        return None
    return merge_live(sessions, "codex", "codex", link=by_rollout)

# --------------------------------------------------------------------------
# live processes
# --------------------------------------------------------------------------

# A session exists the moment its CLI starts, but most agents write nothing to
# disk for the first minute or two. Watching for the process as well means a
# session you just opened appears immediately instead of after its first flush.
_LIVE_PROCS = (
    ("codex", re.compile(r"(?:^|/)codex(?:\s|$)")),
    ("antigravity", re.compile(r"(?:^|/)(?:agy|antigravity)(?:\s|$)")),
)
# Long-lived helpers and editor hosts are not sessions.
_NOT_SESSION = re.compile(
    r"app-server|--analytics|language-server|\.vscode/extensions|dashboard\.py|"
    r"bg-pty-host|bg-spare|mcp|--daemon")

_cwd_cache = {}


def _etime_seconds(text):
    """ps etime: [[dd-]hh:]mm:ss"""
    days = 0
    if "-" in text:
        days, text = text.split("-", 1)
        days = int(days)
    parts = [int(x) for x in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


# proc_pidinfo(PROC_PIDVNODEPATHINFO): struct proc_vnodepathinfo is two
# vnode_info_path blocks, cwd then root; each is a 152-byte vnode_info followed
# by a MAXPATHLEN path. Read straight out of the buffer rather than declaring
# the whole struct.
_PROC_PIDVNODEPATHINFO = 9
_VNODEPATHINFO_SIZE = 2352
_VNODE_INFO_SIZE = 152
_MAXPATHLEN = 1024
try:
    _libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
except OSError:
    _libproc = None


def _cwd_syscall(pid):
    """The process's working directory from libproc: 40µs, and it cannot
    time out the way lsof did under load -- which left a process with no
    folder, so no session matched it and its tile lost the ×."""
    if not _libproc:
        return ""
    buf = ctypes.create_string_buffer(_VNODEPATHINFO_SIZE)
    got = _libproc.proc_pidinfo(ctypes.c_int(pid), ctypes.c_int(_PROC_PIDVNODEPATHINFO),
                                ctypes.c_uint64(0), buf, ctypes.c_int(_VNODEPATHINFO_SIZE))
    if got < _VNODE_INFO_SIZE + 1:
        return ""
    raw = buf.raw[_VNODE_INFO_SIZE:_VNODE_INFO_SIZE + _MAXPATHLEN]
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def _process_cwd(pid):
    # Keyed by int, because the sweep at the end of the scan builds its live set
    # from int(pid). Cached under a string, every entry missed that set and was
    # evicted on the very pass that wrote it -- so the cache never once returned
    # a hit, and each pass paid for a fresh lsof per process.
    pid = int(pid)
    hit = _cwd_cache.get(pid)
    if hit:
        return hit
    cwd = _cwd_syscall(pid)
    if cwd:
        _cwd_cache[pid] = cwd
        return cwd
    try:
        proc = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                              capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in proc.stdout.splitlines():
        if line.startswith("n/"):
            _cwd_cache[pid] = line[1:]
            return line[1:]
    return ""


_files_cache = {}
FILES_SECONDS = 12.0


def _process_files(pid, under):
    """Regular files the process holds open below `under`, as real paths.

    Cached a dozen seconds per pid: a session's transcript does not move, but
    a TUI can start a fresh thread in place, so the answer is not forever.
    """
    pid = int(pid)
    hit = _files_cache.get(pid)
    if hit and time.time() - hit[0] < FILES_SECONDS:
        return hit[1]
    held = set()
    try:
        proc = subprocess.run(["lsof", "-a", "-p", str(pid), "-Fn"],
                              capture_output=True, text=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        # Back off half a window rather than paying a timed-out lsof on every
        # pass; the folder heuristic carries the tile meanwhile.
        _files_cache[pid] = (time.time() - FILES_SECONDS / 2, held)
        return held
    for line in proc.stdout.splitlines():
        if line.startswith("n/") and line[1:].startswith(under):
            held.add(os.path.realpath(line[1:]))
    _files_cache[pid] = (time.time(), held)
    return held


_ps_cache = (0.0, "")
PS_SECONDS = 1.0


def _ps():
    """One process table per rebuild, not one per provider.

    Three lanes each asked `ps` for the same 60ms listing, which was a
    third of the cost of a whole refresh. The window is shorter than the
    refresh interval, so every pass still gets its own reading.
    """
    # Telemetry walked the table a fourth time in its own module, for the same
    # listing with different columns. Both now read one spawn, owned there with
    # the rest of the host readings; the union of columns puts etime second.
    return metrics.process_table()


def live_processes(provider):
    """Every running CLI session for one provider: pid, cwd, age."""
    out = _ps()
    pattern = dict(_LIVE_PROCS).get(provider)
    if not pattern:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, etime, _rss, _pcpu, _ppid, args = parts
        if _NOT_SESSION.search(args) or not pattern.search(args):
            continue
        try:
            age = _etime_seconds(etime)
        except ValueError:
            continue
        found.append({"pid": int(pid), "cwd": _process_cwd(pid),
                      "started": int((time.time() - age) * 1000)})
    # Drop stale pids from the cwd cache, measured against every pid on the
    # machine rather than this provider's matches. live_processes runs once per
    # provider, so sweeping by `found` meant the claude pass evicted codex's
    # entries and the codex pass evicted claude's -- the cache could never hold
    # more than the last lane scanned, whatever its keys were.
    alive = set()
    for line in out.splitlines():
        head = line.split(None, 1)
        if head and head[0].isdigit():
            alive.add(int(head[0]))
    for pid in list(_cwd_cache):
        if pid not in alive:
            _cwd_cache.pop(pid, None)
    for pid in list(_files_cache):
        if pid not in alive:
            _files_cache.pop(pid, None)
    return found


# A CLI that has run this long without a thread of its own on disk is not a
# brand-new session still writing its first row; it is a resumed one whose
# thread predates it. Past this age a process may claim the folder's freshest
# unclaimed session, timestamps notwithstanding.
SETTLED_S = 20


def merge_live(sessions, provider, label, link=None):
    """Add a tile for any running process that no on-disk session accounts for.

    `link(proc, pool)` may name the session a process belongs to outright
    (Codex: the rollout it holds open). Otherwise a process is reconciled with
    the freshest session in its cwd, even when the provider's own liveness
    timestamp briefly says idle. Candidates are sessions that wrote since the
    process started, so a brand-new CLI in a familiar repo does not steal an
    unrelated session from yesterday and inherit its name and description --
    unless the process has been around long enough that no new row is coming,
    in which case the freshest orphan in that folder is the one it resumed.
    """
    on_disk = list(sessions)
    now_ms = time.time() * 1000
    for proc in live_processes(provider):
        cwd = (proc["cwd"] or HOME).rstrip("/")
        matched = link(proc, on_disk) if link else None
        if not matched:
            in_cwd = [s for s in on_disk if (s.get("cwd") or "").rstrip("/") == cwd]
            candidates = [s for s in in_cwd
                          if (s.get("updated") or 0) >= proc["started"] - 30_000]
            if not candidates and now_ms - proc["started"] > SETTLED_S * 1000:
                candidates = in_cwd
            if candidates:
                matched = max(candidates, key=lambda s: s.get("updated") or 0)
        if matched:
            on_disk.remove(matched)       # one process, one on-disk session
            matched["pid"] = proc["pid"]
            if matched.get("state") not in ("blocked", "waiting"):
                matched["state"] = "running"
            continue
        project = os.path.basename(cwd) or "home"
        if cwd == HOME.rstrip("/"):
            project = "home"
        sessions.append({
            "id": "%s:pid:%d" % (provider, proc["pid"]),
            "provider": provider,
            "name": "%s %d" % (label, proc["pid"]),
            "project": project,
            "place": "live",
            "kind": "interactive",
            "state": "running",
            "brief": "",
            "now": "",
            "needs": "",
            "next": "",
            "links": [],
            "tokens": None,
            "turns": 0,
            "cwd": cwd,
            "sessionId": "",
            "resume": "",
            "started": proc["started"],
            "updated": int(time.time() * 1000),
            "jobId": "",
            "pid": proc["pid"],
        })
    return sessions
