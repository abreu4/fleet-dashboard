# Two new world themes for FLEET

Research proposal. Nothing in the project was edited.

Target file (live, confirmed serving :8787): `/Users/tiago/.local/share/fleet-dashboard/ui.html`
— 3,850 lines. Calibrated against the shipping `hoarstone`, `aperture` and `cardstock`
blocks in that file, not the stale 5,393-line copy in `~/Documents/Dev/agent-dashboard`.

**House rule counts, measured in the live file** (occurrences of the theme's attribute
selector, which is roughly 1.3× the rule count):

| theme | sel. count | | theme | sel. count |
|---|---|---|---|---|
| console | 13 | | vellum | 75 |
| earth | 13 | | hoarstone | 97 |
| neutral | 15 | | signal | 61 |
| cyber | 18 | | ochre | 58 |
| miami86 | 22 | | aperture | 56 |
| chequer | 36 | | paper | 41 |
| cardstock | 40 | | | |

So a fully realised world theme is **~15–30 ornament rules**, not hundreds. Both specs
below land at 6 rule groups (≈22 and ≈26 selector occurrences) — deliberately at the
`chequer`/`cardstock` weight rather than the `hoarstone` weight, because the tell in each
case is carried by one structural idea, not by accumulation.

---

## 1. Candidate survey

### Shortlist (8), grounded in each game's actual art direction

| # | world | key | label | what it actually is, materially | the tell it would bring | verdict |
|---|---|---|---|---|---|---|
| 1 | Persona 5 | `offcut` | persona 5 | Two-colour print job: vermilion ink on newsprint black, bone paper doing the cutting. Art Director Masayoshi Sudou **refused gradations and refused sub-colours** — every graphic is filled flat. Letters are salvage: mixed faces, mixed cases, cut-out like a ransom note, pasted along an oblique. | **The snipped corner.** Every tile is a shape cut with scissors; the cut is diagonal and the ink shows along it. No other theme changes a tile's *silhouette*. | **SPEC'D** |
| 2 | Minecraft | `cobble` | minecraft | 16×16 texel textures; ore and stone as pigment (official map colours: stone `#8B8B8B`, dirt `#A9704F`, grass `#8DB360`); and the canonical shading rule — every base colour rendered at **×135, ×180, ×220 or ×255 ÷ 255**. | **The map-shade ladder + the block face.** The four surface tokens *are* the game's four shading multipliers off one base stone, and every plane gets a 2px lit arris and a 2px undercut. | **SPEC'D** |
| 3 | Cuphead | `nitrate` | cuphead | Inked-on-paper contours, watercolour grounds, three-strip Technicolor saturation, and a deliberate reproduction of period film defects — gate weave, scratches, dust. | Film-gate jitter on the whole sheet plus a heavy ink contour on every box: the board becomes a title card. | Strong, held back. Would be the **fifth** light theme (`paper`, `aperture`, `cardstock`, `ochre` already), and its cream-plus-ink-outline read overlaps `ochre` at a glance. |
| 4 | Hollow Knight | `chitin` | hollow knight | Void as layered deep indigo under dark grey; bone-white line art; Infection as a yellow core bled into orange with a thin white halo. | A bone hairline that traces only the *top* of each plane, like chitin catching light in a dark room. | Good, and the cleanest dark palette on the list — but the indigo ground sits next to `chequer`'s cobalt, and recognisability is narrower than 1–3. |
| 5 | NieR: Automata | `bisque` | nier automata | The most board-shaped UI ever shipped: systematic, sterile, beautiful; warm beige on near-black; hairline boxes; a dot-matrix ground. Yoko Taro's explicit instruction was to **avoid a wide range of colours** and carry meaning with font weight and darkness instead. | Hairline frames and a glitch bar; it *is* an information board already. | **Rejected on its own rule.** A theme whose stated identity is "depend on colour as little as possible" cannot host six mutually distinguishable state colours. Honour it and the states collapse; break it and it stops being the theme. |
| 6 | Metroid Prime | `cermet` | metroid prime | Diegetic visor: cyan glowing line-work and holographic widgets curved onto the inside of a helmet, affected by light, steam and rain; Jon Wofford's Remastered pass is the reference. | Curved bracket frames — every panel bowed by the helmet it's printed on. | Rejected. The tell is *curvature in 3D*, which flat CSS can only fake with border-radius, and cyan-on-black is `console`'s and `signal`'s ground. |
| 7 | Journey | `vermeil` | journey | Sand and cloth, nothing else; HDRI bloom and filmic tone-mapping over a single warm ramp; vermilion robe, gold trim. | Wind ripple raked across the ground plane, and a cloth banner for the rail. | Rejected for the palette, not the beauty: the whole world is one warm ramp, so `blocked`, `waiting` and `done` have nowhere to separate. |
| 8 | Hades | `meander` | hades | Pen-and-ink in the Mignola line, Greek architecture, saturated red light, bold fluorescents over a limited palette (Jen Zee, BAFTA 2021). | The meander (Greek key) border as the rail pattern. | Rejected as a duplicate: gold-on-near-black with a crimson bloom is `vellum` plus `miami86`'s saturation. |

### Explicitly rejected, with the reason

