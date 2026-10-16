'use strict';
/* Iris dashboard. Every piece of text that comes from an API, a wallet name or a social post goes through esc(). */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v } catch (e) { return d } },
  set(k, v) { try { localStorage.setItem(k, v) } catch (e) {} }
};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = u => (typeof u === 'string' && /^https:\/\//.test(u)) ? u : '';

/* ---------- formatting ---------- */
function usd(n, forceDec) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  const a = Math.abs(n), d = forceDec ?? (a >= 1000 ? 0 : 2);
  return (n < 0 ? '-' : '') + '$' + a.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
const usdS = n => n === null || n === undefined ? '—' : (n > 0 ? '+' : '') + usd(n);
const pctS = n => n === null || n === undefined ? '' : (n > 0 ? '+' : '') + n.toFixed(2) + '%';
const cls = n => n > 0 ? 'pos' : n < 0 ? 'neg' : '';
function compact(n) {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k';
  return String(Math.round(n));
}
const usdC = n => (n < 0 ? '-' : '') + '$' + compact(Math.abs(n));
const num = n => n === null || n === undefined ? '—' : Math.round(n).toLocaleString('en-US');
const numS = n => n === null || n === undefined ? '' : (n > 0 ? '+' : '') + Math.round(n).toLocaleString('en-US');
function px(n) {
  if (n >= 1000) return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (n >= 1) return '$' + n.toFixed(2);
  if (n >= 0.01) return '$' + n.toFixed(4);
  return '$' + n.toPrecision(3);
}
function amt(n) {
  if (n >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (n >= 1) return n.toLocaleString('en-US', { maximumFractionDigits: 3 });
  return n.toPrecision(3);
}
const cv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();   // current theme colour
const hexRgb = h => { h = String(h).trim().replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) || 0) };
const mixHex = (a, b, t) => { const A = hexRgb(a), B = hexRgb(b); return '#' + A.map((v, i) => Math.round(v * t + B[i] * (1 - t)).toString(16).padStart(2, '0')).join('') };   // t of a, the rest of b
const chartFill = col => mixHex(col, cv('--bg3'), .6);   // a deep shade of the line colour: stays clean instead of turning grey over a differently coloured panel
const palette = () => [cv('--c'), cv('--c2'), '#a395ff', cv('--pos'), cv('--warn'), '#ff8a3d', '#ff7bd0', '#2fd1b5', '#7f94a8'];

async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let j = null; try { j = await r.json() } catch (e) {}
  if (!r.ok) {
    let d = j && j.detail;
    if (Array.isArray(d)) d = d.map(x => x.msg).join('; ');
    throw new Error(d || ('Error ' + r.status));
  }
  return j;
}

/* ---------- header bits ---------- */
for (let i = 0; i < 9; i++) { const h = document.createElement('div'); h.className = 'hex'; h.style.setProperty('--i', i); $('#hexes').appendChild(h) }
setInterval(() => { $('#clock').textContent = new Date().toLocaleTimeString('en-GB') }, 1000);

let ST = null, SOC = [], offline = false, MKTS = [], CALD = null;
let RANGE = store.get('nx_range', '1w'), ALLOC = store.get('nx_alloc', 'assets'), CALM = null, HOLD_ALL = false;
let HIST = null;

function statusText() {
  const b = document.body.classList;
  const al = typeof LIVE !== 'undefined' && LIVE.alerting();
  b.toggle('thinking', NX.busy); b.toggle('speaking', NX.speaking); b.toggle('alert', al);
  $('#status').textContent = offline ? 'OFFLINE' : NX.busy ? 'PROCESSING' : al ? 'ALERT' : NX.speaking ? 'SPEAKING' : 'ONLINE';
}

/* ---------- colour themes ---------- */
const THEMES = [
  ['cyan', 'IRIS CYAN', '#3ee0ff', '#1a7dff', '#07204f'],
  ['matrix', 'MATRIX', '#2bff88', '#00b35a', '#03170d'],
  ['solana', 'SOLANA', '#14f195', '#9945ff', '#120a29'],
  ['tokyo', 'TOKYO NIGHT', '#7aa2f7', '#bb9af7', '#1a1b26'],
  ['violet', 'ULTRAVIOLET', '#b388ff', '#7c4dff', '#1a0b3d'],
  ['synth', 'SYNTHWAVE', '#ff4fd8', '#00e5ff', '#21062e'],
  ['bitcoin', 'BITCOIN', '#f7931a', '#ffcf5a', '#1f1105'],
  ['red', 'RED TEAM', '#ff3b4e', '#ff7a45', '#1f050a'],
  ['carbon', 'CARBON', '#e4e4e7', '#a1a1aa', '#101013']
];
function applyTheme(id, redraw) {
  const t = THEMES.find(x => x[0] === id) || THEMES.find(x => x[0] === 'solana');
  if (t[0] === 'cyan') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t[0];
  store.set('nx_theme2', t[0]);
  $('#themes').innerHTML = THEMES.map(x => `<button type="button" class="sw ${x[0] === t[0] ? 'on' : ''}" data-theme="${x[0]}" title="${esc(x[1])}" aria-label="${esc(x[1])}" aria-pressed="${x[0] === t[0]}" style="background:linear-gradient(135deg,${x[2]} 0 52%,${x[3]} 52% 100%);box-shadow:inset 0 0 0 3px ${x[4]}"></button>`).join('');
  $('#themeName').textContent = '· ' + t[1]; $('#themeBtn').textContent = 'THEME: ' + t[1];
  if (redraw && ST) { renderAll(); renderSocials(); loadHistory(); loadMarkets(); loadCalendar() }   // charts draw their colours in JS
}
$('#scBtn').onclick = async () => {
  const b = $('#scBtn'); b.disabled = true;
  try { const r = await api('/api/shortcut', {}); $('#you').textContent = ''; $('#note').textContent = ''; $('#reply').textContent = r.message; setExplain(false) }
  catch (e) { $('#reply').textContent = 'Could not add the desktop icon: ' + e.message }
  b.disabled = false;
};
(() => { const on = !!(window.NX && window.NX.cosmic), want = store.get('nx_orb', 'cosmic'); $('#orbBtn').textContent = 'ORB: ' + (on ? 'COSMIC' : want === 'cosmic' ? 'CLASSIC (no WebGL)' : 'CLASSIC');
  $('#orbBtn').onclick = () => { store.set('nx_orb', on || want === 'cosmic' ? 'classic' : 'cosmic'); location.reload() } })();
$('#themeBtn').onclick = () => { const i = THEMES.findIndex(x => x[0] === (document.documentElement.dataset.theme || 'cyan')); applyTheme(THEMES[(i + 1) % THEMES.length][0], true) };
$('#themes').addEventListener('click', e => { const b = e.target.closest('[data-theme]'); if (b) applyTheme(b.dataset.theme, true) });

/* ---------- soft highlight of the part of the app being explained ---------- */
const SPOT = { els: [], t: null, still: false };
function spotOff() { SPOT.els.forEach(e => e.classList.remove('spot')); SPOT.els = [] }
function spotOn(sel) {
  spotOff(); if (!sel) return;
  const els = $$(sel).filter(e => !e.hidden && e.offsetParent !== null);
  els.forEach(e => e.classList.add('spot')); SPOT.els = els;
  const first = els.find(e => !e.closest('footer,header'));       // never scroll for the header or the chat bar
  if (first && !SPOT.still) { const r = first.getBoundingClientRect(); if (r.bottom < 0 || r.top > innerHeight - 150) first.scrollIntoView({ block: 'center', behavior: 'smooth' }) }
}
function stopTour() { clearTimeout(SPOT.t); clearInterval(SPOT.t); spotOff() }
/* where the voice is right now (0..1 of the sentence being spoken), from the word positions the browser reports. A tour that explains
   what is being said moves on when the voice reaches the next sentence, so the highlight never drifts away from the words. */
