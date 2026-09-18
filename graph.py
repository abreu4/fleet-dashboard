"""The trail of one run, for the graph window.

A session's transcript already holds everything the graph needs: what the
agent said, what each tool call was for, and which files it touched. This
module reads that once, on request, and keeps reading only the bytes that
land after -- the same incremental pass the collectors make, on a file the
board otherwise never opens in full.

Nothing here is synthesised. A step's label is the agent's own text, the
one-line `description` it wrote on a shell command, or the tool and the
file's name; a file is a path the tool call named. Hidden reasoning is
mostly not on disk (Claude Code writes empty `thinking` blocks unless the
session opted in, Codex encrypts its reasoning and keeps only a summary),
so where a thought *is* written it rides along and where it is not, the
label is what the call was for.

    steps    one per model response: [{i, t, kind, tool, label, what, text,
             think, files:[[file, verb], ...], open, n}] -- `label` is the
             agent's text when it wrote any, else `what` (the tool's own
             one-liner), else the thought; `n` counts the tool calls
    prompts  where the user spoke: [{i, t, text}] -- `i` is the step it
             precedes, so a prompt splits the spine into phases
    files    [{path, name, dir, reads, writes, first, last}]
    tail     what the last row was -- 'prompt', 'call', 'result' or 'say' --
             which is what the page needs to show *thinking* apart from
             *running a tool* at the head of the spine

Verbs on a file edge: read (Read/Grep/Glob, or a shell command that only
looks), edit (Edit/MultiEdit/NotebookEdit, sed -i, apply_patch update),
write (Write, a redirection, cp/mv/rm/touch, apply_patch add), run (a
shell command that names the file for anything else: a test, a script).
"""

import json
import os
import re
import sqlite3
import threading

from collectors import (
    CLAUDE_DIR, CODEX_DIR, HOME, _codex_text, _epoch_ms, _looks_like_codex_user,
    clip, flatten, looks_like_user, message_text,
)

LABEL_CHARS = 110
TEXT_CHARS = 600
THINK_CHARS = 400
FILES_PER_STEP = 14        # a `ls` of forty files is not forty edges

# --------------------------------------------------------------------------
# paths in shell commands
# --------------------------------------------------------------------------

_EXTS = (
    "py pyi js mjs cjs ts tsx jsx html htm css scss less md mdx rst json jsonl "
    "yaml yml toml txt sh zsh bash fish swift plist sql csv tsv rs go java kt "
    "c h cc cpp hpp m mm rb php ipynb cfg ini conf env lock xml svg png jpg "
    "jpeg gif webp pdf command service tf proto graphql vue svelte dart lua "
    "r jl ex exs erl hs ml scala gradle cmake mk log out err bak orig diff patch"
).split()
_BARE = {"Makefile", "Dockerfile", "Justfile", "Rakefile", "Gemfile",
         "Procfile", "LICENSE", "README", "CLAUDE", "AGENTS"}
_EXT_RE = re.compile(r"\.(%s)$" % "|".join(_EXTS), re.I)
# Split a command into shell words: whitespace, the operators, quotes, and
# the `=` of a --flag=value.
_SPLIT = re.compile(r"""[\s;|&()<>'"`=,]+""")
_SEGMENT = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
_TRAIL = re.compile(r"[:.,)\]}]+$")
_LINE_SUFFIX = re.compile(r":\d+(?::\d+)?$")
_URL = re.compile(r"^\w+://")
_GLOB = re.compile(r"[*?{}$\[\]]")
# what a path is made of; a sed expression (`s/^#//`), a regex, an escape
# or an option with a slash in it has other characters and is not one
_PATHISH = re.compile(r"^[\w.~@%+/-]+$")
_WRITERS = {"tee", "touch", "mkdir", "rm", "rmdir", "chmod", "chown", "ln",
            "patch", "unlink"}