- **Fallout / Pip-Boy** — its designers' own account is that the hardest battle was *keeping the screen monochrome*, because colour was the easy fix for every usability problem. The identity is one phosphor. Six states need hue; adding hue deletes the theme. The phosphor slot is also already held twice, by `console` and `cyber`.
- **Doom (1993)** — the tell is the embossed brown status bar with red LED numerals. Brown-on-brown leaves `blocked` nowhere to sit, and it collides with `earth` and `ochre`.
- **Breath of the Wild** — luminous orange runes etched into blue-grey slate is, almost token for token, `hoarstone`'s contract (cold slate, single warm ember accent). It would ship as a hoarstone variant.
- **Tetris / Among Us / Pac-Man** — identity is a fixed set of saturated screen primaries. Directly against the house line ("nothing here is a screen primary"), and the piece/crewmate/ghost colours would fight the six state colours for the same hues.
- **Monument Valley** — identity is impossible isometric geometry, which does not survive as flat CSS; and a pastel palette cannot hold six states at tile size.
- **Half-Life 2** — same studio, same stencilled-industrial vocabulary as `aperture`, one hazard-orange different.
- **GTA: Vice City** — `miami86` already owns it.
- **Super Mario / Space Invaders / any arcade pixel world** — `cardstock` holds printed pixel, `chequer` holds arcade CRT. Nothing left to say.
- **Dark Souls / Elden Ring / The Witcher 3** — gold on near-black with parchment menus: `vellum` + `hoarstone`.
- **Mass Effect / Destiny** — holographic screen glow, no material anywhere, and `console` already does instrument blue.
- **Disco Elysium** — oil impasto is lovely and reduces, at tile size, to `earth` plus noise; the tell needs raster assets.
- **Ōkami** — sumi-e on rice paper is `paper` plus `vellum` with a brush added.
- **Animal Crossing / Stardew Valley** — more light themes, and their identity is props, not a graphic system.

---

## 2. `offcut` — persona 5

### Art direction

> *OFFCUT — a calling card left on the desk.* Not the game's red as a screen colour: the
> red of a cheap two-colour job, vermilion hit once onto newsprint black, with the white of
> the stock doing all of the cutting. Every plane here was **cut out with scissors** —
> snipped at forty-five degrees, pasted down slightly off-square, the ink showing along the
> edge where the paper has gone. Nothing is graduated, because the art director filled every
> graphic flat and refused sub-colours that would dilute the one ink. The wordmark is
> salvage: one letter lifted from a different face, reversed out of a block of vermilion.
> Textures are screentone and the nap of rough stock, and there is no glow anywhere — a
> printed page does not emit. Zero glow is the whole point: this is the only theme on the
> board where the tile's *shape* is doing the work the other twelve ask light to do.

### Contract block

```css
/* ============================================================================
   OFFCUT — a calling card, cut out and pasted down.
   Two inks and a paper: vermilion, soot, bone. The reds are printing-ink reds,
   warm-black rather than grey-black, because newsprint has no neutral. Zero
   glow: nothing on a printed page emits. The accent and the alarm are the same
   vermilion on purpose — a two-colour job has no second red (see note).
   ========================================================================== */
:root[data-theme="offcut"]{
  color-scheme: dark;
  --void:#0e0b0b; --panel:#171212; --cell:#1c1616; --tile:#241d1c; --tile-hi:#2f2523;
  --edge:#3c2f2c; --edge-hot:#c4281f;
  --ink:#f6f1e6; --dim:#bdb5a8; --faint:#9a9083;
  --accent:#e83a2e;
  --blocked:#e83a2e; --running:#46cc7c; --idle:#6a8cde; --done:#edc93b; --unknown:#938a7c;
  --good:#46cc7c; --warn:#edc93b; --waiting:#f07aa8;
  --glow:0; --sigil:"\2702";                          /* ✂ the scissors that made it */
  --scan:rgba(246,241,230,.020);
  --halo:rgba(232,58,46,.12);
  --grain:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cdefs%3E%3Cfilter id='t'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.88' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Cpattern id='d' width='4' height='4' patternUnits='userSpaceOnUse'%3E%3Ccircle cx='1' cy='1' r='.85' fill='%23f6f1e6'/%3E%3C/pattern%3E%3C/defs%3E%3Crect width='180' height='180' filter='url(%23t)' opacity='.085'/%3E%3Crect width='180' height='180' fill='url(%23d)' opacity='.045'/%3E%3Cg fill='%23e83a2e' fill-opacity='.055'%3E%3Cpath d='M0 22l46-9 4 13-48 7z'/%3E%3Cpath d='M132 104l48-14 5 16-50 11z'/%3E%3Cpath d='M58 156l40 6-2 14-39-8z'/%3E%3C/g%3E%3C/svg%3E");
  --hud-a:#211918; --hud-b:#110c0c; --rail-a:#c4281f; --rail-b:#8c1a14;
}
```

**Note on `--blocked` == `--accent`.** This is a deliberate choice, not an oversight: the
theme has exactly one ink, and in the source material the brand red *is* the danger red.
The usual confusion (a selected tile looking blocked) is removed in ornament rule 4 below,
which overrides `.bubble.sel` to a **bone keyline** — `--accent` never appears as a ring, so
the vermilion only ever means "blocked". If an implementer wants hue separation anyway, the
drop-in alternative is `--blocked:#f2512f` (scarlet); it costs ~0.5 dE of colour-blind
separation against `waiting` and gains +0.5:1 of contrast.