const SPEECH = { f: 0, last: 0 };
function tour(steps, still) {   // steps: [[selector, milliseconds], ...]; still = never scroll the page
  clearInterval(SPOT.t); clearTimeout(SPOT.t); SPOT.still = !!still;
  let i = 0, at = 0; const w = steps.every(x => x[2]) ? 2 : 1, total = steps.reduce((a, x) => a + x[w], 0) || 1; let acc = 0; const ends = steps.map(x => (acc += x[w]) / total);     // share of the spoken text each step covers
  const go = () => { if (i >= steps.length) { clearInterval(SPOT.t); spotOff(); return } spotOn(steps[i][0]); at = performance.now(); i++ };
  go(); if (steps.length === 1) { SPOT.t = setTimeout(() => { spotOff() }, steps[0][1]); return }
  SPOT.t = setInterval(() => {
    const now = performance.now(), live = now - SPEECH.last < 900, k = i - 1;
    if (k >= steps.length - 1) { if (now - at >= steps[k][1]) go(); return }                      // the last step simply runs its time
    if (live ? SPEECH.f >= ends[k] - .005 && now - at > 450 : now - at >= steps[k][1]) go();      // voice reports positions: follow it; otherwise use the estimate
  }, 120);
}
const speakMs = t => 700 + t.length * 62;          // rough speaking time, so each highlight lines up with its sentence
const stepsFor = parts => parts.flatMap(([t, sel]) => {     // the question bubbles light up one after the other, in order
  if (sel !== '#sugg') return [[sel, speakMs(t), t.length]];
  const n = Math.max(1, document.querySelectorAll('#sugg .bub').length), each = Math.max(1100, speakMs(t) / n);
  return Array.from({ length: n }, (_, i) => [`#sugg .bub:nth-child(${i + 1})`, each, t.length / n]);
});
const setExplain = on => { const c = document.querySelector('.caption'); if (c) c.classList.toggle('explain', !!on) };
const FOCUS = { start: '#connBtn,#wDemo', claude: '#connBtn', connect: '#connBtn', social: '[data-sec=socials]', market: '[data-sec=market]', pnl: '[data-sec=balance]', positions: '[data-sec=portfolio]',
  stable: '[data-sec=allocation]', biggest: '[data-sec=accounts]', markets: '[data-sec=markets]', balance: '[data-sec=balance]', demo: '#wDemo,#demoBanner', intro: '#welcome,#connBtn' };

/* ---------- section visibility ---------- */
const SECTIONS = { balance: 'Balance', accounts: 'Accounts', allocation: 'Allocation', markets: 'Markets', portfolio: 'Portfolio', holdings: 'Holdings', socials: 'Socials', market: 'Market news' };
function hiddenSecs() { try { return JSON.parse(store.get('nx_hidden', '[]')) } catch (e) { return [] } }
function applyViews() {
  const hid = hiddenSecs();
  $$('[data-sec]').forEach(el => { el.hidden = hid.includes(el.dataset.sec) });
  $('#views').innerHTML = Object.entries(SECTIONS).map(([k, v]) =>
    `<label class="chk"><input type="checkbox" data-sec-toggle="${k}" ${hid.includes(k) ? '' : 'checked'}>${v}</label>`).join('');
}
$('#views').addEventListener('change', e => {
  const k = e.target.dataset.secToggle; if (!k) return;
  const hid = hiddenSecs().filter(x => x !== k); if (!e.target.checked) hid.push(k);
  store.set('nx_hidden', JSON.stringify(hid)); applyViews(); redrawChart();
});

/* ---------- small chart helpers ---------- */
function spark(vals, color, w = 100, h = 24) {
  if (!vals || vals.length < 2) return '';
  const lo = Math.min(...vals), hi = Math.max(...vals), rng = (hi - lo) || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 2 - (v - lo) / rng * (h - 4)).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`;
}

function donut(items) {
  const total = items.reduce((s, i) => s + i.usd, 0) || 1, R = 45, C = 2 * Math.PI * R;
  let off = 0;
  const arcs = items.map((it, i) => {
    const len = it.usd / total * C, el = `<circle cx="60" cy="60" r="${R}" fill="none" stroke="${palette()[i % palette().length]}" stroke-width="14" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 60 60)"/>`;
    off += len; return el;
  }).join('');
  return `<svg viewBox="0 0 120 120" role="img" aria-label="Allocation"><circle cx="60" cy="60" r="${R}" fill="none" stroke="rgba(${cv('--c-rgb')},.1)" stroke-width="14"/>${arcs}<text x="60" y="64" text-anchor="middle" fill="#fff" font-family="Orbitron,sans-serif" font-size="12">${esc(usdC(total))}</text></svg>`;
}

function fmtTick(t, spanSec) {
  const d = new Date(t * 1000);
  if (spanSec <= 2 * 86400) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function lineChart(host, tip, pts, emptyMsg) {
  if (!pts || pts.length < 2) { host.innerHTML = `<div class="cempty">${esc(emptyMsg || 'Collecting data… the chart fills in as Iris keeps running.')}</div>`; return; }
  const W = host.clientWidth || 600, H = host.clientHeight || 300, padL = 62, padR = 14, padT = 16, padB = 26, w = W - padL - padR, h = H - padT - padB;
  const ys = pts.map(p => p[1]), x0 = pts[0][0], x1 = Math.max(pts[pts.length - 1][0], x0 + 1);
  let lo = Math.min(...ys), hi = Math.max(...ys); if (hi === lo) { hi += 1; lo -= 1 }
  const pad = (hi - lo) * .1; lo -= pad; hi += pad;
  const X = t => padL + (t - x0) / (x1 - x0) * w, Y = v => padT + (1 - (v - lo) / (hi - lo)) * h;
  const up = ys[ys.length - 1] >= ys[0], col = up ? cv('--pos') : cv('--neg');
  const line = pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join('');
  const area = line + `L${X(x1).toFixed(1)},${padT + h}L${padL},${padT + h}Z`;
  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, y = Y(v);
    grid += `<line x1="${padL}" x2="${W - padR}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(${cv('--c-rgb')},.12)"/><text x="${padL - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="${cv('--dim')}" font-size="11">${esc(usdC(v))}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const t = x0 + (x1 - x0) * i / 4;
    grid += `<text x="${X(t).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}" fill="${cv('--dim')}" font-size="11">${esc(fmtTick(t, x1 - x0))}</text>`;
  }
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Balance chart"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${chartFill(col)}" stop-opacity=".9"/><stop offset="1" stop-color="${chartFill(col)}" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${area}" fill="url(#cg)"/><path d="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/><line id="cx" y1="${padT}" y2="${padT + h}" stroke="#fff" stroke-opacity=".5" style="display:none"/><circle id="cd" r="4" fill="${col}" stroke="#fff" style="display:none"/></svg>`;
  const svg = host.querySelector('svg'), cx = svg.querySelector('#cx'), cd = svg.querySelector('#cd');
  svg.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), mx = (e.clientX - r.left) / r.width * W;
    let a = 0, b = pts.length - 1;
    while (b - a > 1) { const m = (a + b) >> 1; (X(pts[m][0]) < mx) ? a = m : b = m }
    const p = Math.abs(X(pts[a][0]) - mx) < Math.abs(X(pts[b][0]) - mx) ? pts[a] : pts[b], x = X(p[0]), y = Y(p[1]);
    cx.setAttribute('x1', x); cx.setAttribute('x2', x); cx.style.display = '';
    cd.setAttribute('cx', x); cd.setAttribute('cy', y); cd.style.display = '';
    tip.style.display = 'block';
    tip.innerHTML = `${esc(new Date(p[0] * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))}<br><b>${esc(usd(p[1], 2))}</b>`;
    const tw = tip.offsetWidth, left = Math.min(Math.max(x / W * host.clientWidth - tw / 2, 4), host.clientWidth - tw - 4);
    tip.style.left = left + 'px'; tip.style.top = Math.max(4, y / H * host.clientHeight - 54) + 'px';
  });
  svg.addEventListener('mouseleave', () => { cx.style.display = 'none'; cd.style.display = 'none'; tip.style.display = 'none' });
}