_READERS = {"cat", "head", "tail", "less", "more", "grep", "rg", "egrep",
            "fgrep", "awk", "wc", "diff", "ls", "find", "stat", "file", "cut",
            "sort", "uniq", "tr", "sed", "jq", "yq", "md5", "shasum", "od",
            "hexdump", "strings", "nl", "column", "tree", "du", "df",
            "bat", "fd", "which", "type"}
_MOVERS = {"cp", "mv", "rsync", "install"}
_RANK = {"read": 0, "run": 1, "edit": 2, "write": 3}
_NOISE_DIRS = ("/dev/", "/proc/", "/sys/", "/tool-results/", "/node_modules/",
               "/.git/objects/", "/.fleet/")


def _dequote_paths(command):
    """Paths in a heredoc body or a python -c snippet are noise; the parts
    of a command that name files are outside them."""
    text = command or ""
    # a heredoc: `cat > file <<'EOF' ... EOF` -- keep the opening line only
    text = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?\n.*?\n\1\b", " ", text, flags=re.S)
    return text


def _tokens(command):
    for raw in _SPLIT.split(_dequote_paths(command)):
        tok = _TRAIL.sub("", _LINE_SUFFIX.sub("", raw.strip()))
        if len(tok) < 2 or _URL.match(tok) or _GLOB.search(tok):
            continue
        yield tok


def looks_like_path(tok, cwd=None):
    """A shell word that names a file. Anchored paths and words with a
    known extension qualify on their face; a bare `a/b` or `README` could
    as easily be a regex or a word in a grep, so those must exist."""
    if tok.endswith("/") or tok.startswith("-") or not _PATHISH.match(tok):
        return False                      # a folder, a flag, a pattern
    if tok in (".", "..", "~"):
        return False
    if _EXT_RE.search(tok):
        return True
    if "/" in tok or os.path.basename(tok) in _BARE:
        # `/api/state` in a quoted sentence is anchored and still not a file
        full = os.path.expanduser(tok)
        if not os.path.isabs(full):
            full = os.path.join(cwd or HOME, full)
        return os.path.isfile(full)
    return False


def resolve(tok, cwd):
    """Absolute, normalised, `~` expanded, relative to the row's cwd."""
    path = os.path.expanduser(tok)
    if not os.path.isabs(path):
        path = os.path.join(cwd or HOME, path)
    path = os.path.normpath(path)
    if any(part in path for part in _NOISE_DIRS):
        return None
    return path


def paths_in_command(command, cwd):
    """[(path, verb)] for the files a shell command names.

    Each `;`/`|`/`&&` segment is read on its own: its first word says what
    it does to the paths after it, and a redirection target is a write
    whatever the program was.
    """
    found = []
    seen = {}
    lost = False                    # cwd unknown after `cd $VAR`

    def add(path, verb):
        if not path:
            return
        at = seen.get(path)
        if at is not None:              # named twice: the stronger verb wins
            if _RANK[verb] > _RANK[found[at][1]]:
                found[at] = (path, verb)
        elif len(found) < FILES_PER_STEP:
            seen[path] = len(found)
            found.append((path, verb))

    for segment in _SEGMENT.split(_dequote_paths(command or "")):
        if not segment.strip():
            continue
        # cd into a folder first, so `cd repo && pytest tests/x.py` resolves;
        # after `cd $DIR` nothing relative can be placed, so it is dropped
        m = re.match(r"^\s*cd\s+(\S+)\s*$", segment)
        if m:
            target = m.group(1).strip("'\"")
            cwd = resolve(target, cwd) if _PATHISH.match(target) else None
            lost = cwd is None
            continue
        # redirection targets: `> out.txt`, `2>> log`, `>| f`
        writes = set()
        for m in re.finditer(r"(?:^|\s)\d?>{1,2}\|?\s*([^\s;|&]+)", segment):
            writes.add(m.group(1).strip("'\""))
        words = [w for w in _tokens(segment)]
        if not words:
            continue
        program = os.path.basename(words[0])
        if program in ("sudo", "env", "time", "nohup", "exec", "command") and len(words) > 1:
            words = words[1:]
            program = os.path.basename(words[0])
        in_place = (program in ("sed", "perl") and re.search(r"\s-[a-zA-Z]*i", segment))
        if program in _MOVERS:
            verb = "read"
        elif in_place:
            verb = "edit"
        elif program in _WRITERS:
            verb = "write"
        elif program in _READERS:
            verb = "read"
        else:
            verb = "run"
        candidates = [w for w in words[1:] if looks_like_path(w, cwd)]
        # `python3 script.py` runs the script; `./install.sh` runs itself
        if looks_like_path(words[0], cwd) and program not in _READERS:
            candidates.insert(0, words[0])
        for idx, tok in enumerate(candidates):
            if lost and not tok.startswith(("/", "~")):
                continue
            path = resolve(tok, cwd)
            if not path:
                continue
            if tok in writes:
                add(path, "write")
            elif program in _MOVERS and idx == len(candidates) - 1 and len(candidates) > 1:
                add(path, "write")
            else:
                add(path, verb)
        for tok in writes:
            # the target of a `>` is a file whatever it is called
            if lost and not tok.startswith(("/", "~")):
                continue
            if _PATHISH.match(tok) and not tok.endswith("/") and tok not in (".", ".."):
                add(resolve(tok, cwd), "write")
    return found


