'use strict';
/* Market pulse panel (next to SOCIALS): important news and data releases, the economic calendar, Fear & Greed and a mood score.
   Free public sources only, nothing to set up. Loaded after live.js: it hands alerts and question bubbles to LIVE. Everything from the
   network goes through esc() or textContent. */
const MKT = (() => {
  const seenNews = new Set(), seenEv = new Set();
  let M = null, tried = false, first = true, tab = store.get('nx_mkt_tab', 'news'), on = store.get('nx_mkt_alerts', '1') === '1';
  const KEYEV = /fomc|\bfed\b|cpi|payroll|nonfarm|employment|unemployment|ppi|retail sales|gdp|powell|interest rate|pce/i;

  /* ---------- wording ---------- */
  const sayTxt = t => String(t || '').replace(/\+(?=\d)/g, 'plus ').replace(/(^|[\s(])-(?=\d)/g, '$1minus ').replace(/%/g, ' percent').replace(/\bFOMC\b/g, 'F O M C')
    .replace(/\bm\/m\b/gi, 'month on month').replace(/\by\/y\b/gi, 'year on year').replace(/\bq\/q\b/gi, 'quarter on quarter').replace(/\bNFP\b/g, 'non farm payrolls').replace(/\s+/g, ' ').trim();
  const sentence = t => /[.!?]$/.test(t) ? t : t + '.';
  const cut = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s };
  function inWords(min) {
    min = Math.round(min);
    if (min < 1) return 'moments';
    if (min < 60) return min + (min === 1 ? ' minute' : ' minutes');
    if (min < 36 * 60) { const h = Math.round(min / 60); return h + (h === 1 ? ' hour' : ' hours') }
    const d = Math.round(min / 1440); return d + (d === 1 ? ' day' : ' days');
  }
  const fcText = e => (e.forecast ? ' Forecast ' + sayTxt(e.forecast) + (e.previous ? ', previous ' + sayTxt(e.previous) : '') + '.' : e.previous ? ' Previous ' + sayTxt(e.previous) + '.' : '');
  const ago = t => { const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60)); return m < 1 ? 'now' : m < 60 ? m + 'm' : m < 1440 ? Math.floor(m / 60) + 'h' : Math.floor(m / 1440) + 'd' };
  const inShort = min => { if (Math.abs(min) < 1) return 'now'; const a = Math.abs(min), t = a < 60 ? Math.round(a) + 'm' : a < 2880 ? Math.floor(a / 60) + 'h ' + Math.round(a % 60) + 'm' : Math.round(a / 1440) + 'd'; return min >= 0 ? 'in ' + t : t + ' ago' };
  const sg = v => (v > 0 ? '+' : '') + v;
  const bls = t => String(t || '').replace(/^BLS data:\s*/, '');
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null && text !== '') e.textContent = text; return e };

  /* ---------- spoken alerts + bubbles ---------- */
  function newsSpeech(n) {
    if (n.source === 'BLS') return 'Data release. ' + sentence(sayTxt(bls(n.title)));
    return 'Market alert. ' + n.source + ': ' + sentence(sayTxt(n.title));
  }
  function check(m) {
    const now = m.now || Date.now() / 1000, fresh = [];
    (m.news || []).forEach(n => { if (seenNews.has(n.id)) return; seenNews.add(n.id); if (!first && n.imp >= 3 && now - n.ts < 25 * 60) fresh.push(n) });
    fresh.sort((a, b) => a.ts - b.ts).forEach(n => {
      const q = n.source === 'BLS' ? 'What does the new ' + cut(bls(n.title).replace(/\s+[+\-$\d].*$/, ''), 40) + ' data mean for the market?' : 'What does "' + cut(n.title, 56) + '" mean for crypto?';
      LIVE.event('mkt-news' + n.id, q, 'mkt-news', () => ({ reply: n.source + ' reported: ' + sentence(n.title) + ' Add your Claude key under Connections and I can explain what it could mean for the coins you hold.', sel: '[data-sec=market]' }));
      if (on) LIVE.alert(newsSpeech(n), 'mkt-news', 'MARKET ALERT');
    });
    (m.events || []).forEach(e => {
      if (e.country !== 'USD') return;
      const mins = (e.ts - now) / 60, key = KEYEV.test(e.title);
      const due = [60, 10, 0].filter(st => mins <= st && mins > (st === 0 ? -20 : -1) && !seenEv.has(e.id + '|' + st) && (st !== 60 || key));
      [60, 10, 0].forEach(st => { if (mins <= st) seenEv.add(e.id + '|' + st) });
      if (first || !due.length) return;
      const st = due[due.length - 1], t = sayTxt(e.title);
      const msg = st === 0 ? t + ' is out now.' + fcText(e) + (/fomc/i.test(e.title) ? ' Watch the statement and the press conference.' : '')
        : st === 10 ? t + ' in ' + inWords(Math.max(1, mins)) + '.' + fcText(e)
        : 'Heads up. ' + t + ' in about ' + inWords(mins) + '.' + fcText(e);
      if (st) LIVE.event('mkt-ev' + e.id + st, 'What should I expect from ' + cut(e.title, 40) + '?', 'mkt-cal', () => ({ reply: sentence(sayTxt(e.title)) + ' It is ' + (mins > 0 ? 'in ' + inWords(mins) : 'out now') + '.' + fcText(e), sel: '[data-sec=market]' }));
      if (on) LIVE.alert(msg, 'mkt-cal', 'MARKET ALERT');
    });
    first = false;
  }

  /* what is worth a mention in the startup briefing: only said when something important happened or is about to */
  function lines() {
    const m = M; if (!m) return [];
    const out = [], now = m.now || Date.now() / 1000;
    (m.news || []).filter(n => n.imp >= 3 && now - n.ts < 12 * 3600).slice(0, 2).forEach((n, i) => {
      const t = sentence(sayTxt(n.source === 'BLS' ? bls(n.title) : n.title));
      out.push(n.source === 'BLS' ? (i ? 'Also new data: ' : 'New data from the Bureau of Labor Statistics: ') + t : (i ? 'Also in the markets: ' : 'In the markets, ' + n.source + ' reports: ') + t);
    });
    const up = (m.events || []).filter(e => e.country === 'USD' && e.ts > now && e.ts - now < 24 * 3600 && KEYEV.test(e.title)).slice(0, 2);
    up.forEach(e => out.push('Coming up: ' + sayTxt(e.title) + ' in ' + inWords((e.ts - now) / 60) + '.' + fcText(e)));
    const nf = m.next_fomc;
    if (nf && !up.some(e => /fomc/i.test(e.title)) && nf.ts - now < 7 * 86400) out.push('The next Fed rate decision is in ' + inWords((nf.ts - now) / 60) + '.');
    const fg = m.fear_greed;
    if (fg && (fg.value <= 25 || fg.value >= 75 || (fg.yesterday != null && Math.abs(fg.value - fg.yesterday) >= 10)))
      out.push('Market mood: ' + fg.label + ', ' + fg.value + ' out of one hundred' + (fg.yesterday != null ? ', ' + (fg.value >= fg.yesterday ? 'up' : 'down') + ' from ' + fg.yesterday + ' yesterday.' : '.'));
    return out;
  }

  /* ---------- drawing ---------- */
  function drawMood(m) {
    const box = $('#mkmood'); box.textContent = '';
    if (!m) { box.append(el('div', 'sub err', 'Market data is not reachable right now. Check your internet connection.')); return }
    const mm = m.mood || {}, fg = m.fear_greed, top = el('div', 'mk-top');
    if (mm.score != null) {
      const sc = el('div', 'mk-score ' + (mm.score > 14 ? 'pos' : mm.score < -14 ? 'neg' : ''), mm.label); sc.append(el('small', '', sg(mm.score)));
      const bar = el('div', 'mk-bar'), pin = el('i'); pin.style.left = Math.max(2, Math.min(98, (mm.score + 100) / 2)) + '%'; bar.append(pin); top.append(sc, bar);
    }
    box.append(top);
    const facts = el('div', 'mk-facts');
    if (fg) { const f = el('span'); f.append('Fear & Greed ', Object.assign(el('b', fg.value >= 55 ? 'pos' : fg.value <= 45 ? 'neg' : ''), { textContent: fg.value + ' ' + fg.label })); facts.append(f) }
    const pr = mm.parts || {};
    [['news', 'Headlines'], ['reddit', 'Reddit']].forEach(([k, l]) => { if (pr[k] != null) { const f = el('span'); f.append(l + ' ', Object.assign(el('b', pr[k] > 14 ? 'pos' : pr[k] < -14 ? 'neg' : ''), { textContent: sg(pr[k]) })); facts.append(f) } });
    if (facts.childNodes.length) box.append(facts);
  }
  function drawBody(m) {
    const body = $('#mkbody'); body.textContent = '';
    $$('#mkTabs .stab').forEach(b => b.classList.toggle('active', b.dataset.t === tab));
    if (!m) return;
    const now = m.now || Date.now() / 1000;
    if (tab === 'events') {
      const list = (m.events || []).slice(0, 14);
      if (!list.length) body.append(el('div', 'sub', 'No high-impact events in the coming days.'));
      list.forEach(e => {
        const mins = (e.ts - now) / 60, r = el('div', 'mk-ev' + (mins < 60 && mins > -60 ? ' soon' : '') + (/fomc/i.test(e.title) ? ' fomc' : '')), nm = el('div', 'nm');
        nm.append(el('b', '', e.title), el('small', '', e.country + (e.forecast || e.previous ? ' · forecast ' + (e.forecast || '—') + ' · previous ' + (e.previous || '—') : '')));
        r.append(el('span', 'when', new Date(e.ts * 1000).toLocaleString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })), nm, el('span', 'in', inShort(mins)));
        body.append(r);
      });
    } else if (tab === 'talk') {
      if ((m.trending || []).length) { body.append(el('div', 'mk-sub', 'TRENDING COINS')); const c = el('div', 'mk-chips'); m.trending.forEach(t => c.append(el('span', 'mk-chip', t.symbol))); body.append(c) }
      const posts = ((m.reddit && m.reddit.posts) || []).slice(0, 6);
      if (posts.length) body.append(el('div', 'mk-sub', 'WHAT PEOPLE ARE TALKING ABOUT'));
      posts.forEach(p => { const a = el('a', 'mk-nw'), u = safeUrl(p.link); if (u) { a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer' } const b = el('div'); b.append(el('div', 'tp', 'r/' + p.sub), el('div', 'ti', p.title)); a.append(el('span', 'ag'), b); body.append(a) });
      if (!(m.trending || []).length && !posts.length) body.append(el('div', 'sub', 'Nothing to show yet. Trending coins and community posts appear here when their sources answer.'));
    } else {
      const news = (m.news || []).slice(0, 30);
      news.forEach(n => {
        const a = el('a', 'mk-nw' + (n.imp >= 3 && now - n.ts < 1800 ? ' hot' : '')), u = safeUrl(n.link);
        if (u) { a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer' }
        const b = el('div'), tp = el('div', 'tp');
        if (n.imp >= 2) tp.append(el('span', 'mk-pill b' + n.imp, n.imp >= 3 ? 'BREAKING' : 'IMPORTANT'));
        tp.append(document.createTextNode(n.source + ((n.also && n.also.length) ? ' +' + n.also.length : '')));
        b.append(tp, el('div', 'ti' + (n.tone > 0 ? ' up' : n.tone < 0 ? ' dn' : ''), n.title));
        a.append(el('span', 'ag', ago(n.ts)), b); body.append(a);
      });
      if (!news.length) body.append(el('div', 'sub', 'Waiting for the news feeds…'));
    }
    const errs = Object.keys(m.errors || {}).filter(k => k !== 'reddit' && k !== 'trending');
    const info = $('#mkinfo'); info.textContent = errs.length ? errs.length + ' SOURCE' + (errs.length > 1 ? 'S' : '') + ' OFFLINE' : 'LIVE'; info.title = errs.join(', ');
  }
  const render = m => { drawMood(m); drawBody(m) };

  async function load() {
    try { const m = await api('/api/market'); M = m; tried = true; if (!m.error) { check(m); if (typeof LIVE.onMarket === 'function') LIVE.onMarket(m) } render(m) }
    catch (e) { tried = true; if (!M) render(null) }
  }

  /* ---------- controls ---------- */
  $('#mkTabs').onclick = e => { const b = e.target.closest('.stab'); if (!b) return; tab = b.dataset.t; store.set('nx_mkt_tab', tab); drawBody(M) };
  const paintBtn = () => { const b = $('#mkBtn'); if (b) b.textContent = 'MARKET ALERTS: ' + (on ? 'ON' : 'OFF') };
  const mb = $('#mkBtn'); if (mb) mb.onclick = () => { on = !on; store.set('nx_mkt_alerts', on ? '1' : '0'); paintBtn() };
  paintBtn();
  load(); setInterval(() => { if (!document.hidden) load() }, 30000);

  return { ready: () => tried, lines, data: () => M };
})();
