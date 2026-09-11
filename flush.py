"""Clearing finished work off the board, without touching the work itself.

The board fills up with sessions that are simply over: an agy conversation from
two days ago, a Codex thread that was answered, a Claude job that shipped. They
are not processes any more, they are records on disk that the collectors keep
finding, and they crowd the sessions that are actually moving.

Flushing dismisses those TILES. It never signals, kills or deletes anything:
no process is touched, no transcript, no sqlite row, no agent state. The only
thing written is one small file of "I have seen this one, stop showing it".

The dismissal is deliberately not permanent. Each entry remembers how far the
session had got when it was flushed, and the tile comes back the moment the
session writes anything newer. So flushing a session that turns out to still be
alive costs nothing -- it reappears on the next refresh -- and the button can be
pressed at any time without having to think about whether it is safe.
"""

import json
import os
import tempfile
import threading
import time

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".config", "fleet")
STORE = os.path.join(CONFIG_DIR, "dismissed.json")

# Live work is never flushed, whatever the button is asked to do.
FLUSHABLE = ("done", "idle", "unknown")


def key_for(session):
    """Same identity the alias layer uses: provider + the session's own id.

    Tile ids are not stable for a CLI that has not written to disk yet, so a
    dismissal keyed on them would evaporate on the next refresh.
    """
    sid = session.get("sessionId") or session.get("id") or ""
    return "%s:%s" % (session.get("provider") or "?", sid)


class Dismissed:
    def __init__(self, path=None):
        self.path = path or os.environ.get("FLEET_DISMISSED") or STORE
        self._lock = threading.Lock()
        self._data = {}
        self._stamp = None
        self._load()

    # ---- storage ---------------------------------------------------------
    def _load(self):
        """Stat before parsing, so hand-editing the file lands within a refresh."""
        try:
            info = os.stat(self.path)
        except OSError:
            self._data = {}
            self._stamp = None
            return
        if self._stamp == (info.st_mtime, info.st_size):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
            self._data = raw.get("dismissed") or {}
        except (OSError, ValueError):
            # A corrupt file is worth one lost flush, never a blank board.
            self._data = {}
        self._stamp = (info.st_mtime, info.st_size)

    def _save(self):
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        body = json.dumps({"dismissed": self._data, "version": 1},
                          indent=2, sort_keys=True)
        # Written through a temp file so a crash mid-write cannot leave a
        # half-parsed file that would un-dismiss everything.
        handle = tempfile.NamedTemporaryFile(
            "w", dir=CONFIG_DIR, prefix=".dismissed-", suffix=".json",
            delete=False, encoding="utf-8")
        try:
            handle.write(body)
            handle.close()
            os.chmod(handle.name, 0o600)
            os.replace(handle.name, self.path)
        except OSError:
            try:
                os.remove(handle.name)
            except OSError:
                pass
            raise
        try:
            info = os.stat(self.path)
            self._stamp = (info.st_mtime, info.st_size)
        except OSError:
            self._stamp = None

    # ---- use -------------------------------------------------------------
    def apply(self, sessions):
        """Drop dismissed sessions, and forget any that have moved on.

        A tile returns the moment its session writes something newer than the
        point it was flushed at, which is what makes the button safe to press.
        """
        with self._lock:
            self._load()
            if not self._data:
                return sessions
            kept, revived = [], []
            for session in sessions:
                mark = self._data.get(key_for(session))
                if mark is None:
                    kept.append(session)
                    continue
                seen = mark.get("updated") or 0
                now = session.get("updated") or 0
                if now > seen:                      # it woke up
                    revived.append(key_for(session))
                    kept.append(session)
            if revived:
                for k in revived:
                    self._data.pop(k, None)
                try:
                    self._save()
                except OSError:
                    pass
            return kept

    def flush(self, sessions):
        """Dismiss every session that is finished or quiet. Returns the count."""
        with self._lock:
            self._load()
            n = 0
            for session in sessions:
                if session.get("state") not in FLUSHABLE:
                    continue
                self._data[key_for(session)] = {
                    "updated": session.get("updated") or 0,
                    "name": session.get("name") or "",
                    "provider": session.get("provider") or "",
                    "at": int(time.time()),
                }
                n += 1
            if n:
                self._save()
            return n

    def dismiss(self, session):
        """Dismiss one tile, whatever its state. Used after closing a session:
        the process is gone but its transcript is still on disk, so the tile
        would otherwise sit there as idle until the next flush. Like every
        dismissal it lifts by itself the moment the session writes again."""
        with self._lock:
            self._load()
            self._data[key_for(session)] = {
                "updated": session.get("updated") or 0,
                "name": session.get("name") or "",
                "provider": session.get("provider") or "",
                "at": int(time.time()),
            }
            self._save()

    def restore(self):
        """Bring everything back. The undo for a flush pressed too eagerly."""
        with self._lock:
            self._load()
            n = len(self._data)
            self._data = {}
            if n:
                self._save()
            return n

    def count(self):
        with self._lock:
            self._load()
            return len(self._data)
