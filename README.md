# Fleet — agent console

A single page that shows every agent session running on this Mac: Claude Code,
Antigravity (`agy`) and Codex, grouped by agent and by project, alongside live
host telemetry. Built for a MacBook Air used as a second screen.

    ./install.sh          # deploy, install deps, run at login on port 8787
    ./fleet.command       # open it in a chromeless dashboard window
    ./uninstall.sh        # remove the login agent

The installer keeps a self-contained runtime and virtual environment under
`~/.local/share/fleet-dashboard`. This avoids macOS denying a background
LaunchAgent access to a checkout under `~/Documents`. It requires Python 3.10+
and selects Homebrew or Anaconda Python automatically when Apple Python is too
old.

Or run the dependency-free core by hand: `python3 dashboard.py --port 8787`.

## How it reads sessions

Nothing is asked of the agents. Every field is read from state they already
write to disk, so no session has to summarise itself or keep a status file:

| Lane | Source |
|---|---|
| Claude Code | `claude agents --json`, `~/.claude/jobs/<id>/state.json`, `~/.claude/jobs/<id>/timeline.jsonl`, the session transcript under `~/.claude/projects/` |
| Antigravity | `~/.gemini/antigravity-cli/conversations/*.db` (`steps`), `presence/*.lock`, `history.jsonl` for the workspace |
| Codex | `~/.codex/state_5.sqlite` (`threads`) |
| any of them | the running process itself, via `ps` + `lsof` |

A session exists the moment its CLI starts, but Codex and Antigravity write
nothing to disk for the first minutes — a Codex thread row only appears once the
turn is committed. So a running `codex` or `agy` process with no matching
on-disk session gets its own tile immediately, marked `live`, and is replaced by
the real record once one is written. Editor hosts, app-servers and daemons are
excluded. Adding a fourth agent means one line in `_LIVE_PROCS`.

Transcripts are read incrementally: the first pass scans the file, and every
refresh after that reads only the bytes appended since.

### Refresh

The snapshot is rebuilt every two seconds and the page polls every second, so
a change is on screen about a second after it lands on disk. Two things sit on
slower clocks so that pace stays cheap: `claude agents --json` spawns the Node
CLI and costs ~350ms against ~90ms for everything else put together, so the
roster is re-read every six seconds while the transcripts behind it -- which
is where a tile's state, gist and age come from -- are re-read every pass; and
the process table, which all three lanes used to ask for separately, is now
read once per pass. Net effect: a rebuild costs ~165ms against the ~450ms it
used to, so the board refreshes two and a half times as often for about the
same CPU. The rebuild loop sleeps the remainder of the interval rather than
the whole of it, so the cadence is the two seconds it claims.

The page rebuilds the tiles only when something on them actually moved, with
a five-second floor so ages keep counting on a quiet board. Otherwise a hover,
a scroll position or a half-made click would be thrown away every second, and
an open drawer would pull the text selection out from under you.

### Antigravity in particular

`history.jsonl` records most prompts **without** a `conversationId`, so keying
off it loses whole sessions. The conversation databases are read instead: steps
are protobuf blobs, and the prompt is recovered as the printable run that occurs
twice in the message — length alone picks injected rules like
`#timeout_long_running_search_command` over a prompt like `test_update`. A
running `agy` with no fresh presence lock hands its live state to the most
recently touched conversation, so it shows as itself rather than as a pid.

## The name and the two lines on each tile

Nothing here is summarised by this tool or by an agent on demand. Every line is
a summary somebody already wrote, picked off disk in order of quality:

**Name** — what the agent itself calls the session. Claude Code writes two
kinds of title into the transcript: `custom-title` (the `--name` a worktree
or `/rename` gave it) and `ai-title` (the title the model wrote from the
opening prompt, "Agentic workflows presentation"). The custom one wins, then
the model's, and only a session with neither falls back to the roster handle
(`tiago-01`). The handle is still what `claude attach` takes, so it stays in
the drawer beside the name and `fleet-name` matches on it. Antigravity keeps
a model-written title per conversation in `conversation_summaries.db`, and
Codex in `threads.name`; both lead their tiles, with a clipped opening prompt
only when there is none. A model title is written once, at the start, so a
session that has drifted a long way from its first prompt keeps its first
name -- the gist beneath it is where the drift shows, and `fleet-name` is
the fix when it matters.