### Measured contrast (sRGB, WCAG 2.x ratios)

`--faint #9a9083` on `--tile #241d1c` = **5.28:1** (requirement was ~4.5; `hoarstone` ships
5.60, `chequer` ships 4.30). On `--cell` 5.69:1, on `--panel` 5.91:1.
`--ink` on `--tile` 14.71:1; `--dim` on `--tile` 8.16:1.

The board's glance layer tints a tile's face with its own state colour (blocked 13 %,
waiting 11 %, running 7 %) and then paints `.bubble .foot` in that same colour, so each state
has to read *as text on its own tinted face*:

| state | hex | face it sits on | contrast | L\* |
|---|---|---|---|---|
| blocked | `#e83a2e` | `#3d211e` | 3.54:1 | 52.3 |
| unknown | `#938a7c` | `#241d1c` | 4.87:1 | 57.9 |
| idle | `#6a8cde` | `#241d1c` | 5.06:1 | 59.1 |
| waiting | `#f07aa8` | `#3a272b` | 5.35:1 | 66.0 |
| running | `#46cc7c` | `#262923` | 7.16:1 | 73.5 |
| done | `#edc93b` | `#241d1c` | 10.27:1 | 81.9 |

Lowest is 3.54:1 on `blocked`, which beats every shipping theme's lowest (`hoarstone` 3.04,
`chequer` 3.33, `cardstock` 4.46). L\* rises monotonically 52 → 58 → 59 → 66 → 74 → 82.

**Colour blindness.** Simulated with a Viénot-style LMS collapse, then CIE76 ΔE across all
15 state pairs:

- deuteranopia — worst pair `waiting`/`done` **ΔE 22.5**
- protanopia — worst pair `waiting`/`unknown` **ΔE 24.7**

For comparison, measured the same way: `hoarstone` worst ΔE **7** (`running`/`unknown` are
effectively the same colour to a deuteranope), `chequer` worst ΔE **3**, `cardstock` worst
ΔE **18**. The thing that buys this is putting `waiting` on **rose `#f07aa8`** rather than
the house's usual warm salmon. Red-green blindness keeps the blue–yellow axis, so six slots
can only be: dark-yellow (red), mid-yellow (green), light-yellow (gold), blue, grey, and one
magenta-ish — which a deuteranope resolves as a light blue, clear of the darker `idle` blue.
`chequer` already ships a violet `--waiting:#c98ae0`, so the precedent is in the file.

### Ornament — six rules, the tell first

