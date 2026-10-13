/* The Iris orb: glowing core, rotating glyph rings and little "data collectors" flying in and out.
   window.NX = { busy, speaking, kick() }  -> the app sets busy / speaking; kick() makes the orb flare (new data). */
(function () {
  if (window.NX && window.NX.cosmic) return;          // the COSMIC orb (orb3d.js) is running instead
  const stage = document.getElementById('stage'), cv = document.getElementById('fx'), g = cv.getContext('2d');
  const NX = window.NX = { busy: false, speaking: false, amp: 0, _kick: 0, kick(n) { this._kick = Math.min(.9, this._kick + (n || .3)); } };
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const C = 300, TAU = Math.PI * 2, R_ORB = 84;
  let K = 1, T = 0, last = performance.now(), nextAt = 0;
  const rnd = (a, b) => a + Math.random() * (b - a), pick = s => s[Math.random() * s.length | 0];
  const polar = (a, r) => [C + r * Math.cos(a), C + r * Math.sin(a)];
  const HEX = '0123456789ABCDEF', BIN = '01', RUNE = 'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓ0123456789:.=*+<>|';
  const FONT = "'Cascadia Mono',Consolas,'MS Gothic',monospace";
  let hue = [62, 224, 255];
  const col = a => `rgba(${hue[0] | 0},${hue[1] | 0},${hue[2] | 0},${a.toFixed(3)})`;
  const warm = a => `rgba(255,246,224,${a.toFixed(3)})`;

  function fit() {
    const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    cv.width = Math.max(1, Math.round(r.width * dpr)); cv.height = Math.max(1, Math.round(r.height * dpr));
    K = dpr * (r.width / 600 || 1);
  }
  new ResizeObserver(fit).observe(cv); fit();

  function ring(r, size, set, base, w) {
    const n = Math.round(TAU * r / (size * 1.1)), ch = [];
    for (let i = 0; i < n; i++) ch.push(i % 5 === 4 && set === HEX ? ' ' : pick(set));
    return { r, size, set, base, w, n, ch, rot: Math.random() * TAU };
  }
  const rings = [ring(273, 8, HEX, .55, -.10), ring(235, 9, RUNE, .5, .13), ring(211, 6.4, BIN, .4, -.17)];
  const arcs = Array.from({ length: 9 }, (_, i) => ({ a: i * TAU / 9 + rnd(-.1, .1), len: rnd(.18, .55) }));
  const links = []; let spin = 0;

  const state = () => NX.busy ? 'think' : NX.speaking ? 'speak' : 'idle';
  const RATE = { idle: 1.1, speak: 3, think: 7 };
  function spawn() {
    if (links.length > 26) return;
    const a = rnd(0, TAU), rt = pick([211, 235, 260, 273]);
    links.push({ a, rt, bend: rnd(-70, 70), t: 0, dur: rnd(.5, 1.3) * (state() === 'think' ? .6 : 1), back: false, trail: [], bits: 2 + (Math.random() * 4 | 0) });
  }
  function leg(L, u) {
    const x0 = C + R_ORB * Math.cos(L.a), y0 = C + R_ORB * Math.sin(L.a), x2 = C + L.rt * Math.cos(L.a), y2 = C + L.rt * Math.sin(L.a), v = 1 - u;
    const mx = (x0 + x2) / 2 + Math.cos(L.a + Math.PI / 2) * L.bend, my = (y0 + y2) / 2 + Math.sin(L.a + Math.PI / 2) * L.bend;
    return [v * v * x0 + 2 * v * u * mx + u * u * x2, v * v * y0 + 2 * v * u * my + u * u * y2];
  }
  function dot(x, y, r, a) {
    const gr = g.createRadialGradient(x, y, 0, x, y, r * 3.4);
    gr.addColorStop(0, warm(a)); gr.addColorStop(.4, col(a * .5)); gr.addColorStop(1, col(0));
    g.fillStyle = gr; g.beginPath(); g.arc(x, y, r * 3.4, 0, TAU); g.fill();
  }

  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000) * (reduce ? .25 : 1); last = now; T += dt; spin += dt;
    const cs = getComputedStyle(document.body).getPropertyValue('--c').trim();
    if (/^#[0-9a-f]{6}$/i.test(cs)) { const n = parseInt(cs.slice(1), 16), t = [n >> 16, n >> 8 & 255, n & 255]; for (let i = 0; i < 3; i++) hue[i] += (t[i] - hue[i]) * Math.min(1, dt * 6); }

    // orb pulse: heartbeat while idle, faster while thinking, ripple while speaking
    const beat = p => { const ph = (T * 1000 % p) / p, e = (c, w) => Math.exp(-Math.pow((ph - c) / w, 2)); return e(.10, .045) + .6 * e(.30, .05); };
    const base = NX.busy ? .06 + .5 * beat(950) : NX.speaking ? .2 + .12 * Math.sin(T * 12) * Math.sin(T * 4) : .04 + .22 * beat(1900);
    NX._kick *= .92; NX.amp = Math.min(1, Math.max(0, base + NX._kick));
    stage.style.setProperty('--amp', NX.amp.toFixed(3));

    g.setTransform(K, 0, 0, K, 0, 0); g.clearRect(0, 0, 600, 600); g.globalCompositeOperation = 'lighter';

    // soft light around the core
    const halo = 120 + NX.amp * 90, hg = g.createRadialGradient(C, C, 20, C, C, halo);
    hg.addColorStop(0, `rgba(255,252,242,${(.16 + NX.amp * .22).toFixed(3)})`); hg.addColorStop(1, 'rgba(255,240,215,0)');
    g.fillStyle = hg; g.beginPath(); g.arc(C, C, halo, 0, TAU); g.fill();

    // dotted orbits + segmented arcs
    g.lineWidth = 1; g.setLineDash([1, 7]); g.lineDashOffset = -spin * 8; g.strokeStyle = col(.4);
    g.beginPath(); g.arc(C, C, 125, 0, TAU); g.stroke(); g.lineDashOffset = spin * 11; g.beginPath(); g.arc(C, C, 150, 0, TAU); g.stroke(); g.setLineDash([]);
    g.strokeStyle = col(.55); g.lineWidth = 3;
    for (const s of arcs) { g.beginPath(); g.arc(C, C, 188, s.a + spin * .21, s.a + spin * .21 + s.len); g.stroke(); }
    g.lineWidth = 1; g.strokeStyle = col(.3);
    for (let i = 0; i < 120; i++) { const a = i * TAU / 120 + spin * .026, p = polar(a, 292), q = polar(a, i % 5 ? 297 : 303); g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke(); }

    // glyph rings
    g.textAlign = 'center'; g.textBaseline = 'middle';
    for (const R of rings) {
      R.rot += R.w * dt; g.font = R.size + 'px ' + FONT;
      for (let j = 0; j < 3; j++) { const i = Math.random() * R.n | 0; if (R.ch[i] !== ' ') R.ch[i] = pick(R.set); }
      for (let i = 0; i < R.n; i++) {
        if (R.ch[i] === ' ') continue;
        const th = R.rot + i * TAU / R.n, c = Math.cos(th), s = Math.sin(th);
        g.fillStyle = col(R.base * (.78 + .22 * Math.sin(T * 2.6 + i * 1.9)));
        g.setTransform(-K * s, K * c, -K * c, -K * s, K * (C + R.r * c), K * (C + R.r * s));
        g.fillText(R.ch[i], 0, 0);
      }
    }
    g.setTransform(K, 0, 0, K, 0, 0);

    // collectors
    nextAt -= dt;
    if (nextAt <= 0) { spawn(); nextAt = -Math.log(1 - Math.random()) / RATE[state()]; }
    for (let i = links.length - 1; i >= 0; i--) {
      const L = links[i]; L.t += dt / L.dur;
      const u = L.back ? 1 - Math.pow(Math.min(1, L.t), 1.8) : 1 - Math.pow(1 - Math.min(1, L.t), 2.2);
      const p = leg(L, u); L.trail.push([p[0], p[1], T]); while (L.trail.length > 2 && T - L.trail[0][2] > .4) L.trail.shift();
      g.lineCap = 'round';
      for (let k = 1; k < L.trail.length; k++) {
        const age = (T - L.trail[k][2]) / .4; if (age >= 1) continue; const al = Math.pow(1 - age, 1.6);
        g.strokeStyle = L.back ? warm(al * .9) : col(al * .9); g.lineWidth = 1 + 2.2 * al;
        g.beginPath(); g.moveTo(L.trail[k - 1][0], L.trail[k - 1][1]); g.lineTo(L.trail[k][0], L.trail[k][1]); g.stroke();
      }
      dot(p[0], p[1], 3.2, 1);
      if (L.t >= 1) { if (!L.back) { L.back = true; L.t = 0; L.dur *= 1.2; } else { NX.kick(.05 + .02 * L.bits); links.splice(i, 1); } }
    }
    g.globalCompositeOperation = 'source-over';
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