/* ---------- panels ---------- */
function pnlRow(label, p) {
  if (!p) return `<small>${label}</small><b>—</b><span></span>`;
  return `<small>${label}${p.partial ? ' *' : ''}</small><b class="${cls(p.usd)}" ${p.partial ? `title="Tracking started ${esc(p.since)}"` : ''}>${esc(usdS(p.usd))}</b><span class="${cls(p.usd)}">${esc(pctS(p.pct))}</span>`;
}

function renderTotal() {
  const s = ST, el = $('#pf');
  if (!s.configured) { el.innerHTML = '<div class="sub">Nothing connected yet. Open <b>Connections</b> to add an exchange or wallet, or try the demo data.</div>'; return }
  el.innerHTML = `<div class="big">${esc(usd(s.total_usd, 2))}</div>
    <div class="pl">${pnlRow('24H', s.pnl.d1)}${pnlRow('7D', s.pnl.d7)}${pnlRow('30D', s.pnl.d30)}</div>
    <div class="row" style="margin-top:8px"><span>Open positions PnL</span><span class="${cls(s.upnl_usd)}">${esc(usdS(s.upnl_usd))}</span></div>
    <div class="row"><span>In stablecoins</span><span>${esc(s.stable_pct)}%</span></div>
    ${s.incomplete ? '<div class="sub warnc" style="margin-top:6px">Some accounts could not be read, so the total may be too low. See ACCOUNTS.</div>' : ''}
    ${Object.values(s.pnl).some(p => p && p.partial) ? '<div class="sub">* tracking started later than the period; PnL counts from then.</div>' : ''}`;
}

const KIND = { exchange: 'EXCHANGE', wallet: 'WALLET' };
function renderAccounts() {
  const s = ST, el = $('#accts');
  if (!s.accounts.length) { el.innerHTML = '<div class="sub">No accounts yet.</div>'; return }
  el.innerHTML = s.accounts.map(a => `<div class="ac">
    <div class="t"><span class="n">${esc(a.name)}<i>${esc(a.network || KIND[a.kind] || a.kind)}</i></span><b>${a.total_usd === null ? '—' : esc(usd(a.total_usd))}</b></div>
    ${a.total_usd === null ? '' : `<div class="bar2"><i style="width:${Math.min(100, a.share_pct)}%"></i></div>
    <div class="s">${esc(a.share_pct)}% · ${esc(a.top.map(t => t.symbol).join(', ') || 'no assets')}${a.n_assets > a.top.length ? ' +' + (a.n_assets - a.top.length) : ''}${a.unpriced.length ? ' · unpriced: ' + esc(a.unpriced.join(', ')) : ''}</div>`}
    ${a.error ? `<div class="e">${esc(a.error)}</div>` : ''}${a.warnings.map(w => `<div class="w">${esc(w)}</div>`).join('')}
  </div>`).join('');
}

function renderAlloc() {
  const s = ST, el = $('#alloc'), items = (s.allocation[ALLOC] || []).filter(i => i.usd > 0);
  $$('#allocMode .stab').forEach(b => b.classList.toggle('active', b.dataset.m === ALLOC));
  if (!items.length) { el.innerHTML = '<div class="sub">Nothing to show yet.</div>'; return }
  const total = items.reduce((t, i) => t + i.usd, 0);
  el.innerHTML = `<div class="don">${donut(items)}<div>${items.map((i, k) => `<div class="al"><u style="background:${palette()[k % palette().length]}"></u><span>${esc(i.label)}</span><span>${esc(usd(i.usd))}</span><span class="p">${(i.usd / total * 100).toFixed(1)}%</span></div>`).join('')}</div></div>`;
}

function renderTiles() {
  const s = ST, p = s.pnl || {}, ok = s.accounts.filter(a => a.total_usd !== null).length;
  const t = (label, val, sub, c) => `<div class="tile"><small>${label}</small><b class="${c || ''}">${val}</b><span>${sub || '&nbsp;'}</span></div>`;
  const pt = (label, x) => x ? t(label, esc(usdS(x.usd)), esc(pctS(x.pct)) + (x.partial ? ' *' : ''), cls(x.usd)) : t(label, '—', 'collecting…');
  $('#tiles').innerHTML = t('TOTAL BALANCE', esc(usd(s.total_usd)), `${ok} account${ok === 1 ? '' : 's'}`) + pt('24H', p.d1) + pt('7 DAYS', p.d7) + pt('30 DAYS', p.d30) +
    t('OPEN POSITIONS PNL', esc(usdS(s.upnl_usd)), `${s.positions.length} open`, cls(s.upnl_usd)) + t('STABLECOINS', esc(s.stable_pct) + '%', 'of total');
  $('#plive').textContent = s.demo ? 'DEMO DATA' : 'LIVE';
}

function renderPositions() {
  const ps = ST.positions;
  $('#posinfo').textContent = ps.length ? `${ps.length} OPEN` : '';
  $('#pos').innerHTML = !ps.length ? '<div class="sub">No open futures positions.</div>' : ps.map(p => `<div class="tr ${esc(p.side)}">
    <span class="sd">${p.side === 'long' ? 'LONG' : 'SHORT'}</span>
    <span class="mid">${esc(p.symbol)}<small>${esc(p.account)} · ${esc(amt(p.size))} @ ${esc(px(p.entry))}${p.leverage ? ' · ' + esc(p.leverage) + 'x' : ''}${p.liq ? ' · liq ' + esc(px(p.liq)) : ''}</small></span>
    <span class="am ${cls(p.upnl)}">${esc(usdS(p.upnl))}</span></div>`).join('');
}

function renderHoldings() {
  const rows = ST.holdings, shown = HOLD_ALL ? rows : rows.slice(0, 12);
  $('#holdMore').hidden = rows.length <= 12; $('#holdMore').textContent = HOLD_ALL ? 'SHOW LESS' : 'SHOW ALL';
  if (!rows.length) { $('#hold').innerHTML = '<div class="sub">No holdings yet.</div>'; return }
  $('#hold').innerHTML = `<table class="tbl"><thead><tr><th>ASSET</th><th>AMOUNT</th><th>VALUE</th><th>SHARE</th><th class="where">WHERE</th></tr></thead><tbody>${shown.map(h => `<tr>
    <td>${esc(h.symbol)}</td><td>${esc(amt(h.amount))}</td><td>${esc(usd(h.usd))}</td>
    <td><span class="pbar"><i style="width:${Math.min(100, h.pct)}%"></i></span>${esc(h.pct.toFixed(1))}%</td>
    <td class="where">${esc(h.in.slice(0, 3).map(w => w.account + (w.where ? ' (' + w.where + ')' : '')).join(' · '))}${h.in.length > 3 ? ' …' : ''}</td></tr>`).join('')}</tbody></table>`;
}