# --------------------------------------------------------------------------
# tool calls
# --------------------------------------------------------------------------

_FILE_TOOLS = {"Read": "read", "Edit": "edit", "MultiEdit": "edit",
               "NotebookEdit": "edit", "Write": "write"}
_SCOPE_TOOLS = {"Grep", "Glob", "LSP"}


def _short(text, limit):
    return clip(flatten(text), limit)


def tool_touches(name, inp, cwd):
    """[(path, verb)] a Claude Code tool call names."""
    inp = inp if isinstance(inp, dict) else {}
    if name in _FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
        if path:
            path = resolve(str(path), cwd)
            return [(path, _FILE_TOOLS[name])] if path else []
        return []
    if name in _SCOPE_TOOLS:
        path = inp.get("path") or inp.get("file_path")
        if path and looks_like_path(str(path)) and _EXT_RE.search(str(path)):
            path = resolve(str(path), cwd)
            return [(path, "read")] if path else []
        return []
    if name == "Bash":
        return paths_in_command(inp.get("command") or "", cwd)
    return []


def tool_label(name, inp):
    """What a tool call was for, in the agent's words where it wrote any."""
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return _short(inp.get("description") or inp.get("command") or "shell", LABEL_CHARS)
    if name in _FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
        return "%s %s" % (_FILE_TOOLS[name], os.path.basename(str(path)) or "file")
    if name == "Grep":
        return "grep " + _short(inp.get("pattern") or "", 60)
    if name == "Glob":
        return "find " + _short(inp.get("pattern") or "", 60)
    if name in ("Agent", "Task"):
        return "agent: " + _short(inp.get("description") or inp.get("prompt") or "", LABEL_CHARS)
    if name == "WebSearch":
        return "search: " + _short(inp.get("query") or "", 80)
    if name == "WebFetch":
        url = str(inp.get("url") or "")
        return "fetch " + re.sub(r"^\w+://", "", url).split("/")[0]
    if name == "Skill":
        return "skill /" + str(inp.get("skill") or "")
    if name == "AskUserQuestion":
        qs = inp.get("questions") or []
        first = qs[0].get("question") if qs and isinstance(qs[0], dict) else ""
        return "asks: " + _short(first or "", 90)
    if name in ("TaskCreate", "TaskUpdate"):
        return "todo: " + _short(inp.get("subject") or inp.get("status") or "", 80)
    if name.startswith("mcp__"):
        parts = name.split("__")
        return (parts[-1] if parts else name).replace("_", " ").replace("-", " ")
    return name


# --------------------------------------------------------------------------
# the reader
# --------------------------------------------------------------------------

