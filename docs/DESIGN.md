# Fleet Dashboard — how it works

The long-form notes behind the board: what each surface shows, where every
number comes from, and why it is measured the way it is. Start with the
[README](../README.md) for what it is and how to install it; this document is
the reference.

    ./install.sh          # deploy, install deps, run at login on port 8787
    ./fleet.command       # open it in a chromeless dashboard window
    ./uninstall.sh        # remove the login agent

The installer keeps a self-contained runtime and virtual environment under
`~/.local/share/fleet-dashboard`. This avoids macOS denying a background
LaunchAgent access to a checkout under `~/Documents`. It requires Python 3.10+
and selects Homebrew or Anaconda Python automatically when Apple Python is too
old. It also builds `Fleet Dashboard.app` in the runtime and links it onto the
Desktop: double-click it to open the board, and if the board is down it starts
the login agent itself.

The dashboard owns the shells it opens, and a restart hangs up on all of them.
Run `install.sh` from one of those shells and it detaches the restart into its
own session first, so the board comes back even though the shell that asked
for it does not.

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

Twenty-six colour schemes, listed alphabetically, picked from the HUD and
remembered per browser.
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
| **Portal** | clean test-chamber white; a blue and an orange portal in the side walls, and a companion cube floating about the room that goes in one and out the other with its speed kept — pick it up and throw it; a session changing state also crosses, as a dot in its new colour |
| **Lord of the Rings** | candlelit vellum: an illuminated initial on every title, the session's own note rubricated in red ink, and the One Ring at the foot of the desk — plain gold while the cpu is cold, red-hot with the inscription burning as it climbs, captioned with the figure; collapse the board for the beacons of Gondor, one lit per session stuck or asking |
| **Skyrim** | black glass, hairlines and diamonds, an aurora; magicka/health/stamina bars that are the memory left, the pressure headroom and the CPU idle, each captioned with its reading |
| **Pokémon** | yellow-bordered cards, type-coloured headers, a four-green handheld screen, Poké Ball status dots, a battle box with a live HP bar |
| **Sonic** | cobalt CRT, ring gold and chequered motion |
| **Team Fortress** | TF2 for real: dark HUD plaques over cream, RED/BLU project plates, the rails as charcoal plaques with the agent's mark on a class-emblem badge, a capture stripe on running tiles, a kill feed; a quiet lane's RED/BLU bar is a control point — the ceasefire stripe sits at the cpu (then memory, then pressure), prints the figure, and the legend says which side is which; the round control point is set into the floor at the corner, under the lanes, and collapsing the board uncovers it |
| **Casino Royale** | a roulette table set into marble: each lane is cloth inside a padded leather rail with the racetrack — the same oval on every lane, its ends a fixed radius — printed on it, and the cloth is six layers — weave, nap, pile highlights, lamp sheen, vignette — tuned per material. The outside bets printed on a closed rail (or the table section of the settings card) lay a different cloth each — green baize, blue speed cloth, red velvet, black leather, burgundy felt, royal pinstripe — remembered per browser. Every card wears its suit in the corner (hearts in play, diamonds for a jackpot, spades for a bust, clubs waiting on your bet), a project's head count is a die, an agent's count on its rail a chip, the card in hand wears the dealer button, the gauges' tracks are the wheel's frets, an empty lane says PLACE YOUR BETS, the side panel is papered in suits, the wheel turns in the corner — set into the table under the padded rails and the cards, with a red ball loose in it — and a session finishing drops the ball. The card room: every card is a real one — cream stock, a printed frame, its index (rank by its place in the hand, suit by state) top left and bottom right in the suit's ink, one deep colour per state; a folded card (idle, or off the table) lies face down with nothing on it but the back, wine with a gold lattice and the house spade — point at it to peek, the way you look at a hole card; a new hand is dealt in (face down if it arrives folded), a card whose state changes is turned right over, a card that folds turns down onto its back and one that comes back turns up off it, the wordmark riffles the deck; the rails, the closed rails, the drawer and the sheet's bar are crushed velvet (wine, or midnight on the red cloths), and a velvet rope goes across a closed table |
| **Fallout** | a Pip-Boy tube: P1 phosphor behind curved glass, scanlines, amber for what needs you |
| **Matrix** | black terminal with the rain behind the glass, P31 mint, a blinking cursor for a sigil |
| **Persona 5** | a two-colour print job: vermilion on newsprint black, every tile snipped with scissors, zero glow |
| **Minecraft** | quarried stone by torchlight, grass-block headers, a splash on the title; the survival HUD is live and captioned -- hearts for the memory left, the XP bar for the CPU, the level for the sessions at work |
| **Hollow Knight** | layered indigo void, bone hairlines on the top edge only, souls drifting up, a bench to rest on; move the pointer over the void and a lumafly's worth of light shows Cornifer's map under it — a dozen hatched rooms with their ledges, tunnels with dead ends and side chambers, dashed paths he only heard about, benches, stag stations, grub jars, a hot spring, geo, his compass — one tile drawn to run on across its own edges |
| **Severance** | the severed floor: the MDR terminal's teal-black glass with the numbers faint under everything, files numbered on their door plates; a stuck session's numbers tremble (they are scary), a session waiting is a wellness check; the bins along the foot are the host's quota — WO the cpu, FC the memory, DR the pressure, MA the disk — filling as the figures rise; collapse the board for the refinement field with a box drawn round every frightening cluster |
| **Evangelion** | Central Dogma: orange on black, two corners cut off every panel, a hex grid behind the instruments; every status dot a hexagon, a stuck unit is PATTERN BLUE (hazard rib, flashing tag); always on, the sync ratio (cpu), the A.T. field (memory headroom) and the power source — external on the umbilical cable, internal on the battery with its charge, red and flashing (the flash has a switch in the settings card, under **power**); collapse the board for the MAGI, one computer per provider voting off its own lane (承認 / 保留 / 否決 / 不在) and the resolution |
| **Doom** | the base, 1993: riveted plates, red LED digits, E1M1-numbered maps, blood on a stuck door; the status bar runs the full width, always on — AMMO the sessions working, HEALTH the memory free, ARMS the states present, ARMOR the pressure headroom, KEYS what is finished / waiting / stuck, the ammo table the sessions by provider — and the marine's face in the middle bleeds while anything is stuck or the pressure is over 85, grins when a session finishes, and otherwise glances about at random and blinks on its own clock; collapse the board for the intermission tally |
| **The Sims** | the lot: sky-blue glass, white rounded cards, navy in a rounded sans — the only world with daylight; a plumbob turns over every Sim in its state's colour; always on, the needs — Energy the cpu idle, Hunger the memory free, Comfort the pressure headroom, Bladder the disk free, Social the share at work, Fun the share finished — green, yellow or red the way the game does it; collapse the board for the household's mood, its wants (who is waiting on you) and fears (who is stuck), and a word of Simlish when something happens |
| **Star Trek** | LCARS, 2364: black, and on it the library computer's bars — orange, peach, tan, lavender, blue — with the elbow at the top of every lane's rail, projects as pill bars, tiles capped in their state's colour, labels black on the colour; the frame goes to yellow alert while a session waits on you and flashes red alert while one is stuck; the status line along the foot carries the stardate, the condition, warp (cpu), shields (memory free) and life support (pressure headroom); collapse the board for the ship's systems, one bar each |
| **Stardew Valley** | the farm: dark wood frames with a bright inner edge, parchment cards, pixel lettering, gold for the numbers; always on, the clock box — the real day and season, the weather off the board's mood (stormy while anything is stuck, rain while one waits on you), the time, the gold (the turns taken by every session) — and the energy bar beside it, the cpu idle; collapse the board for the field: one crop per session, wilted when stuck, a knock at the door when waiting, a seed mound asleep, growing with the turns while at work, ripe and glowing when done, and a scarecrow |
| **corporate intranet** | the ugly one, on purpose. Apollo was here, and it came out clean, blocky and out of tune, so it was pushed the rest of the way instead of tuned: a light grey page, white boxes with a one-pixel grey border on every one of them, Verdana at eleven pixels, bold black headings on grey bars, session names as navy links that underline when you point at them, the buttons the browser draws when nobody styles them, a dotted focus rectangle, fat grey scrollbars; nothing rounded, nothing shadowed, nothing glowing, nothing moving. The only colour is a spreadsheet's OK, Warning and Error, and a session's state is a bordered cell in that colour; a row that needs you is filled the pale yellow or pale red a form uses. Always on, the status bar along the foot that says Ready (or the worst word on the page and what for), the head count, the cpu, the pressure and when the page last refreshed; collapse the board for the status page, three web parts: System status (one row per figure with a value and OK / Warning / Error), Active sessions (one row per session at work with how long since it last reported; past 2:30 it is Not responding), Recent activity (the last five things that happened, timestamped). Sounds are the PC speaker |

