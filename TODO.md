# Fleet Dashboard Tasks

## Open board — ranked (2026-09-22)

Ranked for what the board is for: a glance from a metre away, most of the day
with the terminal maximised. A wrong reading ranks above a missing one; the
daily posture above any one world; a world's bug above its polish. Each entry
says what it does now (checked in the code, not guessed), why, and the fix
direction. Nothing here is started. Python-side items need a board restart
(which kills embedded terminals); page-only items deploy by patching the
runtime copy.

1. [ ] **The 5h window dial is misleading.** It reads e.g. `128k · 5h window`
   with a yellow arc near full. The number is Claude Code output tokens since
   the open usage window began (this Mac only, Claude only — `usage.window()`);
   the arc is *time elapsed* in the five hours, not usage; and the colour is
   always `var(--warn)`. So it reads "near the limit" when it means "near the
   reset". Nothing local knows the real limit (the docstring in `usage.py`
   says as much), so it can only be a clock or go. Direction: retire the dial;
   fold the window into the readout's `resets` cell as a countdown (`resets
   23:58 · 58m`), tokens-in-window in its tooltip; give the freed dial to the
   consolidation in 3. Page-only (`drawHud` specs, `ui.html`).

2. [ ] **Terminal rides over a fixed bottom bar.** With the sheet maximised
   (88vh) it covers Skyrim's bars, NERV's status bar, the Minecraft HUD and
   the casino wheel, and the band never shows while the sheet is on
   (`.band` is `:not(:has(.sheet.on))`). Why: `.sheet` is `fixed; bottom:0`
   at z 8; `.ghud` sits at z 2; only some instruments ride `--taken`, and
   those float up over the tiles instead. Direction: one fixed bottom bar,
   `--hud-inset` tall, that owns every always-on instrument (the `.ghud`s,
   the band's object, the wheel); the sheet's `bottom` becomes the top of
   that bar and its steps become `calc(100vh - hud-inset - hud)` at most;
   `--taken` no longer moves the instruments, only the board. Every world's
   fixed-bottom ornament (`bottom:calc(Npx + var(--taken))`, ~20 rules)
   needs re-homing or removing from the `--taken` ride. Acceptance: at each
   sheet step, in every world with an inset, the instrument is whole and the
   sheet's last row is visible; with no inset the bar is 0 tall. Page-only,
   but the biggest item on the board.

3. [ ] **The two sides of the graph read as one instrument.** Left, six dials
   whose arcs measure six different things against six denominators (share
   of the fleet, vs today's peak minute, time elapsed, % of a ceiling, OS
   pressure, done÷(done+active)); right, six cells that repeat some of the
   same readings (`out today` beside tok/min, `resets` beside the window)
   and carry a dead one: `waiting` is "longest a session has waited on you",
   and no collector emits `blocked`/`waiting`, so it always prints `—` (the
   same reason the tally never shows those chips). Direction: one rule for
   each side — a dial is a fill against a hard ceiling that means something
   is about to go wrong (context, pressure, maybe agents' memory); a cell is
   a count with its window named (out today, tok/min, done, resets, load,
   agents) — no reading twice, nothing that cannot move. Drop `waiting`
   until a collector can emit it (or make it "oldest idle session", which is
   what "waiting on you" is in practice). Subsumes where 4 and 5 land.
   Page-only.

4. [ ] **`max context` — say which session.** It is the fullest context on
   the board (`d.context`: name, used, max); the name is only in the hover
   tooltip and the tile is a click-to-open. Direction: print the session's
   name (aliased) under the percentage, and mark that tile on the board.
   Page-only; small.

5. [ ] **`done today` is always 0.** Not the timezone: the live board's
   midnight is 00:00 WEST (`local_midnight_ms` uses `time.localtime`). The
   count is `~/.claude/jobs/*/state.json` in state `done` since midnight
   (the last one was 2026-09-20) plus roster sessions in state `done`, and
   only jobs ever get that state — an interactive session goes running →
   idle and never counts. The arc, done÷(done+active), is a made-up ratio.
   Direction: define done for interactive work — turns finished today
   (running→idle transitions, which the collectors already see) or sessions
   that wrote today and are now idle — or retire the dial into a cell in 3.
   Python side (`usage.finished`, `dashboard.py`), so a restart.

6. [x] **A totals panel: everything the fleet has spent, and its records.**
   Nothing on the board can answer this. `usage.Ledger` keeps one-minute
   buckets for `HORIZON_MINUTES` (30 hours) and prunes past that, and
   `_discover` only tracks transcripts touched inside the same horizon -- so
   `today` is the longest window the board can report, and no reading survives
   the day it was taken. Worse, the raw material is going away: no
   `cleanupPeriodDays` in `~/.claude/settings.json`, so Claude Code's 30-day
   default applies and the transcripts on disk now reach back only to
   2026-08-12. Every day that passes, the oldest day's evidence is deleted.
   Whatever is going to remember the fleet's history has to start writing it
   down before the transcripts do.

   Wanted: a toggleable panel -- overall token expenditure, the biggest day by
   tokens, the biggest day spun by sessions, and more (proposals below, to
   pick from before anything is built).

   **Where the numbers come from.** A day-rollup file, `~/.config/fleet/`
   (`music.py`'s convention), one row per local day: out, fresh in, cache
   read, cache write, requests, distinct sessions, split by provider, the
   day's peak minute. Written two ways: a backfill that walks every transcript
   still on disk, and the live ledger folding today's row in as it goes. A day
   once closed is never recomputed -- its transcripts will not be there. The
   backfill is cheap enough to simply re-run at every start, which also
   self-heals a deleted file: measured at **2.4 s for 0.92 GB across 247
   transcripts**, the same byte-needle prefilter `_tail` already uses. Codex
   folds in the same way through `_codex_row`'s deltas. Antigravity writes no
   usage anywhere, so `agy` cannot be counted -- the panel should say so
   rather than quietly under-report.

   **Found while measuring, worth its own fix.** `_discover` scans one level
   under each project dir, so the 96 subagent transcripts at
   `<project>/<session>/subagents/*.jsonl` are counted by nothing -- 0.28M
   output all-time (~1%, but 0.11M of one day on 2026-09-05). The rollup walk
   must include them, and widening `_discover` fixes today's tok/min, out
   today and the 5h window at the same time.

   **Both definitions are settled** (2026-09-23).

   *A session counts on the day it was started*, not the days it wrote --
   the first timestamped row of its transcript. This is not what
   `today.sessions` counts now (distinct files with a bucket, so a session
   running past midnight counts on both days), so the rollup keeps its own
   per-day start count beside the write count the ledger already has. Cheap:
   the backfill reads each file's first row, and the live fold only needs it
   once per new path. Two consequences to carry: a *resumed* transcript keeps
   its original first row, so it counts on the day it was first opened even
   if all its work happened weeks later -- which is the honest reading of
   "spun up", and why starts span 49 days where tokens span 37; and subagent
   transcripts are not sessions, so they are excluded from this count while
   their tokens still count.

   *Cache reads stay out of the panel.* Not a second line, not a tooltip --
   6.9 billion against 29.4M of output, it would be the biggest number shown
   and the least meaningful. Output is the panel's word for tokens. Cache
   writes and fresh input are worth keeping in the rollup rows (they cost
   nothing to store and say what the context was doing) but they are not
   drawn unless a later reading needs them.

   **What it would print today** (measured 2026-09-22/23, so the discussion
   has real numbers): 37 days of tokens on record, 49 of session starts;
   29.4M output tokens, of which Codex 1.4M; 32,056 requests; 287 sessions
   started; biggest day by tokens 2026-09-10 at 2.8M; most sessions started
   2026-09-18 at 23.

   **Proposed readings, to discuss** -- each with what it would be read from,
   so it can be costed:
   - *Records.* Busiest minute ever, with when (the ledger already finds
     today's). Longest day, first write to last. Longest unbroken run of days
     worked; days worked over days elapsed.
   - *Rhythm.* A calendar heat map of output per day. An hour-of-day profile
     (24 buckets per day row, near-free). A weekday profile.
   - *Where it went.* Top projects all-time -- the project dir is in the
     transcript path and `aliases.py` already maps it to a display name.
     Share by agent; share by model (`modelId` rides the attachment row).
   - *What came out.* Jobs finished and merge requests opened all-time, from
     `~/.claude/jobs/*/state.json` -- what `usage.finished` reads for today,
     34 job dirs now -- carrying item 5's caveat that only jobs reach `done`.
   - *The long record.* `~/.claude/history.jsonl` holds every prompt typed
     back to **2025-10-24**: 2,714 prompts over 118 days in 103 projects. No
     tokens, no session id, but it is the only thing on this Mac that
     remembers last year, and it is the honest source for "days worked" and
     "prompts typed" over a span the transcripts cannot reach.
   - *Notional cost.* What the output would have cost at API list prices, by
     model. A subscription makes it a number that was never paid -- label it
     that way or leave it out.

   **The panel.** A third overlay beside settings (Cmd-,) and the graph
   (Cmd-G): an entry in the `#more` menu next to `settings...` and `graph`,
   its own shortcut, built on the `.settings` scrim-and-card so all 26 worlds
   theme it for free. Not on the HUD -- item 3's rule is one reading in one
   place, and this is the retrospective view; the HUD stays the live one. It
   has to read correctly before the first backfill lands, and on a Mac with no
   history at all. Ranked below 1-5 because nothing reads *wrong* without it.
   Python side (a rollup module, an endpoint) so a restart, plus page-only
   work for the panel itself.

   **Done (2026-09-24).** `totals.py` keeps the day-rollup in
   `~/.config/fleet/totals.json` (`FLEET_TOTALS` moves it): a walker that
   subclasses `usage.Ledger` -- same needles, same row readers, only `_credit`
   replaced -- reads every transcript on disk (Claude, its subagents, Codex
   under any date) on its own thread 3 s after start (5.7 s in-server for
   1.3 GB), then folds appended bytes once a minute. A day seals an hour after
   its midnight and a sealed row is never recomputed; the write is atomic and
   sealed rows come from the transcripts alone, so two boards write the same
   past; bumping `VERSION` discards them. Rows carry out, fresh in, cache
   read/write, requests, per-provider, starts (subagents excluded), sessions
   that wrote, output by model and by project, 24 hour buckets, the peak
   minute, first and last write. `/api/totals`; the panel is `Σ totals` in the
   `⋯` menu and `⌘I`, on the `.settings` card: spent with the agent split
   (Antigravity "not countable"), six records, a calendar heat map, top
   projects and models. It reads "reading the transcripts…" before the first
   walk, "nothing on record yet" on an empty Mac, and "needs a board restart"
   against a server without the route. `_discover` now reads
   `<session>/subagents/*.jsonl`, and `today.sessions` leaves them out.
   Printed today: 32.6M output (Claude Code 31.2M, Codex 1.4M), 42k requests,
   301 sessions started, biggest day 2026-09-10 at 3.0M, most started
   2026-09-18 at 23, busiest minute 88k (5 Sep 18:48), longest run 32 days,
   56 days worked of 128. Days with tokens read 56, not 37: Codex rollouts
   reach back to 2026-05-20. Needs a board restart. Still open: notional
   cost, the `history.jsonl` long record, jobs and MRs all-time, the
   hour-of-day and weekday profiles and the longest day (their data is
   already in the rows).