```css
/* ===== OFFCUT ornament ===================================================== */
/* 1. THE TELL. Everything on this board was cut out with scissors: one 45°
   snip off the bottom-right of every session tile, with the ink showing along
   the cut where the paper has gone. Nothing is rounded — a pair of scissors
   has never produced a radius. The wedge is drawn on the tile's own background,
   so the clip eats its outer corner and leaves a band along the diagonal. */
:root[data-theme="offcut"] .project,
:root[data-theme="offcut"] .lane,
:root[data-theme="offcut"] .gauge,
:root[data-theme="offcut"] .trace,
:root[data-theme="offcut"] .readout,
:root[data-theme="offcut"] .stat,
:root[data-theme="offcut"] .chip,
:root[data-theme="offcut"] .panel,
:root[data-theme="offcut"] button.ghost,
:root[data-theme="offcut"] .ctl select{border-radius:0}
:root[data-theme="offcut"] .bubble{
  border-radius:0;
  clip-path:polygon(0 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%);
  background-image:linear-gradient(315deg, var(--accent) 0 12.5px, transparent 12.5px);
}
/* blocked floods its own cut instead of glowing: the tile has been stamped */
:root[data-theme="offcut"] .bubble[data-state="blocked"]{
  background-image:linear-gradient(315deg, var(--accent) 0 21px, transparent 21px);
}

/* 2. Headers are oversized strips pasted on an oblique — the type stays
   upright and legible, the strip under it does the leaning. */
:root[data-theme="offcut"] .project > header{
  border-radius:0; border-bottom:2px solid var(--ink);
  color:var(--ink); font-weight:800; letter-spacing:.14em;
  background-image:linear-gradient(101deg,
    var(--accent) 0 24%, #8c1a14 24% 25.2%, transparent 25.2%);
  text-shadow:1px 1px 0 rgba(14,11,11,.55);
}

/* 3. The wordmark is salvage: the opening letter is a different face, reversed
   out of a block of ink, and it sits a shade off the baseline. */
:root[data-theme="offcut"] .brand > div > b{display:inline-block; letter-spacing:.2em}
:root[data-theme="offcut"] .brand > div > b::first-letter{
  font-size:20px; color:#0e0b0b; background:var(--accent);
  padding:0 5px 1px; margin-right:3px;
}
:root[data-theme="offcut"] .brand > div > b::after{
  color:var(--accent); font-size:14px; vertical-align:-1px; margin-left:9px; opacity:1;
}

/* 4. Screentone, never glow. Hover lays a 4px dot field over the stock and
   draws a bone keyline; the tile does not lift, because paper does not float.
   Selection is bone too — the vermilion is spoken for and only means blocked. */
:root[data-theme="offcut"] .bubble:hover{
  transform:none;
  box-shadow:inset 0 0 0 2px var(--ink);
  background-image:
    linear-gradient(315deg, var(--accent) 0 12.5px, transparent 12.5px),
    radial-gradient(circle at 1px 1px, rgba(246,241,230,.11) 1px, transparent 1.3px);
  background-size:auto, 4px 4px;
}
:root[data-theme="offcut"] .bubble.sel{
  border-color:var(--ink);
  box-shadow:inset 0 0 0 2px var(--ink), 0 0 0 2px #0e0b0b;
}

/* 5. The agent rail is the red spine of the page: solid ink, halftoned, with a
   hard charcoal keyline where it meets the work. */
:root[data-theme="offcut"] .rail,
:root[data-theme="offcut"] .hrail{
  color:#f6f1e6;
  background-image:
    radial-gradient(circle at 1.5px 1.5px, rgba(14,11,11,.26) 1.2px, transparent 1.4px),
    linear-gradient(180deg, var(--rail-a), var(--rail-b));
  background-size:5px 5px, auto;
}
:root[data-theme="offcut"] .rail{border-right:2px solid #0e0b0b}
:root[data-theme="offcut"] .hrail{
  background-image:
    radial-gradient(circle at 1.5px 1.5px, rgba(14,11,11,.26) 1.2px, transparent 1.4px),
    linear-gradient(90deg, var(--rail-a), var(--rail-b));
  background-size:5px 5px, auto;
}
:root[data-theme="offcut"] .rail .vlabel,
:root[data-theme="offcut"] .rail .rcount,
:root[data-theme="offcut"] .hrail .who,
:root[data-theme="offcut"] .hrail .note{
  color:#f6f1e6; font-weight:800; text-shadow:1px 1px 0 rgba(14,11,11,.6);
}
:root[data-theme="offcut"] .rail svg{color:#f6f1e6; filter:none}

/* 6. EGG — an empty board says so in the register of a note left behind. */
:root[data-theme="offcut"] .empty,
:root[data-theme="offcut"] .hrail .note{font-size:0}
:root[data-theme="offcut"] .empty::after,
:root[data-theme="offcut"] .hrail .note::after{
  content:"nobody took the bait"; font:11px/1.6 var(--mono); letter-spacing:.09em;
}
:root[data-theme="offcut"] .toast{background:#1b1413; border-color:var(--accent)}
:root[data-theme="offcut"] .scrim{background:rgba(10,7,7,.82)}
:root[data-theme="offcut"] .acts button:hover{
  background:#2f2523; box-shadow:0 0 0 2px var(--ink);
}
```

**Cost.** `clip-path` on a static polygon is composited once per layout; the hover change is
two background layers and a `box-shadow`, both cheap. No animation at all, so nothing to
gate behind `prefers-reduced-motion` — the theme is the board's first genuinely still one,
which is also why it is the most restful thing on the list for all-day use. No `filter`, no
`backdrop-filter`, no per-frame JS.

### Sigil

`--sigil:"\2702"` — **✂**. The theme is named for what is left after a cut; the mark is the
tool that made it. It renders at 13px next to the wordmark, where its silhouette is
unmistakable at a metre, and it is the only sigil on the board that names an *action* rather
than an ornament. Austere alternative if ✂ reads too literally: `\25E2` (◢), the cut corner
itself.

### `THEME_MUSIC`

```js
offcut:    'acid jazz funk hammond organ heist groove instrumental',
```

### `THEME_MARKS` — cut-paper silhouettes

Approach: solid fills, no strokes, no curves. Each mark is a shape someone cut out and
pasted down — so one edge of each is deliberately snipped flat or torn, and all three sit on
the same −8° oblique via a `matrix` transform rather than being drawn skewed. Flat fill,
`currentColor`, so the vermilion accent keeps driving them.

```js
/* persona 5 — cut paper, pasted on an oblique */
offcut:{
  /* eight-point star cut from card, two points snipped flat by the scissors */
  claude:'<path transform="matrix(1,0,-0.141,1,1.13,0)" d="M6.6 1.9L9.4 1.9L9.15 5.23L12.95 3.05L10.77 6.85L14.1 6.6L14.1 9.4L10.77 9.15L12.95 12.95L9.15 10.77L8 15L6.85 10.77L3.05 12.95L5.23 9.15L1 8L5.23 6.85L3.05 3.05L6.85 5.23Z" fill="currentColor"/>',
  /* arrow head above a pasted strip whose bottom edge is torn, not cut */
  antigravity:'<path transform="matrix(1,0,-0.141,1,1.13,0)" d="M8 1.2L14.4 8.2L10.4 8.2L10.4 11L5.6 11L5.6 8.2L1.6 8.2ZM5.6 12.2H10.4L10.4 14.3L9.2 13.4L8 14.7L6.8 13.4L5.6 14.5Z" fill="currentColor" fill-rule="evenodd"/>',
  /* two heavy brackets, each with a hairline paste gap showing through */
  codex:'<path transform="matrix(1,0,-0.141,1,1.13,0)" d="M7.2 1.9L4.9 1.9L1.6 8L4.9 14.1L7.2 14.1L4.3 8ZM8.8 1.9L11.1 1.9L14.4 8L11.1 14.1L8.8 14.1L11.7 8ZM4.55 6.6L6.0 6.6L6.0 7.5L4.55 7.5Z" fill="currentColor" fill-rule="evenodd"/>',
},
```