Each theme sets a `--glow` factor that every shadow multiplies, so neutral is
genuinely flat rather than dimmed.

## The HUD

One row, sized in `vh` so the readings keep their share of the screen instead
of being squeezed to hold the session tiles at a fixed size: the brand and
tally, six arc gauges in a 2x3 block, the trace, and the numeric readout. The
gauge dials scale with the strip. Every reading names its window in its label
or its hover text, because a number without one is a guess; hover anything
for what it is and how it is counted.

The board is glanced at from a metre away while something else has your
attention, so the six gauges answer five questions in order and nothing else:

| gauge | what it is |
| --- | --- |
| `live` | sessions working right now (running or blocked on you) over everything on the board |
| `tok/min · 5m` | output tokens the whole fleet is writing per minute, averaged over the last five whole minutes; the arc is against today's busiest minute |
| `5h window` | estimated output tokens in the open five-hour Claude usage window; the arc is how much of the window has elapsed |
| `max context` | the fullest context on the board, as a share of that session's window; amber past 70%, red past 85%, and clicking it opens the session |
| `mem pressure` | macOS memory pressure, the number that predicts a stall (below) |
| `done today` | jobs that reached done since midnight, with the merge requests they opened in the hover |

"Tokens" everywhere on the board means **output** tokens: what the model
wrote, thinking included. That is the number the job file eventually stamps,
so a live session's count lands on the figure the job will report. They are
read off the transcripts as each request lands -- the job file's own count is
written once, when the job ends, which is why the old `tokens` cell sat still
all day. Input is kept too (almost all of it cache reads, tens of millions per
session) and shows in the drawer as `read`, with the cache share in the hover;
it says how big the context is, not how much work was done.