function renderMarkets(list) {
  $('#mkts').innerHTML = !list.length ? '<div class="sub">Market prices unavailable right now (public price APIs unreachable).</div>' : list.map(m => `<div class="mk">
    <b>${esc(m.symbol)}</b>${spark(m.spark, m.change24h >= 0 ? cv('--pos') : cv('--neg'))}<span class="px">${esc(px(m.price))}</span><span class="ch ${cls(m.change24h)}">${esc(pctS(m.change24h))}</span></div>`).join('');
}

/* ---------- history chart + calendar ---------- */
async function loadHistory() {
  try { HIST = await api('/api/history?range=' + RANGE) } catch (e) { HIST = null }
  redrawChart();
}
function redrawChart() {
  $$('#range .stab').forEach(b => b.classList.toggle('active', b.dataset.r === RANGE));
  const host = $('#chart'); if (!host.clientWidth) return;
  lineChart(host, $('#ctip'), HIST && HIST.points, ST && !ST.configured ? 'Connect an account to see your balance over time.' : null);
}
new ResizeObserver(() => redrawChart()).observe($('#chart'));

const MONTHS = ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'];
async function loadCalendar() {
  let c; try { c = await api('/api/calendar' + (CALM ? '?month=' + CALM : '')) } catch (e) { return }
  CALM = c.month; CALD = c;
  const [y, m] = c.month.split('-').map(Number), first = new Date(y, m - 1, 1), n = new Date(y, m, 0).getDate(), lead = (first.getDay() + 6) % 7;
  const now = new Date(), cur = now.getFullYear() === y && now.getMonth() === m - 1;
  $('#calLabel').textContent = MONTHS[m - 1] + ' ' + y;
  $('#calNext').disabled = cur || (y > now.getFullYear()) || (y === now.getFullYear() && m - 1 >= now.getMonth());
  const tot = $('#calTot'); tot.textContent = Object.keys(c.days).length ? usdS(c.total) : ''; tot.className = cls(c.total);
  let cells = '';
  for (let i = 0; i < lead; i++) cells += '<div class="cd pad"></div>';
  for (let d = 1; d <= n; d++) {
    const key = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`, v = c.days[key];
    const future = key > c.today, k = v ? (v.usd > 0 ? 'profit' : v.usd < 0 ? 'loss' : '') : (future ? 'future' : '');
    cells += `<div class="cd ${k} ${key === c.today ? 'today' : ''}" title="${v ? esc(usdS(v.usd)) + (v.partial ? ' (partial day)' : '') : ''}"><i>${d}</i>${v && v.usd !== 0 ? `<b>${esc(usdC(v.usd).replace('$', v.usd > 0 ? '+$' : '$'))}</b>` : ''}</div>`;
  }
  $('#cal').innerHTML = `<div class="cwk">${['M', 'T', 'W', 'T', 'F', 'S', 'S'].map(x => `<span>${x}</span>`).join('')}</div><div class="cgrid">${cells}</div>`;
}
$('#calPrev').onclick = () => { if (!CALM) return; const [y, m] = CALM.split('-').map(Number), d = new Date(y, m - 2, 1); CALM = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; loadCalendar() };
$('#calNext').onclick = () => { if (!CALM) return; const [y, m] = CALM.split('-').map(Number), d = new Date(y, m, 1); CALM = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; loadCalendar() };
$('#range').onclick = e => { const b = e.target.closest('[data-r]'); if (!b) return; RANGE = b.dataset.r; store.set('nx_range', RANGE); loadHistory() };
$('#allocMode').onclick = e => { const b = e.target.closest('[data-m]'); if (!b) return; ALLOC = b.dataset.m; store.set('nx_alloc', ALLOC); if (ST) renderAlloc() };
$('#holdMore').onclick = () => { HOLD_ALL = !HOLD_ALL; if (ST) renderHoldings() };

/* ---------- socials ---------- */
function growth(label, g) { return g ? `<span>${label} <b class="${cls(g.change)}">${esc(numS(g.change))}</b>${g.partial ? '*' : ''}</span>` : '' }
function renderSocials() {
  const el = $('#soc');
  const tot = SOC.reduce((s, a) => s + (a.followers || 0), 0);
  $('#socinfo').textContent = SOC.length ? `TOTAL AUDIENCE ${num(tot)}` : '';
  if (!SOC.length) {
    el.innerHTML = '<div class="soc empty">Track followers, growth and the likes/views of your latest posts. Add your YouTube, Instagram, X, Telegram or Discord accounts.<button type="button" class="mini" data-open-social>+ ADD ACCOUNT</button></div>'; return;
  }
  el.innerHTML = '<div class="soc-grid">' + SOC.map(a => {
    const g = a.growth || {}, up = (g.d30 ? g.d30.change : 0) >= 0, url = safeUrl(a.url);
    const stats = Object.entries(a.stats || {}).map(([k, v]) => `${esc(num(v))} ${esc(k)}`).join(' · ');
    return `<div class="soc"><div class="h"><span class="plat plat-${esc(a.platform)}">${esc(a.platform_label.toUpperCase())}</span><b title="${esc(a.title || a.name)}">${esc(a.name)}</b>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="Open">↗</a>` : ''}</div>
      ${a.followers === null ? '<div class="n">—</div>' : `<div class="n">${esc(num(a.followers))}<small>FOLLOWERS</small></div>`}
      <div class="g">${growth('24H', g.d1)}${growth('7D', g.d7)}${growth('30D', g.d30)}</div>
      ${spark(g.spark, up ? cv('--pos') : cv('--neg'), 100, 34)}
      ${stats ? `<div class="st">${stats}</div>` : ''}
      ${a.posts && a.posts.length ? `<div class="ps">${a.posts.slice(0, 3).map(p => { const u = safeUrl(p.url), t = esc(p.title || 'post');
        const m = [p.likes != null ? `♥ ${compact(p.likes)}` : '', p.views != null ? `${compact(p.views)} views` : '', p.comments != null ? `${compact(p.comments)} comments` : ''].filter(Boolean).join(' · ');
        return `<div class="p"><span>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${t}</a>` : t}</span><span>${esc(m)}</span></div>` }).join('')}</div>` : ''}
      ${a.error ? `<div class="e">${esc(a.error)}</div>` : ''}</div>`;
  }).join('') + '</div>';
}
async function loadSocials(force) {
  try { SOC = (await api('/api/socials' + (force ? '?force=true' : ''))).accounts } catch (e) { SOC = [] }
  renderSocials(); if (typeof LIVE !== 'undefined') LIVE.onSocials();
}

async function loadMarkets() { try { MKTS = (await api('/api/markets')).markets || []; renderMarkets(MKTS); if (typeof LIVE !== 'undefined') LIVE.onMarkets(MKTS) } catch (e) { MKTS = []; renderMarkets([]) } }

/* ---------- status polling ---------- */
function renderAll() {
  const s = ST;
  $('#connBtn').classList.toggle('cta', !!s.demo);   // demo on: CONNECTIONS pulses until the demo is turned off and real accounts are added
  $('#demoBanner').hidden = !s.demo; $('#scBtn').hidden = !s.can_shortcut; if (typeof DONATE !== 'undefined') DONATE.sync(s);
  $('#welcome').hidden = s.configured || s.demo || s.has_socials;
  renderTotal(); renderAccounts(); renderAlloc(); renderTiles(); renderPositions(); renderHoldings();
}
async function refreshStatus(force) {
  try { ST = await api('/api/status' + (force ? '?force=true' : '')); offline = false; renderAll(); if ((ST.vault_error || ST.shortcut_error || ST.say_error) && !window.__scNote) { window.__scNote = 1; $('#note').textContent = ST.vault_error || ST.say_error || ST.shortcut_error } if (typeof maybeIntro === 'function') maybeIntro(); if (typeof LIVE !== 'undefined') LIVE.onStatus() } catch (e) { offline = true }
  statusText();
}
function everything() { refreshStatus(); loadHistory(); loadCalendar(); loadMarkets(); loadSocials() }
setInterval(() => { if (!document.hidden) refreshStatus() }, 15000);
setInterval(() => { if (!document.hidden) { loadHistory(); loadMarkets() } }, 60000);
setInterval(() => { if (!document.hidden) { loadSocials(); loadCalendar() } }, 180000);

/* reset PnL: two clicks */
let resetArm = 0;
$('#resetBtn').onclick = async e => {
  const b = e.currentTarget;
  if (!resetArm) { resetArm = setTimeout(() => { resetArm = 0; b.textContent = 'RESET PNL'; b.classList.remove('sure') }, 4000); b.textContent = 'SURE?'; b.classList.add('sure'); return }
  clearTimeout(resetArm); resetArm = 0; b.textContent = 'RESET PNL'; b.classList.remove('sure');
  try { await api('/api/reset', { confirm: true }); everything() } catch (err) {}
};

/* ---------- layout + view popover ---------- */
function applyLayout() { const c = store.get('nx_layout', 'orb') === 'charts'; document.body.classList.toggle('cfirst', c); $('#layoutBtn').textContent = c ? 'CHARTS FIRST' : 'ORB FIRST'; setTimeout(redrawChart, 30) }
$('#layoutBtn').onclick = () => { store.set('nx_layout', store.get('nx_layout', 'orb') === 'charts' ? 'orb' : 'charts'); applyLayout() };
$('#gear').onclick = () => { const p = $('#pop'); p.hidden = !p.hidden; $('#gear').setAttribute('aria-expanded', String(!p.hidden)) };
document.addEventListener('click', e => { if (!e.target.closest('#pop') && !e.target.closest('#gear')) { $('#pop').hidden = true; $('#gear').setAttribute('aria-expanded', 'false') } });

/* ---------- chat + voice ---------- */
const synth = ('speechSynthesis' in window) ? window.speechSynthesis : null;
let voiceOn = store.get('nx_voice', '1') === '1',   // voice is ON by default (until the user switches it off)
     voice = null, chatBusy = false;
const active = new Set();
function loadVoices() {
  if (!synth) { $('#vbtn').disabled = true; $('#vsel').hidden = true; return }
  const vs = synth.getVoices().filter(v => /^en/i.test(v.lang)).sort((a, b) => (/natural|online/i.test(b.name) - /natural|online/i.test(a.name)) || a.name.localeCompare(b.name));
  $('#vsel').innerHTML = vs.map(v => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join('');
  const saved = store.get('nx_voice_name', ''); voice = vs.find(v => v.name === saved) || vs.find(v => /zira/i.test(v.name) && /en-US/i.test(v.lang)) || vs.find(v => /zira/i.test(v.name)) || vs[0] || null;   // default: Microsoft Zira (US English) if installed
  if (voice) $('#vsel').value = voice.name;
}
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices }
$('#vsel').onchange = () => { voice = synth.getVoices().find(v => v.name === $('#vsel').value) || null; store.set('nx_voice_name', $('#vsel').value) };
function paintVoice() { $('#vbtn').textContent = 'VOICE: ' + (voiceOn ? 'ON' : 'OFF') }
$('#vbtn').onclick = () => { voiceOn = !voiceOn; store.set('nx_voice', voiceOn ? '1' : '0'); paintVoice(); if (!voiceOn) stopTalking() };
paintVoice();
let serverTalk = false;

/* the caption is typed out as Iris speaks it: it follows the voice's word positions when the browser reports them, otherwise the expected speaking time */
const CAP = (() => {
  let timer = null, hold = null, armed = false, el = null, full = '', t0 = 0, dur = 1, shown = 0, bf = -1, lastB = 0, useB = false;
  const paint = n => {
    if (n >= full.length) { if (el.firstElementChild) el.textContent = full; return true }
    el.textContent = ''; const a = document.createElement('span'), b = document.createElement('span');
    a.textContent = full.slice(0, n); b.className = 'ghost'; b.textContent = full.slice(n); el.append(a, b); return false;
  };
  function finish() { clearInterval(timer); timer = null; clearTimeout(hold); hold = null; armed = false; if (el && el.textContent === full && el.firstElementChild) el.textContent = full; el = null }
  function tick() {
    if (!el || el.textContent !== full) { clearInterval(timer); timer = null; el = null; return }   // the caption was replaced by something else
    const now = performance.now(), byTime = Math.min(1, (now - t0) / dur) * full.length;
    const live = useB && bf >= 0 && now - lastB < 900;       // the voice is reporting its word positions: follow them exactly, otherwise keep up by the clock (never fall behind)
    shown = Math.max(shown, live ? bf * full.length : byTime);
    if (paint(Math.floor(shown))) finish();
  }
  /* spoken: the text being said; sinceMs: how long ago the speech was requested (the app's own voice answers a moment late) */
  function start(spoken, sinceMs) {
    clearTimeout(hold); hold = null;
    const e = $('#reply');
    if (timer && el === e && e.textContent === full) { useB = Math.abs(full.length - spoken.length) <= spoken.length * .2; return }   // already typing this caption (it started early): carry on
    if (!armed || el !== e || e.textContent !== full) { finish(); if (!e || !e.textContent.trim()) return; el = e; full = e.textContent; shown = 0 }
    armed = false; t0 = performance.now() - (sinceMs || 0); dur = Math.max(600, full.length * 56); bf = -1; lastB = 0;
    useB = Math.abs(full.length - spoken.length) <= spoken.length * .2;   // word positions only make sense when the caption IS the spoken text
    clearInterval(timer); timer = setInterval(tick, 30); tick();
  }
  /* called the moment speech is requested: hide the text right away and start typing when the voice starts, or after a short wait if the browser is slow or never says it started */
  function arm(spoken) {
    finish(); const e = $('#reply'); if (!e || !e.textContent.trim()) return;
    el = e; full = e.textContent; shown = 0; armed = true; paint(0);
    hold = setTimeout(() => start(spoken, 0), 700);
  }
  return { start, arm, finish, bound(f) { if (el) { bf = Math.max(bf, Math.min(1, f)); lastB = performance.now() } } };
})();
function stopTalking() { CAP.finish(); if (synth) synth.cancel(); active.clear(); NX.speaking = false; stopTour(); statusText(); if (serverTalk) { serverTalk = false; api('/api/say/stop', {}).catch(() => {}) } }
$('#mute').onclick = stopTalking;
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (typeof infoOpen === 'function' && infoOpen()) { closeInfo(); return } stopTalking(); closeConn() } });
function serverSay(text, onStart) {      // the browser blocked speech (no click yet): the app itself speaks through the computer's voice
  if (!ST || !ST.can_say) { $('#note').textContent = 'Click anywhere on the page to hear Iris.'; return }
  const asked = performance.now();
  api('/api/say', { text }).then(r => {
    if (!r.ok) { $('#note').textContent = 'Click anywhere on the page to hear Iris.'; return }
    serverTalk = true; NX.speaking = true; statusText(); CAP.start(text, Math.min(1500, performance.now() - asked)); if (onStart) onStart();
    setTimeout(() => { if (serverTalk) { serverTalk = false; NX.speaking = false; statusText(); CAP.finish() } }, speakMs(text));
  }).catch(() => {});
}
function speak(text, onStart, force, srv) {     // srv: if the browser blocks speech, let the app speak instead
  if (!synth) { if (srv && (voiceOn || force)) serverSay(text, onStart); return }
  if (!voiceOn && !force) { stopTour(); if (onStart) setTimeout(onStart, 0); return }   // voice is off: still highlight the area, just silently
  stopTalking(); SPEECH.f = 0; SPEECH.last = 0;
  const clean = text.replace(/[*_#`]/g, ''), u = new SpeechSynthesisUtterance(clean);
  let began = false, fell = false;
  const fallback = () => { if (srv && !began && !fell) { fell = true; serverSay(clean, onStart) } };
  if (voice) u.voice = voice;
  u.onstart = () => { began = true; NX.speaking = true; statusText(); CAP.start(clean); if ($('#note').textContent.startsWith('Click anywhere')) $('#note').textContent = ''; if (onStart) onStart() };
  u.onboundary = ev => { NX.kick(.18); if (ev && typeof ev.charIndex === 'number' && clean.length) { const f = (ev.charIndex + (ev.charLength || 5)) / clean.length; CAP.bound(f); SPEECH.f = Math.min(1, f); SPEECH.last = performance.now() } };
  const done = () => { active.delete(u); NX.speaking = active.size > 0; statusText(); if (!active.size) CAP.finish() };
  u.onend = done; u.onerror = ev => { done(); if (ev && ev.error === 'not-allowed') fallback() };
  active.add(u); CAP.arm(clean); synth.speak(u);
  if (srv) setTimeout(() => { if (!began && active.has(u)) fallback() }, 1600);
}