(The third subpath in `codex` is the paste gap — `fill-rule="evenodd"` punches it out of the
left bracket's arm, so the mark reads as two pieces of paper overlapping rather than one
drawn glyph.)

### Registration

```html
<option value="offcut">persona 5</option>
```

Key `offcut` — the scrap left behind after a cut. Material word, no trademark, same register
as `vellum` / `chequer` / `cardstock`.

---

## 3. `cobble` — minecraft

### Art direction

> *COBBLE — the stone layer, by torchlight.* Not the grass-field screenshot: the wall you
> actually stare at, quarried stone and mortar with ore in it. The surfaces are not a
> gradient — they are **one base stone rendered at the four shades this world has ever
> had**, `×135`, `×180`, `×220`, `×255` over 255, which is the same ladder the game's own
> maps use; the board's `--panel`, `--cell`, `--tile` and `--tile-hi` are literally those
> four values off `#2f3840`, and `--void` is the same stone with no light on it. The state
> colours are ore, not RGB: redstone, emerald, lapis, gold, amethyst, and the dull grey of
> iron in the rock. Nothing curves and nothing is anti-aliased — every plane gets a two-pixel
> lit arris on top and a two-pixel undercut beneath, because that is how a cube is drawn
> here. Text is set twice, once in ink and once one pixel down and right at a quarter value,
> with no blur: that shadow is a glyph, not a glow. The only light source is a torch, and a
> torch does not dim smoothly — light travels this world in whole levels.

### Contract block

```css
/* ============================================================================
   COBBLE — the stone layer, by torchlight.
   Every surface below is one base stone (#2f3840) at the four canonical map
   shades: x135, x180, x220, x255 over 255. --void is the same stone unlit.
   State colours are ore: redstone, amethyst, emerald, lapis, gold, iron.
   Accent is diamond — the one cool light in a room lit by fire.
   ========================================================================== */
:root[data-theme="cobble"]{
  color-scheme: dark;
  --void:#101417; --panel:#191e22; --cell:#21282d; --tile:#293037; --tile-hi:#2f3840;
  --edge:#3e4954; --edge-hot:#62707d;
  --ink:#f1f4f3; --dim:#c3cbd1; --faint:#9ea9b2;
  --accent:#4fcfc9;
  --blocked:#ea5740; --running:#6fcb7a; --idle:#7aa0e0; --done:#f0d164; --unknown:#748699;
  --good:#6fcb7a; --warn:#e0a850; --waiting:#ae74dc;
  --glow:.4; --sigil:"\25A9";                         /* ▩ a block with texture in it */
  --scan:rgba(233,239,243,.014);
  --halo:rgba(255,176,74,.075);
  --grain:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='s'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.55' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3CfeComponentTransfer%3E%3CfeFuncA type='discrete' tableValues='0 .35 .7 1'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23s)' opacity='.11'/%3E%3C/svg%3E");
  --hud-a:#2f3840; --hud-b:#1b2125; --rail-a:#293037; --rail-b:#1b2024;
}
```

The `feComponentTransfer` with `tableValues='0 .35 .7 1'` quantises the speckle into **four**
alpha levels rather than a smooth ramp — the same ladder applied to the grain, so even the
noise in this theme steps instead of fading.

### Measured contrast

`--faint #9ea9b2` on `--tile #293037` = **5.58:1** (`hoarstone` ships 5.60 — parity).
On `--cell` 6.24:1, on `--panel` 7.02:1. `--ink` on `--tile` 12.07:1; `--dim` 8.13:1.
`--accent #4fcfc9` on `--void` 9.79:1, on `--hud-b` 8.60:1.

| state | ore | hex | face it sits on | contrast | L\* |
|---|---|---|---|---|---|
| unknown | iron in rock | `#748699` | `#293037` | 3.57:1 | 55.1 |
| blocked | redstone | `#ea5740` | `#423538` | 3.30:1 | 56.8 |
| waiting | amethyst | `#ae74dc` | `#383749` | 3.50:1 | 58.7 |
| idle | lapis | `#7aa0e0` | `#293037` | 5.05:1 | 65.5 |
| running | emerald | `#6fcb7a` | `#2e3b3c` | 5.81:1 | 74.5 |
| done | gold | `#f0d164` | `#293037` | 8.91:1 | 84.5 |

Lowest is 3.30:1 on `blocked`, ahead of `hoarstone`'s 3.04:1.

**Colour blindness:** deuteranopia worst pair `waiting`/`unknown` **ΔE 15.3**; protanopia
worst pair `running`/`done` **ΔE 19.2**. Comfortably ahead of `hoarstone` (7) and `chequer`
(3), level with `cardstock` (18), but **behind `offcut` (22.5)** — cobble has to spend three
of its six slots inside the warm ore range (redstone, gold, plus iron grey nearby), and
that is the honest cost of a palette dug out of one mine.

### Ornament — six rules

