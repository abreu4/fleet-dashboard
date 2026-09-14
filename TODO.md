# Fleet Dashboard Tasks

## Theme Quality Board

### Done
- [x] Keep the top-right kiosk controls on one stable row (six squares that share the column; state labels can no longer spill out of them; collapse is a square, ⌘E).
- [x] Keep Minecraft's “Also try Skyrim!” splash fully inside the title area.
- [x] Team Fortress (`ochre`): cream scoreboard clamped in RED/BLU paint, plaques, control point and hazard ring above the terminal sheet, a legible terminal bar, and a kill feed for state changes. (The "restrained scoreboard" rebuild is gone.)
- [x] Replace Sonic's clipped loop with a compact live arcade score panel.
- [x] Raise Pokémon card, metadata, and project-header contrast.
- [x] Sounds actually play: the engine only cued on `blocked`/`waiting`/`done`, states no collector emits; a running session going idle now plays the done cue.

### Next — specialized interactive gimmicks
- [ ] Casino Royale (`staunton`): prototype one focused table toy — either a clickable roulette wheel or a keyboard-accessible, endlessly loopable deck of cards.
- [ ] Minecraft (`cobble`): make the inventory slots clickable and tie them to real dashboard actions.
- [ ] Give each game theme one purpose-built interaction; avoid generic ornaments shared between worlds.
- [ ] Add reduced-motion, keyboard, focus, and narrow-window acceptance checks for every interactive gimmick.

### Later — deliberately stupid themes
- [ ] Design two or three knowingly ridiculous mashup themes from unrelated random subjects.
- [ ] Keep mashups opt-in and ship them only after the core theme interactions feel finished.

## Automation & Actions
- [ ] Implement automation actions framework.
- [ ] Minecraft (`cobble`) theme: Make the inventory slots clickable and usable, tied to the automation actions.