const SUGGEST = ["What's my total balance?", 'How did I do this week?', 'Which assets am I most exposed to?', 'Do I have any open positions at risk?',
  'How much BTC do I hold across everything?', "What's moving in the market today?", 'Which of my accounts is the biggest?', 'How are my socials growing?',
  'What share of my portfolio is in stablecoins?', 'Summarize my portfolio in two sentences.'];
const GUIDE_SUGGEST = ['What is Iris?', 'How do I get started?', 'Is it safe? Can it trade?', 'How do I add my Claude key?', "What's my total balance?", 'How does PnL work?'];
function showSuggestions() {
  if (typeof LIVE !== 'undefined') return LIVE.paint();
  const pick = [...(ST && !ST.ai_ready ? GUIDE_SUGGEST : SUGGEST)].sort(() => Math.random() - .5).slice(0, 3);
  $('#sugg').innerHTML = pick.map(t => `<button type="button" class="bub">${esc(t)}</button>`).join('');
}
$('#sugg').onclick = e => { const b = e.target.closest('.bub'); if (b) { if (typeof LIVE !== 'undefined') LIVE.asked(b.title || b.textContent); send(b.title || b.textContent) } };

async function send(text) {
  text = (text || '').trim(); if (!text || chatBusy) return;
  if (typeof LIVE !== 'undefined' && LIVE.isBriefingAsk(text)) { $('#msg').value = ''; LIVE.briefing(); showSuggestions(); return }   // answered locally, no AI call
  const L = typeof LIVE !== 'undefined' ? LIVE.local(text) : null;      // no Claude key yet: answered right here from the numbers on the page
  if (L) { stopTalking(); setExplain(false); $('#you').textContent = '> ' + text; $('#reply').textContent = L.reply; $('#note').textContent = L.note || ''; $('#msg').value = ''; speak(L.reply); if (L.sel) tour([[L.sel, speakMs(L.reply) + 1500]]); showSuggestions(); return }
  chatBusy = true; stopTalking(); setExplain(false); NX.busy = true; statusText();
  $('#you').textContent = '> ' + text; $('#reply').textContent = '…'; $('#note').textContent = ''; $('#msg').value = '';
  try {
    const r = await api('/api/chat', { text });
    $('#reply').textContent = r.reply; $('#note').textContent = r.note || ''; setExplain(!!r.guide);
    if (!r.error) speak(r.reply);
    if (r.guide && FOCUS[r.focus]) tour([[FOCUS[r.focus], speakMs(r.reply) + 1500]]);
    if (r.needs_key) setTimeout(() => openConn('g-ai'), 400);
  } catch (e) { $('#reply').textContent = 'Something went wrong: ' + e.message }
  chatBusy = false; NX.busy = false; statusText(); showSuggestions();
}
$('#form').onsubmit = e => { e.preventDefault(); send($('#msg').value) };