```css
/* ===== COBBLE ornament ===================================================== */
/* 1. One block wall runs behind the whole console, pinned to the viewport, so
   the courses line through HUD, lanes and tiles instead of restarting inside
   every box — mortar line dark, the lit edge beside it. 16px, never 15. */
:root[data-theme="cobble"] .hud,
:root[data-theme="cobble"] .lane,
:root[data-theme="cobble"] .project,
:root[data-theme="cobble"] .project > header,
:root[data-theme="cobble"] .bubble,
:root[data-theme="cobble"] .gauge,
:root[data-theme="cobble"] .trace,
:root[data-theme="cobble"] .readout,
:root[data-theme="cobble"] .chip,
:root[data-theme="cobble"] .stat,
:root[data-theme="cobble"] .panel,
:root[data-theme="cobble"] button.ghost,
:root[data-theme="cobble"] .ctl select{
  border-radius:0;
  background-image:
    repeating-linear-gradient(90deg, rgba(0,0,0,.24) 0 1px, rgba(215,228,238,.045) 1px 2px, transparent 2px 16px),
    repeating-linear-gradient(0deg,  rgba(0,0,0,.24) 0 1px, rgba(215,228,238,.045) 1px 2px, transparent 2px 16px),
    var(--grain);
  background-attachment:fixed;
}

/* 2. THE TELL. The four map shades are not a ramp, they are the faces of a
   block: a 2px lit arris in the x255 shade on top and left, a 2px undercut in
   the x135 shade beneath and right. Hard edges only — a cube in this world has
   never been anti-aliased, and it has never floated either. */
:root[data-theme="cobble"] .project,
:root[data-theme="cobble"] .bubble,
:root[data-theme="cobble"] .gauge,
:root[data-theme="cobble"] .trace,
:root[data-theme="cobble"] .readout,
:root[data-theme="cobble"] .stat,
:root[data-theme="cobble"] .chip{
  box-shadow:inset 2px 2px 0 #2f3840, inset -2px -2px 0 #191e22;
}
:root[data-theme="cobble"] .bubble:hover{
  transform:none;
  box-shadow:inset 2px 2px 0 #3d4853, inset -2px -2px 0 #141a1e, 0 0 0 2px #62707d;
}
:root[data-theme="cobble"] .bubble.sel{
  box-shadow:inset 2px 2px 0 #3d4853, inset -2px -2px 0 #141a1e, 0 0 0 2px var(--accent);
}
:root[data-theme="cobble"] .bubble::before{box-shadow:inset -2px 0 0 #141a1e}

/* 3. Text in this world is drawn twice: once in ink, once one pixel down and
   right at a quarter value. No blur, ever. */
:root[data-theme="cobble"] .brand b,
:root[data-theme="cobble"] .project > header,
:root[data-theme="cobble"] .rail .vlabel,
:root[data-theme="cobble"] .rail .rcount,
:root[data-theme="cobble"] .hrail .who,
:root[data-theme="cobble"] .bubble .nm,
:root[data-theme="cobble"] .bubble .foot,
:root[data-theme="cobble"] .gauge .lab,
:root[data-theme="cobble"] .trace .cap,
:root[data-theme="cobble"] .stat .v{
  text-shadow:1px 1px 0 rgba(8,11,13,.85);
}

/* 4. The only light source is a torch, and a torch does not dim smoothly —
   light travels this world in whole levels. Four steps, a second and a half,
   and nothing moves but the opacity of one fixed layer. */
:root[data-theme="cobble"] .wrap::after{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:3;
  background:
    radial-gradient(540px 340px at 14% -6%, rgba(255,176,74,.13), transparent 68%),
    radial-gradient(420px 300px at 88% 3%,  rgba(255,176,74,.07), transparent 70%),
    radial-gradient(130% 104% at 50% 46%, transparent 40%, rgba(4,7,9,.62) 100%);
  animation:torchlevel 1.5s steps(4, jump-none) infinite alternate;
}
@keyframes torchlevel{from{opacity:.84}to{opacity:1}}
@media (prefers-reduced-motion:reduce){
  :root[data-theme="cobble"] .wrap::after{animation:none; opacity:.93}
}

/* 5. The instrument deck sits above a row of sunken slots, the way a hand of
   tools sits under everything you are looking at. */
:root[data-theme="cobble"] .hud{position:relative; border-bottom:2px solid #141a1e}
:root[data-theme="cobble"] .hud::after{
  content:""; position:absolute; left:0; right:0; bottom:0; height:10px;
  pointer-events:none; opacity:.9;
  background:repeating-linear-gradient(90deg,
    #141a1e 0 2px, #2b333b 2px 20px, #3d4853 20px 21px, #141a1e 21px 24px);
  box-shadow:inset 0 2px 0 #141a1e, inset 0 -1px 0 #3d4853;
}

/* 6. EGG — a vein of ore is buried in the stone at the foot of every agent
   rail, four pixels of diamond where the mortar happens to run out. */
:root[data-theme="cobble"] .rail{
  border-right:2px solid #141a1e;
  background-image:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' shape-rendering='crispEdges'%3E%3Cg fill='%234fcfc9' fill-opacity='.5'%3E%3Crect x='6' y='8' width='4' height='4'/%3E%3Crect x='12' y='4' width='4' height='4'/%3E%3Crect x='10' y='14' width='4' height='4'/%3E%3Crect x='16' y='12' width='4' height='4'/%3E%3C/g%3E%3C/svg%3E"),
    linear-gradient(180deg, var(--rail-a), var(--rail-b));
  background-repeat:no-repeat, repeat;
  background-position:center calc(100% - 10px), 0 0;
}
:root[data-theme="cobble"] .empty,
:root[data-theme="cobble"] .hrail .note{font-size:0}
:root[data-theme="cobble"] .empty::after,
:root[data-theme="cobble"] .hrail .note::after{
  content:"nothing is mining here"; font:11px/1.6 var(--mono); letter-spacing:.07em;
}
:root[data-theme="cobble"] .toast{background:#21282d; border-color:#62707d}
:root[data-theme="cobble"] .scrim{background:rgba(6,9,11,.82)}
```

