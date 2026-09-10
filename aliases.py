"""User-chosen names for sessions, laid over the names the collectors read.

This is the dashboard's own mapping and nothing else's. It never writes to an
agent's store: a rename here changes what this board calls a session, and the
agent goes on calling it whatever it called it. That is the whole point -- it
works for every provider, including ones added later, and the worst a bad
write can cost is one small JSON file that the board rebuilds empty.

The key is `provider:sessionId`, not the tile id. Tile ids are not all stable:
a live process with nothing on disk yet gets `codex:pid:75676`, and that id is
gone the moment the process restarts. Keying on the session id means a name
survives the session disappearing from the board and coming back -- after a
`--resume`, after a reboot, after the CLI is updated. A tile with no session id
is simply not renamable, and says so.

The file is written whole, through a temporary file in the same directory and
an atomic rename, so a crash mid-write leaves the previous version intact
rather than a truncated one.
"""

import json
import os
import re
import tempfile
import threading
import time

# Kept out of the repo so `git pull` and a reinstall never touch it, and out of
# ~/.claude, ~/.codex and ~/.gemini so this tool owns every byte it writes.
DEFAULT_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "fleet", "aliases.json")

NAME_MAX = 60
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WS = re.compile(r"\s+")


def clean_name(text):
    """One line, no control characters, short enough to fit a tile."""
    name = _WS.sub(" ", _CONTROL.sub(" ", text or "")).strip()
    return name[:NAME_MAX].strip()


def key_for(session):
    """The stable identity of a session, or '' when it has none yet.

    `sessionId` is what every provider hands out once it has written anything
    to disk, and it is what a resume takes. A tile that only exists because a
    process is running has no session id and cannot be named.
    """
    sid = (session.get("sessionId") or "").strip()
    if not sid:
        return ""
    return "%s:%s" % (session.get("provider") or "?", sid)


class Aliases:
    """The mapping, loaded once and re-read only when the file changes.

    Every public method is safe to call from the HTTP threads and the snapshot
    thread at the same time.
    """

    def __init__(self, path=None):
        self.path = path or os.environ.get("FLEET_ALIASES") or DEFAULT_PATH
        self._lock = threading.Lock()
        self._records = {}
        self._stamp = None          # (mtime, size) of the file we last read
        self._load()

    # ---------------------------------------------------------------- disk

    def _load(self):
        """Re-read the file if it has changed since we last looked.

        Cheap enough to call on every rebuild: one stat, and a parse only when
        the file actually moved. Editing the JSON by hand therefore lands on
        the board within one refresh, which makes the file a real interface
        rather than an opaque cache.
        """
        try:
            info = os.stat(self.path)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            if self._stamp is not None:      # the file was removed under us
                self._records, self._stamp = {}, None
            return
        if stamp == self._stamp:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            # A corrupt file must not blank the board or, worse, get
            # overwritten silently on the next rename. Keep what we have.
            return
        records = data.get("aliases") if isinstance(data, dict) else None
        self._records = records if isinstance(records, dict) else {}
        self._stamp = stamp

    def _save(self):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        body = json.dumps({"version": 1, "aliases": self._records},
                          indent=2, sort_keys=True, ensure_ascii=False)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, prefix=".aliases-",
            suffix=".tmp", delete=False)
        try:
            handle.write(body + "\n")
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
        try:
            info = os.stat(self.path)
            self._stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            self._stamp = None

    # --------------------------------------------------------------- apply

    def apply(self, sessions):
        """Lay the aliases over a freshly collected list, in place.

        Adds three fields to every session:
          aliasKey      stable identity, '' when the session cannot be named
          detectedName  whatever the collector read, kept for the reset button
          aliased       True when the name on screen is the user's, not the
                        collector's
        """
        with self._lock:
            self._load()
            seen = time.time()
            touched = False
            for session in sessions:
                key = key_for(session)
                session["aliasKey"] = key
                session["detectedName"] = session.get("name") or ""
                record = self._records.get(key) if key else None
                if not record or not record.get("name"):
                    session["aliased"] = False
                    continue
                session["name"] = record["name"]
                session["aliased"] = True
                # `detected` and `lastSeen` are only bookkeeping: they let the
                # file be read by a human, and let a future prune tell a name
                # that is merely old from one whose session is gone for good.
                if record.get("detected") != session["detectedName"]:
                    record["detected"] = session["detectedName"]
                    touched = True
                if seen - (record.get("lastSeen") or 0) > 3600:
                    record["lastSeen"] = int(seen)
                    touched = True
            if touched:
                try:
                    self._save()
                except OSError:
                    pass                       # bookkeeping is never worth an error
        return sessions

    # --------------------------------------------------------------- write

    def set(self, session, name):
        """Name a session. An empty name clears the alias instead.

        Returns (ok, message, name) where `name` is what the board will now
        show -- the alias, or the detected name once it is cleared.
        """
        key = key_for(session)
        if not key:
            return False, "this session has no id yet, so it cannot be named", None
        detected = session.get("detectedName") or session.get("name") or ""
        name = clean_name(name)
        with self._lock:
            self._load()
            if not name:
                existed = self._records.pop(key, None) is not None
                if existed:
                    self._save()
                return True, ("reset to the detected name" if existed
                              else "no alias to reset"), detected
            if name == detected:
                # Naming a session what it is already called is a reset, not a
                # pinned alias that would then survive the detected name
                # changing underneath it.
                existed = self._records.pop(key, None) is not None
                if existed:
                    self._save()
                return True, "same as the detected name, alias cleared", detected
            self._records[key] = {
                "name": name,
                "detected": detected,
                "provider": session.get("provider") or "",
                "sessionId": session.get("sessionId") or "",
                "cwd": session.get("cwd") or "",
                "setAt": int(time.time()),
                "lastSeen": int(time.time()),
            }
            self._save()
        return True, "renamed", name

    def clear(self, session):
        return self.set(session, "")

    # -------------------------------------------------------------- upkeep

    def prune(self, older_than_days=90):
        """Drop aliases whose session has not been seen for a long time.

        Not called anywhere. It exists so the answer to "does this file grow
        forever" is written down: it grows by one small record per rename, and
        this is the deliberate, manual way to shrink it. Nothing prunes on a
        session merely being absent -- a session that vanishes and comes back
        must come back with its name.
        """
        cutoff = time.time() - older_than_days * 86400
        with self._lock:
            self._load()
            dropped = [k for k, r in self._records.items()
                       if (r.get("lastSeen") or r.get("setAt") or 0) < cutoff]
            for key in dropped:
                del self._records[key]
            if dropped:
                self._save()
        return dropped