/* ---------- welcome intro + demo tour (shown while no Claude key is saved) ---------- */
const INTRO_PARTS = [
  ["Hi, I'm Iris, your crypto control room.", '#welcome'], ["I run only on your computer.", '#welcome'],
  ["I show your balances across exchanges and wallets, your open futures positions, how your profit and loss is moving, and how your social accounts are growing.", '#welcome'],
  ["Everything is read-only, so I can never trade or move your money.", '#welcome'],
  ["To get started, press Try Demo Data to look around with made-up numbers.", '#wDemo'],
  ["When you're ready, open Connections and add a read-only key or a public wallet address, and later your Claude key, so I can answer questions about your real numbers.", '#wOpen,#connBtn'],
  ["Until then, tap a question below and I'll show you what I can do.", '#sugg']];
const INTRO_TEXT = INTRO_PARTS.map(x => x[0]).join(' ');
const DEMO_PARTS = [
  ["This is demo data, all made up.", '#demoBanner'], ["Your total balance and profit and loss are at the top.", '[data-sec=balance]'],
  ["The charts show your balance over time, what you hold, and a calendar of daily changes.", '[data-sec=portfolio],[data-sec=allocation]'],
  ["Futures positions, markets and socials are further down.", '[data-sec=markets],[data-sec=socials]'],
  ["Tap a question below to try me.", '#sugg'], ["When you're ready, open Connections, add your real accounts, and switch the demo off.", '#connBtn']];
const DEMO_TEXT = DEMO_PARTS.map(x => x[0]).join(' ');
const INTRO_SHOW = "Hi, I'm Iris. Press TRY DEMO DATA to look around, or open Connections to add your accounts. Tap a question below to see what I can do.";
const DEMO_SHOW = "This is demo data, all made up. Tap a question below to try me. When you're ready, open Connections and add your real accounts.";
let introShown = false;
function speakIntro(force) { speak(INTRO_TEXT, () => { store.set('nx_intro_boot', String(ST && ST.boot)); tour(stepsFor(INTRO_PARTS), true) }, force, true) }
function maybeIntro() {
  if (introShown || !ST || ST.ai_ready || (ST.accounts && ST.accounts.length && ST.total_usd > 0)) return; introShown = true; showSuggestions();
  if (!ST.demo) { $('#you').textContent = ''; $('#reply').textContent = INTRO_SHOW; setExplain(true) }
  const heard = () => store.get('nx_intro_boot', '') === String(ST.boot);     // the welcome plays automatically once per start of Iris
  if (!heard()) {
    speakIntro();   // browsers often block speech until the first click, so also try again on the first click or key press
    const again = e => { if (!heard() && !(e.target.closest && e.target.closest('#vbtn,#mute,#gear,#vsel'))) speakIntro() };
    document.addEventListener('pointerdown', again, { once: true }); document.addEventListener('keydown', again, { once: true });
  }
}
$('#wHear').onclick = () => { $('#you').textContent = ''; $('#note').textContent = ''; $('#reply').textContent = INTRO_SHOW; setExplain(true); speakIntro(true) };