class Trail:
    """One transcript's steps, prompts and files, kept up to date by
    `absorb`-ing appended rows."""

    def __init__(self, provider):
        self.provider = provider
        self.steps = []
        self.prompts = []
        self.files = []
        self._file_index = {}
        self.tail = "quiet"
        self.started = None
        self.updated = None
        self.pending = set()        # tool ids without a result yet
        self._group = None          # message id of the step being built
        self._thought = ""          # Codex: a reasoning summary awaiting its call
        self._cwd = None

    # ---- shared ----

    def _file(self, path):
        idx = self._file_index.get(path)
        if idx is None:
            idx = len(self.files)
            self._file_index[path] = idx
            home = HOME.rstrip("/")
            folder = os.path.dirname(path)
            if folder == home:
                folder = "~"
            elif folder.startswith(home + "/"):
                folder = "~" + folder[len(home):]
            self.files.append({"path": path, "name": os.path.basename(path),
                               "dir": folder, "reads": 0, "writes": 0,
                               "first": len(self.steps), "last": len(self.steps)})
        return idx

    def _step(self, stamp, kind, group=None):
        """Start a step, or return the one being built when `group` (the
        API message id) is the same: Claude Code writes one row per content
        block, so a response's text and its tool calls arrive on
        consecutive rows that share an id."""
        if group and self._group == group and self.steps:
            return self.steps[-1]
        if self.steps:
            # a model only continues once its results are in, so a new step
            # closes whatever the last one still had in flight
            self.steps[-1]["open"] = False
        step = {"i": len(self.steps), "t": _epoch_ms(stamp), "kind": kind,
                "tool": "", "label": "", "what": "", "text": "", "think": "",
                "files": [], "open": False, "n": 0}
        self.steps.append(step)
        self._group = group
        return step

    def _touch(self, step, touches):
        i = step["i"]
        for path, verb in touches:
            fi = self._file(path)
            file = self.files[fi]
            file["reads" if verb in ("read", "run") else "writes"] += 1
            file["last"] = i
            for edge in step["files"]:
                if edge[0] == fi:
                    # the stronger verb wins on a repeated touch
                    if _RANK.get(verb, 0) > _RANK.get(edge[1], 0):
                        edge[1] = verb
                    break
            else:
                step["files"].append([fi, verb])

    def _prompt(self, stamp, text):
        self.prompts.append({"i": len(self.steps), "t": _epoch_ms(stamp),
                             "text": _short(text, 160)})
        self._group = None
        self.tail = "prompt"

    # ---- Claude Code ----

    def absorb_claude(self, row):
        kind = row.get("type")
        stamp = row.get("timestamp")
        if stamp:
            self.updated = _epoch_ms(stamp) or self.updated
            self.started = self.started or self.updated
        if row.get("isSidechain"):
            return
        if row.get("cwd"):
            self._cwd = row["cwd"]
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        if kind == "user":
            if row.get("isMeta") or row.get("isCompactSummary"):
                return
            content = message.get("content")
            results = [b for b in content if isinstance(b, dict)
                       and b.get("type") == "tool_result"] if isinstance(content, list) else []
            if results:
                for block in results:
                    self.pending.discard(block.get("tool_use_id"))
                if self.steps and not self.pending:
                    self.steps[-1]["open"] = False
                self.tail = "result"
                self._group = None
                return
            text = message_text(message)
            if looks_like_user(text):
                self._prompt(stamp, text)
            return
        if kind != "assistant":
            return
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            return
        group = message.get("id") or row.get("requestId") or row.get("uuid")
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "thinking":
                thought = (block.get("thinking") or "").strip()
                if thought:
                    step = self._step(stamp, "think", group)
                    step["think"] = step["think"] or _short(thought, THINK_CHARS)
                    self.tail = "say"
            elif btype == "text":
                text = (block.get("text") or "").strip()
                if not text:
                    continue
                step = self._step(stamp, "say", group)
                if step["kind"] == "think":
                    step["kind"] = "say"
                step["text"] = step["text"] or _short(text, TEXT_CHARS)
                self.tail = "say"
            elif btype == "tool_use":
                name = block.get("name") or "tool"
                step = self._step(stamp, "tool", group)
                step["kind"] = "agent" if name in ("Agent", "Task") else "tool"
                step["n"] += 1
                step["tool"] = step["tool"] or name
                step["what"] = step["what"] or tool_label(name, block.get("input"))
                self._touch(step, tool_touches(name, block.get("input"), self._cwd))
                self.pending.add(block.get("id"))
                step["open"] = True
                self.tail = "call"
        if self.steps and self._group == group:
            _settle(self.steps[-1])

    # ---- Codex ----

    def absorb_codex(self, row):
        rtype = row.get("type")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        stamp = row.get("timestamp")
        if stamp:
            self.updated = _epoch_ms(stamp) or self.updated
            self.started = self.started or self.updated
        if rtype == "session_meta" and payload.get("cwd"):
            self._cwd = payload["cwd"]
            return
        if rtype == "turn_context" and payload.get("cwd"):
            self._cwd = payload["cwd"]
            return
        if rtype != "response_item":
            return
        ptype = payload.get("type")
        if ptype == "message":
            text = _codex_text(payload)
            role = payload.get("role")
            if role == "user":
                if _looks_like_codex_user(text):
                    self._prompt(stamp, text)
            elif role == "assistant" and text.strip():
                step = self._step(stamp, "say")
                step["text"] = _short(text, TEXT_CHARS)
                step["think"], self._thought = self._thought, ""
                _settle(step)
                self.tail = "say"
            return
        if ptype == "reasoning":
            summary = payload.get("summary") or []
            parts = [s.get("text") for s in summary if isinstance(s, dict) and s.get("text")]
            if parts:
                self._thought = _short(" ".join(parts), THINK_CHARS)
            self.tail = "say"
            return
        if ptype in ("custom_tool_call", "function_call", "local_shell_call"):
            name = payload.get("name") or ptype
            step = self._step(stamp, "tool")
            step["tool"] = name
            step["n"] = 1
            step["think"], self._thought = self._thought, ""
            command, touches = codex_call(payload, self._cwd)
            step["what"] = _short(command or name, LABEL_CHARS)
            self._touch(step, touches)
            _settle(step)
            self.pending.add(payload.get("call_id"))
            step["open"] = True
            self.tail = "call"
            return
        if ptype in ("custom_tool_call_output", "function_call_output", "local_shell_call_output"):
            self.pending.discard(payload.get("call_id"))
            if self.steps and not self.pending:
                self.steps[-1]["open"] = False
            self.tail = "result"

    # ---- out ----

    def payload(self):
        return {"steps": self.steps, "prompts": self.prompts, "files": self.files,
                "tail": self.tail, "started": self.started, "updated": self.updated}


