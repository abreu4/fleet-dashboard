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
- [x] Apollo (`houston`): a twentieth world built to the band rule from the start — the indicator lamp is the tell, the GO/NO GO poll is the band (per-session plaques read off `.bubble[data-state]`, GET clock, MASTER ALARM, a loop line for AOS / 1202 / SPLASHDOWN). Untested live: a NO GO lamp, since no session was blocked at build time.

### Next — specialized interactive gimmicks
- [x] Casino Royale (`staunton`): a session finishing drops the ball (pass 7). Still open: a clickable wheel or a loopable deck of cards.
- [ ] Bare bands left: earth, cyber, neutral, paper (base themes — keep calm), cyberpunk (`signal`), hollow knight (`chitin`), skyrim (`hoarstone`), pokémon (`cardstock`), team fortress (`ochre`).
- [ ] Minecraft (`cobble`): make the inventory slots clickable and tie them to real dashboard actions.
- [ ] Give each game theme one purpose-built interaction; avoid generic ornaments shared between worlds.
- [ ] Add reduced-motion, keyboard, focus, and narrow-window acceptance checks for every interactive gimmick.

### Later — deliberately stupid themes
- [ ] Design two or three knowingly ridiculous mashup themes from unrelated random subjects.
- [ ] Keep mashups opt-in and ship them only after the core theme interactions feel finished.

## Automation & Actions
- [ ] Implement automation actions framework.
- [ ] Minecraft (`cobble`) theme: Make the inventory slots clickable and usable, tied to the automation actions.