/* ---------- connections ---------- */
let CONN = null, armed = null;
const infoBtn = (id, title) => `<button type="button" class="ibtn" data-act="info" data-id="${esc(id)}" title="How does this work?" aria-label="How does ${esc(title)} work?">i</button>`;
const infoOpen = () => !$('#info').hidden;
function closeInfo() { $('#info').hidden = true }
function openInfo(id) {
  if (!CONN) return;
  const p = CONN.providers.find(x => x.id === id), h = p ? p.help : (CONN.help || {})[id];
  if (!h) return;
  const title = p ? p.title : id === 'wallets' ? 'Wallets' : 'Tracked accounts';
  $('#infoTitle').textContent = 'HOW IT WORKS · ' + title.toUpperCase();
  let html = `<h4>WHAT IT DOES</h4><p>${esc(h.what)}</p><h4>HOW TO SET IT UP</h4><ol>${(h.steps || []).map(x => `<li>${esc(x)}</li>`).join('')}</ol>`;
  if (h.permissions) html += `<h4>PERMISSIONS &amp; SAFETY</h4><div class="perm">${esc(h.permissions)}</div>`;
  if (h.extra) html += `<h4>GOOD TO KNOW</h4><p>${esc(h.extra)}</p>`;
  if (p && p.link && /^https:\/\//.test(p.link)) html += `<a class="gotolink" href="${esc(p.link)}" target="_blank" rel="noopener noreferrer">Open the page where you get the key ↗</a>`;
  $('#ibody').innerHTML = html; $('#info').hidden = false; $('#info').scrollTop = 0;
}
$('#iclose').onclick = closeInfo;
$('#info').addEventListener('mousedown', e => { if (e.target === $('#info')) closeInfo() });
const GROUPS = [['ai', 'g-ai', 'CLAUDE AI (CHAT)'], ['exchange', 'g-ex', 'EXCHANGES'], ['wallet', 'g-wallet', 'WALLETS (PUBLIC ADDRESSES)'],
  ['social', 'g-social', 'SOCIALS'], ['network', 'g-net', 'ADVANCED']];
function capture() { const m = {}; $$('#mbody [data-key]').forEach(i => { if (!i.disabled) m[i.dataset.key] = i.type === 'checkbox' ? i.checked : i.value }); return m }
function restore(m) { $$('#mbody [data-key]').forEach(i => { if (i.disabled || !(i.dataset.key in m)) return; if (i.type === 'checkbox') i.checked = m[i.dataset.key]; else i.value = m[i.dataset.key] }) }

function providerCard(p) {
  const saved = p.fields.some(f => f.set), L = p.locked;
  const fields = p.fields.map(f => {
    const key = `${p.id}:${f.key}`; let ctl;
    if (f.options) ctl = `<select data-key="${esc(key)}" ${L ? 'disabled' : ''}>${f.options.map(o => `<option ${o === (f.value || f.default) ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    else if (f.secret) ctl = L ? `<input type="text" value="${esc(f.value)}" disabled>` : `<input type="password" autocomplete="new-password" spellcheck="false" data-key="${esc(key)}" placeholder="${esc(f.set ? 'leave blank to keep ' + f.value : f.placeholder || (f.required ? 'required' : 'optional'))}">`;
    else ctl = `<input type="text" data-key="${esc(key)}" value="${esc(f.value)}" ${L ? 'disabled' : ''} spellcheck="false">`;
    return `<div class="frow"><label>${esc(f.label)}${f.required ? '' : ' <span style="opacity:.6">(optional)</span>'}</label>${ctl}${f.help ? `<div class="hint">${esc(f.help)}</div>` : ''}</div>`;
  }).join('');
  const btns = L
    ? `<button type="button" data-act="unlock" data-id="${p.id}">UNLOCK TO EDIT</button><button type="button" data-act="test" data-id="${p.id}">TEST</button>`
    : `<button type="button" class="primary" data-act="save" data-id="${p.id}">SAVE &amp; LOCK</button>${saved ? `<button type="button" data-act="test" data-id="${p.id}">TEST</button><button type="button" data-act="remove" data-id="${p.id}">REMOVE</button>` : ''}`;
  return `<div class="card" id="card-${p.id}"><div class="ch"><b>${esc(p.title)}</b>${infoBtn(p.id, p.title)}<span class="pill ${p.configured ? 'on' : ''}">${p.configured ? 'CONNECTED' : 'NOT SET'}</span>${L ? '<span class="pill lock">LOCKED</span>' : ''}<div class="sp"></div>${p.link ? `<a href="${esc(p.link)}" target="_blank" rel="noopener noreferrer" style="color:var(--c);font-size:13px">Get a key ↗</a>` : ''}</div>
    <div class="bl">${esc(p.blurb)}</div>${fields}<div class="cbtn">${btns}</div><div class="res" id="res-${p.id}"></div></div>`;
}

function renderConn() {
  const C = CONN, mem = capture(); let h = '';
  for (const [g, anchor, title] of GROUPS) {
    h += `<div class="mgroup" id="${anchor}"><div class="ptitle">${title}${g === 'wallet' ? infoBtn('wallets', 'Wallets') : ''}</div>`;
    if (g === 'wallet') {
      h += C.wallets.length ? C.wallets.map(w => `<div class="wrow"><span class="n">${esc(w.name)}<small>${esc(C.chains[w.chain] || w.chain)} · ${esc(w.address.slice(0, 6) + '…' + w.address.slice(-6))}${w.chain === 'evm' ? ' · ' + esc(w.networks.join(', ')) : ''}</small></span>
        <button type="button" class="mini" data-act="wlock" data-name="${esc(w.name)}" data-locked="${w.locked}">${w.locked ? 'LOCKED' : 'UNLOCKED'}</button>
        <button type="button" class="mini" data-act="wremove" data-name="${esc(w.name)}" ${w.locked ? 'disabled title="Unlock first"' : ''}>REMOVE</button></div>`).join('') : '<div class="sub">No wallets yet. Only PUBLIC addresses; Iris can look but never move anything.</div>';
      h += `<div class="addform">
        <input data-key="w-name" placeholder="Name (e.g. Main wallet)" maxlength="24"><select data-key="w-chain">${Object.entries(C.chains).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
        <input class="full" data-key="w-addr" placeholder="Public address (never a seed phrase or private key)" spellcheck="false" autocomplete="off">
        <div class="full nets" id="w-nets">${C.evm_networks.map(n => `<label class="chk"><input type="checkbox" data-key="w-net-${n}" ${C.default_evm.includes(n) ? 'checked' : ''}>${esc(n)}</label>`).join('')}</div>
        <div class="full"><button type="button" class="primary" data-act="wadd">ADD WALLET</button></div></div><div class="msg err" id="w-msg"></div>`;
    } else if (g === 'social') {
      h += C.providers.filter(p => p.group === 'social').map(providerCard).join('');
      h += `<div class="ptitle" style="margin-top:14px">TRACKED ACCOUNTS${infoBtn('social_accounts', 'Tracked accounts')}</div>`;
      h += C.social_accounts.length ? C.social_accounts.map(a => `<div class="srow"><span class="n">${esc(a.name)}<small>${esc((C.platforms[a.platform] || {}).label || a.platform)} · ${esc(a.handle)}</small></span>
        <button type="button" class="mini" data-act="slock" data-name="${esc(a.name)}" data-locked="${a.locked}">${a.locked ? 'LOCKED' : 'UNLOCKED'}</button>
        <button type="button" class="mini" data-act="sremove" data-name="${esc(a.name)}" ${a.locked ? 'disabled title="Unlock first"' : ''}>REMOVE</button></div>`).join('') : '<div class="sub">No accounts yet. Add the key for a platform above, then the account here (Discord needs no key).</div>';
      h += `<div class="addform"><input data-key="s-name" placeholder="Name (e.g. My channel)" maxlength="24"><select data-key="s-plat">${Object.entries(C.platforms).map(([k, v]) => `<option value="${k}">${esc(v.label)}${v.needs_key && !v.key_ready ? ' (add key first)' : ''}</option>`).join('')}</select>
        <input class="full" data-key="s-handle" id="s-handle" placeholder="${esc((Object.values(C.platforms)[0] || {}).handle || '')}" spellcheck="false" autocomplete="off">
        <div class="full"><button type="button" class="primary" data-act="sadd">ADD ACCOUNT</button></div></div><div class="msg err" id="s-msg"></div>`;
    } else {
      h += C.providers.filter(p => p.group === g).map(providerCard).join('');
    }
    h += '</div>';
  }
  h += `<div class="mgroup"><div class="ptitle">DEMO DATA</div><div class="card"><div class="bl">Fill the dashboard with made-up numbers to look around or take screenshots. Nothing real is read or changed.</div>
    <div class="cbtn"><button type="button" data-act="demo" data-on="${!C.demo}">${C.demo ? 'TURN OFF DEMO DATA' : 'TURN ON DEMO DATA'}</button></div></div></div>`;
  $('#mbody').innerHTML = h; restore(mem); syncWalletForm(); syncSocialForm();
}
function syncWalletForm() { const c = $('#mbody [data-key="w-chain"]'); if (c && $('#w-nets')) $('#w-nets').hidden = c.value !== 'evm' }
function syncSocialForm() { const p = $('#mbody [data-key="s-plat"]'); if (p && CONN && $('#s-handle')) $('#s-handle').placeholder = (CONN.platforms[p.value] || {}).handle || '' }
$('#mbody').addEventListener('change', e => { if (e.target.dataset.key === 'w-chain') syncWalletForm(); if (e.target.dataset.key === 's-plat') syncSocialForm() });

async function openConn(anchor) {
  try { CONN = await api('/api/connections') } catch (e) { return }
  $('#modal').hidden = false; document.body.style.overflow = 'hidden'; renderConn();
  if (anchor) { const el = document.getElementById(anchor); if (el) el.scrollIntoView({ block: 'start' }) } else $('#modal').scrollTop = 0;
}
function closeConn() { if ($('#modal').hidden) return; $('#modal').hidden = true; document.body.style.overflow = ''; everything() }
$('#connBtn').onclick = () => openConn(); $('#mclose').onclick = closeConn;
$('#modal').addEventListener('mousedown', e => { if (e.target === $('#modal')) closeConn() });
$('#wOpen').onclick = () => openConn(); $('#wDemo').onclick = () => setDemo(true); $('#demoOff').onclick = () => setDemo(false);
$('#socAdd').onclick = () => openConn('g-social');
$('#soc').addEventListener('click', e => { if (e.target.closest('[data-open-social]')) openConn('g-social') });
async function setDemo(on) {
  const doTour = on && ST && !ST.ai_ready;
  await api('/api/demo', { on }); if (!$('#modal').hidden) { CONN = await api('/api/connections'); renderConn() } everything();
  if (doTour) { if (typeof LIVE !== 'undefined') LIVE.skipBrief(); $('#you').textContent = ''; $('#note').textContent = ''; $('#reply').textContent = DEMO_SHOW; setExplain(true); speak(DEMO_TEXT, () => tour(stepsFor(DEMO_PARTS))) }
}

function showRes(id, html) { const el = document.getElementById('res-' + id); if (el) el.innerHTML = html }
function confirmTwice(btn, key) {   // first click arms the button, second click within 4 s goes through
  if (armed && armed.key === key) { clearTimeout(armed.t); armed = null; return true }
  if (armed) { clearTimeout(armed.t); armed.reset() }
  const old = btn.textContent; btn.textContent = 'SURE?'; btn.classList.add('sure');
  armed = { key, reset: () => { btn.textContent = old; btn.classList.remove('sure') }, t: setTimeout(() => { armed.reset(); armed = null }, 4000) };
  return false;
}

$('#mbody').addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) return;
  const act = b.dataset.act, id = b.dataset.id, name = b.dataset.name, say = (m, err) => { const t = $('#w-msg'); if (t) t.textContent = m };
  if (act === 'info') { openInfo(id); return }
  try {
    if (act === 'save') {
      const p = CONN.providers.find(x => x.id === id), values = {};
      p.fields.forEach(f => { const i = $(`#mbody [data-key="${id}:${f.key}"]`); if (i && i.value.trim()) values[f.key] = i.value.trim() });
      showRes(id, '<div class="l info">Saving…</div>'); CONN = await api('/api/connections/' + id, { values }); renderConn(); showRes(id, '<div class="l info">Saved and locked. Press TEST to check it.</div>');
    } else if (act === 'unlock') { CONN = await api(`/api/connections/${id}/lock`, { locked: false }); renderConn() }
    else if (act === 'remove') { if (!confirmTwice(b, 'rm' + id)) return; CONN = await api(`/api/connections/${id}/remove`, {}); renderConn() }
    else if (act === 'test') {
      showRes(id, '<div class="l info">Testing…</div>'); b.disabled = true;
      try {
        const r = await api(`/api/connections/${id}/test`, {});
        showRes(id, `<div class="l ${r.ok ? 'pos' : 'neg'}">${r.ok ? '✔' : '✖'} ${esc(r.message)}</div>` + (r.notes || []).map(n => `<div class="l ${r.danger && /WITHDRAW/.test(n) ? 'danger' : 'warn'}">⚠ ${esc(n)}</div>`).join(''));
      } finally { b.disabled = false }
    }
    else if (act === 'wadd') {
      const v = k => { const i = $(`#mbody [data-key="${k}"]`); return i ? i.value.trim() : '' };
      const nets = CONN.evm_networks.filter(n => { const i = $(`#mbody [data-key="w-net-${n}"]`); return i && i.checked });
      CONN = await api('/api/wallets', { name: v('w-name'), address: v('w-addr'), chain: v('w-chain'), networks: nets });
      ['w-name', 'w-addr'].forEach(k => { const i = $(`#mbody [data-key="${k}"]`); if (i) i.value = '' }); renderConn();
    } else if (act === 'wlock') { CONN = await api('/api/wallets/lock', { name, locked: b.dataset.locked !== 'true' }); renderConn() }
    else if (act === 'wremove') { if (!confirmTwice(b, 'w' + name)) return; CONN = await api('/api/wallets/remove', { name }); renderConn() }
    else if (act === 'sadd') {
      const v = k => { const i = $(`#mbody [data-key="${k}"]`); return i ? i.value.trim() : '' };
      CONN = await api('/api/social-accounts', { name: v('s-name'), platform: v('s-plat'), handle: v('s-handle') });
      ['s-name', 's-handle'].forEach(k => { const i = $(`#mbody [data-key="${k}"]`); if (i) i.value = '' }); renderConn();
    } else if (act === 'slock') { CONN = await api('/api/social-accounts/lock', { name, locked: b.dataset.locked !== 'true' }); renderConn() }
    else if (act === 'sremove') { if (!confirmTwice(b, 's' + name)) return; CONN = await api('/api/social-accounts/remove', { name }); renderConn() }
    else if (act === 'demo') { await setDemo(b.dataset.on === 'true') }
  } catch (err) {
    const msg = esc(err.message);
    if (['wadd', 'wlock', 'wremove'].includes(act)) $('#w-msg').innerHTML = msg;
    else if (['sadd', 'slock', 'sremove'].includes(act)) $('#s-msg').innerHTML = msg;
    else if (id) showRes(id, `<div class="l neg">✖ ${msg}</div>`);
  }
});

/* ---------- go ---------- */
applyTheme(store.get('nx_theme2', '') || 'solana'); applyViews(); applyLayout(); showSuggestions(); everything();
