/* COSMIC orb: a living "AI mind" made of three layers.
   1) WebGL shader: a plasma core with glowing veins, a tilted accretion disc and a drifting nebula (colours follow the theme).
   2) 2D canvas: a swarm of neural nodes joined by synapses with data packets, gyroscope rings, lightning from the core,
      shock waves and star dust, all in 3D and reacting to the mouse.
   3) State: idle = slow breathing, thinking = inhale + storm of packets and bolts, speaking = ripples, alert = flare.
   Same interface as the classic orb: window.NX = { busy, speaking, kick() }.  If WebGL is missing, orb.js (classic) takes over.
   Choose the style in the gear menu (ORB: COSMIC / CLASSIC). */
(function () {
  let want = 'cosmic'; try { want = localStorage.getItem('nx_orb') || 'cosmic' } catch (e) { /* ignore */ }
  const stage = document.getElementById('stage'), old = document.getElementById('fx');
  if (want !== 'cosmic' || !stage || !old) return;
  const gc = document.createElement('canvas'), oc = document.createElement('canvas');
  gc.id = 'fxg'; oc.id = 'fx2'; gc.setAttribute('aria-hidden', 'true'); oc.setAttribute('aria-hidden', 'true');
  const gl = gc.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'high-performance' });
  if (!gl) return;

  const VS = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FS = `precision highp float;
uniform vec2 uRes;uniform float uT,uAmp,uThink,uSpeak,uAlert,uKick;uniform vec3 uC1,uC2,uC3;uniform vec3 uTilt;
float hash(vec3 p){p=fract(p*0.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
            mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float a=.5,s=0.;for(int i=0;i<5;i++){s+=a*noise(p);p=p*2.03+vec3(1.7,9.2,3.1);a*=.5;}return s;}
void main(){
  vec2 p=(gl_FragCoord.xy/uRes-.5)*2.*1.4;float t=uT;
  float Rc=.347*(1.+uAmp*.10+uKick*.07);float r=length(p);vec3 col=vec3(0.);
  vec3 q=vec3(p*1.5,t*.05);
  float neb=fbm(q+fbm(q*1.3+t*.03)*1.5);
  neb=smoothstep(.38,.88,neb)*smoothstep(1.3,.2,r);
  col+=mix(uC2,uC3,fbm(q*.6+3.))*neb*(.20+.22*uAmp+.25*uThink);
  vec2 pr=vec2(cos(uTilt.x)*p.x+sin(uTilt.x)*p.y,-sin(uTilt.x)*p.x+cos(uTilt.x)*p.y);
  float d=max(r-Rc,0.);
  col+=(uC1*.9+vec3(.12))*exp(-d*7.)*(.34+.6*uAmp+.4*uKick);
  col+=uC3*exp(-d*2.4)*(.10+.08*uAmp);
  // polar jets: two beams of energy shooting out of the core, perpendicular to the disc
  float al_=abs(pr.y),la_=abs(pr.x);
  float jn=fbm(vec3(la_*6.,al_*3.-t*(1.2+uThink*3.),t*.3));
  float jet=exp(-la_*la_/(.0016+.010*al_))*smoothstep(Rc*.7,Rc*1.25,al_)*exp(-al_*2.5)*(.25+jn*1.2);
  col+=mix(uC1,vec3(1.),.35)*jet*(.35+uAmp*1.4+uThink*.8+uKick*1.2+uSpeak*.5);
  float ph=exp(-pow((r-Rc)/.014,2.));col+=mix(uC1,vec3(1.),.5)*ph*(.55+uAmp);
  if(r<Rc){
    float z=sqrt(Rc*Rc-r*r);vec3 n=vec3(p,z)/Rc;float fres=pow(1.-n.z,2.4);
    float a=t*.16;n.xz=mat2(cos(a),-sin(a),sin(a),cos(a))*n.xz;
    vec3 s=n*2.0+vec3(0.,0.,t*.10*(1.+uThink*3.));
    float w=fbm(s+fbm(s*1.7-t*.1)*1.3);
    float rg=1.-abs(fbm(s*2.5+w*1.5)*2.-1.);rg=pow(rg,3.2);
    vec3 base=mix(uC2*.30,uC1*.60,w);
    col=base+uC1*rg*(1.1+uAmp*1.9+uThink*.9+uKick*1.5)+vec3(1.)*pow(rg,3.)*(.35+.9*uAmp);
    col+=uC3*fres*(.9+uAmp*1.2);
    col+=vec3(1.,.97,.9)*exp(-r*r/(Rc*Rc*.10))*(.95+uAmp*.9+uKick);
    col=mix(col,col*vec3(1.2,.65,.55)+vec3(.25,.04,0.),uAlert*.45);
  }
  col*=smoothstep(1.36,.92,max(abs(p.x),abs(p.y)))*smoothstep(1.3,.78,r);
  col=1.-exp(-col*1.35);
  float al=max(col.r,max(col.g,col.b));
  gl_FragColor=vec4(col,al);
}`;
  function sh(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null }
  const vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS), prog = gl.createProgram();
  if (!vs || !fs) return;
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
  gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = {}; for (const n of ['uRes', 'uT', 'uAmp', 'uThink', 'uSpeak', 'uAlert', 'uKick', 'uC1', 'uC2', 'uC3', 'uTilt']) U[n] = gl.getUniformLocation(prog, n);

  /* ---- from here on the cosmic orb is committed ---- */
  stage.classList.add('cosmic'); old.style.display = 'none'; stage.appendChild(gc); stage.appendChild(oc);
  const g = oc.getContext('2d');
  const NX = window.NX = { cosmic: true, busy: false, speaking: false, amp: 0, _kick: 0, kick(n) { this._kick = Math.min(1, this._kick + (n || .3)); bolts(Math.ceil((n || .3) * 6)); if ((n || .3) > .25) wave(false) } };
  gc.addEventListener('webglcontextlost', e => { e.preventDefault(); try { localStorage.setItem('nx_orb', 'classic') } catch (x) { /* ignore */ } location.reload() });
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const TAU = Math.PI * 2, LW = 840, CX = LW / 2, CORE = 104, SC = 1.3;      // logical size of the canvases (stage x 1.4), core radius, content scale
  const rnd = (a, b) => a + Math.random() * (b - a), clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const GLY = '0123456789ABCDEF', FONT = "'Cascadia Mono',Consolas,monospace";
  let K = 1, Q = 1, T = 0, last = performance.now(), ema = 16, slow = 0, fast = 0, vis = .1, thinkK = 0, speakK = 0, alertK = 0;
  const C1 = [62, 224, 255], C2 = [26, 125, 255], C3 = [62, 224, 255];
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${clamp(a, 0, 1).toFixed(3)})`;
  const white = a => `rgba(255,248,232,${clamp(a, 0, 1).toFixed(3)})`;
  const hex = s => /^#[0-9a-f]{6}$/i.test(s) ? [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16), parseInt(s.slice(5, 7), 16)] : null;
  function theme(dt) {
    const cs = getComputedStyle(document.body), k = Math.min(1, dt * 5);
    [['--c', C1], ['--c2', C2], ['--c3', C3]].forEach(([v, c]) => { const t = hex(cs.getPropertyValue(v).trim()); if (t) for (let i = 0; i < 3; i++) c[i] += (t[i] - c[i]) * k });
  }

  function fit() {
    const r = gc.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1) * Q, w = Math.max(2, Math.round(r.width * dpr));
    gc.width = gc.height = oc.width = oc.height = w; K = w / LW; gl.viewport(0, 0, w, w);
  }
  new ResizeObserver(fit).observe(gc); fit();

  /* ---- neural swarm ---- */
  const NODES = Array.from({ length: 62 }, () => {
    const u = [rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)], l = Math.hypot(...u) || 1, a = u.map(x => x / l);
    let b = [rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)]; const dp = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; b = b.map((x, i) => x - dp * a[i]); const bl = Math.hypot(...b) || 1; b = b.map(x => x / bl);
    return { u: a, v: b, r: rnd(150, 270), a: rnd(0, TAU), s: rnd(.12, .45) * (Math.random() < .5 ? -1 : 1), size: rnd(1, 2.6), hot: Math.random() < .22, x: 0, y: 0, z: 0, d: 1 };
  });
  // gyroscope rings: slow big ones, medium ones and small fast ones close to the planet. Every ring has its own living speed
  // (two sine waves with different periods + random kicks that sometimes reverse it), a wobbling tilt and a drifting axis.
  const RINGS = [
    { R: 300, tx: .55, tz: 2.2, sp: .55, tick: 80, w: 1.4, gl: false, f1: .21, f2: .07 },
    { R: 262, tx: 1.15, tz: .3, sp: -.85, tick: 96, w: 1.2, gl: true, f1: .33, f2: .11 },
    { R: 226, tx: 1.45, tz: -.8, sp: 1.35, tick: 0, w: 1, gl: false, f1: .27, f2: .09 },
    { R: 178, tx: .9, tz: 1.6, sp: -2.2, tick: 0, w: 1, gl: false, f1: .41, f2: .13 },
    { R: 146, tx: 1.3, tz: -2.1, sp: 3.1, tick: 0, w: 1.4, gl: false, f1: .53, f2: .17 },
    { R: 128, tx: .35, tz: .9, sp: -4.3, tick: 0, w: 1.2, gl: false, f1: .61, f2: .19 }
  ].map(R => Object.assign(R, { ang: rnd(0, TAU), imp: 0, ph1: rnd(0, TAU), ph2: rnd(0, TAU), drift: rnd(-.12, .12), dz: 0, sat: Math.random() < .5 ? 2 : 1 }));
  const DUST = Array.from({ length: 90 }, () => ({ a: rnd(0, TAU), r: rnd(140, 400), s: rnd(.01, .05), z: rnd(.2, 1), p: rnd(0, TAU) }));
  const packets = [], bs = [], waves = [];
  function bolts(n) { for (let i = 0; i < n && bs.length < 14; i++) bs.push({ n: NODES[Math.random() * NODES.length | 0], life: 1, seed: Math.random() * 1000, big: Math.random() < .3 }) }
  function wave(inward) { if (waves.length < 8) waves.push({ r: inward ? 400 : CORE + 6, v: inward ? -430 : 320, a: inward ? .0 : .75, inward }) }

  /* ---- pointer ---- */
  const P = { x: 0, y: 0, on: false, yaw: 0, pit: 0, ty: 0, tp: 0 };
  addEventListener('pointermove', e => {
    const r = stage.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, s = LW / (r.width * 1.4);
    P.x = (e.clientX - cx) * s; P.y = (e.clientY - cy) * s; P.on = Math.hypot(P.x, P.y) < 400;
    P.ty = clamp((e.clientX - cx) / innerWidth * 2, -1, 1) * .55; P.tp = clamp((e.clientY - cy) / innerHeight * 2, -1, 1) * .4;
  }, { passive: true });
  addEventListener('pointerdown', e => { if (P.on) { NX.kick(.5); wave(false) } }, { passive: true });
  document.addEventListener('mouseleave', () => { P.on = false; P.ty = P.tp = 0 });

  /* ---- 3D helpers ---- */
  let cy = 1, sy = 0, cp = 1, sp = 0;
  const view = (x, y, z) => { const x1 = x * cy + z * sy, z1 = -x * sy + z * cy, y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp; const f = 900 / (900 - z2); return [CX + x1 * f, CX + y1 * f, z2, f] };
  function ringPt(R, tx, tz, th, spin) {
    const x0 = R * Math.cos(th + spin), y0 = R * Math.sin(th + spin);
    const y1 = y0 * Math.cos(tx), z1 = y0 * Math.sin(tx), x2 = x0 * Math.cos(tz) - y1 * Math.sin(tz), y2 = x0 * Math.sin(tz) + y1 * Math.cos(tz);
    return view(x2, y2, z1);
  }
  function bolt(x0, y0, x1, y1, seed, big) {
    let pts = [[x0, y0], [x1, y1]];
    for (let d = 0; d < 5; d++) {
      const out = [pts[0]];
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i], l = Math.hypot(b[0] - a[0], b[1] - a[1]), nx = (b[1] - a[1]) / (l || 1), ny = -(b[0] - a[0]) / (l || 1), o = (Math.sin(seed * (i + d * 7.3) + d) * .5) * l * .45 * (big ? 1.2 : .8);
        out.push([(a[0] + b[0]) / 2 + nx * o, (a[1] + b[1]) / 2 + ny * o], b);
      }
      pts = out;
    }
    return pts;
  }
  const stroke = pts => { g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])); g.stroke() };

  /* ---- state ---- */
  let prevBusy = false, prevAlert = false, idleBolt = 1, kickAt = 3;
  function states(dt) {
    const think = NX.busy ? 1 : 0, speak = NX.speaking ? 1 : 0, al = document.body.classList.contains('alert') ? 1 : 0;
    thinkK += (think - thinkK) * Math.min(1, dt * 3); speakK += (speak - speakK) * Math.min(1, dt * 4); alertK += (al - alertK) * Math.min(1, dt * 5);
    if (NX.busy && !prevBusy) { wave(true); setTimeout(() => wave(true), 180); setTimeout(() => wave(true), 360) }
    if (!NX.busy && prevBusy) { NX.kick(.85); wave(false); setTimeout(() => wave(false), 160); bolts(8) }
    if (al && !prevAlert) { NX.kick(.7); wave(false); setTimeout(() => wave(false), 220); setTimeout(() => wave(false), 440) }
    prevBusy = !!NX.busy; prevAlert = !!al;
    vis += ((speak ? 1 : think ? .45 : .14) - vis) * Math.min(1, dt * 3);
  }

  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000) * (reduce ? .3 : 1); last = now; T += dt;
    ema += ((dt / (reduce ? .3 : 1) * 1000) - ema) * .05;
    if (ema > 27) { if (++slow > 90 && Q > .55) { Q = Math.max(.55, Q * .8); slow = 0; fit() } } else slow = 0;
    if (ema < 12) { if (++fast > 400 && Q < 1) { Q = Math.min(1, Q * 1.15); fast = 0; fit() } } else fast = 0;
    theme(dt); states(dt);

    // heartbeat while idle, faster when thinking, ripple while speaking; kicks decay
    const beat = p => { const ph = (T * 1000 % p) / p, e = (c, w) => Math.exp(-Math.pow((ph - c) / w, 2)); return e(.10, .05) + .6 * e(.30, .06); };
    const base = thinkK * (.12 + .5 * beat(900)) + speakK * (.22 + .14 * Math.sin(T * 12) * Math.sin(T * 4)) + (1 - Math.max(thinkK, speakK)) * (.05 + .24 * beat(1900));
    NX._kick *= Math.pow(.9, dt * 60); NX.amp = clamp(base + NX._kick, 0, 1);
    stage.style.setProperty('--amp', NX.amp.toFixed(3));
    const amp = NX.amp;

    // camera follows the mouse, slowly orbits by itself
    P.yaw += (P.ty - P.yaw) * Math.min(1, dt * 2.2); P.pit += (P.tp - P.pit) * Math.min(1, dt * 2.2);
    const yaw = P.yaw + Math.sin(T * .17) * .35 + T * .03 * (1 + thinkK * 4), pit = P.pit * .8 + Math.sin(T * .13) * .15;
    cy = Math.cos(yaw); sy = Math.sin(yaw); cp = Math.cos(pit); sp = Math.sin(pit);

    // --- WebGL: plasma core, disc, nebula ---
    gl.uniform2f(U.uRes, gc.width, gc.height); gl.uniform1f(U.uT, T); gl.uniform1f(U.uAmp, amp); gl.uniform1f(U.uThink, thinkK); gl.uniform1f(U.uSpeak, speakK);
    gl.uniform1f(U.uAlert, alertK); gl.uniform1f(U.uKick, NX._kick);
    gl.uniform3f(U.uC1, C1[0] / 255, C1[1] / 255, C1[2] / 255); gl.uniform3f(U.uC2, C2[0] / 255, C2[1] / 255, C2[2] / 255); gl.uniform3f(U.uC3, C3[0] / 255, C3[1] / 255, C3[2] / 255);
    gl.uniform3f(U.uTilt, -.35 + yaw * .5 + Math.sin(T * .2) * .12, .35 + pit * 1.4 + .25, 0);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    // --- 2D overlay ---
    g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, oc.width, oc.height); g.setTransform(K, 0, 0, K, 0, 0);
    g.globalCompositeOperation = 'lighter'; g.lineCap = 'round';
    const coreR = CORE * (1 + amp * .10);

    // star dust: drifts outward, spirals in while thinking
    for (const d of DUST) {
      d.a += d.s * dt * (1 + thinkK * 5); d.r += (thinkK ? -22 : 5) * d.z * dt * (1 + speakK * 3); if (d.r < coreR + 8) d.r = rnd(380, 410); if (d.r > 415) d.r = rnd(160, 260);
      const p = view(Math.cos(d.a) * d.r, Math.sin(d.a) * d.r * .8, (d.z - .5) * 260), tw = .35 + .65 * Math.abs(Math.sin(T * 1.7 + d.p));
      g.fillStyle = rgba(C3, .55 * tw * p[3] * d.z); g.fillRect(p[0], p[1], 1.4 * p[3], 1.4 * p[3]);
    }

    // gyroscope rings: varied, never repeating speeds
    g.textAlign = 'center'; g.textBaseline = 'middle';
    kickAt -= dt; if (kickAt <= 0) { const R = RINGS[Math.random() * RINGS.length | 0]; R.imp += (Math.random() < .4 ? -1 : 1) * rnd(2.5, 6) * (R.sp > 0 ? 1 : -1); kickAt = rnd(2.5, 7) }
    RINGS.forEach((R, ri) => {
      const sp = R.sp * (1 + .5 * Math.sin(T * R.f1 + R.ph1) + .28 * Math.sin(T * R.f2 * 2.7 + R.ph2)) * (1 + thinkK * 2 + speakK * .5 + amp * .4);
      R.imp *= Math.exp(-dt * 1.1); R.ang += (sp + R.imp) * dt; R.dz += R.drift * dt;
      const tx = R.tx + .28 * Math.sin(T * R.f1 * .8 + R.ph2) + P.pit * .3, tz = R.tz + R.dz + .2 * Math.sin(T * R.f2 + R.ph1), N = R.R < 200 ? 64 : 96; let prev = null;
      const col = ri % 3 === 1 ? C2 : ri % 3 === 2 ? C3 : C1, fast = Math.abs(R.sp) > 1.5;
      g.lineWidth = R.w;
      for (let i = 0; i <= N; i++) {
        const p = ringPt(R.R, tx, tz, i * TAU / N, R.ang * .15);
        if (prev) { const dpt = (p[2] + 330) / 660; g.strokeStyle = rgba(col, (.08 + .34 * dpt) * (1 + amp * .8) * (fast ? .85 : 1)); g.beginPath(); g.moveTo(prev[0], prev[1]); g.lineTo(p[0], p[1]); g.stroke() }
        prev = p;
      }
      if (R.tick) for (let i = 0; i < R.tick; i++) {
        const th = i * TAU / R.tick, a = ringPt(R.R, tx, tz, th, R.ang * .15), b = ringPt(R.R + (i % 6 ? 4 : 9), tx, tz, th, R.ang * .15), dpt = (a[2] + 330) / 660;
        g.strokeStyle = rgba(C1, (.1 + .34 * dpt) * (i % 6 ? .55 : 1)); g.lineWidth = 1; g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
      }
      if (R.gl) for (let i = 0; i < 28; i++) {
        const p = ringPt(R.R + 16, tx, tz, i * TAU / 28, R.ang * .15), dpt = (p[2] + 330) / 660;
        g.font = (8 + 4 * dpt) + 'px ' + FONT; g.fillStyle = rgba(C3, (.12 + .45 * dpt) * (.7 + .3 * Math.sin(T * 3 + i)));
        g.fillText(GLY[(((i * 7 + (T * (2 + thinkK * 8) | 0)) % 16) + 16) % 16], p[0], p[1]);   // never a negative index
      }
      for (let s2 = 0; s2 < R.sat; s2++) {                            // satellites with trails; their own speed, so they overtake the ring pattern
        const dir = (R.sp > 0 ? 1 : -1), th = R.ang * (1.6 + ri * .35) * .6 + s2 * Math.PI + Math.sin(T * R.f1 * 1.7 + ri) * .5, tl = fast ? 20 : 12;
        for (let k = 0; k < tl; k++) {
          const p = ringPt(R.R, tx, tz, th - k * (fast ? .05 : .035) * dir, R.ang * .15), dpt = (p[2] + 330) / 660;
          g.fillStyle = k ? rgba(C3, (1 - k / tl) * .55 * (.4 + dpt)) : white(.95); g.beginPath(); g.arc(p[0], p[1], k ? Math.max(.6, 2 - k * .08) : 3.4, 0, TAU); g.fill();
        }
      }
    });

    // neural nodes
    const reach = 92 * (1 + thinkK * .6 + amp * .3);
    for (const n of NODES) {
      n.a += n.s * dt * (1 + thinkK * 3 + speakK * .8);
      const rr = n.r * (1 + .05 * Math.sin(T * .8 + n.a * 3)) * (1 - thinkK * .12 + amp * .06), ca = Math.cos(n.a), sa = Math.sin(n.a);
      const p = view(rr * (ca * n.u[0] + sa * n.v[0]), rr * (ca * n.u[1] + sa * n.v[1]), rr * (ca * n.u[2] + sa * n.v[2]));
      n.x = p[0]; n.y = p[1]; n.z = p[2]; n.d = (p[2] + 260) / 520; n.f = p[3];
    }
    g.lineWidth = 1;
    for (let i = 0; i < NODES.length; i++) {
      const a = NODES[i];
      for (let j = i + 1; j < NODES.length; j++) {
        const b = NODES[j], dx = a.x - b.x, dy = a.y - b.y, dd = dx * dx + dy * dy;
        if (dd < reach * reach) {
          const k = 1 - Math.sqrt(dd) / reach, dp = clamp((a.d + b.d) / 2, 0, 1);
          g.strokeStyle = rgba(a.hot ? C3 : C1, k * k * (.10 + .5 * dp) * (1 + amp * .8)); g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
          if (packets.length < 70 && Math.random() < (.0012 + thinkK * .012 + speakK * .004 + amp * .002) * k) packets.push({ a, b, t: 0, sp: rnd(.8, 2.2) * (1 + thinkK * 1.5) });
        }
      }
    }
    for (let i = packets.length - 1; i >= 0; i--) {
      const k = packets[i]; k.t += dt * k.sp; if (k.t >= 1) { packets.splice(i, 1); continue }
      const x = k.a.x + (k.b.x - k.a.x) * k.t, y = k.a.y + (k.b.y - k.a.y) * k.t;
      g.fillStyle = white(.9); g.beginPath(); g.arc(x, y, 1.9, 0, TAU); g.fill();
      g.fillStyle = rgba(C1, .25); g.beginPath(); g.arc(x, y, 5.5, 0, TAU); g.fill();
    }
    for (const n of NODES) {
      let glow = .25 + .6 * n.d, rad = n.size * n.f;
      if (P.on) { const dd = Math.hypot(n.x - CX - P.x, n.y - CX - P.y); if (dd < 110) { glow += (1 - dd / 110) * .9; g.strokeStyle = rgba(C3, (1 - dd / 110) * .55); g.lineWidth = 1; g.beginPath(); g.moveTo(n.x, n.y); g.lineTo(CX + P.x, CX + P.y); g.stroke() } }
      g.fillStyle = rgba(n.hot ? C3 : C1, glow * .35); g.beginPath(); g.arc(n.x, n.y, rad * 3.2, 0, TAU); g.fill();
      g.fillStyle = n.hot ? white(glow) : rgba(C1, glow + .2); g.beginPath(); g.arc(n.x, n.y, rad, 0, TAU); g.fill();
    }
    if (P.on) { const pg = g.createRadialGradient(CX + P.x, CX + P.y, 0, CX + P.x, CX + P.y, 34); pg.addColorStop(0, rgba(C3, .35)); pg.addColorStop(1, rgba(C3, 0)); g.fillStyle = pg; g.beginPath(); g.arc(CX + P.x, CX + P.y, 34, 0, TAU); g.fill() }

    // lightning from the core to nodes
    idleBolt -= dt * (.35 + thinkK * 4 + speakK * 1.2 + amp * 1.5); if (idleBolt <= 0) { bolts(1 + (thinkK > .5 ? 2 : 0)); idleBolt = rnd(.6, 1.6) }
    for (let i = bs.length - 1; i >= 0; i--) {
      const b = bs[i]; b.life -= dt * (b.big ? 2.2 : 3.4); if (b.life <= 0) { bs.splice(i, 1); continue }
      const dx = b.n.x - CX, dy = b.n.y - CX, l = Math.hypot(dx, dy) || 1, sx = CX + dx / l * coreR * .85, sy = CX + dy / l * coreR * .85;
      const pts = bolt(sx, sy, b.n.x, b.n.y, b.seed + Math.floor(T * 22), b.big), al = b.life * b.life;
      g.strokeStyle = rgba(C1, al * .28); g.lineWidth = 6 * (b.big ? 1.4 : 1); stroke(pts);
      g.strokeStyle = white(al * .95); g.lineWidth = b.big ? 1.9 : 1.2; stroke(pts);
      g.fillStyle = rgba(C3, al * .7); g.beginPath(); g.arc(b.n.x, b.n.y, 7 * al + 2, 0, TAU); g.fill();
    }

    // ring of fine ticks around the core: always the same calm look (it does not react to speech, the pulse rings below do)
    const bars = 120, v = .14;
    for (let i = 0; i < bars; i++) {
      const a = i * TAU / bars - T * .08, sp2 = Math.abs(Math.sin(i * .66 + T * 9) * Math.sin(i * .21 - T * 5.3)) * (.45 + .55 * Math.abs(Math.sin(i * 1.9 + T * 2.4)));
      const len = 3 + v * (6 + 40 * sp2 * .55), r0 = coreR + 36;
      g.strokeStyle = rgba(i % 6 === 0 ? C3 : C1, (.18 + .5 * v) * (.5 + sp2)); g.lineWidth = 2;
      g.beginPath(); g.moveTo(CX + Math.cos(a) * r0, CX + Math.sin(a) * r0 * .86); g.lineTo(CX + Math.cos(a) * (r0 + len), CX + Math.sin(a) * (r0 + len) * .86); g.stroke();
    }

    // shock waves
    for (let i = waves.length - 1; i >= 0; i--) {
      const w = waves[i]; w.r += w.v * dt;
      if (w.inward) { w.a = Math.min(.8, w.a + dt * 3); if (w.r < coreR + 10) { waves.splice(i, 1); NX._kick = Math.min(1, NX._kick + .05); continue } }
      else { w.a *= Math.pow(.955, dt * 60); if (w.a < .02 || w.r > 430) { waves.splice(i, 1); continue } }
      g.strokeStyle = rgba(C1, w.a * .7); g.lineWidth = 2.2; g.beginPath(); g.ellipse(CX, CX, w.r, w.r * .94, 0, 0, TAU); g.stroke();
      g.strokeStyle = white(w.a * .5); g.lineWidth = .8; g.beginPath(); g.ellipse(CX, CX, w.r, w.r * .94, 0, 0, TAU); g.stroke();
    }
    if (speakK > .5 && Math.random() < dt * 2.2) wave(false);
    g.globalCompositeOperation = 'source-over';
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