The five-hour window is Anthropic's usage-limit period: it opens on the first
message and closes five hours later, and the next message after that opens
another. The ledger chains that forward from the last gap of five quiet hours
(which guarantees a fresh start), so the open window's start, total and reset
time come from local data alone. It sees only this machine's Claude Code
sessions -- claude.ai chats draw on the same limit and are invisible here --
so it is an estimate, labelled as one. The actual percentage Anthropic holds
against you needs the `/usage` endpoint and the CLI's OAuth token, which this
board does not read.

The trace is output tokens per minute, one bar a minute, with the number of
sessions writing in that minute as a line over it: a burst of bars is a wave
of agents answering, a flat stretch is you reading, and the last bar is always
short because the minute is not over. The dashed rule is where the open
five-hour window began. Click the caption to cycle 15m, 1h and 6h; the choice
is remembered per browser. When more than one agent wrote in the span the
bars stack by provider -- Claude in the accent, Codex in the dim ink -- with
the swatches in the caption; one writer, plain bars.

The readout beside it is the machine and the housekeeping: `load 1m` (the
one-minute load average over the core count -- under the cores is
comfortable, over it processes queue; the CPU and GPU busy shares in the
hover), `agents` (agent processes and their CPU), `swap` (in use; memory,
the agents' share of it and the disk in the hover -- the cell becomes a red
`disk` if the data volume passes 90%, or `power` on the day the machine is
off the cable), `waiting` (the longest anything has been waiting on you and
how many are, amber past five minutes and red past fifteen; clicking it opens
that session), `out today` (output tokens since midnight, with the per-agent
split and the cache share in the hover) and `resets` (when the open window
closes).