**Brief** — what the session was asked to do:
1. the *Primary Request and Intent* section of the session's own compact
   summary (both layouts are parsed — markdown headings and bold numbered
   items — and the boilerplate preamble is skipped)
2. a background worker's launch `intent`; if that intent only points at a brief
   document, the document it names is read instead
3. `~/.claude/plans/<slug>.md` — the plan the model wrote in plan mode, found
   through the `slug` on the session's transcript rows
4. the first substantial user prompt, skipping nudges ("retry?") and
   harness-injected turns (monitor events, task notifications)

**Now** — where it has got to: the compact summary's *Current Work* section,
`output.result` when done, `needs` when blocked, the latest status line, and
otherwise whichever of the last prompt and the last real reply was said
later -- the reply once the agent has answered, the prompt while it is still
working on one (short sign-offs are skipped in favour of the reply before).

**Note** — the one line a session chose to write (`~/.fleet/fleet-note`)
leads the tile while it is current. Once the user has prompted again the
session is on new instructions and the note is about the old ones: it stops
leading, and the drawer files it as "its last note -- before your latest
prompt".

**Next step it planned** (drawer only) — the compact summary's *Optional Next
Step* or *Pending Tasks*.

Codex supplies model-written session names in `threads.name`; those lead the
tile title, with the nickname or a clipped prompt only as fallbacks. Its SQLite
preview often repeats the opening prompt, so **Now** is read incrementally from
the rollout instead: the latest meaningful commentary/final response, or a new
user request that has not received a response yet. Harness instructions and
one-word nudges are excluded, and only newly appended bytes are read after the
first refresh.

## Status colour

Fixed across every theme: **blocked** red, **running** green, **idle** blue
(dimmed), **done** amber, **unknown** grey. Green is the state you can leave
alone; amber is the one waiting for you to come and collect it. The gauges
never followed the status words -- they use `--good` and `--warn`, which are
plain health paint and stay put if the status colours are ever reassigned.

## Themes

Twenty colour schemes, picked from the HUD and remembered per browser.
`?theme=` in the URL overrides one load, and the settings card (`⌘,`) keeps a
count of how often each theme has been picked from the menu.

| | |
|---|---|
| **console** | cold cyan on navy — the default HUD |
| **neon film** | magenta on violet-black, heavy neon, scanline drift |
| **earth** | Sherwood Forest — deep canopy, emerald, bark, film grain |
| **neutral** | grey slate, no glow, no scanlines |
| **paper** | bright monochrome editorial sheet |
| **Hotline Miami** | tropical VHS neon and misregistered colour plates |
| **Cyberpunk 2077** | black-and-yellow warning graphics |
| **Portal** | clean test-chamber white with orange/blue portals |
| **Lord of the Rings** | candlelit vellum and illuminated-page details |
| **Skyrim** | black glass, hairlines and diamonds, magicka/health/stamina bars, an aurora |
| **Pokémon** | yellow-bordered cards, type-coloured headers, a four-green handheld screen, Poké Ball status dots, a battle box with a live HP bar |
| **Sonic** | cobalt CRT, ring gold and chequered motion |
| **Team Fortress** | TF2 for real: dark HUD plaques over cream, RED/BLU plates, class-emblem rails, a capture stripe on running tiles, a kill feed |
| **Casino Royale** | racing green and marble, yellow inlay, a roulette wheel turning in the corner |
| **Fallout** | a Pip-Boy tube: P1 phosphor behind curved glass, scanlines, amber for what needs you |
| **Matrix** | black terminal with the rain behind the glass, P31 mint, a blinking cursor for a sigil |
| **Persona 5** | a two-colour print job: vermilion on newsprint black, every tile snipped with scissors, zero glow |
| **Minecraft** | quarried stone by torchlight, grass-block headers, the survival HUD, a splash on the title |
| **Hollow Knight** | layered indigo void, bone hairlines on the top edge only, souls drifting up, a bench to rest on |
| **Apollo** | Mission Control, 1969: grey-green console bays under the plotboard wall, every status dot a square indicator lamp; collapsing the board uncovers the GO/NO GO poll — a station plaque per session, the GET clock, MASTER ALARM while anything is NO GO |

