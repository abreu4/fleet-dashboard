# FLEET dashboard — theme system audit

**Audited file:** `/Users/tiago/.local/share/fleet-dashboard/ui.html` — 3,850 lines, 220 KB.
This is the **live** file (confirmed: `lsof -iTCP:8787` → `/Users/tiago/.local/share/fleet-dashboard/dashboard.py --port 8787 --terminal`, pid 78519).
Every line number below refers to that file.

`/Users/tiago/Documents/Dev/agent-dashboard/ui.html` (5,393 lines, 654 KB) is a **stale checkout**. I audited it first and re-targeted; §0 records what the live copy fixed, because that rewrite is the single most important fact about the current state of the theme system.

**Method.** I parsed the stylesheet into 597 discrete rules with a brace-matching extractor, resolved the full custom-property cascade per theme *with specificity* (`:root[data-theme=…]` = 0,2,0 always beats bare `:root` = 0,1,0 regardless of source order — a subtlety that produces wrong answers if you assume source order), computed WCAG 2.x contrast from linearised sRGB, and implemented sRGB→OKLab plus Viénot-style dichromat simulation to measure state-colour separation. Scripts are in this scratchpad (`rules.py`, `resolve2.py`, `contrast.py`, `cvd.py`, `count.py`).

---

## 0. What the live rewrite already fixed (and what it cost)

The brief asked me to map verbatim-duplicated ornament blocks and a `THEME_MUSIC` duplicate-key bug. **All of it is already fixed in the live file.** Verified, not assumed:

| Defect in the stale copy | Status in the live file |
|---|---|
| `vellum` + `hoarstone` contract blocks duplicated (stale L881/L1943, L900/L1962) | **Fixed** — one block each (L1397, L1416) |
| `ochre` had **two entirely different palettes** — a light TF2 cream set (stale L1564) and a dark olive set (stale L3240) that silently won on source order | **Fixed** — one block (L1018), the light TF2 palette. The dark-olive variant and its `--tf-*` tokens are gone with no dangling references |
| 63-rule ornament run duplicated (stale L871–1207 → L1933–2269); a further 48-rule and 12-rule run duplicated *inside* the first copy | **Fixed** — my duplicate-run detector finds **0 runs ≥3 rules** and **0 selectors with byte-identical bodies** anywhere in the live file |
| Unsubstituted template placeholders `@GRAIN_VELLUM@`, `@GRAIN_HOARSTONE@`, `@FROST_A/B/C@` — invalid CSS, and `dashboard.py` serves `ui.html` as raw bytes with no substitution | **Fixed** — zero `@TOKEN@` placeholders remain |
| `THEME_MUSIC` duplicate keys (`vellum`, `hoarstone` twice) | **Fixed** — 8 unique keys (L3201–3210) |

I also checked `THEME_MARKS` (L2614) for the same copy-paste damage: **8 unique theme keys, each with exactly 3 marks (`claude`/`antigravity`/`codex`), no duplicates.** Clean. (An early count of mine suggested a missing `codex` mark — that was a `sed` range truncating the last block. Not a bug.)

**What the dedup cost: nothing I can find.** Only two things differ materially between the surviving copies, and both are improvements: `--grain` gained real SVG payloads in place of the placeholders, and `ochre` settled on one palette. The 434 KB size drop is the duplicated ornament plus oversized inline SVG data URIs.

**Conclusion for task B's duplication sub-item: obsolete.** The obstacle to editing themes confidently is gone. Do not spend effort here.

---

## A. Identity audit

### A.1 How much each theme is actually built

Rule and declaration counts, and how many distinct structural hooks each theme reaches for. The hook count is the better measure of identity — it says how much of the *page* a theme re-describes, rather than how many times it repeats itself.

| Theme | Picker label | Rules | Decls | Hooks | Tier |
|---|---|---|---|---|---|
| hoarstone | skyrim | 43 | 136 | 22 | **reference** |
| signal | cyberpunk 2077 | 41 | 134 | 19 | **reference** |
| vellum | lord of the rings | 37 | 123 | 21 | **reference** |
| aperture | portal | 35 | 115 | 19 | strong |
| ochre | team spirit | 34 | 134 | 20 | strong |
| cardstock | pokémon | 33 | 126 | 18 | strong |
| chequer | sonic | 22 | 88 | 14 | thin |
| miami86 | hotline miami | 18 | 76 | 12 | thin |
| paper | paper | 15 | 57 | 17 | thin-but-wide |
| cyber | neon film | 12 | 58 | 10 | **under-built** |
| neutral | neutral | 9 | 44 | 10 | **under-built** |
| earth | earth | 9 | 50 | 9 | **under-built** |
| console | console | **8** | **17** | 9 | **under-built — and it is the default** |

The stated design rationale is at L676–678: *"The world themes below can be theatrical; the five everyday themes should stay quick under a live board."* That rationale does not survive contact with the evidence. The expensive thing about hoarstone is **authoring time**, not render cost — its 43 rules are static gradients, `box-shadow`s and one hover-triggered opacity fade. Nothing in the reference tier would cost a frame on an M-series Mac. The base themes are thin because they were written first and never revisited, and the comment retro-rationalises it.

**The headline asymmetry:** `console` is the default theme, the one loaded on first run and the one most hours get spent looking at, and it is the least realised thing in the file — 8 rules, 17 declarations. Its entire identity is a cyan HUD underline (L682), a header gradient (L686), one lane border colour (L690), a 3.5%-alpha tile sheen (L691) and a 16px grid on the trace (L692). It does not touch `body::after`, `.wrap::after`, `.brand`, `.chip`, `.panel`, `.toast` or `.empty`.

### A.2 Per-theme: does it read as its subject, and the one highest-leverage addition

For each theme the addition is named as a specific technique on a specific selector. These are deliberately **not** "256 rules for everyone" — the proportionate upgrade for a thin theme is 3–6 rules that claim the one surface that carries its idea.

**console — "admiralty chart / cyan vector glass".** Reads as *generic dark dashboard with a cyan accent*. The chart-table idea in the comment never reaches the page; nothing is engraved, ruled or plotted. **Add:** a lat/long graticule on the board ground via `.wrap::before` — two `repeating-linear-gradient`s at 1px/64px in `color-mix(in oklab, var(--accent) 9%, transparent)`, plus one heavier line every 5th via a second pair at 1px/320px. Four declarations, one new rule, and the board becomes a chart surface instead of a dark rectangle. This is the single best ratio in the file because it is the default theme.

**cyber — "Cinestill 800T neon film".** Reads *halfway*. The two corner colour casts (L695–700) are genuinely filmic; the aubergine blacks are right. What is missing is the thing that makes Cinestill *Cinestill*: **halation**. **Add:** `.bubble[data-state="running"], .bubble[data-state="blocked"] { filter: drop-shadow(0 0 6px color-mix(in oklab, var(--rib) 55%, transparent)); }` — halation is red-channel bloom around highlights, and the status rib is the only highlight on a tile. One rule. It will also, usefully, make the glance layer stronger (see C.4).

**earth — "Sherwood as pigment".** Reads as *dark green theme*. The pigment story (bog-oak, lichen, madder) is in the palette but the page has no organic geometry at all — every corner is a 5px radius rectangle. **Add:** asymmetric organic radii on `.bubble` — `border-radius: 10px 3px 9px 4px / 4px 9px 3px 10px` — plus the existing `--grain` already carries a horizontal fibre gradient. Two declarations; it is the cheapest possible "not machined" signal and it reads at arm's length because silhouette survives peripheral vision where texture does not.

**neutral — "graphite on cold-pressed paper", `--glow:0`.** Reads correctly and deliberately. This is the one under-built theme where thinness is the point: it is the "survive a bright room, distract me with nothing" option. **Add:** nothing decorative. The one real gap is that `body::after{display:none}` (L714) kills the theme's only ground treatment, so the board is a flat fill. Give it a single `.wrap::after` vignette at `rgb(0 0 0 / .12)` so the screen reads as lit rather than emitting. One declaration.

**paper — "iron-gall ink on laid paper".** Reads well and is the most *carefully* built of the thin themes (15 rules but 17 hooks — it re-describes more of the page than miami86 does with more rules, because it had to undo every dark-ground assumption). **Add:** a printed red-rule margin on `.rail` — `border-right: 1px solid color-mix(in oklab, var(--blocked) 45%, transparent)` plus a `repeating-linear-gradient` of faint horizontal ruling at 1px/22px across `.bubbles`, so tiles sit *on* ruled paper. Two rules.