**Cost.** One fixed-position layer animating `opacity` in four discrete steps — composited,
no repaint of the board, and disabled under `prefers-reduced-motion` (held at .93 so the
torch pool survives without moving). Everything else is `background-image`, `box-shadow` and
`text-shadow`. Nothing per-frame in JS. The 16px wall uses `background-attachment:fixed`,
which is the same technique `hoarstone` and `vellum` already ship.

### Sigil

`--sigil:"\25A9"` — **▩**, a square with a crosshatch fill: a block with texture *in* it,
which is the one-glyph summary of a world whose entire identity is a 16×16 texel face on a
cube. It is also the only sigil on the board that is itself a pixel grid.

### `THEME_MUSIC`

```js
cobble:    'calm ambient piano and soft synth pads cave reverb building music',
```

### `THEME_MARKS` — block geometry on a strict 2px grid

Approach: everything drawn on a 2×2 grid inside the 16×16 box, so the marks read as 8×8
texel sprites, with `shape-rendering="crispEdges"` to defeat anti-aliasing (the same trick
`cardstock` uses, but at block scale and in a tool-and-terrain idiom rather than creature
heads). Silhouettes chosen to stay distinct at rail size: a gem, a rise, a pair of chevrons.

```js
/* minecraft — block geometry, nothing anti-aliased */
cobble:{
  /* a cut gem: a stepped octagon with one facet punched out */
  claude:'<path shape-rendering="crispEdges" fill-rule="evenodd" d="M6 2H10V4H12V6H14V10H12V12H10V14H6V12H4V10H2V6H4V4H6ZM6 6H8V8H6Z" fill="currentColor"/>',
  /* a rising staircase: ascent, and also literally the block that makes it */
  antigravity:'<path shape-rendering="crispEdges" d="M2 10h4V6h4V2h4v12H2z" fill="currentColor"/>',
  /* brackets cut as blocky chevrons, two texels wide */
  codex:'<path shape-rendering="crispEdges" d="M6 2h2v2H6zM4 4h2v2H4zM2 6h2v4H2zM4 10h2v2H4zM6 12h2v2H6zM8 2h2v2H8zM10 4h2v2h-2zM12 6h2v4h-2zM10 10h2v2h-2zM8 12h2v2H8z" fill="currentColor"/>',
}
```

### Registration

```html
<option value="cobble">minecraft</option>
```

Key `cobble` — the material, not the trademark.

---

## 4. Judgement

### Ship `offcut` first

Four reasons, in order of weight.

1. **It adds an idiom the board does not have.** All thirteen existing themes are the same
   rectangle treated differently — textured (`hoarstone`, `vellum`, `cardstock`), bevelled
   (`aperture`), glowing (`signal`, `miami86`, `chequer`), halftoned (`ochre`). `offcut`
   changes the **silhouette of a tile**. From a metre, a board of snipped rectangles is a
   different object, not a recoloured one. That is the largest perceptual return available
   for ~25 rules, and it is the one thing on this list that makes the board look *designed*
   rather than re-skinned.
2. **The numbers are the best on the board.** Worst colour-blind pair ΔE 22.5 (deutan) /
   24.7 (protan) against `hoarstone`'s 7 and `chequer`'s 3; lowest state-word contrast
   3.54:1 against the shipping floor of 3.04:1; `--faint` at 5.28:1. It would raise the
   board's accessibility floor rather than sit on it.
3. **It is the restful one.** Five of thirteen themes are light or bright, and most of the
   dark ones glow (`signal` 1.1, `miami86` 2.0, `chequer` 1.15, `cyber` 1.25). `offcut` is
   `--glow:0` with zero animation — no scan creep, no roll, no flicker. On a screen that is
   fullscreen beside a working monitor all day, *nothing moving* is a feature, and the board
   currently has only `neutral`, `paper` and `vellum` in that category, none of them a
   world.
4. **Recognition per rule is the highest.** Vermilion, soot, a diagonal cut and a reversed
   opening capital, and everybody names it. `cobble` needs the seams, the arrises, the text
   shadow, the torch and the hotbar all present before it stops reading as "a nice grey
   stone theme" — which is the honest weakness of translating a world whose identity is
   genuinely 3D cubes into flat CSS. It also sits closest of anything proposed to
   `hoarstone`, which already owns cold quarried grey.

`cobble` is the more *beloved* world and the weaker board. Ship it second, and if only one
ever lands, it should not be this one.

### Is the board nearing the point where 15 is worse than 13?

