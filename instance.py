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
