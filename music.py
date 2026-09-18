"""YouTube Music, read through the account you choose to log in as.

Nothing here touches an audio stream. `ytmusicapi` reads the same private
endpoints the web app itself calls, to find out what is in a playlist; the audio
is played by the real music.youtube.com tab already open in Chrome, which this
module drives over AppleScript. The dashboard is a remote control, not a second
player: your Premium, your catalogue, your history and your ads-or-not all stay
exactly as they are, and a track that refuses to embed elsewhere plays fine
because it is playing where it always did. Nothing is downloaded, proxied or
re-hosted.

Two levels of access, and the useful half needs no login at all:

    anonymous   search the catalogue, open any public playlist, play anything
    logged in   the above, plus *your* library playlists

So the player works the moment the page loads, and logging in is an upgrade
rather than a gate.

Every call in here is network-bound and slow by the standards of this app, so
none of it is ever called from the snapshot loop -- that has a two-second budget
to keep. The HTTP handler is threaded, so a slow music request cannot hold up
the board.
"""

import json
import os
import re
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".config", "fleet")
AUTH_FILE = os.path.join(CONFIG_DIR, "ytmusic.json")

_lock = threading.Lock()
_clients = {}          # authed? -> YTMusic
_cache = {}
_last_error = ""


# --------------------------------------------------------------------------
# availability and auth

def available():
    """False if ytmusicapi is not installed: the dashboard still runs."""
    try:
        import ytmusicapi  # noqa: F401
        return True
    except ImportError:
        return False


def configured():
    return os.path.exists(AUTH_FILE)


def _client(authed):
    """One client per access level, built once and kept."""
    from ytmusicapi import YTMusic
    with _lock:
        hit = _clients.get(authed)
        if hit is None:
            hit = YTMusic(AUTH_FILE) if authed else YTMusic()
            _clients[authed] = hit
        return hit


def client():
    return _client(configured())


def configure(headers_raw):
    """Store the request headers the user pasted out of their own browser.

    ytmusicapi's `setup` parses a raw header block copied from the network tab
    on music.youtube.com and keeps the cookie needed to read that library. The
    file is written 0600 and is never read back out over HTTP -- the only thing
    any endpoint ever reports about it is whether it exists.
    """
    from ytmusicapi import setup
    global _clients, _cache
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    setup(filepath=AUTH_FILE, headers_raw=headers_raw)
    os.chmod(AUTH_FILE, 0o600)
    with _lock:
        _clients = {}
        _cache = {}
    return True


def forget():
    global _clients, _cache
    try:
        os.remove(AUTH_FILE)
    except OSError:
        pass
    with _lock:
        _clients = {}
        _cache = {}
    return True


# --------------------------------------------------------------------------

def _cached(key, ttl, produce):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    value = produce()
    _cache[key] = (time.time(), value)
    return value


def _art(thumbs, want=120):
    """The smallest thumbnail that is still at least `want` wide."""
    if not thumbs:
        return ""
    ordered = sorted(thumbs, key=lambda t: t.get("width") or 0)
    for thumb in ordered:
        if (thumb.get("width") or 0) >= want:
            return thumb.get("url") or ""
    return ordered[-1].get("url") or ""


def _artists(item):
    names = [a.get("name") for a in (item.get("artists") or []) if a.get("name")]
    if not names and item.get("author"):
        names = [item["author"]]
    return ", ".join(names)