**Yes — but the problem is the picker, not the count.** The `<select id="theme">` is a flat
list in two `<optgroup>`s. At 15 the "worlds" group is ten trademarked game names with no
preview, applied only on `change`, and the only way to choose is to try all ten and
remember. That is a menu, not UX candy, and it fails at eight already.

Two small fixes make almost any count fine, and both are cheaper than either theme above:

- **Preview while arrowing.** `setTheme` already runs off the select's event; switching that
  listener from `change` to `input` makes the board live-apply as the user arrows through the
  open dropdown, with the previous key restored on Escape. Roughly three lines. Choosing
  becomes *looking*, and the list length stops mattering.
- **Split "worlds" by ground, not by franchise.** Two groups of five — "worlds · lit" and
  "worlds · dark" — puts the user one decision closer before they read a single name, and
  five-item groups are inside what a person scans without counting.

Recommendation: land the picker change **first**, then `offcut`, then `cobble`. Adding the
fourteenth theme to the current picker makes the picker worse by more than the theme makes
the board better.

### Should one of the existing eight be retired or merged?

Two honest calls.

- **Retire `cyber`, folding its halation into `signal`.** These occupy the same slot — neon
  on near-black — and `cyber` is the one without a tell: 18 selector occurrences, a drifting
  magenta scanline, and nothing structural. Its real contribution is the Cinestill halation
  palette (dye magenta, mercury green, sodium amber), and those are five token values that
  `signal` can absorb without changing its own acid-yellow identity. That frees a slot with
  no loss of anything that reads from a metre, and it fixes a genuine oddity: `signal` is
  labelled "cyberpunk 2077" but its palette is screen-printed hazard yellow on soot, which
  is closer to brutalist signage than to 2077 — it could take the halation reds and become
  the better version of both.
- **`miami86` is the thinnest of the eight worlds** (22 occurrences) and its tell — VHS roll
  plus plate misregistration — is shared with `signal`, which does it better. If a slot must
  be freed and `cyber`'s palette is considered load-bearing, `miami86` is the cheaper loss.
  But `cyber` is the more *redundant* one, and redundancy is what a picker suffers from.

Net: retire `cyber`, land the picker preview, add `offcut` → the list stays at thirteen with
a strictly better lineup and a picker that can actually be used, and `cobble` then has room
to be the fourteenth rather than the straw on the camel.

---

### Appendix — verification method

Contrast ratios are WCAG 2.x relative-luminance ratios computed in sRGB. State-word figures
are measured against the **tinted** tile the board actually paints, reproducing
`color-mix(in oklab, var(--state) N%, var(--tile))` at the live mix percentages
(blocked 13 %, waiting 11 %, running 7 %; `idle`, `done` and `unknown` sit on the untinted
tile), because `.bubble .foot` takes the state colour as text on that face.

Colour-blind separation is a Viénot-style linear-RGB LMS collapse for deuteranopia and
protanopia, then CIE76 ΔE across all 15 state pairs, reporting the worst pair. The shipping
themes were run through the identical pipeline so the comparison is like for like: measured
worst-pair ΔE is `hoarstone` 7, `chequer` 3, `cardstock` 18, against `offcut` 22.5 and
`cobble` 15.3.

### Sources

- [Persona 5's Bombastic Art Direction — Cook and Becker](https://www.cookandbecker.com/en/article/137/persona-5-s-bombastic-art-direction.html)
- [Persona 5 developer interview on UI design — Persona Central](https://personacentral.com/persona-5-panel-concept-development-ui/)
- [How Persona 5's UI balances both style and substance](https://medium.com/design-bootcamp/how-persona-5s-ui-balances-both-style-and-substance-de8cb1b807ef)
- [Visual design analysis of Persona 5 Royal](https://medium.com/game-design-fundamentals/visual-design-of-games-practice-analysis-of-persona-5-royal-61a5c18ba9c1)
- [Map item format (map colours and the ×135/180/220/255 shades) — Minecraft Wiki](https://minecraft.wiki/w/Map_item_format)
- [List of block textures — Minecraft Wiki](https://minecraft.fandom.com/wiki/List_of_block_textures)
- [UI Design in NieR:Automata — PlatinumGames official blog](https://www.platinumgames.com/official-blog/article/9624)
- [How Cuphead nailed the look and feel of classic 1930s cartoons — Game Developer](https://www.gamedeveloper.com/art/how-i-cuphead-i-nailed-the-look-and-feel-of-classic-1930s-cartoons)
- [Breaking down the art style of Hollow Knight](https://www.youtube.com/watch?v=xlK8lNyQ8rg)
- [Design and Development of the Pip-Boy model 3000 — Fallout Wiki](https://fallout.fandom.com/wiki/Design_and_Development_of_the_Pip-Boy_model_3000)
- [UI Breakdown: Metroid Prime](https://medium.com/the-space-ape-games-experience/ui-breakdown-metroid-prime-c22cdfbce0bc)
- [Journey's art director breaks down the title's aesthetic — Game Developer](https://www.gamedeveloper.com/art/journeys-art-director-just-broke-down-the-title-s-timeless-aesthetic-in-glorious-detail)
- [The Art of Hades](https://www.pointnthink.fr/en/the-art-of-hades-en/)
