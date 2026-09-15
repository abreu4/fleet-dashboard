# Fleet Dashboard Tasks

## Theme Quality Board

### Done
- [x] Keep the top-right kiosk controls on one stable row (six squares that share the column; state labels can no longer spill out of them; collapse is a square, ⌘E).
- [x] Keep Minecraft's “Also try Skyrim!” splash fully inside the title area.
- [x] Team Fortress (`ochre`): cream scoreboard clamped in RED/BLU paint, plaques, control point and hazard ring above the terminal sheet, a legible terminal bar, and a kill feed for state changes. (The "restrained scoreboard" rebuild is gone.)
- [x] Replace Sonic's clipped loop with a compact live arcade score panel.
- [x] Raise Pokémon card, metadata, and project-header contrast.
- [x] Sounds actually play: the engine only cued on `blocked`/`waiting`/`done`, states no collector emits; a running session going idle now plays the done cue.

- [x] The band (pass 8): collapsing the board uncovers one state-driven object per world — Sonic's rings on Green Hill, Fallout's S.P.E.C.I.A.L., the beacons of Gondor, Portal's turret, Persona's date card — beside the casino wheel that started it.
- [x] Collapsed tiles: the foot drops its path/turns whole instead of truncating to `…/FLE…`; resting on a collapsed tile peeks its line of context.
- [x] Apollo (`houston`): rebuilt — the first cut mirrored the tiles (a plaque per session, stations by index, GET from page load). Now the plotboard places every working session by its silence (LOS at 2:30), the poll is a *systems* poll (one station per real host/fleet figure, each with its own threshold), GET runs from the oldest live session, FLIGHT + GET stay on with the full board. NO GO / STBY / LOS verified through a state-bending proxy.
- [x] Always-on instruments (Skyrim bars, Minecraft HUD, Apollo FLIGHT) get their own strip via `--hud-inset` instead of sitting on the Codex row; Skyrim's aurora moved into the sky.
- [x] Theme menu sorted alphabetically.

### Next — specialized interactive gimmicks
- [x] Casino Royale (`staunton`): a session finishing drops the ball (pass 7); the outside-bet boxes lay six cloths (2026-09-15). Still open: a clickable wheel or a loopable deck of cards.
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
