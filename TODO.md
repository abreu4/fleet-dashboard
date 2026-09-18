# Fleet Dashboard Tasks

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
