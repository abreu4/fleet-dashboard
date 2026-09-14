/* fleet-sounds.js — per-theme UI sound packs for the FLEET dashboard.
 *
 * A classic script (no modules, no assets, no network). Everything is
 * synthesised with the Web Audio API the moment it is needed, so the board
 * stays a single self-contained local app.
 *
 * Wiring: it attaches itself by event delegation on `document`, so ui.html
 * needs nothing beyond the <script> tag:
 *
 *   click  on button / select / .bubble   -> 'tap' (controls) or 'tile' (session tiles)
 *   change on select#theme                -> 'switch', played in the NEW theme's pack
 *   fleet:theme  CustomEvent {theme}      -> switch the active pack (+ 'switch')
 *   fleet:state  CustomEvent {id,from,to} -> 'alert' when to is blocked|waiting,
 *                                            'done'  when to is done, else silence
 *   <html data-theme> mutations           -> fallback pack switching
 *
 * Feel: punchy game-menu UI (Halo / CoD / CS / Portal / Hotline Miami menus).
 * Every tap is a physical hit — a hard noise transient, a short pitched body
 * and a sub-thump — through a per-pack saturator (soft clip, hard clip or
 * bit-crush stairs) and a master compressor. Per theme the *flavour* changes
 * (8-bit for cardstock, wood and harp for vellum, ...) while the baseline
 * stays snappy. Still short: taps <= 60 ms, alerts <= 400 ms, done <= 500 ms.
 *
 * The user is respected: muted by default, state persisted in localStorage
 * (fleet.sound.muted / fleet.sound.volume), AudioContext created lazily on the
 * first click (browsers demand a gesture), alerts rate-limited to one per
 * 1.5 s so a burst of state changes is one sound, not a drum roll.
 *
 * Public surface: window.FleetSounds = { play, pack, packs, volume, mute, muted }.
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Settings                                                            */
  /* ------------------------------------------------------------------ */

  var LS_MUTED = 'fleet.sound.muted';
  var LS_VOLUME = 'fleet.sound.volume';
  var LS_CLICKS = 'fleet.sound.clicks';           // tap / tile / switch on your own actions
  var LS_PACK   = 'fleet.sound.pack';             // 'theme' = follow the theme, else a pack key
  var LS_SOFT   = 'fleet.sound.soft';             // cap drive + lowpass the master
  var DEFAULT_VOLUME = 0.6;
  // What this board is for is ambient awareness, so the defaults are the quiet
  // ones: a sound when something needs you (blocked / waiting) or finishes, and
  // nothing for your own clicks unless you ask. 'soft' caps every pack's drive
  // and rolls off the top end, because a square wave through a hard clipper is
  // an alarm, not a cue.
  var VOLUME_STEPS = [0.35, 0.6, 0.85, 1];  // shift+click on the toggle cycles these
  var MAKEUP = 1.8;                         // after the compressor: 1.0 is loud on laptop speakers
  var SOFT_HZ = 5600;                       // soft mode roll-off; 3.4k dulled the chimes to nothing
  var ALERT_GAP_MS = 1500;                  // never more than one alert per 1.5 s
  var DONE_GAP_MS = 800;
  var MAX_VOICES = 24;                      // concurrent oscillators/buffers, hard cap
  var FALLBACK_PACK = 'quiet';
  var CONTROL_SEL = 'button, select, .bubble';

  function readLS(key, fallback) {
    try {
      var v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch (e) { return fallback; }
  }
  function writeLS(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode etc. */ }
  }
  function clamp(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }

  var muted = readLS(LS_MUTED, false) === true;             // default: on (a sound when you're needed)
  var volume = clamp(Number(readLS(LS_VOLUME, DEFAULT_VOLUME)) || DEFAULT_VOLUME, 0, 1);
  var clicks = readLS(LS_CLICKS, false) === true;             // default: off
  var fixedPack = readLS(LS_PACK, 'theme') || 'theme';
  var soft = readLS(LS_SOFT, true) !== false;                 // default: on

  /* ------------------------------------------------------------------ */
  /* Audio graph                                                         */
  /* ------------------------------------------------------------------ */
  /* voice -> packBus -> packShaper -> comp -> master -> destination
   *                                \-> convolver -> wet -> comp     (packs with `verb`)
   */

  var ctx = null, master = null, comp = null;
  // Sound can be logically on while WebKit is still waiting for a gesture.
  // Track whether a cue has really reached the graph so the speaker's first
  // click activates/tests it instead of silently switching it off.
  var audible = false;
  var pendingCue = null;
  var packBus = null, packShaper = null, verbNode = null, wetGain = null;
  var noiseBuf = null;
  var activeVoices = 0;
  var curveCache = {}, impulseCache = {}, pluckCache = {};
  var tilt = null;

  function ensureCtx() {
    if (ctx) {
      // WebKit may report `interrupted` as well as `suspended` after a display
      // sleep, output-device change, or an automatic dashboard reload. Both
      // states need an explicit resume before the next synthesized cue.
      if (ctx.state !== 'running' && ctx.state !== 'closed') {
        try { ctx.resume(); } catch (e) { /* a normal browser may still require a gesture */ }
      }
      return ctx;
    }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try { ctx = new AC({ latencyHint: 'interactive' }); } catch (e) { return null; }
    // A context that was healthy before display sleep or an output-device
    // change can become suspended/interrupted later. Do not keep claiming it
    // is audible: that made the speaker's recovery click mute the board.
    ctx.onstatechange = function () {
      if (ctx.state !== 'running') audible = false;
      label();
      if (ctx.state === 'running' && pendingCue && !muted) {
        var layers = pendingCue;
        pendingCue = null;
        trigger(layers);
      }
    };

    master = ctx.createGain();
    master.gain.value = muted ? 0 : volume;
    comp = ctx.createDynamicsCompressor();
    // Fast, firm: catches the stacked transients without pumping the tails.
    comp.threshold.value = -16;
    comp.knee.value = 10;
    comp.ratio.value = 5;
    comp.attack.value = 0.001;
    comp.release.value = 0.1;
    // Soft mode: nothing above ~3.4kHz reaches the speaker. Every pack keeps
    // its character below that; what goes is the glassy edge that made the
    // clicks fatiguing on a board you sit beside all day.
    tilt = ctx.createBiquadFilter();
    tilt.type = 'lowpass'; tilt.Q.value = 0.5;
    tilt.frequency.value = soft ? SOFT_HZ : 20000;
    var makeup = ctx.createGain();
    makeup.gain.value = MAKEUP;
    comp.connect(tilt);
    tilt.connect(makeup);
    makeup.connect(master);
    master.connect(ctx.destination);

    // 1 s of white noise, shared by every noise burst (random start offset).
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    var d = noiseBuf.getChannelData(0);
    for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;

    buildPackChain();
    return ctx;
  }

  // Each pack owns its saturator and (optionally) a tiny synthetic room.
  function buildPackChain() {
    if (!ctx) return;
    var nodes = [packBus, packShaper, verbNode, wetGain];
    for (var i = 0; i < nodes.length; i++) { if (nodes[i]) { try { nodes[i].disconnect(); } catch (e) { /* already */ } } }
    verbNode = wetGain = null;

    var p = PACKS[packKey];
    packBus = ctx.createGain();
    packShaper = ctx.createWaveShaper();
    var drive = p.drive || { type: 'soft', k: 1.5 };
    if (soft) drive = { type: 'soft', k: Math.min(drive.k || 1.5, 1.8) };
    packShaper.curve = shapeCurve(drive);
    packShaper.oversample = '2x';
    packBus.connect(packShaper);
    packShaper.connect(comp);

    if (p.verb) {
      verbNode = ctx.createConvolver();
      verbNode.buffer = impulse(p.verb.time);
      wetGain = ctx.createGain();
      wetGain.gain.value = p.verb.mix;
      packShaper.connect(verbNode);
      verbNode.connect(wetGain);
      wetGain.connect(comp);
    }
  }

  /* Saturation curves. 'soft' = tanh drive, 'hard' = brickwall clip,
   * 'crush' = amplitude stairs (k bits) on top of a soft drive — the cheap
   * bit-crusher, no ScriptProcessor needed. */
  function shapeCurve(spec) {
    var key = spec.type + ':' + spec.k;
    if (curveCache[key]) return curveCache[key];
    var n = 4096, c = new Float32Array(n), k = spec.k;
    for (var i = 0; i < n; i++) {
      var x = (i / (n - 1)) * 2 - 1, y;
      if (spec.type === 'hard') y = clamp(k * x, -1, 1);
      else if (spec.type === 'crush') {
        var steps = Math.pow(2, k) / 2;
        y = Math.round((Math.tanh(2 * x) / Math.tanh(2)) * steps) / steps;
      } else y = Math.tanh(k * x) / Math.tanh(k);
      c[i] = y;
    }
    return (curveCache[key] = c);
  }

  // Exponentially decaying noise = a small, dark room. Enough for a "hint".
  function impulse(time) {
    var key = String(time);
    if (impulseCache[key]) return impulseCache[key];
    var sr = ctx.sampleRate, len = Math.max(1, Math.floor(sr * time));
    var buf = ctx.createBuffer(2, len, sr);
    for (var ch = 0; ch < 2; ch++) {
      var d = buf.getChannelData(ch);
      for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    }
    return (impulseCache[key] = buf);
  }

  // Karplus-Strong rendered offline into a buffer (a DelayNode feedback loop
  // cannot go below one render quantum, which rules out anything above ~350 Hz).
  function pluckBuffer(freq, dur, damp) {
    var key = freq + ':' + dur + ':' + damp;
    if (pluckCache[key]) return pluckCache[key];
    var sr = ctx.sampleRate, n = Math.floor(sr * dur), N = Math.max(2, Math.round(sr / freq));
    var buf = ctx.createBuffer(1, n, sr), out = buf.getChannelData(0);
    var ring = new Float32Array(N), i;
    for (i = 0; i < N; i++) ring[i] = Math.random() * 2 - 1;
    var idx = 0;
    for (i = 0; i < n; i++) {
      var cur = ring[idx], nxt = ring[(idx + 1) % N];
      out[i] = cur;
      ring[idx] = (cur + nxt) * 0.5 * damp;
      idx = (idx + 1) % N;
    }
    return (pluckCache[key] = buf);
  }

  /* ------------------------------------------------------------------ */
  /* Synth primitives                                                    */
  /* ------------------------------------------------------------------ */
  /* A sound is an array of layers. Every layer shares:
   *   at    start offset (s)          a   attack (s)     d   decay (s)
   *   g     peak gain                 hard true = flat hold then cut (chip envelopes)
   *   lp/lp2, hp, bp+q  filters (lp2 = sweep target for the lowpass over the layer)
   * and by kind:
   *   osc    w (wave) f (Hz) f2 (glide target) slide (s) det (cents) path [[Hz, at], ...]
   *   noise  (filters only)
   *   fm     f ratio idx idx2 (mod index start/end) w mw
   *   pluck  f damp (0.9-0.999)
   */

  function envelope(param, t, L) {
    var a = L.a === undefined ? 0.001 : L.a, d = L.d === undefined ? 0.05 : L.d;
    var peak = L.g === undefined ? 0.5 : L.g;
    param.setValueAtTime(0, t);
    param.linearRampToValueAtTime(peak, t + a);
    if (L.hard) {
      param.setValueAtTime(peak, t + a + d);
      param.linearRampToValueAtTime(0, t + a + d + 0.003);
      return t + a + d + 0.004;
    }
    param.exponentialRampToValueAtTime(Math.max(peak * 0.002, 1e-4), t + a + d);
    return t + a + d + 0.01;
  }

  function filters(t, L, end) {
    var chain = [], f;
    if (L.hp) { f = ctx.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = L.hp; f.Q.value = 0.7; chain.push(f); }
    if (L.lp) {
      f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.Q.value = L.q || 0.9;
      f.frequency.setValueAtTime(L.lp, t);
      if (L.lp2) f.frequency.exponentialRampToValueAtTime(L.lp2, end);
      chain.push(f);
    }
    if (L.bp) {
      f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = L.bp; f.Q.value = L.q || 4;
      chain.push(f);
    }
    return chain;
  }

  // Wires src -> filters -> gain -> packBus, starts it, and keeps the voice
  // budget honest (the counter only moves once start() has succeeded).
  function route(src, t, L, offset) {
    var g = ctx.createGain();
    var end = envelope(g.gain, t, L);
    var chain = filters(t, L, end);
    var node = src;
    for (var i = 0; i < chain.length; i++) { node.connect(chain[i]); node = chain[i]; }
    node.connect(g);
    g.connect(packBus);
    if (offset !== undefined) src.start(t, offset); else src.start(t);
    src.stop(end + 0.02);
    activeVoices++;
    src.onended = function () { activeVoices--; try { g.disconnect(); } catch (e) { /* gone */ } };
    return end;
  }

  function playOsc(t, L) {
    var o = ctx.createOscillator();
    o.type = L.w || 'sine';
    o.frequency.setValueAtTime(L.f, t);
    if (L.det) o.detune.value = L.det;
    if (L.path) {
      for (var i = 0; i < L.path.length; i++) o.frequency.exponentialRampToValueAtTime(L.path[i][0], t + L.path[i][1]);
    } else if (L.f2) {
      var slide = L.slide || ((L.a || 0.001) + (L.d || 0.05));
      o.frequency.exponentialRampToValueAtTime(L.f2, t + slide);
    }
    route(o, t, L);
  }

  function playNoise(t, L) {
    var s = ctx.createBufferSource();
    s.buffer = noiseBuf;
    s.loop = true;
    s.loopStart = 0; s.loopEnd = noiseBuf.duration;
    route(s, t, L, Math.random() * 0.8);   // random offset: no two bursts identical
  }

  // Classic 2-op FM: modulator at f*ratio, depth idx*f Hz, sweeping idx -> idx2.
  function playFM(t, L) {
    var c = ctx.createOscillator(), m = ctx.createOscillator(), mg = ctx.createGain();
    c.type = L.w || 'sine'; m.type = L.mw || 'sine';
    c.frequency.setValueAtTime(L.f, t);
    if (L.f2) c.frequency.exponentialRampToValueAtTime(L.f2, t + (L.slide || (L.a || 0.001) + (L.d || 0.05)));
    m.frequency.value = L.f * (L.ratio || 2);
    var idx = L.idx === undefined ? 3 : L.idx, idx2 = L.idx2 === undefined ? 0.01 : L.idx2;
    mg.gain.setValueAtTime(Math.max(idx * L.f, 1e-3), t);
    mg.gain.exponentialRampToValueAtTime(Math.max(idx2 * L.f, 1e-3), t + (L.a || 0.001) + (L.d || 0.05));
    m.connect(mg); mg.connect(c.frequency);
    var end = route(c, t, L);
    m.start(t); m.stop(end + 0.02);
  }

  function playPluck(t, L) {
    var s = ctx.createBufferSource();
    s.buffer = pluckBuffer(L.f, (L.a || 0.001) + (L.d || 0.3) + 0.02, L.damp || 0.994);
    route(s, t, L);
  }

  var KIND = { osc: playOsc, noise: playNoise, fm: playFM, pluck: playPluck };

  function trigger(layers) {
    if (!ctx || !packBus) return;
    audible = true;
    label();
    var t0 = ctx.currentTime + 0.004;
    for (var i = 0; i < layers.length; i++) {
      if (activeVoices >= MAX_VOICES) break;
      var L = layers[i];
      try { KIND[L.k](t0 + (L.at || 0), L); } catch (e) { /* one bad layer never kills the sound */ }
    }
  }

  /* ------------------------------------------------------------------ */
  /* Layer factories — the vocabulary the pack tables are written in     */
  /* ------------------------------------------------------------------ */

  function merge(base, extra) {
    var o = {}, k;
    for (k in base) o[k] = base[k];
    if (extra) for (k in extra) o[k] = extra[k];
    return o;
  }
  var S  = function (w, f, o) { return merge({ k: 'osc', w: w, f: f }, o); };           // tone
  var N  = function (o)       { return merge({ k: 'noise' }, o); };                      // noise burst
  var FM = function (f, ratio, idx, o) { return merge({ k: 'fm', f: f, ratio: ratio, idx: idx }, o); };
  var PK = function (f, o)    { return merge({ k: 'pluck', f: f }, o); };
  var at = function (t, L)    { return merge(L, { at: (L.at || 0) + t }); };
  // Sequence: freqs -> layers spaced `step` apart, built by mk(freq, i).
  var seq = function (freqs, step, mk) {
    var out = [];
    for (var i = 0; i < freqs.length; i++) out.push(at(i * step, mk(freqs[i], i)));
    return out;
  };

  // The punch kit. Every pack's taps are built on these three.
  var click = function (o) { return N(merge({ hp: 2500, a: 0.0004, d: 0.009, g: 0.55 }, o)); };  // transient
  var thump = function (o) { return S('sine', 130, merge({ f2: 42, slide: 0.035, a: 0.0008, d: 0.045, g: 0.75 }, o)); };  // sub
  var body  = function (w, f, o) { return S(w, f, merge({ f2: f * 0.55, slide: 0.03, a: 0.001, d: 0.035, g: 0.4 }, o)); };  // pitched hit

  /* ------------------------------------------------------------------ */
  /* Packs                                                               */
  /* ------------------------------------------------------------------ */
  /* Each pack: drive (saturator), optional verb {time, mix}, and the five
   * sounds tap / tile / switch / alert / done as layer arrays. */

  var PACKS = {
    /* quiet -- the pack for someone who does not want a pack. Sine and triangle
     * only, short envelopes, a small room, no drive to speak of. The alert is a
     * two-note descending chime ("your move"), done is the same two notes the
     * other way up, and the UI cues are barely there. Fallback for every theme
     * without a voice of its own, and selectable for all of them. */
    quiet: {
      drive: { type: 'soft', k: 1.1 }, verb: { time: 0.22, mix: 0.16 },
      tap:    [click({ hp: 4000, g: 0.16, d: 0.006 })],
      tile:   [click({ hp: 3200, g: 0.18, d: 0.007 }), S('sine', 660, { a: 0.002, d: 0.06, g: 0.10 })],
      switch: [S('triangle', 523, { a: 0.004, d: 0.14, g: 0.16 }), at(0.11, S('triangle', 784, { a: 0.004, d: 0.18, g: 0.14 }))],
      alert:  [S('sine', 880, { a: 0.004, d: 0.22, g: 0.30 }), at(0.16, S('sine', 659, { a: 0.004, d: 0.30, g: 0.26 }))],
      done:   [S('triangle', 659, { a: 0.004, d: 0.18, g: 0.20 }), at(0.14, S('triangle', 880, { a: 0.004, d: 0.28, g: 0.18 }))]
    },

    /* Orbital command deck, cyan vector glass: clean sine ticks with a glass
     * transient, radar ping for alerts. */
    console: {
      drive: { type: 'hard', k: 8.5 }, verb: { time: 0.05, mix: 0.02 },
      tap:    [click({ hp: 3000, g: 0.9 }), thump({ f: 100, g: 0.8 })],
      tile:   [click({ hp: 2000, g: 0.9 }), thump({ f: 150, g: 0.9 })],
      switch: [click({ g: 1.0 }), thump({ f: 80, g: 1.0 }), N(0.02, 'white', { hp: 4000, d: 0.08, g: 0.4 })],
      alert:  [thump({ f: 160, g: 1.0 }), S('square', 900, { a: 0.01, d: 0.08, g: 0.3 }), at(0.12, S('square', 900, { a: 0.01, d: 0.08, g: 0.2 }))],
      done:   [click({ g: 1.0 }), thump({ f: 120, g: 1.0 }), S('square', 500, { a: 0.01, d: 0.15, g: 0.3 }), at(0.15, S('square', 1000, { a: 0.01, d: 0.2, g: 0.2 }))]
    },

    /* Cinestill neon film on wet asphalt: filtered saw blips, a hint of room,
     * a neon-tube buzz for alerts. */
    cyber: {
      drive: { type: 'soft', k: 2.4 }, verb: { time: 0.32, mix: 0.2 },
      tap:    [click({ hp: 3000, g: 0.45 }), S('sawtooth', 240, { f2: 110, slide: 0.04, lp: 2400, lp2: 350, a: 0.001, d: 0.045, g: 0.45 }), thump({ g: 0.6 })],
      tile:   [click({ hp: 2200, g: 0.4 }), S('sawtooth', 165, { f2: 80, slide: 0.05, lp: 1800, lp2: 300, a: 0.001, d: 0.055, g: 0.5 }), thump({ f: 150, g: 0.7 })],
      switch: [click({ g: 0.35 }), S('sawtooth', 110, { f2: 440, slide: 0.15, lp: 600, lp2: 3000, a: 0.003, d: 0.2, g: 0.35 }), thump({ g: 0.6 })],
      alert:  [thump({ f: 170, g: 0.7 }),
               S('sawtooth', 110, { det: -9, lp: 900, a: 0.003, d: 0.32, g: 0.28 }),
               S('sawtooth', 110, { det: 9, lp: 900, a: 0.003, d: 0.32, g: 0.28 }),
               S('square', 55, { lp: 400, a: 0.003, d: 0.28, g: 0.2 })],
      done:   [click({ g: 0.3 }), S('sawtooth', 330, { lp: 1600, a: 0.002, d: 0.16, g: 0.3 }),
               at(0.12, S('sawtooth', 495, { lp: 2600, lp2: 900, a: 0.002, d: 0.32, g: 0.3 })),
               at(0.12, S('sine', 990, { a: 0.002, d: 0.25, g: 0.12 }))]
    },

    /* Forest floor, wood and moss: woody knocks, a bird-ish chirp for done. */
    earth: {
      drive: { type: 'soft', k: 1.6 },
      tap:    [click({ hp: 1800, g: 0.4 }), N({ bp: 950, q: 7, a: 0.0006, d: 0.03, g: 0.9 }), thump({ f: 190, f2: 80, g: 0.7 })],
      tile:   [click({ hp: 1400, g: 0.35 }), N({ bp: 620, q: 7, a: 0.0006, d: 0.04, g: 1.0 }), thump({ f: 160, f2: 60, g: 0.8 })],
      switch: [N({ bp: 700, q: 6, a: 0.0006, d: 0.04, g: 0.9 }), thump({ g: 0.6 }),
               at(0.09, S('sine', 1500, { f2: 2400, slide: 0.05, a: 0.004, d: 0.09, g: 0.25 }))],
      alert:  [N({ bp: 800, q: 6, a: 0.0006, d: 0.04, g: 1.0 }), thump({ f: 150, g: 0.8 }),
               at(0.1, N({ bp: 800, q: 6, a: 0.0006, d: 0.04, g: 0.9 })), at(0.1, thump({ f: 150, g: 0.7 })),
               S('sine', 140, { a: 0.004, d: 0.3, g: 0.35 })],
      done:   [click({ g: 0.2 }), S('sine', 1800, { path: [[2700, 0.06], [2000, 0.12]], a: 0.004, d: 0.12, g: 0.3 }),
               at(0.16, S('sine', 2100, { path: [[3100, 0.07], [2400, 0.14]], a: 0.004, d: 0.14, g: 0.28 }))]
    },

    /* Graphite, disciplined: dry, short, near-silent — but still a hit. */
    neutral: {
      drive: { type: 'soft', k: 1.3 },
      tap:    [click({ hp: 3500, d: 0.007, g: 0.4 }), thump({ f: 110, d: 0.03, g: 0.45 })],
      tile:   [click({ hp: 2400, d: 0.009, g: 0.4 }), thump({ f: 130, d: 0.035, g: 0.5 })],
      switch: [click({ g: 0.35 }), S('sine', 660, { a: 0.002, d: 0.07, g: 0.22 }), thump({ g: 0.4 })],
      alert:  [thump({ f: 140, g: 0.5 }), S('sine', 660, { a: 0.003, d: 0.2, g: 0.32 })],
      done:   [click({ g: 0.2 }), S('sine', 880, { a: 0.003, d: 0.22, g: 0.28 })]
    },

    /* Editorial desk: paper-flick and pencil-tap noise, a typewriter ding for
     * done, carriage-return whoosh for alerts. */
    paper: {
      drive: { type: 'soft', k: 1.5 },
      tap:    [click({ hp: 5000, g: 0.4 }), N({ bp: 2600, q: 1.6, a: 0.0006, d: 0.02, g: 0.6 }), thump({ f: 120, g: 0.5 })],
      tile:   [click({ hp: 2600, g: 0.4 }), N({ bp: 1300, q: 3, a: 0.0006, d: 0.016, g: 0.8 }), thump({ f: 150, g: 0.65 })],
      switch: [N({ bp: 2800, q: 1.4, a: 0.001, d: 0.05, g: 0.5 }), at(0.07, N({ bp: 1300, q: 3, a: 0.0006, d: 0.016, g: 0.8 })), at(0.07, thump({ g: 0.5 }))],
      alert:  [N({ lp: 3200, lp2: 500, a: 0.004, d: 0.22, g: 0.5 }), at(0.22, N({ bp: 1400, q: 3, a: 0.0006, d: 0.02, g: 0.9 })), at(0.22, thump({ f: 150, g: 0.7 }))],
      done:   [click({ hp: 6000, g: 0.4 }), S('sine', 2200, { a: 0.001, d: 0.4, g: 0.3 }), S('sine', 6070, { a: 0.001, d: 0.18, g: 0.12 }),
               thump({ f: 120, g: 0.4 })]
    },

    /* Hotline Miami, 80s synthwave / VHS: chunky FM stabs, sawtooth pitch drops,
     * a bit of tape crush. */
    miami86: {
      drive: { type: 'crush', k: 7 }, verb: { time: 0.22, mix: 0.14 },
      tap:    [click({ hp: 2500, g: 0.5 }), S('sawtooth', 460, { f2: 200, slide: 0.045, lp: 3200, a: 0.001, d: 0.045, g: 0.45 }), thump({ g: 0.7 })],
      tile:   [click({ hp: 2000, g: 0.45 }), S('sawtooth', 330, { f2: 140, slide: 0.05, lp: 2600, a: 0.001, d: 0.05, g: 0.5 }), thump({ f: 150, g: 0.8 })],
      switch: [click({ g: 0.4 }), S('sawtooth', 880, { f2: 110, slide: 0.2, lp: 3500, lp2: 500, a: 0.002, d: 0.22, g: 0.4 }), thump({ g: 0.6 })],
      alert:  [thump({ f: 170, g: 0.8 }), FM(220, 2, 6, { w: 'square', idx2: 0.3, a: 0.002, d: 0.3, g: 0.35 }),
               S('sawtooth', 220, { f2: 55, slide: 0.32, lp: 2000, a: 0.002, d: 0.32, g: 0.28 })],
      done:   [click({ g: 0.3 }), FM(261.6, 2, 5, { idx2: 0.4, a: 0.002, d: 0.26, g: 0.28, w: 'sawtooth', lp: 2800 }),
               FM(392, 2, 5, { idx2: 0.4, a: 0.002, d: 0.26, g: 0.24, w: 'sawtooth', lp: 2800 }),
               at(0.18, S('sawtooth', 523, { f2: 261, slide: 0.25, lp: 2200, a: 0.002, d: 0.26, g: 0.25 })),
               thump({ f: 150, g: 0.7 })]
    },

    /* Cyberpunk 2077, acid-yellow brutalist: hard square data blips, glitchy
     * stutter for alerts, brickwall clip. */
    signal: {
      drive: { type: 'hard', k: 2.6 },
      tap:    [click({ hp: 3000, g: 0.5 }), S('square', 1300, { a: 0.0005, d: 0.012, g: 0.3, hard: true }),
               at(0.016, S('square', 650, { a: 0.0005, d: 0.01, g: 0.3, hard: true })), thump({ g: 0.7 })],
      tile:   [click({ hp: 2400, g: 0.45 }), S('square', 820, { a: 0.0005, d: 0.014, g: 0.32, hard: true }),
               at(0.02, S('square', 410, { a: 0.0005, d: 0.014, g: 0.3, hard: true })), thump({ f: 150, g: 0.8 })],
      switch: [click({ g: 0.4 }), S('square', 200, { f2: 2400, slide: 0.1, lp: 4000, a: 0.001, d: 0.12, g: 0.3 }),
               at(0.1, N({ hp: 1500, a: 0.0005, d: 0.03, g: 0.4 })), thump({ g: 0.6 })],
      alert:  seq([1100, 550, 1100, 550, 1650, 825], 0.04, function (f) { return S('square', f, { a: 0.0005, d: 0.022, g: 0.3, hard: true }); })
              .concat([thump({ f: 170, g: 0.8 }), at(0.24, N({ hp: 2000, a: 0.0005, d: 0.06, g: 0.5 })), at(0.24, thump({ f: 140, g: 0.7 }))]),
      done:   seq([660, 880, 1320], 0.05, function (f) { return S('square', f, { a: 0.0005, d: 0.035, g: 0.3, hard: true }); })
              .concat([at(0.15, S('square', 1320, { a: 0.0005, d: 0.18, g: 0.3 })), at(0.15, S('square', 1320, { det: 8, a: 0.0005, d: 0.18, g: 0.15 })), thump({ g: 0.6 })])
    },

    /* Portal test chamber: sterile lab tones, a two-note portal-ish chirp for
     * alerts, descending clean triad for done. Original synthesis. */
    aperture: {
      drive: { type: 'soft', k: 1.4 }, verb: { time: 0.26, mix: 0.18 },
      tap:    [click({ hp: 5000, g: 0.4 }), S('sine', 1000, { a: 0.001, d: 0.03, g: 0.35 }), S('sine', 1500, { a: 0.001, d: 0.02, g: 0.2 }), thump({ g: 0.55 })],
      tile:   [click({ hp: 3500, g: 0.4 }), S('sine', 750, { a: 0.001, d: 0.04, g: 0.4 }), S('sine', 1125, { a: 0.001, d: 0.025, g: 0.2 }), thump({ f: 150, g: 0.65 })],
      switch: [click({ g: 0.35 }), S('sine', 400, { f2: 1600, slide: 0.14, a: 0.002, d: 0.16, g: 0.3 }), S('triangle', 800, { f2: 3200, slide: 0.14, a: 0.002, d: 0.16, g: 0.12 }), thump({ g: 0.55 })],
      alert:  [thump({ f: 160, g: 0.7 }), S('sine', 600, { f2: 1200, slide: 0.04, a: 0.002, d: 0.12, g: 0.4 }),
               at(0.09, S('sine', 900, { f2: 1800, slide: 0.05, a: 0.002, d: 0.16, g: 0.4 })),
               at(0.09, S('triangle', 1800, { f2: 3600, slide: 0.05, a: 0.002, d: 0.12, g: 0.12 }))],
      done:   seq([1320, 990, 660], 0.09, function (f, i) { return S('sine', f, { a: 0.002, d: 0.12 + i * 0.08, g: 0.32 }); })
              .concat([click({ g: 0.25 }), thump({ f: 120, g: 0.45 })])
    },

    /* Scriptorium and parchment (Lord of the Rings): low wooden knocks, a
     * plucked harp (Karplus-Strong) for done, a stone hall behind it. */
    vellum: {
      drive: { type: 'soft', k: 1.5 }, verb: { time: 0.34, mix: 0.22 },
      tap:    [click({ hp: 1600, g: 0.35 }), N({ bp: 520, q: 5, a: 0.0006, d: 0.03, g: 0.9 }), thump({ f: 120, f2: 65, g: 0.7 })],
      tile:   [click({ hp: 1200, g: 0.3 }), N({ bp: 380, q: 5, a: 0.0006, d: 0.04, g: 1.0 }), thump({ f: 100, f2: 50, g: 0.8 })],
      switch: [N({ bp: 450, q: 5, a: 0.0006, d: 0.035, g: 0.9 }), thump({ g: 0.6 }), at(0.06, PK(392, { d: 0.22, g: 0.5, damp: 0.992 }))],
      alert:  [N({ bp: 500, q: 5, a: 0.0006, d: 0.035, g: 1.0 }), thump({ f: 130, f2: 55, g: 0.8 }),
               at(0.11, N({ bp: 500, q: 5, a: 0.0006, d: 0.035, g: 0.9 })), at(0.11, thump({ f: 130, f2: 55, g: 0.7 })),
               at(0.2, PK(330, { d: 0.18, g: 0.5, damp: 0.99 }))],
      done:   seq([523.3, 659.3, 784], 0.08, function (f, i) { return PK(f, { d: 0.3 - i * 0.02, g: 0.5, damp: 0.995 }); })
              .concat([click({ hp: 1500, g: 0.2 })])
    },

    /* Cold stone and iron (Skyrim): stone-on-stone thud, an iron ring for
     * alerts, a scrape when the world changes. */
    hoarstone: {
      drive: { type: 'soft', k: 2.0 }, verb: { time: 0.28, mix: 0.14 },
      tap:    [click({ hp: 2000, g: 0.5 }), N({ lp: 420, a: 0.0005, d: 0.028, g: 1.1 }), thump({ f: 95, f2: 40, d: 0.055, g: 0.85 })],
      tile:   [click({ hp: 1500, g: 0.45 }), N({ lp: 320, a: 0.0005, d: 0.035, g: 1.2 }), thump({ f: 80, f2: 36, d: 0.06, g: 0.95 })],
      switch: [N({ lp: 400, a: 0.0005, d: 0.03, g: 1.0 }), thump({ f: 90, f2: 40, g: 0.8 }),
               at(0.04, N({ bp: 900, q: 2, a: 0.01, d: 0.16, g: 0.35, lp: 1400, lp2: 300 }))],
      alert:  [click({ g: 0.5 }), thump({ f: 110, f2: 45, g: 0.8 }),
               S('sine', 880, { a: 0.0008, d: 0.38, g: 0.32 }), S('sine', 1320, { a: 0.0008, d: 0.3, g: 0.2 }),
               S('sine', 2120, { a: 0.0008, d: 0.22, g: 0.14 }), S('triangle', 440, { a: 0.0008, d: 0.3, g: 0.14 })],
      done:   [N({ lp: 400, a: 0.0005, d: 0.03, g: 0.9 }), thump({ f: 90, f2: 40, g: 0.8 }),
               at(0.05, S('sine', 660, { a: 0.0008, d: 0.4, g: 0.3 })), at(0.05, S('sine', 990, { a: 0.0008, d: 0.3, g: 0.16 })),
               at(0.05, S('sine', 1590, { a: 0.0008, d: 0.2, g: 0.1 }))]
    },

    /* Game Boy (Pokémon): 4-bit square and triangle, hard envelopes, the
     * classic confirm arpeggio for done. Crushed to 4 bits. */
    cardstock: {
      drive: { type: 'crush', k: 4 },
      tap:    [S('square', 1046, { a: 0.0005, d: 0.014, g: 0.35, hard: true }), at(0.016, S('square', 1568, { a: 0.0005, d: 0.014, g: 0.35, hard: true })),
               S('triangle', 130, { f2: 50, slide: 0.03, a: 0.0005, d: 0.035, g: 0.7, hard: true })],
      tile:   [S('triangle', 523, { a: 0.0005, d: 0.025, g: 0.6, hard: true }), at(0.028, S('square', 784, { a: 0.0005, d: 0.014, g: 0.3, hard: true })),
               S('triangle', 110, { f2: 45, slide: 0.03, a: 0.0005, d: 0.035, g: 0.7, hard: true })],
      switch: seq([200, 400, 800, 1600], 0.035, function (f) { return S('square', f, { a: 0.0005, d: 0.03, g: 0.3, hard: true }); })
              .concat([S('triangle', 120, { f2: 50, slide: 0.03, a: 0.0005, d: 0.04, g: 0.6, hard: true })]),
      alert:  seq([440, 880, 440, 880, 440, 880], 0.045, function (f) { return S('square', f, { a: 0.0005, d: 0.035, g: 0.32, hard: true }); })
              .concat([S('triangle', 110, { a: 0.0005, d: 0.25, g: 0.4, hard: true })]),
      done:   seq([523.3, 659.3, 784, 1046.5], 0.045, function (f, i) { return S('square', f, { a: 0.0005, d: i === 3 ? 0.24 : 0.04, g: 0.32, hard: true }); })
              .concat([at(0.18, S('triangle', 261.6, { a: 0.0005, d: 0.24, g: 0.5, hard: true }))])
    },

    /* Genesis YM2612 (Sonic): bright FM pings, ring/coin-style rising two-note
     * for done. */
    chequer: {
      drive: { type: 'soft', k: 1.8 },
      tap:    [click({ hp: 4000, g: 0.4 }), FM(1320, 3.5, 3, { a: 0.0005, d: 0.02, g: 0.35 }), thump({ g: 0.6 })],
      tile:   [click({ hp: 3000, g: 0.4 }), FM(990, 3.5, 3.5, { a: 0.0005, d: 0.028, g: 0.4 }), thump({ f: 150, g: 0.7 })],
      switch: [click({ g: 0.35 }), FM(440, 2, 4, { f2: 1760, slide: 0.12, idx2: 0.5, a: 0.001, d: 0.14, g: 0.35 }), thump({ g: 0.6 })],
      alert:  [thump({ f: 160, g: 0.7 }), FM(880, 7, 5, { idx2: 1, a: 0.001, d: 0.15, g: 0.35 }),
               at(0.13, FM(880, 7, 5, { idx2: 1, a: 0.001, d: 0.15, g: 0.3 })), at(0.26, FM(660, 7, 4, { idx2: 0.5, a: 0.001, d: 0.12, g: 0.25 }))],
      done:   [click({ g: 0.25 }), FM(988, 2, 2, { idx2: 0.2, a: 0.001, d: 0.07, g: 0.35 }),
               at(0.07, FM(1319, 2, 2.5, { idx2: 0.1, a: 0.001, d: 0.36, g: 0.35 })), at(0.07, S('sine', 2638, { a: 0.001, d: 0.2, g: 0.08 }))]
    },

    /* Painted stencils and big band (Team Fortress 2): brassy short stabs, a
     * cartoon boing for alerts. */
    ochre: {
      drive: { type: 'soft', k: 2.4 },
      tap:    [click({ hp: 2500, g: 0.45 }), S('sawtooth', 330, { det: -7, lp: 2600, lp2: 900, a: 0.002, d: 0.04, g: 0.3 }),
               S('square', 330, { det: 7, lp: 2200, lp2: 800, a: 0.002, d: 0.04, g: 0.2 }), thump({ g: 0.6 })],
      tile:   [click({ hp: 2000, g: 0.4 }), S('sawtooth', 220, { det: -7, lp: 2200, lp2: 700, a: 0.002, d: 0.05, g: 0.32 }),
               S('square', 220, { det: 7, lp: 1900, lp2: 600, a: 0.002, d: 0.05, g: 0.2 }), thump({ f: 150, g: 0.7 })],
      switch: [click({ g: 0.35 }), S('sawtooth', 262, { lp: 900, lp2: 3200, a: 0.03, d: 0.1, g: 0.32 }), S('sawtooth', 330, { lp: 900, lp2: 3200, a: 0.03, d: 0.1, g: 0.26 }), thump({ g: 0.5 })],
      alert:  [thump({ f: 150, g: 0.7 }), S('sine', 300, { path: [[110, 0.08], [230, 0.16], [140, 0.24], [190, 0.32]], a: 0.002, d: 0.34, g: 0.4 }),
               S('sawtooth', 300, { path: [[110, 0.08], [230, 0.16], [140, 0.24], [190, 0.32]], lp: 1200, a: 0.002, d: 0.3, g: 0.14 })],
      done:   [click({ g: 0.3 }), S('sawtooth', 349, { lp: 2400, lp2: 1000, a: 0.004, d: 0.14, g: 0.28 }), S('sawtooth', 440, { lp: 2400, lp2: 1000, a: 0.004, d: 0.14, g: 0.24 }),
               at(0.14, S('sawtooth', 440, { lp: 2800, lp2: 900, a: 0.004, d: 0.3, g: 0.28 })), at(0.14, S('sawtooth', 554, { lp: 2800, lp2: 900, a: 0.004, d: 0.3, g: 0.24 })),
               at(0.14, thump({ f: 140, g: 0.6 }))]
    },

    /* Two-colour print job and acid jazz (Persona 5): sharp paper snips, a jazz
     * chord stab for done. */
    offcut: {
      drive: { type: 'soft', k: 1.9 },
      tap:    [click({ hp: 4500, d: 0.006, g: 0.55 }), at(0.011, N({ bp: 2600, q: 2.5, a: 0.0004, d: 0.012, g: 0.6 })), thump({ g: 0.6 })],
      tile:   [click({ hp: 3200, d: 0.007, g: 0.5 }), at(0.013, N({ bp: 1600, q: 2.5, a: 0.0004, d: 0.014, g: 0.7 })), thump({ f: 150, g: 0.7 })],
      switch: [click({ hp: 4500, g: 0.5 }), at(0.012, N({ bp: 2600, q: 2.5, a: 0.0004, d: 0.012, g: 0.6 })), thump({ g: 0.5 }),
               at(0.06, S('sawtooth', 261.6, { lp: 1800, a: 0.002, d: 0.1, g: 0.18 })), at(0.06, S('sawtooth', 493.9, { lp: 1800, a: 0.002, d: 0.1, g: 0.14 }))],
      alert:  seq([0, 0, 0], 0.07, function () { return click({ hp: 4000, d: 0.007, g: 0.55 }); })
              .concat(seq([0, 0, 0], 0.07, function () { return at(0.012, N({ bp: 2400, q: 2.5, a: 0.0004, d: 0.014, g: 0.6 })); }))
              .concat([thump({ f: 160, g: 0.7 }), at(0.2, S('sawtooth', 110, { lp: 1200, lp2: 400, a: 0.002, d: 0.18, g: 0.3 })), at(0.2, thump({ f: 140, g: 0.6 }))]),
      done:   [click({ g: 0.35 }), thump({ f: 140, g: 0.6 }),
               S('sawtooth', 261.6, { lp: 2200, lp2: 700, a: 0.003, d: 0.24, g: 0.2 }), S('sawtooth', 329.6, { lp: 2200, lp2: 700, a: 0.003, d: 0.24, g: 0.16 }),
               S('sawtooth', 392, { lp: 2200, lp2: 700, a: 0.003, d: 0.24, g: 0.16 }), S('sawtooth', 493.9, { lp: 2200, lp2: 700, a: 0.003, d: 0.24, g: 0.14 }),
               S('triangle', 587.3, { lp: 2600, a: 0.003, d: 0.24, g: 0.14 })]
    },

    /* Stone by torchlight (Minecraft): block-place thuds, a soft xylophone
     * note for done. */
    cobble: {
      drive: { type: 'soft', k: 1.8 },
      tap:    [click({ hp: 1800, g: 0.45 }), N({ lp: 320, a: 0.0005, d: 0.035, g: 1.1 }), thump({ f: 75, f2: 36, d: 0.05, g: 0.9 })],
      tile:   [click({ hp: 1400, g: 0.4 }), N({ lp: 260, a: 0.0005, d: 0.045, g: 1.2 }), thump({ f: 65, f2: 32, d: 0.055, g: 1.0 })],
      switch: [N({ lp: 320, a: 0.0005, d: 0.035, g: 1.0 }), thump({ f: 75, f2: 36, g: 0.8 }),
               at(0.06, S('sine', 1046, { a: 0.001, d: 0.14, g: 0.3 })), at(0.06, S('sine', 2890, { a: 0.001, d: 0.06, g: 0.1 }))],
      alert:  [N({ lp: 350, a: 0.0005, d: 0.035, g: 1.1 }), thump({ f: 80, f2: 38, g: 0.9 }),
               at(0.12, N({ lp: 350, a: 0.0005, d: 0.035, g: 1.0 })), at(0.12, thump({ f: 80, f2: 38, g: 0.8 })),
               at(0.24, N({ hp: 600, lp: 2400, a: 0.0005, d: 0.1, g: 0.5 })), at(0.24, thump({ f: 100, f2: 40, g: 0.7 }))],
      done:   [click({ hp: 3000, g: 0.3 }), S('sine', 1046, { a: 0.001, d: 0.32, g: 0.32 }), S('sine', 2890, { a: 0.001, d: 0.1, g: 0.12 }),
               at(0.1, S('sine', 1568, { a: 0.001, d: 0.3, g: 0.26 })), at(0.1, S('sine', 4330, { a: 0.001, d: 0.08, g: 0.08 })), thump({ f: 90, g: 0.5 })]
    },

    /* Black terminal, phosphor mint (matrix): hard square chip-tones an octave
     * apart with a dry click, the way a serial terminal beeps. The alert is a
     * trace call -- a fast rising trill that breaks off -- and done is a
     * three-note descending resolve that lands on the octave. Dry: there is
     * no room, only the tube. */
    matrix: {
      drive: { type: 'hard', k: 4.5 }, verb: { time: 0.08, mix: 0.04 },
      tap:    [click({ hp: 3500, g: 0.5 }), S('square', 1480, { a: 0.0005, d: 0.014, g: 0.26, hard: true }), thump({ f: 110, g: 0.6 })],
      tile:   [click({ hp: 2600, g: 0.45 }), S('square', 740, { a: 0.0005, d: 0.018, g: 0.28, hard: true }),
               at(0.022, S('square', 1480, { a: 0.0005, d: 0.012, g: 0.2, hard: true })), thump({ f: 150, g: 0.7 })],
      switch: seq([370, 740, 1480, 2960], 0.028, function (f) { return S('square', f, { a: 0.0005, d: 0.024, g: 0.24, hard: true }); })
              .concat([click({ g: 0.35 }), thump({ g: 0.5 })]),
      alert:  seq([880, 1109, 1319, 1760, 2217], 0.05, function (f) { return S('square', f, { a: 0.0005, d: 0.04, g: 0.28, hard: true }); })
              .concat([thump({ f: 160, g: 0.7 }), at(0.3, N({ hp: 3000, a: 0.0005, d: 0.05, g: 0.45 })), at(0.3, thump({ f: 130, g: 0.6 }))]),
      done:   seq([1760, 1319, 880], 0.07, function (f, i) { return S('square', f, { a: 0.0005, d: i === 2 ? 0.22 : 0.05, g: 0.26, hard: i !== 2 }); })
              .concat([click({ g: 0.3 }), thump({ g: 0.5 }), at(0.14, S('sine', 1760, { a: 0.001, d: 0.2, g: 0.1 }))])
    },

    /* Wrist terminal, yellow-green tube (fallout): a warmer, rounder chip
     * voice -- triangle-heavy, low-passed, a soft thump under every press
     * like a real key on a heavy case. The alert is a Geiger burst, three
     * dry noise ticks quickening into a low two-tone. Done is a rising
     * fourth with a tube hum under it. */
    pipboy: {
      drive: { type: 'soft', k: 2.8 }, verb: { time: 0.14, mix: 0.08 },
      tap:    [click({ hp: 2400, g: 0.45 }), S('triangle', 660, { lp: 2600, a: 0.001, d: 0.03, g: 0.3 }), thump({ f: 95, g: 0.75 })],
      tile:   [click({ hp: 1900, g: 0.42 }), S('triangle', 495, { lp: 2200, a: 0.001, d: 0.04, g: 0.32 }),
               at(0.03, S('triangle', 660, { lp: 2200, a: 0.001, d: 0.03, g: 0.2 })), thump({ f: 140, g: 0.85 })],
      switch: [click({ g: 0.35 }), S('triangle', 330, { f2: 990, slide: 0.12, lp: 2400, a: 0.002, d: 0.16, g: 0.28 }),
               at(0.05, N({ hp: 1200, lp: 4000, a: 0.0005, d: 0.02, g: 0.3 })), thump({ g: 0.6 })],
      alert:  seq([0, 0, 0, 0], 0.045, function () { return N({ bp: 3200, q: 3, a: 0.0004, d: 0.012, g: 0.75 }); })
              .concat([thump({ f: 150, g: 0.6 }),
                       at(0.2, S('triangle', 392, { lp: 1800, a: 0.003, d: 0.2, g: 0.3 })), at(0.2, S('square', 196, { lp: 700, a: 0.003, d: 0.2, g: 0.12 })),
                       at(0.36, S('triangle', 330, { lp: 1800, a: 0.003, d: 0.26, g: 0.3 })), at(0.36, S('square', 165, { lp: 700, a: 0.003, d: 0.26, g: 0.12 }))]),
      done:   [click({ g: 0.3 }), thump({ f: 120, g: 0.6 }),
               S('triangle', 523.3, { lp: 2400, a: 0.002, d: 0.14, g: 0.3 }),
               at(0.12, S('triangle', 698.5, { lp: 2600, a: 0.002, d: 0.3, g: 0.3 })), at(0.12, S('sine', 1397, { a: 0.002, d: 0.18, g: 0.08 })),
               at(0.12, S('sawtooth', 87.3, { lp: 320, a: 0.01, d: 0.34, g: 0.12 }))]
    },

    /* Void indigo and bone white (Hollow Knight): glassy, echoing, minor-key;
     * a distant soft bell for done. */
    chitin: {
      drive: { type: 'soft', k: 1.3 }, verb: { time: 0.5, mix: 0.4 },
      tap:    [click({ hp: 5000, g: 0.4 }), S('sine', 1760, { a: 0.0008, d: 0.03, g: 0.3 }), S('sine', 2640, { a: 0.0008, d: 0.02, g: 0.14 }), thump({ g: 0.55 })],
      tile:   [click({ hp: 3500, g: 0.4 }), S('sine', 1318, { a: 0.0008, d: 0.04, g: 0.34 }), S('sine', 1977, { a: 0.0008, d: 0.025, g: 0.14 }), thump({ f: 150, g: 0.65 })],
      switch: seq([1760, 1318, 1046], 0.06, function (f) { return S('sine', f, { a: 0.001, d: 0.09, g: 0.28 }); })
              .concat([click({ g: 0.3 }), thump({ g: 0.5 })]),
      alert:  [thump({ f: 150, g: 0.7 }), S('sine', 880, { a: 0.001, d: 0.14, g: 0.36 }), S('sine', 1320, { a: 0.001, d: 0.1, g: 0.14 }),
               at(0.14, S('sine', 1046, { a: 0.001, d: 0.24, g: 0.36 })), at(0.14, S('sine', 1569, { a: 0.001, d: 0.16, g: 0.14 }))],
      done:   [click({ hp: 6000, g: 0.2 }), S('sine', 659, { a: 0.002, d: 0.46, g: 0.26 }), S('sine', 1318, { a: 0.002, d: 0.34, g: 0.12 }),
               S('sine', 1984, { a: 0.002, d: 0.24, g: 0.08 }), S('sine', 329.5, { a: 0.002, d: 0.4, g: 0.12 })]
    }
  };

  /* ------------------------------------------------------------------ */
  /* State                                                               */
  /* ------------------------------------------------------------------ */

  var packKey = FALLBACK_PACK;
  var announced = null;                         // last pack a 'switch' was played for
  var born = Date.now();                        // theme mutations right after load are not switches
  var lastAlert = 0, lastDone = 0;

  function resolvePack(key) {
    if (fixedPack !== 'theme' && PACKS.hasOwnProperty(fixedPack)) return fixedPack;
    return PACKS.hasOwnProperty(key) ? key : FALLBACK_PACK;
  }

  function play(name) {
    var p = PACKS[packKey], layers = p && p[name];
    if (!layers || muted || !ctx) return false;
    if (ctx.state !== 'running') {
      // Suspended/interrupted until playback is permitted: ask, and play this
      // same cue once resume completes rather than losing the notification.
      // Keep only the latest cue. A sleeping display may accumulate many
      // state changes; on wake we want one useful notification, not a queue.
      pendingCue = layers;
      try {
        var resumed = ctx.resume();
        var fired = false;
        var afterResume = function () {
          if (!fired && ctx.state === 'running') {
            fired = true;
            var queued = pendingCue;
            pendingCue = null;
            if (queued && !muted) trigger(queued);
          }
        };
        if (resumed && resumed.then) resumed.then(afterResume);
        // Older WebKit builds did not reliably return the resume promise even
        // when the context resumed. The guarded follow-up covers that path.
        setTimeout(afterResume, 80);
      } catch (e) { /* no */ }
      return false;
    }
    trigger(layers);
    return true;
  }

  function switchTo(key, announce) {
    key = resolvePack(key);
    var changed = key !== packKey;
    packKey = key;
    if (changed && ctx) buildPackChain();
    if (announce && key !== announced && Date.now() - born > 1200) {
      announced = key;
      if (clicks) play('switch');
    } else if (!announce) announced = key;
  }

  function setMuted(on) {
    muted = !!on;
    if (muted) pendingCue = null;
    writeLS(LS_MUTED, muted);
    if (master) master.gain.setTargetAtTime(muted ? 0 : volume, ctx.currentTime, 0.01);
    label();
  }
  function setVolume(v) {
    volume = clamp(Number(v) || 0, 0, 1);
    writeLS(LS_VOLUME, volume);
    if (master && !muted) master.gain.setTargetAtTime(volume, ctx.currentTime, 0.01);
    label();
  }
  function cycleVolume() {
    var i = 0;
    for (var j = 0; j < VOLUME_STEPS.length; j++) if (Math.abs(VOLUME_STEPS[j] - volume) < 0.01) i = j + 1;
    setVolume(VOLUME_STEPS[i % VOLUME_STEPS.length]);
  }

  /* ------------------------------------------------------------------ */
  /* The toggle button                                                   */
  /* ------------------------------------------------------------------ */

  var btn = null;
  function label() {
    if (!btn) return;
    btn.innerHTML = muted ? '🔇<span> off</span>' : '🔊<span> on</span>';
    btn.title = 'sound ' + (muted ? 'off' : 'on') + ' · volume ' + Math.round(volume * 100) + '%'
              + (!muted && !audible ? '\nclick: activate and test sound' : '\nclick: mute / unmute')
              + ' · shift+click: cycle volume · volume, pack and cues under \u22ef';
    btn.setAttribute('aria-pressed', muted ? 'false' : 'true');
  }
  function mount() {
    if (btn || document.getElementById('snd')) return true;
    var ctl = document.querySelector('.ctl');
    if (!ctl) return false;
    btn = document.createElement('button');
    btn.className = 'ghost';
    btn.id = 'snd';
    btn.addEventListener('click', function (e) {
      // Capture this before ensureCtx(): resume is asynchronous in WebKit.
      // Otherwise an interrupted context still looks "audible" here and the
      // recovery click takes the mute branch instead of testing the output.
      var needsActivation = !audible || !ctx || ctx.state !== 'running';
      ensureCtx();                                  // this IS the gesture the browser wants
      if (e.shiftKey) {
        cycleVolume();
        if (!muted) play('tap');
      } else if (!muted && needsActivation) {
        // After a page reload the saved state can say “on” while WebKit has
        // suspended the fresh AudioContext. Make this click an audible unlock;
        // once unlocked, subsequent clicks keep the normal mute behaviour.
        play('switch');
      } else {
        setMuted(!muted);
        if (!muted) play('switch');                 // the pack introduces itself
      }
    });
    ctl.appendChild(btn);
    label();
    return true;
  }
  // .ctl is static markup, but be patient in case the header renders late.
  function mountWhenReady() {
    if (mount()) return;
    var tries = 0, timer = setInterval(function () {
      if (mount() || ++tries > 40) clearInterval(timer);
    }, 500);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountWhenReady);
  else mountWhenReady();

  /* ------------------------------------------------------------------ */
  /* Delegated wiring                                                    */
  /* ------------------------------------------------------------------ */

  // Clicks: capture phase, so a handler that stops propagation still ticks.
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest(CONTROL_SEL) : null;
    if (!el || el.id === 'snd' || el.disabled) return;
    if (!ensureCtx() || muted || !clicks) return;   // create/resume on any gesture, even muted
    play(el.classList.contains('bubble') ? 'tile' : 'tap');
  }, true);

  // First gesture of any kind resumes a context that was created suspended.
  ['pointerdown', 'keydown', 'touchstart'].forEach(function (ev) {
    document.addEventListener(ev, function () {
      if (ctx && ctx.state !== 'running' && ctx.state !== 'closed') ensureCtx();
    }, true);
  });

  // Theme picker committed: announce in the NEW pack. (The data-theme observer
  // below usually gets there first while the picker previews; `announced`
  // keeps the two from playing twice for one change.)
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t && t.tagName === 'SELECT' && t.id === 'theme') switchTo(t.value, true);
  }, true);

  document.addEventListener('fleet:theme', function (e) {
    var d = e.detail || {};
    if (d.theme) switchTo(d.theme, true);
  });

  document.addEventListener('fleet:state', function (e) {
    var d = e.detail || {}, now = Date.now();
    if (d.to === 'blocked' || d.to === 'waiting') {
      if (now - lastAlert < ALERT_GAP_MS) return;    // coalesce the burst
      lastAlert = now;
      play('alert');
    } else if (d.to === 'done') {
      if (now - lastDone < DONE_GAP_MS) return;
      lastDone = now;
      play('done');
    }
  });

  // Fallback: follow <html data-theme> whichever way it was set.
  var root = document.documentElement;
  switchTo(root.getAttribute('data-theme'), false);
  if (window.MutationObserver) {
    new MutationObserver(function () { switchTo(root.getAttribute('data-theme'), true); })
      .observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  }

  // If the user left sounds on last time, warm the context up so the first
  // alert after a reload is not lost; the gesture listeners resume it.
  if (!muted) { try { ensureCtx(); } catch (e) { /* fine, lazy path */ } }

  /* ------------------------------------------------------------------ */
  /* Public API                                                          */
  /* ------------------------------------------------------------------ */

  window.FleetSounds = {
    /** Play one of tap / tile / switch / alert / done in the active pack. */
    play: function (name) { ensureCtx(); return play(name); },
    /** Get the active pack key, or switch to `themeKey` (unknown -> console). */
    pack: function (themeKey) { if (themeKey !== undefined) switchTo(themeKey, true); return packKey; },
    /** All pack keys. */
    packs: function () { return Object.keys(PACKS); },
    /** Get or set the master volume (0..1), persisted. */
    volume: function (v) { if (v !== undefined) setVolume(v); return volume; },
    /** Mute or unmute, persisted. */
    mute: function (on) { setMuted(on === undefined ? true : on); return muted; },
    muted: function () { return muted; },
    /** Current browser audio state, used by the settings/debug surface. */
    state: function () { return ctx ? ctx.state : 'uninitialized'; },
    /** UI click cues on/off (default off), persisted. */
    clicks: function (on) { if (on !== undefined) { clicks = !!on; writeLS(LS_CLICKS, clicks); } return clicks; },
    /** Pin one pack for every theme, or 'theme' to follow the theme. Persisted. */
    fixed: function (key) {
      if (key !== undefined) { fixedPack = (key === 'theme' || PACKS.hasOwnProperty(key)) ? key : 'theme'; writeLS(LS_PACK, fixedPack); switchTo(document.documentElement.getAttribute('data-theme'), false); }
      return fixedPack;
    },
    /** Soft mode: capped drive and a 5.6kHz roll-off (default on). Persisted. */
    soft: function (on) {
      if (on !== undefined) { soft = !!on; writeLS(LS_SOFT, soft); if (tilt) tilt.frequency.value = soft ? SOFT_HZ : 20000; if (ctx) buildPackChain(); }
      return soft;
    }
  };
})();