Each theme sets a `--glow` factor that every shadow multiplies, so neutral is
genuinely flat rather than dimmed.

## The HUD

One row, sized in `vh` so the readings keep their share of the screen instead
of being squeezed to hold the session tiles at a fixed size: the brand and
tally, six arc gauges in a 2x3 block, the trace, and the numeric readout. The
gauge dials scale with the strip, and the trace carries gridlines,
end-of-series markers and its current values in the caption.

The gauges are `cpu`, `mem`, `ram` (resident set of the agent processes),
`live` (active sessions over total), `pres` and `disk` (gigabytes free). The
readout beside them carries `load`, `procs`, `swap`, `power`, `tokens` and
`uptime`. `power` reads `100% AC` on the wall and turns red once the machine
is off the cable and under 20%.

`pres` is memory pressure, read from `memory_pressure -Q`. It sat here as a
thermal gauge until it turned out that Apple Silicon records no CPU thermal
level at all: `pmset -g therm` answers "no CPU power status has been
recorded", the regex never matched, and the dial reported its fallback
constant of 100 forever. Real die temperatures need `powermetrics` as root,
which is not a thing a LaunchAgent should be asking for. Pressure costs
nothing, needs no privilege, moves under load, and measures the resource that
actually bites on a 16GB machine running a fleet -- it counts memory that
cannot be reclaimed, so it tells 76% used and happy apart from 76% used and
swapping.

## Layout

Lanes are as tall as the work moving in them and projects inside a lane as
wide as theirs, so a busy agent or project owns more of the screen. It is
weighted work, not headcount: blocked and running sessions pull a full share,
unknown 0.6, done 0.45 and idle 0.3, with a floor of one share per group. A
project sitting on six idle sessions therefore stops crowding out the one that
is running, while staying visible. Idle tiles are also dimmed and drained of
colour, and come back to full strength on hover or when selected. Every
lane's floor is a fraction of an equal share of the board and the result is
measured and backed off until it genuinely fits, so a fourth or tenth agent
shrinks every lane rather than pushing the last one off the screen. Within a
group every column count the width allows is tried, and the one that leaves the
least dead space while holding a readable tile shape wins. Tile bounds scale
with the viewport, so a smaller screen shrinks the tiles instead of squeezing
the HUD to keep them the same size; below the legibility floor a group scrolls.
Tile width is capped at about 3:1, so two sessions alone in a wide lane get
readable tiles rather than one letterbox each.
Click a project header to minimise it; its area goes to its neighbours and the
choice is remembered. `#<session-id>` in the URL deep-links to a tile.

**Collapse all** strips every tile to its essentials -- name and status line,
no gist -- and lets the lanes shrink to fit what is left, so the whole fleet
reads in a glance and the slack pools once at the foot of the board instead of
opening a hole in every project. The same button then reads **expand all**,
which restores the gist and also brings back any project minimised to a strip.
It sits in the HUD's row of squares (`⊟`/`⊞`) and answers to `⌘E`. The choice
is remembered per browser, and `?collapse=1` forces it for one load the way
`?theme=` does.

## Opening a session

The detail drawer can open a session in iTerm, Terminal or VS Code. The page
only ever sends a session id and a target; the command is assembled in
`actions.py` from the current snapshot, so nothing typed in a browser reaches a
shell. A session that is mid-turn gets a shell in its directory rather than a
`--resume`, which would start a second copy of it.

