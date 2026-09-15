"""Notes an agent chose to leave, read the same way everything else is read.

The board is built out of state agents write anyway -- transcripts, job files,
sqlite rows -- and no session is ever *asked* to report on itself. This is the
one voluntary channel, and it deliberately keeps that shape: an agent drops a
small JSON file in a directory, and the collector picks it up on the next pass.

    ~/.fleet/notes/<anything>.json
    {"cwd": "/Users/tiago/Documents/Dev/thing", "text": "waiting on review",
     "at": 1757500000000}

Writing a file rather than calling an endpoint buys a lot: the dashboard gains
no write surface, the server does not have to be running for a note to survive,
and any agent in any language can leave one with the file tool it already has.

`text` is the only required field. A note identifies its session by `cwd`
(every agent knows its own) or by `session` (a provider session id), and falls
back to the filename. Nothing here is required of anybody: a fleet where no
agent ever writes a note behaves exactly as it does today.
"""

import glob
import json
import os
import time

HOME = os.path.expanduser("~")
NOTES_DIR = os.environ.get("FLEET_NOTES") or os.path.join(HOME, ".fleet", "notes")

# A note is a checkpoint, not a status file: it says what was true when it was
# written. Past this age it stops competing with what the transcript says now.
MAX_AGE_SECONDS = 36 * 3600
# A note written moments after a prompt is about that prompt: the agent read
# the new instructions and checkpointed. Only a prompt clearly later than the
# note overtakes it.
GRACE_MS = 5 * 1000

_cache = (0.0, {}, {})


def _read_one(path):
    try:
        with open(path, encoding="utf-8") as handle:
            row = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict):
        return None
    text = (row.get("text") or "").strip()
    if not text:
        return None
    try:
        stamp = int(row.get("at") or os.path.getmtime(path) * 1000)
    except (OSError, TypeError, ValueError):
        stamp = int(time.time() * 1000)
    return {
        "text": text[:400],
        "at": stamp,
        "by": (row.get("by") or "")[:40],
        "cwd": (row.get("cwd") or "").rstrip("/"),
        "session": (row.get("session") or "").strip(),
        "name": os.path.basename(path)[:-5],
    }


def load():
    """Every fresh note, indexed by session id and by working directory."""
    global _cache
    stamp, by_session, by_cwd = _cache
    if time.time() - stamp < 2.0:
        return by_session, by_cwd

    by_session, by_cwd = {}, {}
    cutoff = (time.time() - MAX_AGE_SECONDS) * 1000
    for path in glob.glob(os.path.join(NOTES_DIR, "*.json")):
        note = _read_one(path)
        if not note or note["at"] < cutoff:
            continue
        # Keep the newest note per target; an agent that checkpoints twice
        # should not have its first note win.
        for index, key in ((by_session, note["session"] or note["name"]),
                           (by_cwd, note["cwd"])):
            if key and (key not in index or index[key]["at"] < note["at"]):
                index[key] = note
    _cache = (time.time(), by_session, by_cwd)
    return by_session, by_cwd


def attach(sessions):
    """Hang each note on its session. Never overwrites what was read off disk.

    The note lands in its own field rather than replacing `now`, so the tile can
    show that a human-authored checkpoint exists without losing the evidence the
    collectors gathered. The UI decides which to lead with.
    """
    by_session, by_cwd = load()
    if not by_session and not by_cwd:
        return sessions

    # A directory is only a usable address when one session is sitting in it.
    # Nine agents share ~/ on this machine, and broadcasting one checkpoint to
    # all nine is worse than showing nothing: it invents nine false statements.
    crowd = {}
    for session in sessions:
        key = (session.get("cwd") or "").rstrip("/")
        crowd[key] = crowd.get(key, 0) + 1

    for session in sessions:
        cwd = (session.get("cwd") or "").rstrip("/")
        note = (by_session.get(session.get("sessionId") or "")
                or by_session.get(session.get("id") or ""))
        if not note and crowd.get(cwd) == 1:
            note = by_cwd.get(cwd)
        if not note:
            continue
        # A checkpoint describes the work as it stood when it was written.
        # Once the user has spoken again the session is on new instructions,
        # and the note -- however recent -- is about the old ones. It stays
        # readable in the drawer; it just stops leading the tile.
        spoke = session.get("promptAt") or 0
        overtaken = spoke > note["at"] + GRACE_MS
        session["noteStale"] = overtaken
        if overtaken:
            session["staleNote"] = note["text"]
            continue
        session["note"] = note["text"]
        session["noteAt"] = note["at"]
    return sessions