def _settle(step):
    """The line the spine shows for a step: what the agent said if it said
    anything, else what the tool call was for, else the thought."""
    step["label"] = (_short(step["text"], LABEL_CHARS) if step["text"]
                     else step["what"] or _short(step["think"], LABEL_CHARS))
_CMD_JSON = re.compile(r'"cmd"\s*:\s*"((?:[^"\\]|\\.)*)"')
_PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete|Move to) File: (.+)$", re.M)


def codex_call(payload, cwd):
    """(command text, [(path, verb)]) for a Codex tool call. `exec` wraps
    the shell command in a JavaScript call whose argument is JSON; the
    older `shell` tool passes `arguments` as JSON with a command list."""
    name = payload.get("name") or ""
    raw = payload.get("input") or payload.get("arguments") or ""
    if not isinstance(raw, str):
        raw = json.dumps(raw)
    if name == "apply_patch" or "*** Begin Patch" in raw:
        touches = []
        for verb, path in _PATCH_FILE.findall(raw):
            full = resolve(path.strip(), cwd)
            if full:
                touches.append((full, {"Add": "write", "Update": "edit",
                                       "Delete": "write", "Move to": "write"}[verb]))
        names = ", ".join(os.path.basename(p) for p, _ in touches[:4])
        return ("patch " + names if names else "apply patch"), touches
    command = ""
    workdir = cwd
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            args = json.loads(raw[start:end + 1])
        except ValueError:
            args = None
        if isinstance(args, dict):
            cmd = args.get("cmd") or args.get("command")
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            command = str(cmd or "")
            workdir = args.get("workdir") or args.get("cwd") or cwd
    if not command:
        m = _CMD_JSON.search(raw)
        if m:
            try:
                command = json.loads('"%s"' % m.group(1))
            except ValueError:
                command = m.group(1)
    if not command and name not in ("exec", "shell", "shell_command"):
        return name, []
    return command, paths_in_command(command, workdir)