**miami86 — "sun-bleached pastel violence".** Under-built relative to its ambition: 18 rules, and its `--glow:2` (the highest in the file) is doing most of the work. It has the VHS roll (L953) and a `.wrap::after`, but no **chromatic aberration**, which is the defining artefact of a third-generation dub. **Add:** `:root[data-theme="miami86"] .bubble .nm { text-shadow: 1.2px 0 0 rgba(49,223,235,.5), -1.2px 0 0 rgba(255,79,184,.5); }` — the cyber theme already does exactly this on `.brand b` (L712), so the technique is in-house; miami86 is where it belongs most and does not use it.

**signal — "acid yellow on soot, brutalist".** Strong, reference tier. Misregistration is the stated concept (magenta/teal "living only in the misregistration") and the `sig-tear` keyframe (L902) sells it. **Add:** the one missing brutalist move is **hard-edged stencil numerals** — `.chip b, .project > header .ct { font-variant-numeric: tabular-nums slashed-zero; -webkit-text-stroke: .4px var(--edge-hot); }`. Cheap, and counts are the numbers you actually read.

**aperture — "clean industrial lab", light.** Strong. Countersunk screws (L815–820) and the bevel are excellent. **Add:** safety-stripe hazard tape on one edge of `.lane` — `repeating-linear-gradient(45deg, var(--done) 0 8px, var(--void) 8px 16px)` as a 3px `border-top` image. The palette comment explicitly cites "safety-stripe signage" and the page never draws one.

**vellum — "candlelit scriptorium", reference.** Reads unmistakably. Illuminated bar-border, ivy sprays, drop-cap `::first-letter` (L971 in stale; present live), `.empty`/`.note` replaced with scribal text via `font-size:0` + `::after`. **Add:** nothing structural. The one gap is that its intended display face never loads (see A.3).

**hoarstone — "cold stone, hammered iron", reference and the bar-setter.** 43 rules, 22 hooks, and the only theme with a *interactive* ornament — hoarfrost creeping in on `.wrap::before` when you hover `FLEET`, gated behind `prefers-reduced-motion`. **Add:** nothing. This is the target, not a candidate.

**cardstock — "offset-printed trading card + handheld LCD".** Strong and inventive: the CMYK rosette in `--grain` (three offset dot `<pattern>`s at 5/6/10px — genuinely the right way to fake halftone), and `.gauge`/`.readout` recoloured to a pale-olive dot-matrix LCD field with its pixel grid showing (L1125–1133). **Add:** the card needs a **holographic/foil tilt** on `.bubble.sel` — a `linear-gradient(110deg, …)` rainbow at ~8% alpha with `background-size:200%` and a slow `background-position` shift, reduced-motion-gated. One rule, and it is the most era-correct flourish available.

**chequer — "Genesis CRT / 1991 arcade", thin.** 22 rules; the `hillroll` keyframe (L1272) and the RGB-stripe `--grain` are right, but it is the most **under-built relative to how distinctive its subject is**. A Genesis-era look has two signatures the theme does not use: a **chequerboard** (the theme is *named* chequer and never draws one) and **dithering**. **Add:** `:root[data-theme="chequer"] .hrail { background-image: conic-gradient(from 90deg at 50% 50%, var(--tile) 0 25%, transparent 0 50%, var(--tile) 0 75%, transparent 0); background-size: 12px 12px; }` — a true 2-colour chequer on the lane rail, in the theme's own name. Then a 2×2 Bayer dither on `.project > header` via a 4px `conic-gradient`. Two rules, and it stops being "a blue theme".

**ochre — "TF2 RED/BLU screen print", strong.** 34 rules / 134 declarations, and it does the boldest thing in the file: the lane rails are literally split RED-over-BLU with a cream ceasefire stripe (L1345–1352, L1353–1359), and project headers alternate team colour by `:nth-child(even)`. **Add:** nothing decorative — it has a real contrast defect instead (B.2) and that is where its budget should go.

### A.3 Every theme is running on its *second-choice* display face

The typography pass (L1900–2487) is a genuine third identity layer — 13 themes, 13 voices, font-family/weight/tracking only. But I checked each named family against this Mac's actual font files (`/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`), and **the first-choice face is missing for 10 of the 13 themes**:

| Theme | Intended first choice | Missing? | Actually renders as |
|---|---|---|---|
| hoarstone | Cinzel | **missing** | Avenir Next Condensed / Futura |
| vellum | IM Fell English SC, EB Garamond | **both missing** | Hoefler Text / Iowan Old Style |
| cardstock | Silkscreen, Gill Sans MT | **both missing** | Gill Sans |
| signal | Rajdhani, Chakra Petch, Share Tech Mono | **all missing** | Krungthep / Iosevka |
| chequer | Archivo, Archivo Black | **both missing** | Impact / Phosphate |
| ochre | Zilla Slab, Archivo, Anton | **all missing** | SuperClarendon / Rockwell |
| miami86 | Archivo Black | **missing** | Phosphate / Impact |
| cyber | Bebas Neue | **missing** | Avenir Next Condensed |
| console | Copperplate Gothic Light | **missing** | Copperplate ✔ (close) |
| aperture | Inter | **missing** | Helvetica Neue (close enough) |
| earth, neutral, paper | — | none missing | as authored |

This is **not a bug** — every stack has a macOS fallback immediately after, which is why nothing looks broken. It is the highest-payoff cheap upgrade in the whole identity half: the four themes whose subject *is* a letterform (vellum's IM Fell, hoarstone's Cinzel, cardstock's Silkscreen, signal's Rajdhani) are each one font file away from a visible tier jump.

And it is architecturally easy, because **the vendor mechanism already exists**: `dashboard.py` L226–228 has a `VENDOR` allowlist dict serving `xterm.js`/`xterm.css`/`xterm-addon-fit.js` from `vendor/`, read and served at L377. Adding five WOFF2 files is one dict entry each plus one `@font-face` per theme — no base64 bloat, no network, single-file property preserved for the HTML itself. (Check each licence: Cinzel, IM Fell English, Silkscreen, Rajdhani and Archivo are all OFL, so self-hosting is permitted.)

---

## B. Cross-theme consistency defects

### B.1 The light-theme letterpress inversion — the worst defect in the file

`paper` was the only light theme when the "ornament, material and legibility" block was written, and two of its rules bake a **dark ground** into every element, with a `paper`-only antidote bolted on after:

```
L494-496   .gauge, .trace, .readout, .chip, .project, .lane, .stat, .bubble{
             box-shadow: inset 0 1px 0 rgb(255 255 255 / .05),
                         inset 0 -1px 0 rgb(0 0 0 / .30); }
L497-501   :root[data-theme="paper"] …same 8 selectors… { /* light antidote */ }

L509-512   .gauge .lab, .trace .cap, .chip, .project > header, .rail .vlabel,
           .hrail .who, .hrail .note, .bubble .foot, .panel .sub,
           .panel section h3, .stat .k, .ctl select, button.ghost,
           .acts button, .readout dt{
             text-shadow: 0 1px 0 rgb(0 0 0 / .50); }       /* ← 15 selectors */
L513-525   :root[data-theme="paper"] …same 15 selectors… { text-shadow: 0 1px 0 rgb(255 255 255 / .95); }
```

`aperture`, `cardstock` and `ochre` were added **later** and never got the antidote for L509.

**Verified by exhaustive selector matching:**

- **Bevel (L494):** `paper`, `cardstock` and `ochre` re-set all 8 selectors. `aperture` re-sets 7 — it misses **`.chip`**, which therefore carries a 30%-black inset smear along its bottom edge on a `#f5f3ee` ground (L807–813 lists `.gauge .trace .readout .project .bubble .stat`, no `.chip`).
- **Letterpress (L509):** only `paper` overrides it. **`aperture`, `cardstock` and `ochre` inherit `text-shadow: 0 1px 0 rgb(0 0 0 / .50)` on all 15 selectors.** The only `text-shadow` those three themes set at all is on `.brand b` (L835, L1152) and `ochre .hrail .note`/`.rail .vlabel` (L1360–1363).

A 50%-black 1px drop shadow beneath **dark text on a light ground** does the opposite of letterpress: it thickens and muddies the glyph instead of crisping it. It lands on every 10–12px uppercase label on the board — gauge labels, project headers, the tile status line, drawer headings, buttons. At arm's length on a laptop panel this is precisely the size where it costs the most.

**Fix** — one rule, no per-theme work, and it inverts automatically for any light theme added later:

```css
/* replaces the paper-only override at L513-525 */
:root[data-theme="paper"],  :root[data-theme="aperture"],
:root[data-theme="cardstock"], :root[data-theme="ochre"]{
  --letterpress: 0 1px 0 rgb(255 255 255 / .95);
}
:root{ --letterpress: 0 1px 0 rgb(0 0 0 / .50); }
.gauge .lab, .trace .cap, .chip, .project > header, .rail .vlabel,
.hrail .who, .hrail .note, .bubble .foot, .panel .sub, .panel section h3,
.stat .k, .ctl select, button.ghost, .acts button, .readout dt{
  text-shadow: var(--letterpress);
}
```

Better still, make it a contract token (`--letterpress`, `--bevel-hi`, `--bevel-lo`) set in each theme's contract block, which removes the "did I remember to add my theme to that list" failure mode entirely. That is the structural version of this fix and it is what the contract is for.

### B.2 `--waiting` is missing from three contract blocks — a 1.88:1 contrast failure

`--waiting` is a **real sixth state** (`STATES` at L2674 is `['blocked','waiting','running','idle','done','unknown']`), and it is the state that *most* needs the user: a session that has stopped and is asking for input.

Themes defining `--waiting` themselves: console L25, cyber L40, earth L55, neutral L70, paper L86, aperture L962, signal L963, miami86 L964, vellum L1541, hoarstone L1652.

**Not defining it: `cardstock`, `chequer`, `ochre`.** All three silently inherit console's `#ff8c68` from the base `:root` at L25. Consequences:

| Theme | `--tile` | waiting word contrast | verdict |
|---|---|---|---|
| **ochre** | `#fff0cf` | **1.88 : 1** | unreadable |
| **cardstock** | `#fffdf6` | **2.06 : 1** | unreadable |
| chequer | `#1b3070` | 4.47 : 1 | legible but off-palette (console salmon in a Genesis palette) |

Two of the three light themes render the most urgent state on the board in near-invisible text. **Fix** (3 lines, in each contract block):

```css
:root[data-theme="cardstock"]{ --waiting:#b4521f; }   /* printed vermilion, ~4.9:1 on #fffdf6 */
:root[data-theme="ochre"]    { --waiting:#b5441a; }   /* Mann Co crate orange, ~4.6:1 on #fff0cf */
:root[data-theme="chequer"]  { --waiting:#ff8f2e; }   /* arcade amber, on-palette */
```

**Guard against recurrence.** The contract has no enforcement. Add a dev-only assertion near `setTheme` (L3176) that reads the computed value of every contract token and warns when a theme inherits one it should own:

```js
// dev guard: a theme that forgets a contract token inherits console's
const CONTRACT = ['--void','--panel','--cell','--tile','--tile-hi','--edge','--edge-hot',
  '--ink','--dim','--faint','--accent','--blocked','--waiting','--running','--idle',
  '--done','--unknown','--good','--warn','--glow','--sigil'];
function auditTheme(name){
  const cs = getComputedStyle(document.documentElement);
  const base = {'--waiting':'#ff8c68'};  // extend as needed
  CONTRACT.forEach(k => {
    const v = cs.getPropertyValue(k).trim();
    if(!v) console.warn(`[theme] ${name} is missing ${k}`);
    else if(base[k] && v === base[k] && name !== 'console')
      console.warn(`[theme] ${name} inherits console's ${k} (${v}) — probably unintended`);
  });
}
```

### B.3 Contrast audit — the legibility pass mostly holds

Full matrix in `contrast.txt`. Computed as WCAG 2.x relative luminance, with `color-mix(in oklab, …)` tile tints resolved through a real OKLab implementation so the `blocked`/`waiting`/`running`/`idle` tinted faces are the actual backgrounds, not `--tile`.

**Text tiers pass nearly everywhere.** The §2 legibility pass (L577–650) did its job. Of 143 token/surface/theme combinations, body text (`--dim`, `--ink`, threshold 4.5:1) **never fails in any theme** — the worst case is `chequer .bubble .gist` at 6.49:1. Small uppercase labels (`--faint`, threshold 3:1) pass in 12 of 13 themes; worst is `chequer .bubble .foot` at 4.30:1. This is genuinely well-tuned and I could not find a text-tier defect worth reporting.

Two notes on apparent failures that are **false positives**, recorded so nobody "fixes" them:
- My first pass flagged `ochre` `--faint`-on-`--rail-a` at **1.07:1** and `--dim`-on-`--rail-a` at **1.57:1**. Catastrophic on paper — `--rail-a:#b8383b` is TEAM RED and `--faint:#776955` is a dark brown. But ochre hand-patches every affected selector to cream `#fff1d2` at L1317–1318 and L1360–1363. Not a live defect.
- `ochre` `--faint` on the idle-tile mix computes 4.43:1 against a 4.5 threshold. Within the error of my luminance rounding; ignore.

**However, that false positive exposes a real structural gap.** `--hud-a/--hud-b` and `--rail-a/--rail-b` are the only surfaces in the contract with **no matching ink token**. Every theme paints `--dim`/`--faint` on them — tokens tuned for `--cell` and `--tile`. That holds only while rails stay near-neutral. `ochre` broke the assumption and had to patch with four hardcoded hex values. Lowest passing margins today: `aperture` `--faint` on rail at **3.37:1** and `paper` at **3.85:1** — both one palette tweak from failing. **Proposal:** add `--ink-rail` (default `var(--dim)`) and `--faint-rail` (default `var(--faint)`) to the contract, point L252–261 and L243–245 at them, and ochre's four hardcoded patches collapse into two token declarations.

**Where contrast genuinely fails is the state words** (`.bubble .foot` recoloured by state, L608–612 and L669):

| | vellum | hoarstone | cardstock | ochre | chequer | earth |
|---|---|---|---|---|---|---|
| blocked | **2.77*** | **2.95*** | 4.55 | 3.64 | 3.06 | 3.31 |
| waiting | 4.25 | 3.84 | **2.06*** | **1.88*** | 4.47 | 4.17 |
| done | 8.78 | 8.27 | 5.02 | **2.87*** | 5.41 | 5.13 |

Six failures against the 3:1 small-text threshold. `vellum`/`hoarstone` `blocked` at 2.77/2.95 are marginal (raise `--blocked` lightness ~6% in OKLch, or drop the tile tint from 13% to 9%). `cardstock`/`ochre` `waiting` are B.2. `ochre` `done` at 2.87 needs `--done` darkened from `#d4772d` to about `#a85a16`.

### B.4 State colours collide badly under red-green colour blindness

Full matrix in `cvd.txt`. OKLab ΔE between all pairs of the six state colours plus `--accent`, under normal, deuteranope and protanope simulation. Flagging ΔE < 0.10 as "not reliably separable at the 7px dot size this board uses".

**Worst collisions (deuteranopia unless noted):**

| Theme | Pair | ΔE | note |
|---|---|---|---|
| cardstock | `blocked` ~ `done` | **0.001** | `#c62d11` vs `#a45c00` — *literally the same colour* |
| aperture | `waiting` ~ `done` | **0.004** (prot) | `#8a6d1f` vs `#c2611a` |
| vellum | `waiting` ~ `running` | **0.007** | `#c08b74` vs `#6fa96e` |
| paper | `running` ~ `accent` | **0.015** (prot) | |
| hoarstone | `waiting` ~ `running` | **0.019** | |
| ochre | `blocked` ~ `running` | **0.019** | `#c9433f` vs `#5f8d45` — textbook red/green |
| cyber | `unknown` ~ `accent` | **0.019** | |
| earth | `idle` ~ `unknown` | 0.027 | 11 colliding pairs total — worst theme overall |
| neutral | `blocked` ~ `waiting` | 0.032 | 13 colliding pairs — worst theme overall |

`earth` and `neutral` are the most affected because both are deliberately low-chroma, which compresses exactly the axis dichromats rely on. Even in **normal** vision, `idle`~`unknown` is under 0.10 in 8 of 13 themes, and `blocked`~`waiting` is under 0.10 in 5 — so this is not purely an accessibility question, it is a glanceability question for everyone.

**Is state ever encoded by hue alone? Partly — and in the pre-attentive channel specifically.**

Redundant encoding that *does* exist: every tile and every tally chip spells the state out in text (`tile()` L2921 emits `<i class="dot s-…"></i>` followed by the state word; `tally` L2801–2802 likewise). So nothing is *unrecoverable*.

But the channels you actually read at a glance carry almost no redundancy:

1. **`.dot` (L179–183)** — a 7px circle, *identical geometry for all six states*. The only non-hue differentiator is `box-shadow: 0 0 calc(var(--glow)*7px)` on `blocked`/`running`/`waiting`. **`--glow` is `0` in `neutral`, `paper`, `vellum`, `cardstock` and `ochre`** — so in 5 of 13 themes the dot is **purely hue-coded**, six indistinguishable circles. This is where `cardstock`'s ΔE 0.001 `blocked`/`done` collision actually bites.
2. **The tile rib `.bubble::before`** — `width: 5px` default, `8px` for `blocked` (L641) and `8px` for `waiting` (L673). So the rib cannot separate `blocked` from `waiting` — the two states that both mean "come here" — and `running`/`idle`/`done`/`unknown` all share 5px, hue-only.
3. **Tile face tint** — `blocked` 13%, `waiting` 11%, `running` 7%, `idle` mixed toward `--cell`, `done`/`unknown` untinted. So `done` and `unknown` differ *only* by rib hue.

**Fix, cheap and theme-agnostic:** give the rib a luminance/texture code in addition to hue, so the six states are separable with no colour vision at all. The rib is already a pseudo-element with nothing in it:

```css
/* state is encoded by rib WIDTH + PATTERN, not hue alone */
.bubble[data-state="blocked"]::before{ width:9px;
  background-image:repeating-linear-gradient(0deg, rgb(0 0 0 /.34) 0 2px, transparent 2px 5px); }
.bubble[data-state="waiting"]::before{ width:9px;
  background-image:repeating-linear-gradient(0deg, rgb(0 0 0 /.34) 0 5px, transparent 5px 10px); }
.bubble[data-state="running"]::before{ width:6px; }
.bubble[data-state="idle"]::before   { width:3px; }
.bubble[data-state="done"]::before   { width:6px;
  background-image:linear-gradient(0deg, transparent 0 50%, rgb(0 0 0 /.30) 50% 100%); }
.bubble[data-state="unknown"]::before{ width:3px;
  background-image:repeating-linear-gradient(0deg, rgb(0 0 0 /.30) 0 1px, transparent 1px 4px); }
```
`blocked` (fine stripe) and `waiting` (coarse stripe) become separable at the same width; `done` (half-bar) and `unknown` (hairline dots) separate without hue. Apply the same `::before` pattern trick to `.dot` via `background-image` and the tally legend becomes colour-blind-safe too.

For the palette itself, the cheapest durable rule is **monotonic luminance ordering**: require the six state colours in every theme to occupy six distinct OKLch lightness bands (e.g. L ≈ .62/.70/.66/.52/.74/.58). That makes them separable in greyscale, which is the same thing as separable in the periphery, *and* it is the check WCAG 1.4.1 ("Use of Color", Level A) is really asking for. My `cvd.py` can be repurposed as a pre-commit check.

Two warnings worth recording, because the obvious fix is a trap:

- **Do not reach for a standard "perceptually uniform" categorical generator.** Tools like R's `colorspace::qualitative_hcl()` deliberately hold chroma *and lightness constant* across the palette to give each category equal perceptual weight. That is the exact opposite of what this board needs: constant lightness collapses to a single grey in the periphery and under achromatopsia. Datawrapper's guidance is the right one — give the hues *different* lightnesses so the set survives greyscale. ColorBrewer's "photocopy safe" filter is the same test.
- **Luminance must track meaning, not hue.** Order the six states by lightness so severity is readable without colour at all.

If any theme's state set needs rebuilding from scratch rather than nudging, the two palettes to start from (both colour-vision-deficiency-designed, both with verified hexes) are **Okabe–Ito** (Okabe & Ito 2008, *Color Universal Design*) and **Paul Tol's "Vibrant"** set, which is explicitly designed for thin lines, small markers and viewing at distance — i.e. this exact use case:

- Okabe–Ito: `#E69F00` orange · `#56B4E9` sky blue · `#009E73` bluish green · `#F0E442` yellow · `#0072B2` blue · `#D55E00` vermillion · `#CC79A7` reddish purple · `#000000`
- Tol Vibrant: `#EE7733` orange · `#0077BB` blue · `#33BBEE` cyan · `#EE3377` magenta · `#CC3311` red · `#009988` teal · `#BBBBBB` grey

Use these as a **separation reference to measure against, not as a palette to adopt** — dropping Okabe–Ito into `vellum` would destroy the pigment palette that makes the theme good (see the argument in C.3). The right move is to keep each theme's hand-mixed hues and adjust their *lightness* until the six are separable.

**Verify visually in Chrome DevTools** → Rendering → "Emulate vision deficiencies" (protanopia, deuteranopia, tritanopia, achromatopsia). Zero install, runs against the live board, and it is the fastest way to confirm the `cardstock` ΔE 0.001 case with your own eyes.

### B.5 Remaining hardcoded colours

The brief said a section already fixed three of these. Confirmed — L661–666, labelled *"Three hardcoded console-blue values that survive a theme change"*, re-points `.scrim`, `.toast` and `.acts button:hover` at tokens, overriding the literals that remain at L426 (`#02060bcc`), L459 (`#0c1826`) and L456 (`#12283a`). Those three are dead and harmless.

**Still leaking, in unscoped rules** (15 unscoped rules contain literal colours; these are the ones that matter):

| Line | Selector | Literal | Impact |
|---|---|---|---|
| L494 | `.gauge,.trace,.readout,.chip,.project,.lane,.stat,.bubble` | `rgb(0 0 0 / .30)` inset | B.1 — `aperture .chip` only |
| L509 | 15 small-caps selectors | `rgb(0 0 0 / .50)` text-shadow | **B.1 — 3 light themes** |
| L282 | `.bubble:hover` | `0 8px 20px -10px #000` | harsh on 4 light themes |
| L526 | `.bubble:hover` | `0 10px 22px -12px #000` | same (this one wins) |
| L325 | `.player` | `0 18px 44px -18px #000` | no theme overrides it |
| L385 | `.crate` | `0 18px 44px -18px #000` | no theme overrides it |
| L431 | `.panel` | `-30px 0 60px -30px #000` | `cardstock`/`ochre`/`aperture` override; `paper` does **not** |
| L1817 | `.sheet` (terminal) | `0 -26px 50px -32px #000` | **no theme overrides it** — newest surface, no light-theme pass at all |
| L536 | `.brand b` | `0 1px 0 rgb(0 0 0 / .5)` | `paper`/`aperture`/`cardstock` override; `ochre` does not |
| L557 | `.wrap::after` | `rgb(0 0 0 / .30)` | `paper` overrides (L566); `aperture`/`cardstock`/`ochre` do not |

**One-rule fix for the whole `#000`-shadow family** — add a `--shadow` token to the contract and use it everywhere:

```css
:root{ --shadow: 0 0 0 #000; --shade: rgb(0 0 0 / .30); }          /* dark default */
:root[data-theme="paper"], :root[data-theme="aperture"],
:root[data-theme="cardstock"], :root[data-theme="ochre"]{
  --shade: rgb(90 70 40 / .16);                                     /* warm, light-ground */
}
.player, .crate { box-shadow: 0 18px 44px -18px var(--shade); }
.panel          { box-shadow: -30px 0 60px -30px var(--shade); }
.sheet          { box-shadow: 0 -26px 50px -32px var(--shade); }
.wrap::after    { background: radial-gradient(120% 95% at 50% 42%, transparent 55%, var(--shade) 100%); }
```

Note `.sheet` (L1817, the terminal sheet) has **no light-theme treatment from any theme**. It is the newest UI surface and the theme passes predate it. Worth a dedicated check once the in-page terminal settles; out of scope here.

### B.6 The `prefers-reduced-motion` count is 5, not ~11

The brief said ~11 blocks. The live file has **5**: L112 (cyber scanline drift), L290 (blocked rib pulse), L978, L1273, L1684. The stale copy had more because the duplicated ornament duplicated them. Coverage against the 5 `@keyframes` (L111 `drift`, L289 `pulse`, L902 `sig-tear`, L953 `vhs-roll`, L1272 `hillroll`) is complete, plus the hoarstone frost transition. **No gap found** — but anything added in part C must extend this set, and 5 is the number to match.

---

## C. UX-candy research

Sourced from two parallel web-research passes (MDN, web.dev, Chrome developer blog, CSSWG drafts, Chrome Platform Status) plus HCI literature. Chrome-only is explicitly safe: one Chrome window, one Mac.