def _track(item):
    """Flatten one YT Music item to what the player actually needs.

    `videoId` is the whole point: it is what the iframe player is handed. An
    item without one cannot be played -- unavailable in this region, taken down,
    or a non-song row -- and is dropped rather than shown as a dead line.
    """
    vid = item.get("videoId")
    if not vid or item.get("isAvailable") is False:     # greyed out in the playlist
        return None
    duration = item.get("duration") or ""
    if not duration and item.get("duration_seconds"):
        secs = int(item["duration_seconds"])
        duration = "%d:%02d" % (secs // 60, secs % 60)
    return {
        "id": vid,
        "title": item.get("title") or "untitled",
        "artist": _artists(item),
        "duration": duration,
        "art": _art(item.get("thumbnails")),
    }


def _tracks(items):
    out = [_track(i) for i in (items or [])]
    return [t for t in out if t]


# --------------------------------------------------------------------------
# reads

def playlists():
    """The signed-in account's own playlists. Empty when not logged in."""
    if not configured():
        return []

    def read():
        out = []
        for item in client().get_library_playlists(limit=50):
            pid = item.get("playlistId")
            if not pid:
                continue
            out.append({
                "id": pid,
                "title": item.get("title") or "untitled",
                "count": item.get("count"),
                "art": _art(item.get("thumbnails")),
            })
        return out
    return _cached("playlists", 300, read)


def playlist(playlist_id, limit=120):
    """One playlist's tracks. Works unauthenticated for public playlists."""
    def read():
        if playlist_id == "LM":          # "Liked music" has its own endpoint
            data = client().get_liked_songs(limit=limit)
        else:
            data = client().get_playlist(playlist_id, limit=limit)
        return {
            "id": playlist_id,
            "title": data.get("title") or "playlist",
            "art": _art(data.get("thumbnails")),
            "tracks": _tracks(data.get("tracks")),
        }
    return _cached("pl:" + playlist_id, 300, read)


def search(query, limit=25):
    """Songs matching a query. This is what makes a theme's playlist work.

    Each theme names its music as a plain search string rather than a playlist
    id, so a theme stays portable: it does not depend on a particular playlist
    existing, or on being logged in at all.

    Returns the songs, and under `more` the videos for the same query. A song
    on YouTube Music is an audio track the label licensed to that app, and a
    fair share of them refuse the standard embed player ("this video is
    unavailable"); nothing on this side can tell which in advance, so the page
    finds out by cueing each one quietly and drops the dead ones (see the
    scout in ui.html). The videos are the reserve it tops the crate up from:
    the same song by way of its video or a fan upload, which is audio all the
    same to a player whose screen is covered by the cover art.
    """
    def read():
        songs = _tracks(client().search(query, filter="songs", limit=limit))[:limit]
        seen = {t["id"] for t in songs}
        try:
            videos = _tracks(client().search(query, filter="videos", limit=limit))
        except Exception:
            videos = []
        return {"tracks": songs, "more": [t for t in videos if t["id"] not in seen][:limit]}
    return _cached("q:" + query.lower().strip(), 600, read)


def state():
    """What the page needs on load: can we play, and whose library is this."""
    if not available():
        return {"available": False, "configured": False, "playlists": [],
                "error": "ytmusicapi is not installed"}
    try:
        return {"available": True, "configured": configured(),
                "playlists": playlists(), "error": _last_error}
    except Exception as exc:
        # A stale cookie shows up here as a parse or auth error. Say so plainly
        # rather than pretending the library is empty.
        return {"available": True, "configured": configured(), "playlists": [],
                "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}


# --------------------------------------------------------------------------
# driving the tab
#
# The page never sends a command string -- it sends a track id or one of three
# fixed words, exactly like the "open in iTerm" path. osascript is invoked
# through argv rather than a shell, and every id is checked against a shape
# below before it is allowed near an AppleScript string literal, so nothing a
# browser types can reach either a shell or the scripting bridge.

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
LIST_RE = re.compile(r"^[A-Za-z0-9_-]{2,128}$")
COMMANDS = ("playpause", "next", "previous")


def _osa(script, timeout=6):
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return "", "osascript unavailable"
    if proc.returncode != 0:
        return "", (proc.stderr or "").strip()[:200]
    return proc.stdout.strip(), ""


def _in_tab(body):
    """Run a body against the first music.youtube.com tab in any window."""
    return ('tell application "Google Chrome"\n'
            '  repeat with w in windows\n'
            '    repeat with t in tabs of w\n'
            '      if URL of t contains "music.youtube.com" then\n'
            '        %s\n'
            '      end if\n'
            '    end repeat\n'
            '  end repeat\n'
            'end tell\n'
            'return "NOTAB"' % body)


# Read straight off the page, so this reports what is actually playing rather
# than what we last asked for. Title, artist and position only.
_STATE_JS = (
    "(function(){"
    "var b=document.querySelector('ytmusic-player-bar');"
    "var v=document.querySelector('video');"
    "if(!b||!v) return '';"
    "var t=b.querySelector('.title');"
    "var y=b.querySelector('.byline');"
    "return JSON.stringify({"
    "title:t?t.textContent.trim():'',"
    "artist:y?y.textContent.trim():'',"
    "playing:!v.paused,"
    "pos:Math.floor(v.currentTime||0),"
    "dur:Math.floor(v.duration||0)});"
    "})()"
)

_CMD_JS = {
    # The <video> element is steadier than the button for play/pause: the
    # button's id has moved twice in YT Music's history, the element has not.
    "playpause": "(function(){var v=document.querySelector('video');"
                 "if(!v) return 'no';v.paused?v.play():v.pause();return 'ok';})()",
    "next": "(function(){var b=document.querySelector('.next-button');"
            "if(!b) return 'no';b.click();return 'ok';})()",
    "previous": "(function(){var b=document.querySelector('.previous-button');"
                "if(!b) return 'no';b.click();return 'ok';})()",
}


def _run_js(code):
    escaped = code.replace("\\", "\\\\").replace('"', '\\"')
    # Chrome's dictionary is `execute <tab> javascript "..."`. The `... in t`
    # form is Safari's `do JavaScript` and AppleScript rejects it here.
    out, err = _osa(_in_tab('return execute t javascript "%s"' % escaped))
    if err and "javascript" in err.lower():
        return "", "jsoff"      # Chrome ships with this switched off
    return out, err


def now():
    """What the tab is playing, with a title-bar fallback.

    Full state needs Chrome's "Allow JavaScript from Apple Events". Without it
    the tab title still carries the track, which is enough for the strip to say
    something true rather than going blank -- so the player degrades to
    "shows what is on, can start a track" instead of breaking outright.
    """
    def read():
        out, err = _run_js(_STATE_JS)
        if out and out != "NOTAB":
            try:
                state = json.loads(out)
                state.update(tab=True, rich=True, jsoff=False)
                return state
            except ValueError:
                pass
        title, terr = _osa(_in_tab("return title of t"))
        if title and title != "NOTAB":
            name = re.sub(r"\s*-\s*YouTube Music\s*$", "", title).strip()
            if name and name.lower() != "youtube music":
                part = name.rsplit(" - ", 1)
                return {"tab": True, "rich": False, "jsoff": err == "jsoff",
                        "playing": None, "title": part[0],
                        "artist": part[1] if len(part) > 1 else ""}
            return {"tab": True, "rich": False, "jsoff": err == "jsoff",
                    "playing": False, "title": "", "artist": ""}
        return {"tab": False, "rich": False, "jsoff": err == "jsoff",
                "reason": terr or err or "no music.youtube.com tab open"}
    return _cached("now", 1.2, read)


def command(cmd):
    """Transport. Only the three fixed strings above ever reach Chrome."""
    if cmd not in COMMANDS:
        return False, "unknown command"
    out, err = _run_js(_CMD_JS[cmd])
    if err == "jsoff":
        return False, ("Chrome needs View > Developer > "
                       "Allow JavaScript from Apple Events")
    if out == "NOTAB":
        return False, "no music.youtube.com tab open"
    if out == "ok":
        return True, ""
    return False, err or "the player bar did not answer"


def seek(seconds):
    """Jump the tab's <video> to a position, in whole seconds.

    Kept apart from command() because it is the one drive call that carries a
    number. It is coerced through int() before it is formatted into the script,
    so the only thing that can reach Chrome is a bare integer.
    """
    try:
        where = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return False, "bad position"
    out, err = _run_js(
        "(function(){var v=document.querySelector('video');"
        "if(!v) return 'no';v.currentTime=%d;return 'ok';})()" % where)
    if err == "jsoff":
        return False, ("Chrome needs View > Developer > "
                       "Allow JavaScript from Apple Events")
    if out == "NOTAB":
        return False, "no music.youtube.com tab open"
    return out == "ok", "" if out == "ok" else "the player did not answer"


def play(video_id, playlist_id=""):
    """Point the tab at a track. Plain navigation, so this needs no JS switch."""
    if not VIDEO_RE.match(video_id or ""):
        return False, "bad track id"
    url = "https://music.youtube.com/watch?v=" + video_id
    if playlist_id and LIST_RE.match(playlist_id):
        url += "&list=" + playlist_id
    out, err = _osa(_in_tab('set URL of t to "%s"\n        return "ok"' % url))
    if out == "ok":
        return True, ""
    if out == "NOTAB":
        return False, "no music.youtube.com tab open"
    return False, err or "Chrome did not answer"