### Optional panels

Those three -- the gauges, the tok/min trace, the readout -- are the essential
set: what a MacBook fits at 1440 wide, and nothing added since may squeeze
them. Anything else is an optional panel: off unless switched on under
**metrics** in the settings card (`⌘,`), remembered per browser -- so the
wall's kiosk and a desk browser each keep their own answer -- and, even
then, laid out only when the row has room for it with the essentials still
at least as wide as they are on the MacBook. Resize the window narrower and
it folds away; wider and it comes back. A panel that is on but has no room
says so beside its switch.

The one so far is the **host trace**: cpu busy as a filled area, gpu, memory
used and the agents' resident set as lines (the last against its own
high-water mark), one sample every two seconds over the last quarter hour.
It is the chart the tok/min bars replaced, back for a screen with the room:
a build pegging the cores or a fleet eating the RAM is still quickest to see
as a line. The GPU comes from the accelerator's own counters in `ioreg`,
which needs no privilege; a machine with nothing that answers gets no GPU
line.

The host's other vitals -- cpu, gpu, the agents' resident set, disk, swap,
battery -- are measured every pass and published as `--g-*` custom
properties on the root for the worlds that draw their own instruments
(Skyrim's bars, Minecraft's hearts, the intranet's status bar). Alongside them:
`--g-rate`, `--g-window`, `--g-ctx`, `--n-done-today` and `--n-tok-min`.

### One reading, one place

A world's own instrument is the better place for a reading it draws:
Skyrim's health bar *is* the memory pressure, Doom's ammo the live count,
NERV's power source the battery. So each world declares what its always-on
instrument reads (`plots`, on the world object, in the HUD's own names --
`live`, `pressure`, `cpu`, `mem`, `disk`, `batt`), and the HUD keeps those
off its own dials: a duplicated gauge goes to the first reading in the
reserve that the world does not draw either -- the agents' resident set
(`agents mem`, which nothing else shows), then cpu busy, memory used, disk
used, gpu busy -- so the block still carries six figures and none of them
twice. In the readout, the `power` cell never takes the slot while the
world's instrument has the battery up; the cell stays on swap. The band
(what a collapsed board uncovers) is not counted: it is a summary, up only
while the board is folded.

One theme never reallocates: **console**, the default, is the control --
its six dials and its readout are always exactly what this section says,
so there is one board to read every other against. (`CONTROL_THEME` in
the page, beside the optional panels.)

`mem pressure` is read from `memory_pressure -Q`. It sat here as a thermal
gauge until it turned out that Apple Silicon records no CPU thermal level at
all: `pmset -g therm` answers "no CPU power status has been recorded", the
regex never matched, and the dial reported its fallback constant of 100
forever. Real die temperatures need `powermetrics` as root, which is not a
thing a LaunchAgent should be asking for. Pressure costs nothing, needs no
privilege, moves under load, and measures the resource that actually bites on
a 16GB machine running a fleet -- it counts memory that cannot be reclaimed,
so it tells 76% used and happy apart from 76% used and swapping.

Per session, the tile's foot carries what it has written and its context
fill (`42k · ctx 24%`, coloured like the gauge), and the drawer adds `read`,
`context` (tokens over the window), and `model` with its effort. Antigravity
reports none of this, so its tiles say so with a dash rather than a number.

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

## The graph window

One run's trail, drawn: `graph` in the drawer, `⌘G`, or the `⋯` menu opens
a window on the session, and the picker in its title bar switches to any
other on the board. Time runs left to right along a spine of dots, one per
model response; the files the run read sit in rows above the spine and the
files it changed in rows below, each joined to the steps that touched it by
a curve in the verb's colour (read, changed, run). A file every step keeps
coming back to shows up as a fan, which is the point. Rings on the spine are
where you spoke, and the stretch between two prompts is a phase, washed
faintly every other one so they read as bands before the words do.

The head of the spine carries the pulse. Three dots breathe after the last
step while the model is between tool calls -- thinking, as far as a
transcript can tell -- and the last step beats with its edges marching while
a tool runs; both stop when the session does. The dot in the title bar says
the same thing from across the room.

Nothing in it is summarised. A step's line is what the agent said, or the
one-line description it wrote on a shell command, or the tool and the file's
name; a file is a path a tool call named. Hidden reasoning is mostly not on
disk -- Claude Code writes empty `thinking` blocks unless the session opted
in, Codex encrypts its reasoning and keeps a summary at best -- so where a
thought *is* written it rides along in the side column, and where it is not
the label is what the call was for. Shell commands are read for the files
they name (`sed -n` reads, `sed -i` edits, a `>` writes, `pytest x.py` runs),
with heredoc bodies, patterns, flags, URLs and folders left out. Antigravity
keeps its steps as opaque protobuf, so its tiles say so rather than draw.

It is lazy: the board never reads a transcript in full for this, only the
page asks, with `/api/graph?id=`, and only for the run it is showing. The
first request parses the file; every one after reads the appended bytes.
While the window is open on a running session it asks again every few
seconds and redraws only when the spine has grown, so the graph builds as
the agent works.

Three states, remembered per browser like the player's: a window in the
bottom-right corner (the player owns the left), a strip with the name, the
pulse and what it is doing this second, and the main view over the board,
with the run's outline, the step in hand and every file down the side. Wheel
to zoom along time, drag to pan, double-click or `⊡` to fit, `Esc` back from
the main view, `←`/`→` to walk the pinned step there. Hover a step or a file
to light its edges; click to pin it. The window is drawn with the same
tokens every other surface uses, so each of the twenty-six worlds paints it
in its own colours without a line of its own.

## The terminal sheet

Start with `--terminal` (the installer does) and a real shell opens inside the
page, in a sheet that docks to the bottom. `⌘J` or `ctrl-\`` toggles it. Every
tile's drawer has a "shell here" button; the sheet's `+` opens a picker — any
folder the board knows about, or one typed under `~`, and shell / claude / agy /
codex — and `×` closes the active one. The page sends a session id, or a folder
plus an agent key; the server maps the key through a fixed table, so no command
string ever comes from the browser. `⌘[` and `⌘]` cycle through terminal tabs
in the order they sit on the bar — drag a tab along the bar to reorder them, and
the order is kept per browser. A shell opened from the `+` button is named `~`
or `~/folder`, not the login name. `⌘T` opens a new shell in `~`, and `⌘W`
closes the active tab. Fresh and
resumed Codex terminals run with `--yolo`. Mac editing keys work as in iTerm's
Natural Text Editing preset (⌘←/→, ⌘⌫, ⌥←/→, ⌥⌫, ⌘K), Shift-Enter inserts a
newline, and `⌘C`/`⌘V` copy a selection and paste as in any terminal. The
face is SF Mono at medium weight with loose leading, whatever the browser's
own monospace preference.

`fleet.command` uses a tiny native WebKit shell (`Fleet Dashboard.app`, from
`fleet-browser.swift`, with an icon drawn by `fleet-icon.swift`) so Chrome
cannot consume `⌘T` before the dashboard sees it. The shell is compiled locally
on first use and whenever its source changes; if the macOS command-line tools
are unavailable, the launcher falls back to Chrome and the on-page shortcuts
that Chrome permits. The shell pings `/api/ping` every five seconds; when the
board stays dark it bootstraps the login agent, shows a placeholder, and
reloads once the board answers -- a dead board is never a stale page.

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