7. [x] **The Sims (`plumbob`): the six needs do not measure what they say.**
   `WORLDS.plumbob.NEEDS` inverts a host gauge or a session ratio into each
   bar, green over 50, yellow over 25, red under. Read off the live board
   (2026-09-22, five sessions, a healthy Mac): Energy 47 yellow, Hunger 26
   yellow, Comfort 47 yellow, Bladder 45 yellow, Social 60 green, Fun 0 red.
   Five of six amber or worse with nothing wrong -- the cuts sit inside the
   band these readings naturally live in, so the household is permanently in
   crisis.

   A motive in the game is a resource that drains while the Sim works, refills
   when you do something about it, and turns red to ask for that something.
   Judged that way:
   - *Energy = cpu idle* (`100 - --g-cpu`). Noisy at the two-second sample,
     no memory of the day, and nothing you could do if it went red. The
     laptop's battery is the right shape: it drains all day, refills when you
     plug in, and a red bar has an action. `--g-batt` is already published
     (`metrics.power()` -> `pmset -g batt`: pct, source, charging). Decide what
     it does while docked -- right now the Mac reads `100% AC, not charging`,
     so the bar would pin full, which is honest (the machine is rested, the
     Sim is asleep in bed) but never moves. Pin it with a plugged-in tell, or
     read time-on-battery instead. Note `--g-batt` falls back to 100 when the
     pct is null, so a Mac that reports no battery also pins full.
   - *Hunger = memory free* and *Comfort = pressure headroom* are the same
     reading one derivative apart -- `--g-mem` is memory used, `--g-pres` is
     the memory that cannot be reclaimed. Two of six bars move together, which
     is item 3's "no reading twice" inside a single panel.
   - *Bladder = disk free* is frozen: 45% today, 45% next week. The joke is
     better than the reading -- the board's own word for clearing stale
     sessions is **flush**. A Bladder that fills as finished and quiet
     sessions pile up and empties when the flush button is pressed is both
     accurate and the better joke.
   - *Social = share of sessions at work* measures busyness, not contact.
     Nearer: how long since you last typed to anything, or the share of
     sessions that have spoken to you recently.
   - *Fun = done / total* is dead. `--n-done` is the tally's `done`, and only
     jobs ever reach that state (item 5) -- the live tally is `{idle: 2,
     running: 3}`, so Fun has been 0 and red since the world shipped.

   Latent, and not only here: `whole(v)` is `round(clamp(v || 0))`, so a
   reading that is missing publishes as 0, and five of these bars invert it --
   an absent gauge (`pressure()` returns None when its regex misses) would
   print as a full green bar. Missing should read missing, not perfect.

   Direction: settle the panel's rule before re-pointing any one bar, the way
   item 3 settles the HUD's two sides. Proposed: a motive is a resource that
   visibly moves over a working day, is not a second view of another bar, goes
   red only when there is something to do about it, and reads blank rather
   than full when its source is missing. Then re-point each bar to the nearest
   reading that satisfies it and re-cut the thresholds so a healthy machine
   reads green. Every re-point also edits `plots: ['cpu', 'mem', 'pressure',
   'disk', 'live']`, which is what hands those dials to HUD reserves -- Energy
   on the battery drops `cpu` and adds `batt`, giving the cpu dial back and
   taking the battery one away. Change them together or the HUD reallocates
   against a world that no longer draws what it claims.

   Scoped to these six. The same host readings are inverted into other worlds'
   instruments -- LCARS (`warp`, `shields`, `life support`, `deflector`,
   `crew`), Doom (health the memory, armor the pressure), Skyrim's three bars,
   Minecraft's hearts, Evangelion's A.T. field -- and the rule settled here
   should sweep them after, as its own item. The Sims panel is where it gets
   written because it is the one with six bars side by side. Page-only
   (`WORLDS.plumbob`, its `plots` and the theme's doc comment, `ui.html`).
   Done (2026-09-24): the rule is in `WORLDS.plumbob`'s doc comment and each
   need cuts on its own figure at the HUD's thresholds -- Energy the battery
   (green on the cable, beside `plugged in`/`charging`), Hunger the memory
   pressure, Comfort the room in the fullest context, Bladder the done and
   20m-quiet sessions a flush would clear, Social the oldest ask waiting on
   you, Fun the running sessions (a quarter bar each, yellow when none);
   read off the snapshot, so a missing source is a hatched empty bar and
   never a full one. `plots` is `batt, pressure, context, live`. On the live
   board: five green, Social red for a session blocked 67m.

8. [ ] **Casino (`staunton`): a folded card flips back when the pointer is
   near its corner.** The face-down rule is on the card itself
   (`.bubble:is([data-state=idle],[data-state=unknown]):not(:hover):not(.sel)
   {rotate:y 180deg}`, `.45s` transition, under `perspective` on
   `.bubbles`), and `:hover` lifts it too. Mid-turn the card's projected
   footprint narrows, a pointer near an edge or corner falls outside it,
   `:hover` drops, the card turns back, the pointer is inside again — it
   oscillates. Direction: hit-test on a box that does not turn (a wrapper
   around the card, or `pointerenter`/`pointerleave` on the stable cell
   setting a class), never `:hover` on the rotating element. Must hold with
   the cursor on the very corner. Page-only.

9. [ ] **Casino: face-down when folded is a setting.** Today idle/unknown
   cards are dealt face down whenever the board is not compact. Add a toggle
   in the settings card beside the cloth picker (`fleet.*` localStorage, per
   browser): cards face up in every state. Default stays face down unless
   decided otherwise. Page-only; small.

10. [ ] **Casino: the wheel centred and 20% bigger.** It is `.wrap::before`,
   fixed at `left:-50px; bottom:-60px`, 320px, cropped by the corner on
   purpose. Wanted: centred, 384px. Note it sits under the cards at z 2
   with `mix-blend-mode:screen`, so centred it crosses the middle lanes; the
   ball (`.ball`) and the winning-number plaque are placed for the corner
   and move with it; and it belongs in the bottom bar of 2, since the sheet
   covers it now. Page-only.

11. [ ] **Skyrim (`hoarstone`): the compass does nothing.** It is a static
   strip of cardinal letters under the HUD (`.hud::after`, centred, clipped
   at the edges, gold needle at 50% — so it always reads S) and a diamond
   per working tile at that tile's x, with no relation to the letters;
   blocked/waiting diamonds never appear (see 3). Fix or replace, decide
   first: (a) a real compass — the strip scrolls so the selected or most
   recent session's tile is the heading and the letters mean something, the
   diamonds keep their bearing; or (b) keep the strip as decoration and give
   the world a different staple — the quest banner ("quest completed" when a
   session finishes, "new objective" when one asks) or the XP bar for the
   day's done. Page-only.

12. [ ] **Folder cards: a (+) that opens a new session of that agent in
   that folder.** Today a new session goes through the sheet's + picker
   (`newTermPicker`): choose a folder, choose an agent, open. The project
   card's header (`boardMarkup`: caret, name, count) has no launcher, though
   it already knows both answers — the lane is the agent, the card is the
   folder. The plumbing exists: `openFresh(cwd, agent)` → `/api/term/open`
   with `{cwd, agent}` → `TERMINAL.open_at` → `actions.fresh_script`, and the
   lane keys (`claude`, `antigravity`, `codex`) are already keys of
   `actions.FRESH`, so the page still never names a command. One catch: a
   card groups by `session.project` (a display name), not by a path, so its
   sessions can sit in different cwds (subfolders, worktrees). Direction: a
   (+) in the header, after the count, that calls `openFresh(cwd, lane.key)`
   with the cwd its sessions share — or their most recent session's cwd when
   they differ (say which in the tooltip); stop the click reaching the
   header's minimise toggle; the terminal-off toast covers boards started
   without `--terminal`. Page-only; small.

13. [ ] **Terminal: two states, fullscreen and normal; normal is resized by
   dragging its top edge.** Today the sheet has three fixed heights —
   `SHEET_STEPS = [34, 54, 88]` vh — cycled by `#term-size`, stored as an
   index in `fleet.sheet`, applied by `applySheet()` to `--sheet` and
   `--taken`. Wanted: (a) *normal* — today's docked sheet, but its height set
   by dragging the top edge, at will, like the sidebar's width already is
   (`#term-grip`, `barWidth`, `--barw`, pointer capture, kept per browser);
   (b) *fullscreen* — the sheet takes the whole viewport. `#term-size`
   becomes the toggle between the two. Direction: a horizontal grip on the
   sheet's top edge (`cursor:row-resize`, `touch-action:none`) that writes
   `--sheet` in px during the drag and refits once on release (`fit()` /
   `refit()`, so the pty is not resized on every pointer move); clamp
   between a few terminal rows and the viewport minus the header; store the
   height (px or vh) in place of the step index, migrating an old index to
   its vh. `--taken` follows `--sheet` in normal and is ignored in
   fullscreen (the board is covered anyway). Interacts with 2: the bottom
   bar's inset is the drag's floor. `termSize()` sizes a pty off
   `SHEET_STEPS[sheetStep]` before it exists and must read the new height.
   Page-only.

14. [x] **Power readings do not follow the cable.** Reported: NERV's power
   readout still says `internal` after the Mac is unplugged — it should
   change the moment the source does, and so should every other instrument
   that reads the battery. Checked 2026-09-23: `metrics.power()` shells
   `pmset -g batt` on every `/api/state` (uncached), the source is read
   right, and NERV's `paintHud` reruns on every poll (`fleet:paint` from
   `afterPaint`, `fleet:hud` from `drawHud`); the runtime copy matches HEAD.
   One bug is certain: `charging = "charging" in raw` matches
   `discharging`, so on battery every reader says *charging* — NERV's
   `<small>` and tooltip, the readout's power cell (`chg`), its tooltip.
   Live at the check: `pmset` said `discharging`, the board said
   `charging: True`. The stuck `internal` did not reproduce from code
   alone: reproduce on the live board (plug and unplug, watch
   `/api/state`'s `host.power` and the readout side by side) before
   deciding whether it is the page, the poll, or the wording (`internal`
   *is* the battery label; `external` is the cable). Then sweep every
   battery reader to use one parsed `{source, charging, pct}`: NERV's
   `power`, the readout's `onBat` cell, the intranet status page's
   `Memory pressure`/`Battery` swap, `--g-batt` (the `batt` plots: Game Boy
   HP, the Sims' needs in 7), and the settings-card hint. Fix direction for
   the parser: match `; charging;` / `discharging` / `charged` / `AC
   attached; not charging` as the states `pmset` prints. Python + page; the
   parser fix needs a board restart.
   Done (2026-09-24): no stuck reading -- `pmset -g log` has the Mac on its
   battery 17:51-18:03 on 09-23 and the report came at 17:59, so `internal ·
   100%` was right; what said otherwise was the line under it, `charging`
   (the `discharging` match), at a full charge that had not moved yet. Now
   `metrics.parse_pmset_batt` is the one reading (`plugged`, `state`,
   `remaining`, 12 tests) and the page's `powerOf` feeds NERV, the readout,
   the intranet row and `--g-batt`, and also corrects an older board's
   `charging` and its `?` source (a failed pmset used to read as `internal`).

15. [ ] **Sweep item 7's rule across the other worlds' instruments.** The Sims'
   needs now follow a rule (`WORLDS.plumbob`'s doc comment): an instrument
   moves over a working day, is not a second view of another bar, goes red
   only when there is something to do, and reads blank rather than full when
   its source is missing. The same host readings are still inverted into
   LCARS (`warp`, `shields`, `life support`, `deflector`, `crew`), Doom
   (health the memory, armor the pressure), Skyrim's three bars,
   Minecraft's hearts, Evangelion's A.T. field and the Pip-Boy's
   S.P.E.C.I.A.L., mostly through `rootNum('--g-*')` -- and `whole(v)` in
   `drawHud` is `round(clamp(v || 0))`, so a missing reading publishes 0 and
   an inverted one draws full. Two ways out, pick one first: publish nothing
   (removeProperty) for a missing reading and let each world's `var(--g-x,
   fallback)` and `rootNum` say what blank looks like, or have the JS worlds
   read the snapshot the way the Sims now do. Then re-point each instrument,
   re-cut so a healthy machine reads well, and edit `plots` in the same
   change. `--g-batt` keeps its fallback of 100 on purpose until then (the
   Game Boy's HP and the Pip-Boy's Endurance read it). Page-only.

## Theme Quality Board

### Done
- [x] Keep the top-right kiosk controls on one stable row (six squares that share the column; state labels can no longer spill out of them; collapse is a square, ⌘E).
- [x] Keep Minecraft's “Also try Skyrim!” splash fully inside the title area.
- [x] Team Fortress (`ochre`): cream scoreboard clamped in RED/BLU paint, plaques, control point and hazard ring above the terminal sheet, a legible terminal bar, and a kill feed for state changes. (The "restrained scoreboard" rebuild is gone.)
- [x] Replace Sonic's clipped loop with a compact live arcade score panel.
- [x] Raise Pokémon card, metadata, and project-header contrast.
- [x] Sounds actually play: the engine only cued on `blocked`/`waiting`/`done`, states no collector emits; a running session going idle now plays the done cue.
- [x] Sounds, checked four ways (2026-09-15, measured in headless Chrome through an analyser on the master bus): an output ceiling stops the louder volume steps clipping the DAC (the alert peaked at 1.44 at volume 1, 1.04 at .85 — the crackle); a cue fired before the render clock moves (the first tens of ms after the context is created or resumed) now waits for it instead of coming out silent or clipped; the voice budget is kept by scheduled end time so a context that sleeps mid-cue cannot exhaust it; a watchdog re-asks a suspended context every 4 s and on focus; the sound button's first click after a reload mutes instead of playing. Still true and not a bug: a Codex or agy session reads `running` for 120 s after its last write, so its done cue lands two minutes late; a Claude cue lags the roster's 6 s clock.
- [x] Click cues on by default (2026-09-15): the kiosk's own localStorage had sound on and the pack pinned, but `fleet.sound.clicks` never set — so every tile and control clicked in silence by design, and the board read as broken. Measured through the real delegated handler: no cue at all before, `tile: played` after. The `neutral` (pinned) and `console` taps were click + sub-thump only, which a MacBook Air speaker cannot reproduce (their energy above 300 Hz sat ~20 dB under the alert tone); each now carries a short mid tone (+8–9 dB in that band).
- [x] The collapse square is drawn, not ⊟/⊞: a burst (blow the board open) when collapsed, a clam (fold it shut) when open.
- [x] Casino Royale's racetrack is a stadium with a fixed end radius (46px), printed on the cloth beside the rail, instead of an ellipse sized in percent of the lane — every agent's lane now prints the same oval; only the straights run with the width.

- [x] The band (pass 8): collapsing the board uncovers one state-driven object per world — Sonic's rings on Green Hill, Fallout's S.P.E.C.I.A.L., the beacons of Gondor, Portal's turret, Persona's date card — beside the casino wheel that started it.
- [x] Collapsed tiles: the foot drops its path/turns whole instead of truncating to `…/FLE…`; resting on a collapsed tile peeks its line of context.
- [x] Apollo (`houston`): personality pass — the poll is a ritual (FLIGHT calls, lamps answer in turn, verdict), loop lines in call-sign form, PAO narration after two quiet minutes, a flight plan (Apollo 11 ÷ 20) the poll is always *for*, and a Quindar-tone sound pack (the theme had none).
- [x] Apollo (`houston`): rebuilt — the first cut mirrored the tiles (a plaque per session, stations by index, GET from page load). Now the plotboard places every working session by its silence (LOS at 2:30), the poll is a *systems* poll (one station per real host/fleet figure, each with its own threshold), GET runs from the oldest live session, FLIGHT + GET stay on with the full board. NO GO / STBY / LOS verified through a state-bending proxy.
- [x] Casino (`staunton`): the cards are real cards — cream faces printed in one deep ink per suit, index top-left / bottom-right; a folded card shows only its back (wine, gold lattice, the house spade) and peeks on hover; fold / unfold / turn are flips on the `rotate` property so the deal and the riffle still compose.
- [x] Hollow Knight (`chitin`): the lantern's map redrawn — a 640px tile that runs on across its own seams, a dozen hatched rooms, tunnels, dead ends, dashed paths, Cornifer's pins and compass — in place of the scribble.
- [x] Music: tracks the embed refuses (100/101/150) go on a per-browser dead list for a month and leave the crate; a scout player cues the rest of the crate ahead of the needle and drops the dead ones before they are reached; the search API returns the same query's videos as a reserve the crate tops up from; the screen shows the sleeve, not the video. Python side (`music.py`, `dashboard.py`) needs a board restart.
- [x] One reading, one place (2026-09-21): a world whose always-on instrument draws a HUD reading (Skyrim's health bar is the pressure, Doom's ammo the live count, NERV's power the battery) declares it in `plots`, and the HUD gives that dial to a reserve reading the world does not draw (`agents mem` first, then cpu busy, memory used, disk, gpu); the readout's `power` cell stays on swap while the instrument has the battery. `console` is the control theme and never reallocates. Evangelion's power source reads the battery's charge (`internal · 64%`) instead of a five-minute countdown scaled by it, and the flash has a switch in settings.
- [x] Apollo retired into **corporate intranet** (`intranet`, the ugly theme on purpose): the room came out clean, blocky and out of tune, so it was pushed the rest of the way -- grey page, bordered white boxes, Verdana, navy links, default buttons, a status bar that says Ready, a status page of three web parts (System status / Active sessions / Recent activity) on the same readings the poll had, the PC speaker for a sound pack. `?theme=houston` and a remembered `houston` map to it.
- [x] Always-on instruments (Skyrim bars, Minecraft HUD, Apollo FLIGHT) get their own strip via `--hud-inset` instead of sitting on the Codex row; Skyrim's aurora moved into the sky.
- [x] Theme menu sorted alphabetically.
- [x] Swept every theme headless (2026-09-15: 26 themes × expanded / drawer / settings / menu / collapsed / in-page switch, plus empty board and reduced motion, against a state-bending proxy with all five states): no exceptions, console errors or failed requests. What it measured and fixed: the readout's `100% AC` ellipsized to `100% …` in nearly every theme at 1440 wide, and long state words (`mission complete`, `aspiration met`, `rip and tear`) read as `MISSION …` on the tally — HUD text now sheds its tracking, then shrinks to a floor, and a chip whose word still does not fit takes the tally's row when there is room; five or more states sit closer so three rows clear the HUD; the brand column is `safe center` so an overflowing tally clips its last row rather than the wordmark; Team Fortress's clock plaque and column gap tightened so its three plaque rows fit at 900px; an inline favicon so a browser tab stops 404ing.

### Next — specialized interactive gimmicks
- [x] Casino Royale (`staunton`): a session finishing drops the ball (pass 7); the outside-bet boxes lay six cloths (2026-09-15). The cloths are velvet now — six layers each (weave, nap, streaked pile highlights, lamp sheen, vignette) inside a stitched leather rail with the racetrack printed on the felt — and the table gained its motifs: suit pips on every card by state, dice for project counts, a chip on each rail, the dealer button on the card in hand, fret-ring gauge tracks, PLACE YOUR BETS on an empty lane, suit wallpaper on the panel, and a cloth picker in the settings card for a board with no closed rail (2026-09-15). Still open: a clickable wheel or a loopable deck of cards.
- [ ] Bare bands left: earth, cyber, neutral, paper (base themes — keep calm), cyberpunk (`signal`), hollow knight (`chitin`), skyrim (`hoarstone`), pokémon (`cardstock`), team fortress (`ochre`).
- [ ] Minecraft (`cobble`): make the inventory slots clickable and tie them to real dashboard actions.
- [x] Six more worlds (2026-09-15), each with a tell, an always-on instrument on real figures, a band and a sound pack: Severance (`lumon`), Evangelion (`nerv`), Doom (`e1m1`), The Sims (`plumbob`), Star Trek LCARS (`lcars`), Stardew Valley (`stardew`).
- [x] Lord of the Rings (`vellum`): the beacons' pyres were clipped inside the hill's clip-path (never visible); illuminated initials, rubricated notes, and the One Ring reading the cpu.
- [x] Portal (`aperture`): the companion cube — floats, bounces, goes through the portals with momentum kept, can be picked up and thrown.
- [ ] Give each game theme one purpose-built interaction; avoid generic ornaments shared between worlds.
- [ ] Add reduced-motion, keyboard, focus, and narrow-window acceptance checks for every interactive gimmick.

### Later — deliberately stupid themes
- [ ] Design two or three knowingly ridiculous mashup themes from unrelated random subjects.
- [ ] Keep mashups opt-in and ship them only after the core theme interactions feel finished.

## Automation & Actions
- [ ] Implement automation actions framework.
- [ ] Minecraft (`cobble`) theme: Make the inventory slots clickable and usable, tied to the automation actions.