class Trails:
    """Incremental readers, one per transcript, behind one lock. A trail is
    built the first time a page asks for it and grows by the appended bytes
    on every request after -- the board's two-second loop never touches it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}

    def read(self, path, provider):
        if not path:
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        with self._lock:
            entry = self._entries.get(path)
            fresh = (entry is None or entry["ino"] != stat.st_ino
                     or stat.st_size < entry["offset"])
            if fresh:
                entry = {"ino": stat.st_ino, "offset": 0, "pending": b"",
                         "trail": Trail(provider)}
                self._entries[path] = entry
            if stat.st_size > entry["offset"]:
                try:
                    with open(path, "rb") as handle:
                        handle.seek(entry["offset"])
                        chunk = handle.read(stat.st_size - entry["offset"])
                except OSError:
                    return entry["trail"]
                entry["offset"] = stat.st_size
                self._absorb(entry, chunk)
            return entry["trail"]

    @staticmethod
    def _absorb(entry, chunk):
        trail = entry["trail"]
        absorb = trail.absorb_codex if trail.provider == "codex" else trail.absorb_claude
        lines = (entry["pending"] + chunk).split(b"\n")
        entry["pending"] = lines.pop()
        for raw in lines:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(row, dict):
                try:
                    absorb(row)
                except Exception:        # one odd row must not lose the trail
                    continue


TRAILS = Trails()

# --------------------------------------------------------------------------
# locating a session's transcript
# --------------------------------------------------------------------------

_codex_rollouts = {}


def codex_rollout(thread_id):
    path = _codex_rollouts.get(thread_id)
    if path and os.path.exists(path):
        return path
    db = os.path.join(CODEX_DIR, "state_5.sqlite")
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=1)
        row = conn.execute("select rollout_path from threads where id = ?",
                           (thread_id,)).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if row and row[0]:
        _codex_rollouts[thread_id] = row[0]
        return row[0]
    return None


def locate(session, transcripts):
    """(path, provider, why-not) for the transcript behind a session."""
    provider = (session or {}).get("provider")
    if provider == "claude":
        path = transcripts.path_for(session.get("sessionId"), session.get("cwd"))
        if path:
            return path, "claude", ""
        return None, "claude", "nothing written to disk yet"
    if provider == "codex":
        path = codex_rollout(session.get("sessionId") or session.get("id"))
        if path:
            return path, "codex", ""
        return None, "codex", "no rollout on disk yet"
    if provider == "antigravity":
        return None, provider, "Antigravity keeps its steps as opaque protobuf; no trail to read"
    return None, provider or "", "unknown provider"


def build(session, transcripts):
    """The graph payload for one session, or the reason there is none."""
    base = {"id": (session or {}).get("id"), "name": (session or {}).get("name"),
            "provider": (session or {}).get("provider"),
            "state": (session or {}).get("state")}
    if not session:
        return dict(base, available=False, why="no such session on the board")
    path, provider, why = locate(session, transcripts)
    if not path:
        return dict(base, available=False, why=why)
    trail = TRAILS.read(path, provider)
    if trail is None:
        return dict(base, available=False, why="transcript unreadable")
    return dict(base, available=True, **trail.payload())