**Baseline of what the file uses today:** `color-mix()` 13 times (including `in oklab`, L614/644/648/671) — so modern colour CSS is already idiomatic here. **Zero** uses of `oklch()`, `@property`, `view-transition*`, `@starting-style`, or `linear()`. 14 `transition:` declarations, 5 `@keyframes`. There is a lot of headroom and none of it is exotic relative to the house style.

### C.1 The architectural fact that governs everything in this section

`render()` at L2858 does a **full subtree replacement**: `board.innerHTML = d.lanes.map(…)` at L2869. Every tile is destroyed and recreated. And the re-render gate at L2863–2866 is

```js
const sig = JSON.stringify(d.lanes) + '|' + [...minimised].sort().join(',')
          + '|' + compact + '|' + document.documentElement.dataset.theme
          + '|' + Math.floor(Date.now() / 5000);
if(sig === boardSig) return;
```

Two consequences that any animation work must respect:

1. **`Math.floor(Date.now()/5000)` means the board rebuilds at least once every 5 seconds even when nothing changed** (deliberately — so relative ages stay fresh). Therefore **any entry animation attached to tile insertion will fire on every tile every 5 seconds** — a board-wide flash, forever. This is the single biggest trap in this section. Entry/exit animation must be keyed off a **real state diff**, not off DOM insertion.
2. There is currently **no transient of any kind** when a session changes state: the old tile vanishes and a new one appears in the same paint. That is the textbook setup for change blindness (C.4), and it is the strongest argument for view transitions here.

**Prerequisite for everything below: keep a previous-state map.** This is ~6 lines and it is what makes the rest cheap and correct:

```js
let prevState = new Map();                       // session id -> state
function stateDiff(d){
  const now = new Map(), changed = new Set(), arrived = new Set();
  d.lanes.forEach(l => l.projects.forEach(p => p.sessions.forEach(s => {
    now.set(s.id, s.state);
    if(!prevState.has(s.id)) arrived.add(s.id);
    else if(prevState.get(s.id) !== s.state) changed.add(s.id);
  })));
  const left = [...prevState.keys()].filter(id => !now.has(id));
  prevState = now;
  return {changed, arrived, left};
}
```

### C.2 View transitions — yes, and use the *scoped* form

| Feature | Chrome | Status |
|---|---|---|
| `document.startViewTransition()` | 111 (`types` 121) | Baseline newly available, Oct 2025 |
| `view-transition-class` | 125 | Baseline newly available |
| `view-transition-name: match-element` | 137 | Baseline newly available |
| **`element.startViewTransition()`** (scoped) | **147, Mar 2026** | Chrome-only — **this is the one to use** |
| `@view-transition { navigation: auto }` | 126 | **cross-document only — irrelevant here** (confirmed) |

