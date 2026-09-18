"""Host and fleet telemetry, read straight off the machine.

Nothing here asks an agent for anything: it is `sysctl`, `vm_stat`, `ps` and a
couple of file sizes. Expensive readings carry their own longer cache.
"""

import os
import re
import subprocess
import time

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")

_slow_cache = {}


def _sh(*args, timeout=4):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _cached(key, ttl, produce):
    hit = _slow_cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    value = produce()
    _slow_cache[key] = (time.time(), value)
    return value


def _sysctl_int(name):
    raw = _sh("sysctl", "-n", name).strip()
    try:
        return int(raw)
    except ValueError:
        return 0


_const_cache = {}


def _sysctl_const(name):
    """A sysctl that cannot change while the machine is up.

    hw.memsize and kern.boottime were each being spawned thirty times a minute
    to be told the same number. Nothing about a rebuild is cheap enough to
    afford asking twice, let alone a thousand times an hour.
    """
    if name not in _const_cache:
        _const_cache[name] = _sh("sysctl", "-n", name).strip()
    return _const_cache[name]


def process_table():
    """The one `ps -A` per rebuild, shared with the session collectors.

    The collectors already collapsed their own three walks into one; this was
    the fourth, left outside because telemetry lives in a different module and
    wanted different columns. The column set here is the union of what both
    readers need, so one spawn now answers both. The window is shorter than the
    rebuild interval, so every pass still gets its own reading.
    """
    return _cached("ps", 1.0, lambda: _sh(
        "ps", "-Ao", "pid=,etime=,rss=,pcpu=,ppid=,args=", timeout=6))


def parents():
    """pid -> parent pid, from the same listing. The terminal sheet walks
    this to find which of its shells an agent process is running under."""
    found = {}
    for line in process_table().splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            found[int(parts[0])] = int(parts[4])
        except ValueError:
            pass
    return found


# --------------------------------------------------------------------------

def memory():
    total = int(_sysctl_const("hw.memsize") or 0)
    out = _sh("vm_stat")
    if not out or not total:
        return {"total": total, "used": 0, "pct": 0}
    page = 4096
    head = re.search(r"page size of (\d+) bytes", out)
    if head:
        page = int(head.group(1))
    counts = dict(re.findall(r"^([^:]+):\s+(\d+)\.", out, re.M))

    def pages(label):
        return int(counts.get(label, 0))

    used = (pages("Pages active") + pages("Pages wired down")
            + pages("Pages occupied by compressor")) * page
    return {"total": total, "used": used,
            "pct": round(100.0 * used / total, 1) if total else 0}


def swap():
    raw = _sh("sysctl", "-n", "vm.swapusage")
    used = re.search(r"used\s*=\s*([\d.]+)M", raw)
    return {"usedMb": float(used.group(1)) if used else 0.0}


def cpu():
    cores = os.cpu_count() or 1
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        one = five = fifteen = 0.0
    return {"cores": cores, "load1": round(one, 2), "load5": round(five, 2),
            "load15": round(fifteen, 2),
            "pct": round(min(100.0, 100.0 * one / cores), 1)}


def uptime():
    raw = _sysctl_const("kern.boottime")
    match = re.search(r"sec\s*=\s*(\d+)", raw)
    return int(time.time() - int(match.group(1))) if match else 0


def disk():
    def read():
        try:
            st = os.statvfs("/System/Volumes/Data")
        except OSError:
            try:
                st = os.statvfs("/")
            except OSError:
                return {"freeGb": 0, "pct": 0}
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        return {"freeGb": round(free / 1e9, 1),
                "pct": round(100.0 * (total - free) / total, 1) if total else 0}
    return _cached("disk", 60, read)


def power():
    raw = _sh("pmset", "-g", "batt")
    pct = re.search(r"(\d+)%", raw)
    source = "AC" if "AC Power" in raw else ("battery" if raw else "?")
    charging = "charging" in raw and "not charging" not in raw
    return {"pct": int(pct.group(1)) if pct else None, "source": source,
            "charging": charging}


def pressure():
    """Memory pressure: the macOS number that actually predicts a stall.

    This slot used to hold a thermal reading off `pmset -g therm`, but Apple
    Silicon records no CPU thermal level at all -- it answers "no CPU power
    status has been recorded", the regex never matched, and the gauge sat on
    its hardcoded 100 forever. Real temperatures need `powermetrics` as root,
    which a LaunchAgent has no business asking for. Pressure is free, needs no
    privilege, moves under load, and is what bites first on a 16GB machine
    running a fleet: it counts memory that cannot be reclaimed, so it separates
    "75% used and perfectly happy" from "75% used and swapping".
    """
    def read():
        free = re.search(r"free percentage:\s*(\d+)",
                         _sh("memory_pressure", "-Q"))
        return 100 - int(free.group(1)) if free else None
    return _cached("pressure", 15, read)


def gpu():
    """GPU busy share, off the accelerator's own counters.

    Apple Silicon publishes "Device Utilization %" in the IOAccelerator
    registry entry, readable by anyone; no `powermetrics`, no root. One
    `ioreg` costs about 25ms. None when the machine has nothing that
    answers (a VM, an unfamiliar GPU), and the trace leaves that line out.
    """
    def read():
        raw = _sh("ioreg", "-r", "-d", "1", "-c", "IOAccelerator",
                  "-k", "PerformanceStatistics")
        match = re.search(r'"Device Utilization %"=(\d+)', raw)
        return {"pct": int(match.group(1))} if match else {"pct": None}
    return _cached("gpu", 1.0, read)


_AGENT_PATTERNS = (
    ("claude", re.compile(r"(^|/)claude(\s|$)|/share/claude/versions/|claude bg-")),
    ("codex", re.compile(r"/codex(\s|$)|(^|/)codex\s")),
    ("antigravity", re.compile(r"antigravity")),
)
# The desktop apps are not agent sessions; they would swamp the footprint.
_NOT_AGENT = re.compile(r"/Applications/|Electron Framework|Helper|crashpad")


def processes():
    """RSS and CPU actually spent by agent CLIs, split by provider."""
    out = process_table()
    tally = {key: {"count": 0, "rssMb": 0.0, "cpu": 0.0}
             for key, _ in _AGENT_PATTERNS}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        _, _etime, rss, pcpu, _ppid, args = parts
        if _NOT_AGENT.search(args):
            continue
        for key, pattern in _AGENT_PATTERNS:
            if pattern.search(args):
                try:
                    tally[key]["rssMb"] += int(rss) / 1024.0
                    tally[key]["cpu"] += float(pcpu)
                except ValueError:
                    pass
                tally[key]["count"] += 1
                break
    for slot in tally.values():
        slot["rssMb"] = round(slot["rssMb"], 1)
        slot["cpu"] = round(slot["cpu"], 1)
    return tally


def archive():
    """How much disk the transcript history has grown to."""
    def read():
        total = files = 0
        for root, _, names in os.walk(os.path.join(CLAUDE_DIR, "projects")):
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
                files += 1
        return {"gb": round(total / 1e9, 2), "files": files}
    return _cached("archive", 600, read)


def snapshot():
    procs = processes()
    return {
        "cpu": cpu(),
        "gpu": gpu(),
        "memory": memory(),
        "swap": swap(),
        "disk": disk(),
        "power": power(),
        "pressurePct": pressure(),
        "uptime": uptime(),
        "processes": procs,
        "agentRssMb": round(sum(p["rssMb"] for p in procs.values()), 1),
        "agentCpu": round(sum(p["cpu"] for p in procs.values()), 1),
        "agentProcs": sum(p["count"] for p in procs.values()),
        "archive": archive(),
    }