iTerm receives a temporary `.command` file through macOS LaunchServices, so it
does not need Automation permission. If iTerm refuses the file, Fleet opens the
same safe script in Terminal. When a disposable worktree has already been
removed, the action lands in its surviving project root and still offers the
session resume command.

"Reveal in iTerm" focuses the tab a session is already running in. That one
does script iTerm, so the first click asks macOS for Automation permission
(Python → iTerm). Allow it once; if you clicked Don't Allow, re-enable it in
System Settings → Privacy & Security → Automation.

## The terminal sheet

Start with `--terminal` (the installer does) and a real shell opens inside the
page, in a sheet that docks to the bottom. `⌘J` or `ctrl-\`` toggles it. Every
tile's drawer has a "shell here" button; the sheet's `+` opens a picker — any
folder the board knows about, or one typed under `~`, and shell / claude / agy /
codex — and `×` closes the active one. The page sends a session id, or a folder
plus an agent key; the server maps the key through a fixed table, so no command
string ever comes from the browser. `⌘[` and `⌘]` cycle through terminal tabs,
`⌘T` opens a new shell in `~`, and `⌘W` closes the active tab. Fresh and
resumed Codex terminals run with `--yolo`. Mac editing keys work as in iTerm's
Natural Text Editing preset (⌘←/→, ⌘⌫, ⌥←/→, ⌥⌫, ⌘K), Shift-Enter inserts a
newline, and `⌘C`/`⌘V` copy a selection and paste as in any terminal. The
face is SF Mono at medium weight with loose leading, whatever the browser's
own monospace preference.

`fleet.command` uses a tiny native WebKit shell so Chrome cannot consume
`⌘T` before the dashboard sees it. The shell is compiled locally on first use;
if the macOS command-line tools are unavailable, the launcher falls back to
Chrome and the on-page shortcuts that Chrome permits.

The terminal is loopback-only and gated by a per-process token, so it is off
when the server binds anything but 127.0.0.1.

## One board, no strays

Every instance registers itself under `~/.config/fleet/run/` (an `flock` for
liveness, JSON for description), and an instance nobody polls for 30 minutes
exits on its own — unless it is the kiosk (`--kiosk`, which the installer sets)
or has a live shell open. Fifteen forgotten dev copies once took 28% of the
machine; this is the fix.

    python3 dashboard.py --list                   # who is running, on which port, from where
    python3 dashboard.py --stop-strays            # SIGTERM everything except the kiosk
    python3 dashboard.py --port 8802 --replace    # take a port over from a stray
    python3 dashboard.py --port 8802 --idle-exit 0   # a dev copy that must not idle-exit

A second bind on a taken port fails loudly and names the holder. SIGTERM runs
the same shutdown as Ctrl-C, so a killed instance closes its shells instead of
orphaning them.

## Reaching it from another machine

The board itself is plain HTTP and can be served on the LAN:

    python3 dashboard.py --host 0.0.0.0 --port 8787      # no --terminal: it refuses off-loopback
    ipconfig getifaddr en0                                # this Mac's address, e.g. 192.168.1.23

then open `http://<that address>:8787` on the other device. The LaunchAgent
installed by `install.sh` binds 127.0.0.1 with the terminal on; run a second
copy by hand for the LAN, or edit the plist's `--host` and drop `--terminal`.

## YouTube Music

The floating player uses YouTube's visible iframe player for playback. Fleet
does not download, proxy or re-host audio. Catalogue search and public tracks
work anonymously; signing in adds the account's own library playlists.

To connect a library:

1. Open `music.youtube.com`, sign in, and open the browser developer tools.
2. In **Network**, select an authenticated `browse` request and copy its
   request headers.
3. In Fleet, open **music → sign in**, paste the headers, and choose
   **save account**.

The header block is posted only to the loopback dashboard. It is converted by
`ytmusicapi` into `~/.config/fleet/ytmusic.json`, stored with mode `0600`, never
returned by an endpoint, and removable with **forget account**. Theme changes
can seed the queue with a matching search; the current queue and playback
position survive page refreshes. The player can also collapse to a compact
now-playing bar without unmounting its iframe or interrupting the track.