The scoped form is the correct tool: call it on the board container rather than `document`, and Chrome applies `view-transition-scope: all` + `contain: layout` to that root. It avoids snapshotting the whole document, leaves the rest of the page interactive, and **fixes the known `position: fixed` z-index bug** (CSSWG issue #8941) where `::view-transition` paints above fixed elements regardless of `z-index` — which matters a lot here, because the drawer (`z-index:6`), toast (`7`) and music player (`8`) are all fixed overlays that would otherwise be covered during every transition.

Note the other confirmed gotcha: `overflow:hidden` / `clip-path` **does not clip transitioning descendants**, because `::view-transition-group()` nodes are siblings in the pseudo-tree. `.project` uses `overflow:hidden` (L250) and `.bubbles` uses `overflow:auto` (L263), so a naive implementation will let tiles visually escape their project box mid-animation. Scoping to the board plus animating only *changed* tiles keeps this contained; verify it visually.

**Recommended implementation** — animate only what changed, never the whole board:

```js
const canVT = !!board.startViewTransition &&
              !matchMedia('(prefers-reduced-motion: reduce)').matches;

function render(d){
  /* …existing drawHud(d), sig check… */
  const {changed, arrived} = stateDiff(d);
  const interesting = changed.size > 0 || arrived.size > 0;
  if(!canVT || !interesting) return paintBoard(d);       // the 5s age refresh: no animation

  // name ONLY the tiles that actually changed
  changed.forEach(id => {
    const el = board.querySelector(`.bubble[data-id="${CSS.escape(id)}"]`);
    if(el) el.style.viewTransitionName = 'tile-' + CSS.escape(id);
  });
  const t = board.startViewTransition(() => paintBoard(d));
  t.ready.catch(() => {});                                // superseded -> AbortError, expected
  t.finished.catch(() => {}).finally(() => {
    board.querySelectorAll('.bubble[style*="view-transition-name"]')
         .forEach(el => el.style.viewTransitionName = '');
  });
}
```
```css
.bubble{ view-transition-name: none; }                  /* opt in per-tile from JS */
::view-transition-group(root){ animation: none; }        /* no full-board crossfade */
::view-transition-group(*){
  animation-duration: .42s;
  animation-timing-function: linear(0, .42 18%, .83 42%, 1.02 62%, 1.005 82%, 1);
}
@media (prefers-reduced-motion: reduce){
  ::view-transition-group(*){ animation-duration: 1ms; }
}
```

Use `CSS.escape()` — unescaped `view-transition-name` values are **silently dropped**, and a duplicate active name **skips the entire transition**. Chrome auto-skips a still-running transition when a new one starts, so overlap is safe, but `ready`/`finished` reject with `AbortError` and must be caught or they surface as unhandled rejections every few seconds.

**The one genuinely open risk.** No primary source publishes GPU-memory cost per named element, and **no long-run (multi-hour, thousands-of-cycles) leak study for the native API exists.** For a board that runs for days and would fire a transition every few seconds, that is exactly the unknown that matters. Profile it empirically — DevTools GPU + Memory over an hour — rather than trusting docs. Mitigation is built into the snippet above: transitions fire only on a **real** state diff, which on a quiet board is minutes apart, not every 5 seconds.

### C.3 `@property`, `oklch()` and deriving themes from seeds

**`@property` (Chrome 85, Baseline Jul 2024) is required, not optional, for what this file wants.** Without registration, a custom property inside a `gradient()` or `box-shadow` is re-parsed as a *string* each keyframe, so it jumps discretely instead of interpolating. Every glow in this file is `box-shadow: 0 0 calc(var(--glow)*7px) var(--state)` — currently un-animatable for that exact reason. Animatable syntaxes: `<color> <length> <percentage> <number> <angle> <time> <resolution> <image> <transform-list>`. **Not** animatable: `"*"` and `<custom-ident>`.

**Critical gotcha for a 13-theme file:** `@property` registration is **global to the document** and bypasses the cascade. It cannot be scoped per theme; if two valid registrations share a name, the last in document order silently wins. So **do not** try to register `--glow` or any existing contract token. Namespace new animatable properties (`--fleet-rib-glow`, `--fleet-pulse`) and leave the 30-token contract as plain unregistered properties.

**On deriving a whole theme from 2–3 seed colours — my verdict: don't, for these themes, but adopt the derivation for the *derived* tiers.**

The case *for*: `oklch()` gives perceptually-even lightness, relative colour syntax (`oklch(from var(--seed) calc(l + .08) c h)`) makes ramps one line, and it would mechanically guarantee the B.3/B.4 properties I had to verify with a script — monotonic luminance, fixed contrast ratios, separable state hues. Thirty hand-tuned hex values per theme × 13 themes is 390 numbers with no invariant enforcement, which is precisely why `--waiting` went missing in three of them.

The case *against*, and it is the stronger one here: **these palettes are good because they are not algorithmic.** Read the comments — "Cinestill 800T, Shinjuku 2am", "lamp-black soot, walnut/bistre ink, orpiment saffron", "Nothing here is a screen primary", "the blues carry a violet cast the way a phosphor blue does". The *point* is that `--void` drifts cool while `--tile` drifts warm (console), or that a muddied cobalt sits slightly off where a generator would put it. A seed-derived ramp is hue-constant and chroma-smooth by construction — it cannot produce the deliberate warm/cool split, and it cannot produce "dirty" historical pigment. Algorithmic derivation also reliably mishandles the yellow/blue lightness trap: equal-L yellows and blues do not read as equally light, and gamut clipping at high chroma flattens exactly the saturated accents `miami86` and `signal` depend on.

**The synthesis, and what I actually recommend.** Keep all 13 hand-tuned palettes exactly as they are. Use modern colour CSS only for the tiers that are *already* being computed by hand and are therefore the ones that drift:

```css
/* --faint and --dim are the two tiers that caused every near-miss in B.3.
   Derive them from --ink against the surface they actually sit on. */
:root{
  --dim:   oklch(from var(--ink) calc(l - .18) calc(c * .62) h);
  --faint: oklch(from var(--ink) calc(l - .30) calc(c * .45) h);
}
```
A theme that wants its own hand-mixed `--dim`/`--faint` still just declares them — the derivation is the *default*, not a mandate. That buys the invariant without losing a single hand-tuned decision. `paper`, `vellum` and `hoarstone` would likely keep overriding; `chequer` (worst text margins at 4.30:1) would benefit immediately.

An even better `--faint`/`--dim` recipe than the `oklch(from …)` one above, for this file specifically: **mix the ink toward the surface it sits on**, not toward black or white. That self-corrects across light and dark themes with no per-theme branch at all:

```css
--dim:   color-mix(in oklab, var(--ink) 74%, var(--cell));
--faint: color-mix(in oklab, var(--ink) 56%, var(--cell));
```
Use `in oklab` rather than `in srgb` (which produces grey, muddy mixes) and rather than `in oklch` (polar, and can detour through unintended hues on distant-hue pairs). This is also the smallest possible change, since `color-mix(in oklab, …)` is already used 13 times in the file.

**Relative colour syntax** (`oklch(from var(--seed) calc(l + .1) c h)`) is Chrome 119+, Safari 16.4+, Firefox 128+ — comfortably safe here. Gate with `@supports (color: oklch(from white l c h))` only if the file ever needs to run outside Chrome.

**`contrast-color()` — correction to my own earlier note: it did ship.** Chrome 147, Firefox 146, Safari 26.0; Baseline "newly available" around 2026-04-10. But its scope is much narrower than the name suggests: **it returns only `black` or `white`**, whichever gives greater WCAG contrast against the input (ties go to white). It is *not* the old `color-contrast(bg vs c1, c2, c3…)` candidate-list proposal, which never shipped in any engine. So it is a useful *floor* — a cheap guard against an inverted-contrast disaster on an arbitrarily tinted surface — but it cannot pick a themed ink, and pure black or pure white would be wrong in every one of these 13 palettes. **Verdict: no use for it in this file.** I looked for the case it would fix — ink painted on an `--accent` ground — and found exactly one, L920 (`:root[data-theme="signal"] .project > header .ct { background:var(--accent); color:#0a0b07 }`). That one is correctly theme-scoped to a theme whose accent is a fixed acid yellow, and `#0a0b07` is a deliberate soot-black that `contrast-color()` would replace with pure `black`, losing the choice. Leave it alone.

### C.4 Delight on a board whose purpose is ambient awareness

This is where the file has its most interesting single defect, and it is one the file *itself* diagnoses and then half-fixes.

**What the perception literature says** (pre-attentive processing, peripheral vision):

- **Channel ranking in the periphery: motion / luminance-onset ≫ size change > orientation > blur > hue (weakest, near-useless off-axis).** The cause is retinal — cones carry hue and are foveally concentrated; rods are achromatic and motion-sensitive and dominate from ~20° eccentricity out. Red–green opponency is *behaviourally absent* by 25–30° eccentricity. So a hue change seen from the corner of the eye at 1 m is close to invisible, while a motion or luminance transient is not. (Rosenholtz, *Capabilities and Limitations of Peripheral Vision*, Ann. Rev. Vision Science 2016; Healey & Enns, *Attention and Visual Memory in Visualization and Computer Graphics*, IEEE TVCG 2012 — the latter is the vis-specific canon and documents the luminance-over-hue priority directly.)
  - Useful nuance: the periphery detects flicker **onset** very well but is poor at discriminating *which rate* is flickering (frequency JND is ~2–5% foveally vs >100% peripherally). So encode urgency in **onset and amplitude, not in rate** — which is what the escalation design below does.
- **Change blindness — this is the load-bearing citation for the whole section.** Rensink, O'Regan & Clark (*Psychological Science* 1997) established the flicker paradigm; the "mudsplash" variant (1999) showed that brief high-contrast transients *elsewhere* on screen mask large simultaneous changes. NN/g's modern restatement, *Change Blindness Causes People to Ignore What Designers Expect Them to See*, recommends animated transitions over instantaneous swaps for exactly this reason. **A tile that silently swaps from running-green to blocked-red with no transient is genuinely at risk of being invisible.** The transient, not the final static difference, is what defeats change blindness. This is the strongest single argument for recommendation #4.
- **Habituation is real and documented.** The closest hard evidence is clinical alarm fatigue: 72–99% of ICU monitor alarms are non-actionable, staff meet one every ~4 minutes, and they measurably desensitise (multiple 2021–2022 reviews). Kim & Wogalter (2009) showed visual-warning noticeability decreases across exposures and *dishabituates* when the format changes. Countermeasures: onset-only one-shot transients rather than infinite loops; decay to a static-but-distinct marker; stepwise escalation only if unacknowledged; and never fire the attention animation for something non-actionable.
- **Flicker rate — hard numbers.** WCAG 2.3.1 (A) and 2.3.2 (AAA) cap **three flashes per second**. Photosensitive-seizure risk spans **3–60 Hz with peak sensitivity at 15–20 Hz**. The calm "breathing" band is roughly **1.5–4 s per cycle (≈0.25–0.7 Hz)** — note this is design convention synthesised across sources, not a specified figure. The existing `pulse 2.2s` (0.45 Hz) sits correctly in that band, and the `breathe 2.6s` proposed below does too. Nothing here approaches 3 Hz.
- **Calm technology gives the design vocabulary.** Weiser & Brown (*The Coming Age of Calm Technology*, PARC 1996): *"Calm technology engages both the center and the periphery of our attention, and in fact moves back and forth between the two."* Amber Case's principles add "require the smallest possible amount of attention" and "make use of the periphery." Pousman & Stasko (*A Taxonomy of Ambient Information Systems*, AVI 2006) define **Notification Level** as a first-class design axis. The actionable version for this board: place each of the six states deliberately on the periphery↔centre axis, rather than picking colours per state and hoping. Today `blocked` is the only state with any claim on the centre, and `waiting` — equally actionable — has none.
- **Caveat on the practitioner literature.** There is no rigorous peer-reviewed 2024–2026 work on glanceable observability UI specifically. Grafana's kiosk mode only hides chrome; Datadog's TV-mode guidance amounts to "limit component count for legibility at distance." Directional only.

**Now the defect.** The file already reasons correctly about this. L637–640:

> *"THE GLANCE LAYER. A 4px rib is 0.8mm wide on this display: at 650mm that is 4 arcmin, below what peripheral vision resolves when you look over from the 27". Give blocked and running real AREA — a tinted face is ~3.5° x 1.5°, two orders of magnitude more detectable than a hairline."*

That analysis is right, and it is why `blocked` got a 13% tinted face. **But the only animation on the board is still confined to the rib the same comment calls too small to see:**

```
L288  .bubble[data-state="blocked"]::before{animation:pulse 2.2s ease-in-out infinite}
L289  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
```

So the single most effective peripheral channel (motion) is applied to the single element the author identified as sub-threshold for peripheral vision. Motion belongs on the **tile face**, which has the area.

Two further gaps:
- **`waiting` has no motion at all.** It is the state that means *a session has stopped and is asking you for input* — the most actionable thing on the board — and it is visually quieter than `blocked`.
- **The pulse is infinite**, so it habituates away over a working day, and it conveys no information about *when* the block happened. A block 3 seconds old and one 40 minutes old look identical.

**Recommendation — a two-stage attract: loud transient on onset, calm presence after.**

Two hard constraints shape the implementation:

1. **The sustained animation must be compositor-only.** This board runs unattended for days. Animating `background-color`, `box-shadow` or `filter` in an infinite loop forces a repaint *every frame, forever*, on every blocked tile — measurable thermal and battery cost on a passively-cooled Air. Only `opacity` and `transform` are composited without repaint. So the breathing must be an **opacity fade on a dedicated overlay element**, not a colour animation on the tile.
2. **It cannot use `.bubble::after`.** `signal` (L904) and `cardstock` (L1132, L1141, L1142) already own that pseudo-element. Add one real child instead — one extra span in `tile()`.

```js
// L2921, in tile() — add the overlay as the first child so it paints under the text
return '<button class="bubble" data-id="'+esc(s.id)+'" data-state="'+esc(s.state)+'"'
  + ' style="--rib:var(--'+s.state+')" title="…">'
  + '<i class="halo" aria-hidden="true"></i>'          // ← new
  + '<span class="nm">'+esc(s.name)+'</span>'
  /* …unchanged… */
```
```css
/* The overlay: a tinted face that costs nothing until it is animated.
   `.bubble` is already position:relative / overflow:hidden / display:flex (L274-280),
   so an absolutely-positioned child is free and does not disturb the
   `margin-top:auto` that pins .foot to the bottom.
   Stacking matters: .halo is a real element and therefore paints ABOVE the
   ::before rib at equal z-index, so the rib has to be lifted explicitly. */
.bubble > .halo{
  position:absolute; inset:0; pointer-events:none; z-index:0; opacity:0;
  background: color-mix(in oklab, var(--rib) 26%, transparent);
}
.bubble::before{ z-index:2; }                       /* rib stays on top of the halo */
.bubble > .nm, .bubble > .gist, .bubble > .foot{ position:relative; z-index:1; }

/* 1. PRESENCE — the steady state breathes on the tile FACE, not the rib,
      and only for the two states that actually want you.
      0.38Hz, shallow, opacity-only => composited, no repaint. */
@keyframes breathe{ 0%,100%{opacity:.34} 50%{opacity:.88} }
.bubble[data-state="blocked"] > .halo,
.bubble[data-state="waiting"] > .halo{
  animation: breathe 2.6s ease-in-out infinite;
  will-change: opacity;
}
.bubble[data-state="blocked"]::before{ animation:none; }   /* retire the L288 rib pulse */

/* 2. ONSET — a one-shot transient, fired by a JS class on a real state diff.
      ~900ms, non-looping, so it cannot habituate. transform+opacity only. */
@keyframes arrive{
  0%  { opacity:0;   transform:scale(.94); }
  22% { opacity:1;   transform:scale(1.015); }
  100%{ opacity:.34; transform:scale(1); }
}
.bubble.just-changed > .halo{
  animation: arrive .9s linear(0, .62 16%, .98 32%, 1 44%, .55 70%, .34) 1;
}

/* 3. ESCALATION — stale blocks grow in AMPLITUDE and AREA, never in rate.
      (The periphery cannot discriminate rate anyway; it detects onset.) */
.bubble[data-state="blocked"][data-stale="1"] > .halo{ animation-duration:3.2s;
  background: color-mix(in oklab, var(--rib) 34%, transparent); }
.bubble[data-state="blocked"][data-stale="2"]{
  outline:1px solid color-mix(in oklab, var(--blocked) 55%, transparent);
  outline-offset:2px;
}
.bubble[data-state="blocked"][data-stale="2"] > .halo{ animation-duration:3.8s;
  background: color-mix(in oklab, var(--rib) 42%, transparent); }

@media (prefers-reduced-motion: reduce){
  .bubble > .halo{ animation:none !important; }
  /* keep the INFORMATION, drop only the motion */
  .bubble[data-state="blocked"] > .halo,
  .bubble[data-state="waiting"] > .halo{ opacity:.62; }
}
```
```js
// in render(), after paintBoard(d) — one-shot, onset only
changed.forEach(id => {
  const el = board.querySelector(`.bubble[data-id="${CSS.escape(id)}"]`);
  if(!el) return;
  el.classList.add('just-changed');
  el.addEventListener('animationend', () => el.classList.remove('just-changed'), {once:true});
});
```

Three properties worth noting, each traceable to a finding above:
- **Escalation is by amplitude and area, never by rate** — because the periphery cannot discriminate flicker rate, only onset. It stays at 0.26–0.38 Hz throughout, an order of magnitude below the 3 Hz WCAG ceiling and two below the 15–20 Hz seizure peak.
- **The onset transient is one-shot and diff-driven**, so the 5-second age refresh (C.1) cannot retrigger it, and it cannot habituate the way an infinite loop does.
- **`prefers-reduced-motion` keeps the information** — the halo goes to a static `opacity:.62`, a *stronger* tint than the animated resting state, rather than disappearing. That matches the 2025 accessible-animation guidance: don't delete a cue that carries meaning, make it static.

**`@starting-style` / `linear()` / entry animation** (`@starting-style` + `transition-behavior: allow-discrete`, both Chrome 117, Baseline Aug 2024; `linear()` Chrome 113, Baseline widely available). `linear()` is the right way to get a spring here — there is **no native `spring()` keyword**, it remains an unresolved CSSWG proposal (issue #280); generators like `linear-easing-generator.netlify.app` convert spring physics to `linear()` stops. **But do not use `@starting-style` for tile entry in this file** — `board.innerHTML = …` recreates every tile on every rebuild, so `@starting-style` would animate the entire board every 5 seconds. Use the `.just-changed` class above, which is diff-driven. This is the trap worth stating loudly.

### C.5 Should theme switching be animated?

Yes, and cheaply — `setTheme` (L3176) currently flips `data-theme` and 30 custom properties repaint in one frame, which is a jarring full-screen snap on a fullscreen board.

There are two real options and they trade off against each other. **The choice is forced by the fact that this board will, after recommendation #3, almost always have something animating on it.**

**Option A — document view transition as a pure crossfade.** Compositor-cheap (it snapshots the old painted page and dissolves to the new one; no per-property work at all). **But the snapshot is static**, so anything mid-animation during the swap produces a visible artifact — the breathing halo would freeze in the outgoing snapshot and jump in the incoming one. With #3 in place that is the normal case, not an edge case.

**Option B — register the colour tokens with `@property` and transition them.** Artifact-free, because nothing is snapshotted. The global-registration gotcha from C.3 does **not** block this: the restriction is on *re-registering the same name*, not on setting different values per theme. Register once, globally, and each theme's `:root[data-theme=…]` block keeps declaring plain values as it does today. The cost is a full-tree style recalculation for the duration of the transition, which on a ~60-tile board feeding 13 `color-mix()` sites is not obviously free and should be measured. Note also that `--grain` (image/gradient list) and `--sigil` (string) cannot be registered as interpolable types and will snap regardless.

**My recommendation: Option A with a two-line mitigation** — suppress the sustained animation for the duration of the swap, which removes the only thing the snapshot can tear. It keeps the cheap compositor path and avoids the style-recalc unknown.

```css
/* kill the only moving thing while the crossfade runs */
html.theme-swapping .bubble > .halo{ animation: none; }
```
```js
document.documentElement.classList.add('theme-swapping');
const t = document.startViewTransition({ update: apply, types: ['theme'] });
t.finished.catch(()=>{}).finally(() =>
  document.documentElement.classList.remove('theme-swapping'));
```

The full call, with the reduced-motion and capability guards:

```js
function setTheme(name){
  const moved = document.documentElement.dataset.theme !== name;
  const apply = () => { /* …existing body of setTheme… */ };
  if(!moved || !document.startViewTransition ||
     matchMedia('(prefers-reduced-motion: reduce)').matches) return apply();
  document.startViewTransition({ update: apply, types: ['theme'] });
}
```
```css
html:active-view-transition-type(theme)::view-transition-old(root),
html:active-view-transition-type(theme)::view-transition-new(root){
  animation-duration: .34s; animation-timing-function: ease;
}
```
This is the one place the **document**-scoped call is correct (the whole page is changing), and it is also the one place where the fixed-overlay z-index bug is harmless, because everything crossfades together. `types` (Chrome 121) keeps the theme crossfade stylable separately from the board's tile transitions.

A `filter`/`opacity` veil over `.wrap` is the crude fallback if a transition proves too heavy, but it is strictly worse — it dims rather than dissolves.

One more reason the theme swap is the right place to spend a view transition: it is an **infrequent, user-initiated** event, so its cost is irrelevant to the steady-state performance envelope. That is the opposite of the tile transitions in #4, where frequency is the whole risk.

### C.6 Other media features

`prefers-contrast: more` is the natural hook for the B.3 marginal cases — bump `--faint` toward `--dim` and drop the tile tints, in one unscoped block, instead of hand-tuning 13 palettes for a case that rarely applies. With the `color-mix` derivation from C.3 in place this is a two-line override:

```css
@media (prefers-contrast: more){
  :root{ --dim: var(--ink); --faint: color-mix(in oklab, var(--ink) 78%, var(--cell)); }
}
```

I could **not** pin exact Chrome version numbers for either `prefers-contrast` or `prefers-reduced-transparency` (research returned conflicting signals on the latter — Chrome's own blog says 118+, a platform-status page says experimental). Check caniuse at implementation time and treat both as progressive enhancement, not load-bearing. Neither is on the critical path for anything in section D.

---

## D. Ranked recommendations

Effort: **S** ≈ under 15 min, **M** ≈ an hour, **L** ≈ half a day plus visual iteration.

### The five highest-payoff items — full detail above, snippets inline

| # | What | Where | Kind | Effort | Payoff |
|---|---|---|---|---|---|
| 1 | **Invert the letterpress `text-shadow` for the 3 light themes that never got the antidote.** 15 selectors × 3 themes currently paint a 50%-black drop shadow under dark text on cream. Replace the `paper`-only override with a `--letterpress` token. Snippet in **B.1**. | L509–525 | **fix** | **S** | **Highest.** Single worst legibility defect; affects every small label on 3 of 13 themes; one rule |
| 2 | **Define `--waiting` in `cardstock`, `chequer`, `ochre`.** All three inherit console's `#ff8c68` → the most urgent state renders at **1.88:1** (ochre) and **2.06:1** (cardstock). Snippet + dev guard in **B.2**. | L982, L1000, L1018 | **fix** | **S** | **Highest.** 3 lines; turns an unreadable urgent state legible |
| 3 | **Move the motion from the rib to the tile face, add `waiting`, make onset one-shot, escalate by amplitude.** The file's own comment (L637–640) says the rib is below peripheral resolution, yet the rib is the only animated thing on the board. Uses a new `.halo` child (not `::after` — `signal` and `cardstock` own that) and animates **opacity only**, so it stays compositor-side on a board that runs for days. Full CSS+JS in **C.4**. | L288–290, L2921, L2858 | **add** | **M** | **Highest.** This is the dashboard's core purpose — noticing a block from 1 m — and it is currently encoded in the weakest available channel. Change-blindness research (Rensink 1997) says the silent swap may be missed outright |
| 4 | **Scoped view transitions on the board, diff-driven.** `board.startViewTransition()` (Chrome 147) with `view-transition-name` assigned only to changed tiles; kills the root crossfade; defeats change blindness on state changes. Full snippet + `stateDiff()` in **C.1/C.2**. Profile GPU memory over an hour — the one unverified risk. | L2858–2905 | **add** | **M** | Very high — tiles reflow and restate instead of snapping; also the prerequisite for #3 firing correctly |
| 5 | **Encode state by rib width + pattern, not hue alone.** `cardstock` `blocked`/`done` are ΔE **0.001** apart under deuteranopia; 5 of 13 themes have `--glow:0` so the 7px `.dot` is purely hue-coded. Snippet in **B.4**. | L179–183, L641, L673 | **fix** | **S** | Very high — makes six states separable with no colour vision *and* in the periphery, for everyone |

### Everything else

| # | What | Where | Kind | Effort | Payoff |
|---|---|---|---|---|---|
| 6 | `--shadow`/`--shade` token; retire 6 literal `#000` shadows on `.player`, `.crate`, `.panel`, `.sheet`, `.wrap::after`, `.bubble:hover`. Snippet in **B.5** | L282, 325, 385, 431, 526, 557, 1817 | fix | S | High — light themes stop wearing dark-ground shadows |
| 7 | Animate theme switching as a root view-transition crossfade, **with the `.theme-swapping` guard** that suppresses the #3 halo for the duration (a static snapshot tears against anything mid-animation). Snippet in **C.5** | L3176 | add | S | High — most-visible polish per line changed; infrequent event so cost is irrelevant |
| 8 | Self-host 5 WOFF2 faces (Cinzel, IM Fell English SC, Silkscreen, Rajdhani, Archivo) via the **existing** `VENDOR` allowlist; 10 of 13 themes currently run on their fallback face. See **A.3** | `dashboard.py` L226–228 + `@font-face` | add | M | High — 4 themes jump an identity tier; licences are OFL |
| 9 | Raise `--blocked` lightness in `vellum`/`hoarstone` (2.77/2.95:1) and darken `ochre --done` (2.87:1) | L1397, L1416, L1018 | fix | S | Medium-high — 3 remaining state-word contrast failures |
| 10 | Add `--ink-rail`/`--faint-rail` to the contract; collapse ochre's 4 hardcoded `#fff1d2` patches; protects `aperture` (3.37:1) and `paper` (3.85:1). See **B.3** | L243–261, L1317, L1360 | fix | M | Medium-high — closes the one structural hole in the contract |
| 11 | **console** (the default, 8 rules): graticule on `.wrap::before`. See **A.2** | L681–692 | add | S | Medium-high — best identity ratio in the file, on the most-seen theme |
| 12 | Derive `--dim`/`--faint` as `color-mix(in oklab, var(--ink) N%, var(--cell))` defaults, still overridable per theme. Mixing toward the *surface* self-corrects for light and dark with no branch. See **C.3** | L16–32 | add | M | Medium — buys the contrast invariant without losing hand-tuning; 2 lines |
| 13 | **chequer** (22 rules, named for a pattern it never draws): chequerboard `conic-gradient` on `.hrail` + 2×2 Bayer dither on headers. See **A.2** | L1000–1280 | add | M | Medium — largest identity gap vs. distinctiveness of subject |
| 14 | **miami86**: chromatic aberration on `.bubble .nm` (technique already used by `cyber` at L712) | L776–960 | add | S | Medium |
| 15 | `aperture .chip` still carries the 30%-black bevel inset on a near-white ground | L807–813 | fix | S | Medium-low |
| 16 | **cyber**: halation `drop-shadow` on active ribs | L694–712 | add | S | Medium-low — also strengthens the glance layer |
| 17 | **earth**: asymmetric organic `border-radius` on `.bubble`; **neutral**: restore a faint `.wrap::after` vignette; **paper**: red margin rule + ruled `.bubbles`; **aperture**: hazard stripe on `.lane`; **signal**: stencil numerals; **cardstock**: foil tilt on `.bubble.sel` | per **A.2** | add | S each | Medium-low — proportionate upgrades, 1–3 rules each |
| 18 | Use `prefers-contrast: more` for the marginal contrast cases instead of per-theme tuning. See **C.6** | new block | add | S | Low-medium |
| 19 | Light-theme pass for `.sheet` (terminal, L1817) — no theme treats it at all | L1817 | fix | M | Deferred — new surface, let the terminal settle first |

---

## What I could not verify

- **GPU memory / compositing cost per `view-transition-name`, and long-run stability of native view transitions.** No primary source publishes per-element figures, and no multi-hour/thousands-of-cycles leak study exists. For a board with days of uptime this is the one real unknown in recommendation #4. Profile in DevTools (GPU + Memory) for an hour before committing. The diff-gating in my snippet is the mitigation.
- **The claim that `box-shadow`/`filter` forces a full-snapshot repaint during a view transition.** Widely repeated, no primary source found. Unresolved.
- **The cost of Option B in C.5** (registering ~20 colour tokens with `@property` and transitioning them): a full-tree style recalc for ~340 ms on a 60-tile board feeding 13 `color-mix()` sites. I did not measure it. That is why I recommend Option A with the animation-suppression mitigation instead.
- **Exact Chrome versions for `prefers-contrast` and `prefers-reduced-transparency`** — conflicting or absent sources. Not load-bearing for any recommendation.
- **The "calm pulse" frequency band (~1.5–4 s/cycle).** This is a synthesis across converging design-convention sources, **not a specified or peer-reviewed figure.** The *hard* limits are well sourced (WCAG 3 flashes/s; 15–20 Hz seizure peak) and everything I propose sits far below both, so the risk of being wrong here is aesthetic, not safety.
- **"Decay-to-static" and stepwise escalation as a named pattern.** Inferred from the alarm-fatigue and habituation literature rather than taken from one citable HCI paper. Sound, but synthesis.
- There is **no peer-reviewed 2024–2026 literature on glanceable observability/NOC UI specifically.** The dashboard-practice citations (Grafana kiosk, Datadog TV mode) are practitioner consensus and thin. The perception and calm-technology citations are solid; the "how dashboards should do it" layer is not.
- **Appearance.** This is a static audit. I did not load `http://localhost:8787` or screenshot any theme, so every aesthetic judgement in §A is inferred from CSS and the authors' own comments, not from seeing the board. The contrast and ΔE numbers are computed and trustworthy; the identity rankings are reasoned and should be sanity-checked by eye.
- **Contrast model.** WCAG 2.x relative luminance, which is known to over-rate light-on-dark legibility. APCA would likely flag a few more of the dark themes' `--faint` tiers. I used WCAG 2.x because that is what the ~4.5/~3.0 thresholds in the brief refer to.
- **Font availability** reflects *this* Mac at audit time, verified against on-disk font files in the three standard directories. `SF Mono` shows no file but is supplied via `ui-monospace`, so it is not a gap.
