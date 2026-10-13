/* Iris live layer: context-aware question bubbles that rotate across every section, spoken + highlighted alerts about changing data,
   occasional spoken observations, quick answers from the page's own numbers (when there is no Claude key yet), and the startup briefing.
   Loaded after app.js; it shares app.js's globals (ST, SOC, speak, send, store, $ ...). Everything here only READS the dashboard. */
const LIVE = (() => {
  const FRESH = 45 * 60 * 1000;
  let alertsOn = store.get('nx_alerts', '1') === '1', alertUntil = 0, nextAt = 0, drainT = null;
  const queue = [], events = [], asked = [], hist = [], prevSoc = {}, liqSeen = {}, LOCAL = new Map(), roeLvl = {}, acctHist = {}, acctSeen = {}, moveSeen = {}, socSeen = {};
  let prev = null, prevSig = null, shown = [], slot = 0, lastAi = null, lastHas = null, briefDone = false, briefTimer = null, demoScheduled = false, lastBig = 0, rotT = null,
      busyAt = 0, lastDaySign = 0, lastDayAt = 0, marketsSeen = false, moodPrev = null, fgPrev = null, ambI = 0, ambAt = Date.now() + 300000, lastSpoke = Date.now();

  /* ---------- small helpers ---------- */
  const money = v => { const a = Math.abs(v); return '$' + (a >= 100 ? Math.round(a).toLocaleString('en-US') : a.toFixed(2)) };
  const pctTxt = p => Math.abs(p).toFixed(Math.abs(p) < 10 ? 1 : 0) + ' percent';
  const base = s => String(s || '').replace(/[-_/].*$/, '');
  const FULL = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana' }, nameOf = sym => FULL[base(sym).toUpperCase()] || base(sym);
  const sgnTxt = v => (v < 0 ? 'minus ' : 'plus ');
  const roe = p => { const m = (p.size * p.entry) / (p.leverage || 1); return m > 0 ? p.upnl / m * 100 : null };   // return on the margin put in, like the exchange shows
  const closedTxt = (side, sym, ex, usd, pct, approx) => `A ${nameOf(sym)} ${side} on ${ex} has been closed.` + (usd == null ? '' : ` ${approx ? 'Last seen result' : 'Result'}: ${pct == null ? '' : sgnTxt(pct) + pctTxt(pct) + ', '}${sgnTxt(usd)}${money(usd)}.`);
  const hour = () => new Date().getHours();
  const greeting = () => { const h = hour(); return h >= 5 && h < 12 ? 'Good morning' : h >= 12 && h < 17 ? 'Good afternoon' : h >= 17 && h < 22 ? 'Good evening' : 'Good night' };
  const hasData = () => !!(ST && ST.accounts && ST.accounts.length && ST.total_usd > 0);
  const aiReady = () => !!(ST && ST.ai_ready);


  /* ---------- quick answers from the numbers already on the page (used while there is no Claude key; the AI answers everything otherwise) ---------- */
  const NOTE = 'Quick answer from your dashboard. Add your Claude key under Connections to ask anything about your numbers.';
  const SEC = { bal: '[data-sec=balance]', acc: '[data-sec=accounts]', alloc: '[data-sec=allocation]', mk: '[data-sec=markets]', pf: '[data-sec=portfolio]', hold: '[data-sec=holdings]', soc: '[data-sec=socials]', news: '[data-sec=market]' };
  const STABLE = new Set(['USDT', 'USDC', 'USD', 'DAI', 'FDUSD', 'TUSD', 'EUR', 'GBP']);
  const norm = t => String(t || '').toLowerCase().replace(/[^a-z0-9$% ]+/g, ' ').replace(/\s+/g, ' ').trim();
  const px = v => v >= 100 ? Math.round(v).toLocaleString('en-US') : v >= 1 ? v.toFixed(2) : String(+Number(v).toPrecision(2));
  const qty = v => v >= 100 ? Math.round(v).toLocaleString('en-US') : v >= 1 ? String(+v.toFixed(2)) : String(+Number(v).toPrecision(2));
  const ord = n => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
  const spk = t => String(t || '').replace(/\bm\/m\b/gi, 'month on month').replace(/\by\/y\b/gi, 'year on year').replace(/\bq\/q\b/gi, 'quarter on quarter').replace(/\s+/g, ' ').trim();
  const tag = () => (ST && ST.demo ? ' This is demo data.' : '');
  const R = (reply, sel) => ({ reply, sel, note: NOTE });
  const upDn = v => (v >= 0 ? 'up' : 'down');
  const mk = () => (typeof MKT !== 'undefined' && MKT.data && MKT.data()) || null;
  const heldMap = () => new Map(((ST && ST.holdings) || []).map(h => [String(h.symbol).toUpperCase(), h]));
  const closeness = p => (p.liq && p.mark ? Math.abs(p.mark - p.liq) / p.mark : null);
  const A = {
    account(name) {
      const a = ((ST && ST.accounts) || []).find(x => x.name === name); if (!a) return null;
      if (a.error) return R(`${a.name} is not responding right now. Check its key under Connections.`, SEC.acc);
      const top = (a.top || []).slice(0, 3).map(h => `${h.symbol} ${money(h.usd)}`).join(', '), n = ((ST.positions || []).filter(p => a.name.indexOf(p.exchange) === 0));
      return R(`${a.name} holds ${money(a.total_usd)}, ${Math.round(a.share_pct || 0)} percent of your total.` + (top ? ` The biggest parts are ${top}.` : '')
        + (n.length ? ` It has ${n.length} open position${n.length > 1 ? 's' : ''}.` : '') + tag(), SEC.acc);
    },
    pos(sym) {
      const p = ((ST && ST.positions) || []).find(x => base(x.symbol).toUpperCase() === String(sym).toUpperCase()); if (!p) return R(`I don't see an open ${nameOf(sym)} position right now.`, SEC.pf);
      const r = roe(p), d = closeness(p);
      return R(`Your ${nameOf(p.symbol)} ${p.side} on ${p.exchange}: ${qty(p.size)} from ${px(p.entry)}, now ${px(p.mark)}. It is ${upDn(p.upnl)} ${money(p.upnl)}` + (r != null ? `, ${pctTxt(r)} on the margin` : '')
        + '.' + (d != null ? ` Liquidation is at ${px(p.liq)}, ${pctTxt(d * 100)} away.` : '') + tag(), SEC.pf);
    },
    liq() {
      const P = ((ST && ST.positions) || []).filter(p => closeness(p) != null).sort((a, b) => closeness(a) - closeness(b)); if (!P.length) return R('You have no open positions with a liquidation price right now.', SEC.pf);
      const p = P[0], d = closeness(p);
      return R(`${nameOf(p.symbol)} ${p.side} on ${p.exchange} is closest, ${pctTxt(d * 100)} from liquidation at ${px(p.liq)}. ${d < .1 ? 'That is close, so keep an eye on it.' : 'That is a comfortable distance.'}` + tag(), SEC.pf);
    },
    bestPos(best) {
      const P = ((ST && ST.positions) || []).slice().sort((a, b) => best ? b.upnl - a.upnl : a.upnl - b.upnl); if (!P.length) return R('You have no open positions right now.', SEC.pf);
      const p = P[0];
      return R(`Your ${best ? 'best' : 'weakest'} open position is the ${nameOf(p.symbol)} ${p.side} on ${p.exchange}, ${upDn(p.upnl)} ${money(p.upnl)}. Together your positions are ${upDn(ST.upnl_usd || 0)} ${money(ST.upnl_usd || 0)}.` + tag(), SEC.pf);
    },
    day() {
      const d = ST && ST.pnl && ST.pnl.d1; if (!d || d.usd == null) return R('I am still collecting enough history to say what moved today.', SEC.bal);
      let t = `Over the last day you are ${upDn(d.usd)} ${money(d.usd)}, ${pctTxt(d.pct)}.`;
      const P = (ST.positions || []).slice().sort((a, b) => a.upnl - b.upnl);
      if (P.length) { const p = d.usd < 0 ? P[0] : P[P.length - 1]; t += ` Your open positions are ${upDn(ST.upnl_usd || 0)} ${money(ST.upnl_usd || 0)}; the ${d.usd < 0 ? 'weakest' : 'strongest'} is the ${nameOf(p.symbol)} ${p.side}, ${upDn(p.upnl)} ${money(p.upnl)}.` }
      const held = heldMap(), mv = (MKTS || []).filter(m => held.has(String(m.symbol).toUpperCase()) && !STABLE.has(m.symbol)).sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h))[0];
      if (mv) t += ` Among your coins, ${nameOf(mv.symbol)} moved most, ${upDn(mv.change24h)} ${pctTxt(mv.change24h)}.`;
      return R(t + tag(), SEC.bal);
    },
    hold(sym) {
      const h = ((ST && ST.holdings) || []).find(x => String(x.symbol).toUpperCase() === String(sym).toUpperCase()); if (!h || !h.usd) return R(`I don't see any ${sym} in your accounts.`, SEC.hold);
      const n = (h.in || []).length;
      return R(`You hold ${qty(h.amount)} ${nameOf(sym)}${n ? ` across ${n} account${n > 1 ? 's' : ''}` : ''}, worth ${money(h.usd)}, which is ${Math.round(h.usd / ST.total_usd * 100)} percent of your portfolio.` + tag(), SEC.hold);
    },
    biggest() {
      const H = ((ST && ST.holdings) || []).filter(h => h.usd > 0); if (!H.length) return null;
      const h = H[0], t = ST.total_usd, nxt = H.slice(1, 3).map(x => `${nameOf(x.symbol)} ${Math.round(x.usd / t * 100)} percent`).join(' and ');
      return R(`Your biggest holding is ${nameOf(h.symbol)}, ${money(h.usd)} or ${Math.round(h.usd / t * 100)} percent of everything.` + (nxt ? ` Next come ${nxt}.` : '') + tag(), SEC.alloc);
    },
    split() {
      const L = ((ST && ST.accounts) || []).filter(a => !a.error && a.total_usd > 0).slice(0, 4); if (!L.length) return null;
      return R('Your money is split like this: ' + L.map(a => `${a.name} ${Math.round(a.share_pct || 0)} percent`).join(', ') + '.' + tag(), SEC.acc);
    },
    mover(sym) {
      const m = (MKTS || []).find(x => String(x.symbol).toUpperCase() === String(sym).toUpperCase()); if (!m) return null; const h = heldMap().get(String(sym).toUpperCase());
      return R(`${nameOf(m.symbol)} is ${upDn(m.change24h)} ${pctTxt(m.change24h)} in the last 24 hours, at ${px(m.price)} dollars.` + (h ? ` You hold ${money(h.usd)} of it.` : '') + tag(), SEC.mk);
    },
    movers() {
      const L = (MKTS || []).filter(m => typeof m.change24h === 'number').sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h)).slice(0, 3); if (!L.length) return R('Market prices are not available right now.', SEC.mk);
      return R('Biggest moves in the last 24 hours: ' + L.map(m => `${nameOf(m.symbol)} ${upDn(m.change24h)} ${pctTxt(m.change24h)}`).join(', ') + '.' + tag(), SEC.mk);
    },
    cal() {
      const days = (CALD && CALD.days) || {}, k = Object.keys(days).filter(x => !days[x].partial || true); if (k.length < 2) return R('I need a few more days of history to compare your days.', SEC.pf);
      const best = k.reduce((a, b) => days[b].usd > days[a].usd ? b : a), worst = k.reduce((a, b) => days[b].usd < days[a].usd ? b : a), g = k.filter(x => days[x].usd > 0).length, r = k.filter(x => days[x].usd < 0).length;
      return R(`This month, your best day was the ${ord(+best.slice(8))} with ${sgnTxt(days[best].usd)}${money(days[best].usd)}, and your worst was the ${ord(+worst.slice(8))} with ${sgnTxt(days[worst].usd)}${money(days[worst].usd)}. You have ${g} green and ${r} red days, ${upDn(CALD.total)} ${money(CALD.total)} in total.` + tag(), SEC.pf);
    },
    soc(name) {
      const a = (SOC || []).find(x => x.name === name); if (!a) return null; if (a.error) return R(`${a.name} is not responding right now. Check it under Connections.`, SEC.soc);
      const g = a.growth || {}, part = (k, l) => (g[k] && !g[k].partial ? `${g[k].change >= 0 ? 'plus ' : 'minus '}${Math.abs(g[k].change).toLocaleString('en-US')} ${l}` : '');
      const bits = [part('d1', 'in a day'), part('d7', 'in a week'), part('d30', 'in a month')].filter(Boolean);
      const pl = a.platform_label || a.platform, onP = norm(a.name).includes(norm(pl)) ? '' : ` on ${pl}`;
      return R(`${a.name}${onP} has ${a.followers.toLocaleString('en-US')} followers` + (bits.length ? ': ' + bits.join(', ') : '') + '.' + tag(), SEC.soc);
    },
    socFast() {
      const L = (SOC || []).filter(a => a.growth && a.growth.d7 && !a.growth.d7.partial).sort((a, b) => b.growth.d7.pct - a.growth.d7.pct); if (!L.length) return R('Growth numbers build up while Iris is running, so I need a little more time.', SEC.soc);
      const a = L[0]; return R(`${a.name} is growing fastest this week, plus ${a.growth.d7.change.toLocaleString('en-US')} followers, ${pctTxt(a.growth.d7.pct)}. Together your audience is ${(SOC || []).reduce((t, x) => t + (x.followers || 0), 0).toLocaleString('en-US')}.` + tag(), SEC.soc);
    },
    mood() {
      const m = mk(); if (!m || m.error) return R('Market data is not reachable right now. Check your internet connection.', SEC.news);
      const mm = m.mood || {}, fg = m.fear_greed; let t = mm.label ? `The market mood is ${String(mm.label).toLowerCase()}` + (mm.score != null ? `, ${mm.score >= 0 ? 'plus' : 'minus'} ${Math.abs(mm.score)} on a scale of a hundred` : '') + '.' : '';
      if (fg) t += ` Fear and Greed is ${fg.value}, ${fg.label}` + (fg.yesterday != null ? `, ${fg.value >= fg.yesterday ? 'up' : 'down'} from ${fg.yesterday} yesterday` : '') + '.';
      return R((t || 'No sentiment data yet.') + tag(), SEC.news);
    },
    nextEvent() {
      const m = mk(), now = (m && m.now) || Date.now() / 1000, e = m && (m.events || []).filter(x => x.country === 'USD' && x.ts > now)[0];
      if (!e) return R('No big US events are coming up in the next few days.', SEC.news);
      const h = (e.ts - now) / 3600, when = h < 1 ? 'in under an hour' : h < 36 ? `in about ${Math.round(h)} hour${Math.round(h) === 1 ? '' : 's'}` : `in about ${Math.round(h / 24)} days`;
      return R(`Next up: ${spk(e.title)} ${when}.` + (e.forecast ? ` Forecast ${e.forecast}` + (e.previous ? `, previous ${e.previous}` : '') + '.' : '') + tag(), SEC.news);
    },
    headline() {
      const m = mk(), n = m && ((m.news || []).filter(x => x.imp >= 2)[0] || (m.news || [])[0]); if (!n) return R('No headlines yet. The news feeds are still loading.', SEC.news);
      const mins = Math.round(((m.now || Date.now() / 1000) - n.ts) / 60);
      return R(`${n.source}, ${mins < 2 ? 'just now' : mins < 60 ? mins + ' minutes ago' : Math.round(mins / 60) + ' hours ago'}: ${String(n.title).replace(/\s+/g, ' ')}` + (/[.!?]$/.test(n.title) ? '' : '.') + tag(), SEC.news);
    },
    connected() {
      const ac = (ST && ST.accounts) || [], names = ac.slice(0, 6).map(a => a.name).join(', '), sc = (SOC || []).length;
      if (!ac.length) return R('Nothing is connected yet. Open Connections to add an exchange, a wallet or a social account.', '#connBtn');
      return R(`You have ${ac.length} account${ac.length > 1 ? 's' : ''} connected: ${names}` + (ac.length > 6 ? ' and more' : '') + `. ${sc ? sc + ' social account' + (sc > 1 ? 's are' : ' is') + ' tracked.' : 'No social accounts are tracked yet.'}` + tag(), SEC.acc);
    },
    more() {
      const have = new Set(((ST && ST.accounts) || []).map(a => a.provider)), ex = ['binance', 'bybit', 'okx', 'mexc', 'kraken'].filter(x => !have.has(x)), ch = [['solana', 'Solana'], ['evm', 'Ethereum'], ['bitcoin', 'Bitcoin'], ['hyperliquid', 'Hyperliquid']].filter(x => !have.has(x[0])).map(x => x[1]);
      const NAMES = { binance: 'Binance', bybit: 'Bybit', okx: 'OKX', mexc: 'MEXC', kraken: 'Kraken' }, cap = w => NAMES[w] || w[0].toUpperCase() + w.slice(1);
      return R('Open Connections to add more.' + (ex.length ? ` Exchanges you can still add: ${ex.map(cap).join(', ')}.` : '') + (ch.length ? ` Wallets: ${ch.join(', ')}.` : '') + ' Social accounts work too: YouTube, Instagram, X, Telegram and Discord.', '#connBtn');
    },
  };
  const INTENTS = [   // typed questions, only used while there is no Claude key
    [/liquidat/, () => A.liq()], [/(best|strongest).*position|position.*(best|strongest)/, () => A.bestPos(true)], [/(worst|weakest).*position|position.*(worst|weakest)/, () => A.bestPos(false)],
    [/sentiment|\bmood\b|fear|greed/, () => A.mood()], [/headline|breaking|latest news|\bnews\b/, () => A.headline()], [/\b(fed|fomc|cpi|event|calendar)\b|coming up/, () => A.nextEvent()],
    [/best day|worst day|green day|red day/, () => A.cal()], [/moving|movers|mover|market today|biggest move/, () => A.movers()], [/fastest|growing fastest/, () => A.socFast()],
    [/biggest holding|most exposed|exposure|largest holding/, () => A.biggest()], [/split|breakdown|allocation/, () => A.split()],
    [/what (else )?can i (add|connect)|can i connect|which (exchanges|wallets)|more accounts/, () => A.more()], [/which accounts|what('?s| is) connected|connected accounts/, () => A.connected()],
    [/why .*(down|drop|fell|lower)|why .*(up|jump|rose|gain)|what drove|what moved/, () => A.day()],
  ];
  function local(text) {
    if (aiReady() || !ST) return null;
    try {
      const t = norm(text), f = LOCAL.get(t); if (f) { const r = f(); if (r) return r }
      for (const a of ST.accounts || []) if (a.name.length > 2 && t.includes(norm(a.name))) return A.account(a.name);
      for (const a of SOC || []) if (a.name.length > 2 && t.includes(norm(a.name))) return A.soc(a.name);
      for (const p of ST.positions || []) if (new RegExp('\\b' + base(p.symbol).toLowerCase() + '\\b').test(t) && /position|doing|long|short/.test(t)) return A.pos(base(p.symbol));
      for (const [re, fn] of INTENTS) if (re.test(t)) { const r = fn(); if (r) return r }
    } catch (e) { }
    return null;
  }

  /* ---------- startup briefing (also answers "briefing" / "recap" without using the AI) ---------- */
  function briefingParts() {
    const s = ST, p = [], B = '[data-sec=balance]';
    p.push([`${greeting()}. It is ${new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}.`, '']);
    p.push([`Your balance is ${money(s.total_usd)} across ${s.accounts.length} account${s.accounts.length === 1 ? '' : 's'}.`, B]);
    const d1 = s.pnl && s.pnl.d1, d7 = s.pnl && s.pnl.d7;
    if (d1 && d1.usd != null) p.push([`${d1.partial ? 'Since I started tracking' : 'Over the last day'} you are ${d1.usd >= 0 ? 'up' : 'down'} ${money(d1.usd)}, ${pctTxt(d1.pct)}.`, B]);
    if (d7 && d7.usd != null && !d7.partial) p.push([`Over the week you are ${d7.usd >= 0 ? 'up' : 'down'} ${money(d7.usd)}.`, B]);
    const pos = s.positions || [];
    if (pos.length) p.push([`You have ${pos.length} open position${pos.length === 1 ? '' : 's'}, ${s.upnl_usd >= 0 ? 'up' : 'down'} ${money(s.upnl_usd || 0)} unrealized.`, '[data-sec=portfolio]']);
    const bad = s.accounts.filter(a => a.error).map(a => a.name);
    if (bad.length) p.push([`${bad.slice(0, 2).join(' and ')} ${bad.length === 1 ? 'is' : 'are'} not responding.`, '[data-sec=accounts]']);
    const g = (SOC || []).filter(a => a.growth && a.growth.d7 && !a.growth.d7.partial && a.growth.d7.change > 0).sort((a, b) => b.growth.d7.change - a.growth.d7.change)[0];
    if (g) p.push([`${g.name} gained ${g.growth.d7.change.toLocaleString('en-US')} followers this week.`, '[data-sec=socials]']);
    const held = heldMap(), mv = (MKTS || []).filter(m => held.has(String(m.symbol).toUpperCase()) && !STABLE.has(m.symbol) && Math.abs(m.change24h) >= 4).sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h))[0];
    if (mv) p.push([`${nameOf(mv.symbol)} is ${upDn(mv.change24h)} ${pctTxt(mv.change24h)} today, and you hold ${money(held.get(String(mv.symbol).toUpperCase()).usd)} of it.`, '[data-sec=markets]']);
    if (typeof MKT !== 'undefined') MKT.lines().slice(0, 4).forEach(t => p.push([t, '[data-sec=market]']));       // news / data / Fed events that matter, only when there are any
    p.push([aiReady() ? 'Ask me anything below.' : 'Tap a question below to try me.', '#sugg']);
    return p;
  }
  const briefingText = () => briefingParts().map(x => x[0]).join(' ');
  function say(text, label) {
    $('#you').textContent = label ? '> ' + label : ''; $('#note').textContent = ''; $('#reply').textContent = text; setExplain(false);
    const parts = briefingParts(); speak(text, () => tour(stepsFor(parts)));
  }
  function briefing() { if (hasData()) say(briefingText(), 'BRIEFING') }
  function startupBriefing() {
    if (briefDone || !hasData()) return; briefDone = true;
    let started = false;
    const go = () => { if (!started) { const parts = briefingParts(); speak(parts.map(x => x[0]).join(' '), () => { started = true; tour(stepsFor(parts)) }, false, true) } };
    $('#you').textContent = '> BRIEFING'; $('#note').textContent = ''; $('#reply').textContent = briefingText();
    go();                                           // browsers often block speech before the first click, so retry on the first click or key press
    const again = e => { if (!started && !(e.target.closest && e.target.closest('#vbtn,#mute,#gear,#vsel,#alBtn'))) go() };
    document.addEventListener('pointerdown', again, { once: true }); document.addEventListener('keydown', again, { once: true });
  }

  /* ---------- alerts: highlighted caption + amber orb + spoken ---------- */
  function addEvent(key, q, area, ans) {
    if (ans) LOCAL.set(norm(q), ans);
    if (!aiReady() && !ans) return;                 // a question bubble needs the AI (or a ready answer from the page) to answer it
    for (let i = events.length - 1; i >= 0; i--) if (events[i].area === area) events.splice(i, 1);
    events.push({ key, q, area, t: Date.now() }); if (events.length > 12) events.shift();
    if (!shown.length || chatBusy || shown.some(x => x.q === q)) return;
    let at = shown.findIndex(x => x.hot && x.area === area); if (at < 0) at = shown.findIndex(x => !x.hot); if (at < 0) at = slot % shown.length;
    swap(at, { cat: 'ev:' + area, area, q, w: 12, hot: true });
  }
  const AREA_SEL = { pos: '[data-sec=portfolio]', liq: '[data-sec=portfolio]', demo: '[data-sec=portfolio]', big: '[data-sec=balance]', day: '[data-sec=balance]' };
  const areaSel = a => AREA_SEL[a] || (/^[\[#]/.test(a) ? a : /^mover-/.test(a) ? '[data-sec=markets]' : /^acct-/.test(a) ? '[data-sec=accounts]' : /^mood/.test(a) ? '[data-sec=market]' : '') || (/^(err|ok)-/.test(a) ? '[data-sec=accounts]' : /^soc-/.test(a) ? '[data-sec=socials]' : /^mkt-/.test(a) ? '[data-sec=market]' : '');
  function alertNow(item) {
    const msg = item.msg;
    alertUntil = Date.now() + 4000; statusText(); setTimeout(statusText, 4100);
    $('#you').textContent = '> ' + (item.label || 'ALERT'); $('#note').textContent = ''; $('#reply').textContent = msg; setExplain(false); speak(msg, () => tour([[item.sel, speakMs(msg) + 1500]]), false, true);
    nextAt = Date.now() + 6000 + msg.length * 60; lastSpoke = Date.now(); busyAt = voiceOn ? Date.now() : Date.now() + speakMs(msg);
  }
  function drain() {
    clearTimeout(drainT); if (!queue.length) return;
    const quick = !!queue[0].quick;                 // a follow-up that belongs right after the previous alert: waits only for it to finish speaking, plus a short pause
    if (active.size > 0) busyAt = Date.now();
    if (chatBusy || active.size > 0 || (quick ? Date.now() - busyAt < 2400 : Date.now() < nextAt)) { drainT = setTimeout(drain, quick ? 600 : 2000); return }
    alertNow(queue.shift()); if (queue.length) drainT = setTimeout(drain, queue[0].quick ? 600 : 2000);
  }
  function enqueue(msg, area, label, quick) {
    if (!alertsOn) return;
    if (queue.length < 6) queue.push({ msg, sel: areaSel(area), label, quick }); drain();
  }
  function push(msg, q, area, key, ans, quick) {
    addEvent(key || area + Date.now(), q, area, ans);
    enqueue(msg, area, undefined, quick);
  }
  const alerting = () => Date.now() < alertUntil;

  /* ---------- watching the status for real changes ---------- */
  function onStatus() {
    const s = ST; if (!s) return;
    if (lastAi !== aiReady() || lastHas !== hasData()) { lastAi = aiReady(); lastHas = hasData(); paint() }
    if (!briefTimer && hasData()) {                 // short wait so the socials and the market news are loaded and can be mentioned
      const t0 = Date.now(), go = () => { if (typeof MKT !== 'undefined' && !MKT.ready() && Date.now() - t0 < 9000) briefTimer = setTimeout(go, 700); else startupBriefing() };
      briefTimer = setTimeout(go, 2500);
    }
    if (s.demo && !demoScheduled) {                 // so the demo shows what an alert looks and sounds like
      demoScheduled = true;
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. A new Bitcoin long was just opened on Binance. This is how alerts sound.', 'What is my new BTC position doing?', 'demo') }, 28000);
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. ' + closedTxt('long', 'BTC-PERP', 'Binance', 186, 11.7), 'How did my BTC position do?', 'demo', 'demo-close', null, true) }, 30000);
      /* after the two trade alerts the demo shows OTHER kinds of changing data, spaced further apart (the market headline in the demo wire arrives at about 3 minutes) */
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. Solana is up 6 percent in the last 24 hours. You hold $7,950 of it.', 'How is SOL doing today?', 'mover-SOL', 'demo-mover', () => A.mover('SOL')) }, 120000);
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. Trading channel just gained 40 followers, now 48,250.', 'How is Trading channel growing?', 'soc-Trading channel', 'demo-soc', () => A.soc('Trading channel')) }, 250000);
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. Cold BTC just went up 2 percent to $31,470.', 'What changed in Cold BTC?', 'acct-Cold BTC', 'demo-acct', () => A.account('Cold BTC')) }, 370000);
      setTimeout(() => { if (ST && ST.demo) push('Demo alert. The market mood just changed from neutral to bullish.', 'What is the market sentiment right now?', 'mood', 'demo-mood', () => A.mood()) }, 490000);
    }
    const sig = (s.demo ? 'demo|' : '') + s.accounts.map(a => a.id).sort().join(',');
    if (sig !== prevSig) { prevSig = sig; prev = null; hist.length = 0 }          // demo toggled or an account added/removed: start watching from a fresh baseline, no false alerts
    const errs = new Set(s.accounts.filter(a => a.error).map(a => a.name)), inc = !!s.incomplete || errs.size > 0;
    const now = Date.now(), pos = new Map((s.positions || []).map(p => [`${p.exchange}|${p.symbol}|${p.side}`, p]));
    if (prev) {
      errs.forEach(n => { if (!prev.errs.has(n)) push(`${n} stopped responding. Check its key under Connections.`, `Why is ${n} not loading?`, 'err-' + n, null, () => A.account(n)) });
      prev.errs.forEach(n => { if (!errs.has(n) && s.accounts.some(a => a.name === n)) push(`${n} is back online.`, `How is ${n} doing?`, 'ok-' + n, null, () => A.account(n)) });
      if (!inc && !prev.inc) {
        pos.forEach((p, k) => { if (!prev.pos.has(k)) push(`New position: ${p.side} ${base(p.symbol)} on ${p.exchange}.`, `What is my new ${base(p.symbol)} position doing?`, 'pos', 'open' + k + now, () => A.pos(base(p.symbol))) });
        prev.pos.forEach((p, k) => { if (!pos.has(k)) push(closedTxt(p.side, p.symbol, p.exchange, typeof p.upnl === 'number' ? p.upnl : null, roe(p), true), `How did my ${base(p.symbol)} position do?`, 'pos', 'close' + k + now, () => R(closedTxt(p.side, p.symbol, p.exchange, typeof p.upnl === 'number' ? p.upnl : null, roe(p), true) + ' The exchange shows the final result.', SEC.pf)) });
      }
    }
    if (!inc) {                                     // 3 percent move within 10 minutes, at most one alert per 30 minutes
      hist.push([now, s.total_usd]); while (hist.length && now - hist[0][0] > 15 * 60 * 1000) hist.shift();
      const ref = hist.find(h => now - h[0] <= 10 * 60 * 1000);
      if (ref && ref[1] > 0 && now - lastBig > 30 * 60 * 1000) {
        const ch = (s.total_usd - ref[1]) / ref[1];
        if (Math.abs(ch) >= .03 && Math.abs(s.total_usd - ref[1]) >= 5) { lastBig = now; push(`Your balance just ${ch > 0 ? 'jumped' : 'dropped'} ${pctTxt(ch * 100)} to ${money(s.total_usd)}.`, ch > 0 ? 'Why did my balance just jump?' : 'Why did my balance just drop?', 'big', null, () => A.day()) }
      }
    }
    pos.forEach((p, k) => {                         // close to liquidation
      if (!p.liq || !p.mark) return;
      const d = Math.abs(p.mark - p.liq) / p.mark;
      if (d < .10 && now - (liqSeen[k] || 0) > 60 * 60 * 1000) { liqSeen[k] = now; push(`Careful. Your ${p.side} ${base(p.symbol)} on ${p.exchange} is ${pctTxt(d * 100)} away from liquidation.`, 'Which of my positions is closest to liquidation?', 'liq', 'liq' + k + now, () => A.liq()) }
    });
    if (!inc && prev) extraWatch(s, pos, now);
    prev = { errs, inc, pos };
  }

  /* ---------- more things worth saying out loud ---------- */
  const ROE_STEPS = [10, 25, 50, 100], lvl = r => { const a = Math.abs(r), st = ROE_STEPS.filter(x => a >= x).pop() || 0; return r < 0 ? -st : st };
  function extraWatch(s, pos, now) {
    pos.forEach((p, k) => {                         // a position crossing +/-10, 25, 50 or 100 percent on the margin
      const r = roe(p); if (r == null) return;
      const was = roeLvl[k], l = lvl(r);
      if (was == null) { roeLvl[k] = l; return }
      if (Math.abs(l) > Math.abs(was) && (l * was >= 0)) { roeLvl[k] = l; push(`Your ${nameOf(p.symbol)} ${p.side} on ${p.exchange} is now ${upDn(r)} ${pctTxt(r)}, ${sgnTxt(p.upnl)}${money(p.upnl)}.`, `What is my ${base(p.symbol)} position doing?`, 'pos', 'roe' + k + l, () => A.pos(base(p.symbol))) }
      else if (Math.abs(r) < Math.abs(was) - 5 || l * was < 0) roeLvl[k] = l;      // fell back (or flipped): re-arm
    });
    Object.keys(roeLvl).forEach(k => { if (!pos.has(k)) delete roeLvl[k] });
    s.accounts.forEach(a => {                       // one account moving on its own (a deposit, a big trade, a wallet changing)
      if (a.error || typeof a.total_usd !== 'number') return;
      const h = acctHist[a.name] || (acctHist[a.name] = []); h.push([now, a.total_usd]); while (h.length && now - h[0][0] > 15 * 60 * 1000) h.shift();
      const ref = h.find(x => now - x[0] <= 10 * 60 * 1000);
      if (ref && ref[1] > 0 && now - (acctSeen[a.name] || 0) > 30 * 60 * 1000 && now - lastBig > 60 * 1000) {
        const ch = (a.total_usd - ref[1]) / ref[1];
        if (Math.abs(ch) >= .02 && Math.abs(a.total_usd - ref[1]) >= 50) { acctSeen[a.name] = now; push(`${a.name} just ${ch > 0 ? 'went up' : 'dropped'} ${pctTxt(ch * 100)} to ${money(a.total_usd)}.`, `What changed in ${a.name}?`, 'acct-' + a.name, null, () => A.account(a.name)) }
      }
    });
    const d1 = s.pnl && s.pnl.d1;                   // the day turning from red to green (or the other way round)
    if (d1 && d1.usd != null && !d1.partial) {
      const sign = d1.usd > 0 ? 1 : d1.usd < 0 ? -1 : 0, big = Math.abs(d1.usd) >= Math.max(20, s.total_usd * .002);
      if (big && lastDaySign && sign !== lastDaySign && now - lastDayAt > 2 * 3600 * 1000) { lastDayAt = now; push(`Your day just turned ${sign > 0 ? 'positive' : 'negative'}. Over the last day you are ${upDn(d1.usd)} ${money(d1.usd)}, ${pctTxt(d1.pct)}.`, sign > 0 ? 'What drove my gains today?' : 'Why is my balance down today?', 'day', null, () => A.day()) }
      if (big) lastDaySign = sign;
    }
  }
  function onMarkets(list) {                        // a coin you hold moving 5 percent or more in 24 hours
    if (!ST || !hasData() || !Array.isArray(list)) return;
    const held = heldMap(), now = Date.now();
    list.forEach(m => {
      const sym = String(m.symbol).toUpperCase(), h = held.get(sym); if (!h || STABLE.has(sym) || typeof m.change24h !== 'number' || Math.abs(m.change24h) < 5) return;
      if (now - (moveSeen[sym] || 0) < 6 * 3600 * 1000) return;
      const firstLoad = !marketsSeen; moveSeen[sym] = now; if (firstLoad) return;   // the first load is covered by the startup briefing
      push(`${nameOf(sym)} is ${upDn(m.change24h)} ${pctTxt(m.change24h)} in the last 24 hours. You hold ${money(h.usd)} of it.`, `Why is ${sym} ${m.change24h > 0 ? 'up' : 'down'} today?`, 'mover-' + sym, 'mv' + sym + now, () => A.mover(sym));
    });
    marketsSeen = true;
  }
  function onMarket(m) {                            // the market mood (or Fear and Greed) changing its label
    const mm = m.mood && m.mood.label, fg = m.fear_greed && m.fear_greed.label;
    if (moodPrev && mm && mm !== moodPrev) push(`The market mood just changed from ${moodPrev.toLowerCase()} to ${mm.toLowerCase()}.`, 'What is the market sentiment right now?', 'mood', 'mood' + mm + Date.now(), () => A.mood());
    else if (fgPrev && fg && fg !== fgPrev) push(`Fear and Greed moved from ${fgPrev.toLowerCase()} to ${fg.toLowerCase()}, now ${m.fear_greed.value}.`, 'Is crypto fearful or greedy today?', 'mood', 'fg' + fg + Date.now(), () => A.mood());
    if (mm) moodPrev = mm; if (fg) fgPrev = fg;
  }

  /* ---------- a short spoken observation, only after about five quiet minutes (alerts about real changes come first and reset the wait) ---------- */
  const OBS = [
    () => { const d = ST.pnl && ST.pnl.d1; return d && d.usd != null ? [`Quick check. Your balance is ${money(ST.total_usd)}, ${upDn(d.usd)} ${money(d.usd)} over the last day.`, SEC.bal, 'How are we doing overall today?', () => A.day()] : null },
    () => { const r = A.biggest(); const h = ST.holdings && ST.holdings[0]; return r && h ? [`${nameOf(h.symbol)} is your biggest holding, ${Math.round(h.usd / ST.total_usd * 100)} percent of your portfolio.`, SEC.alloc, 'What is my biggest holding?', () => A.biggest()] : null },
    () => { const P = (ST.positions || []).slice().sort((a, b) => Math.abs(b.upnl) - Math.abs(a.upnl)); const p = P[0]; return p ? [`Your ${nameOf(p.symbol)} ${p.side} on ${p.exchange} is ${upDn(p.upnl)} ${money(p.upnl)} right now.`, SEC.pf, `What is my ${base(p.symbol)} position doing?`, () => A.pos(base(p.symbol))] : null },
    () => { const m = mk(); const mm = m && m.mood; return mm && mm.label ? [`The market mood is ${String(mm.label).toLowerCase()}` + (m.fear_greed ? `, and Fear and Greed reads ${m.fear_greed.value}.` : '.'), SEC.news, 'What is the market sentiment right now?', () => A.mood()] : null },
    () => { const held = heldMap(), mv = (MKTS || []).filter(m => held.has(String(m.symbol).toUpperCase()) && !STABLE.has(m.symbol)).sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h))[0]; return mv ? [`Of your coins, ${nameOf(mv.symbol)} is moving most today, ${upDn(mv.change24h)} ${pctTxt(mv.change24h)}.`, SEC.mk, `How is ${mv.symbol} doing today?`, () => A.mover(mv.symbol)] : null },
    () => { const L = (SOC || []).filter(a => a.growth && a.growth.d7 && !a.growth.d7.partial && a.growth.d7.change > 0).sort((a, b) => b.growth.d7.pct - a.growth.d7.pct)[0]; return L ? [`${L.name} is your fastest growing account this week, plus ${L.growth.d7.change.toLocaleString('en-US')} followers.`, SEC.soc, 'Which social is growing fastest?', () => A.socFast()] : null },
    () => { const m = mk(), now = (m && m.now) || Date.now() / 1000, e = m && (m.events || []).filter(x => x.country === 'USD' && x.ts > now && x.ts - now < 3 * 86400)[0]; return e ? [`Coming up: ${spk(e.title).replace(/[()]/g, '')}, in about ${Math.max(1, Math.round((e.ts - now) / 3600))} hours.`, SEC.news, 'What is the next big event?', () => A.nextEvent()] : null },
    () => { const days = (CALD && CALD.days) || {}, k = Object.keys(days); return k.length >= 3 ? [`This month you have ${k.filter(x => days[x].usd > 0).length} green days and ${k.filter(x => days[x].usd < 0).length} red days, ${upDn(CALD.total)} ${money(CALD.total)} in total.`, SEC.pf, 'What was my best day this month?', () => A.cal()] : null },
    () => (ST.stable_pct != null && ST.stable_pct > 0 ? [`${Math.round(ST.stable_pct)} percent of your balance is in stablecoins.`, SEC.alloc, 'What share of my portfolio is in stablecoins?', null] : null),
    () => { const ac = ST.accounts.filter(a => !a.error && a.total_usd > 0); return ac.length > 1 ? [`${ac[0].name} holds the most, ${Math.round(ac[0].share_pct || 0)} percent of your total.`, SEC.acc, 'How are my accounts split?', () => A.split()] : null },
  ];
  function ambient() {
    if (!alertsOn || !hasData() || document.hidden || chatBusy || queue.length || active.size > 0 || Date.now() < nextAt || Date.now() < ambAt || $('#msg').value) return;
    if (Date.now() - lastSpoke < (ST.demo ? 120000 : 300000)) return;
    for (let k = 0; k < OBS.length; k++) {
      const o = OBS[(ambI + k) % OBS.length]; let r = null; try { r = o() } catch (e) { }
      if (!r) continue; ambI = (ambI + k + 1) % OBS.length; ambAt = Date.now() + (ST.demo ? 90000 : 60000);
      const [msg, sel, q, ans] = r; if (q && (aiReady() || ans)) addEvent('amb' + Date.now(), q, sel, ans);
      enqueue(msg, sel, 'NOTE'); return;
    }
  }
  setInterval(ambient, 15000);
  const MILE = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
  function onSocials() {
    (SOC || []).forEach(a => {
      if (typeof a.followers !== 'number') return;
      const was = prevSoc[a.name]; prevSoc[a.name] = a.followers;
      if (was == null) return;
      const m = MILE.filter(t => was < t && a.followers >= t).pop(), diff = a.followers - was, now = Date.now();
      if (m) { socSeen[a.name] = now; push(`${a.name} just passed ${m.toLocaleString('en-US')} followers.`, `How is ${a.name} growing?`, 'soc-' + a.name, 'soc' + a.name + m, () => A.soc(a.name)) }
      else if (Math.abs(diff) >= Math.max(5, was * .0005) && now - (socSeen[a.name] || 0) > 20 * 60 * 1000) { socSeen[a.name] = now; push(`${a.name} just ${diff > 0 ? 'gained' : 'lost'} ${Math.abs(diff).toLocaleString('en-US')} follower${Math.abs(diff) === 1 ? '' : 's'}, now ${a.followers.toLocaleString('en-US')}.`, `How is ${a.name} growing?`, 'soc-' + a.name, 'sd' + a.name + now, () => A.soc(a.name)) }
    });
  }

  /* ---------- question bubbles that fit what is happening and the time of day ---------- */
  function candidates() {
    const out = [], ai = aiReady(), shuf = arr => arr.slice().sort(() => Math.random() - .5);
    if (!ST) return SUGGEST.map(q => ({ cat: q, q, w: 1 }));
    /* add(category, question, weight, local answer): with no Claude key only questions the page can answer itself are offered */
    const add = (cat, q, w, loc, guide) => { if (!ai && !loc && !guide) return; if (loc) LOCAL.set(norm(q), loc); out.push({ cat, q, w }) };
    events.filter(e => Date.now() - e.t < FRESH && (ai || LOCAL.has(norm(e.q)))).forEach(e => out.push({ cat: 'ev:' + e.area, area: e.area, q: e.q, w: 12 + 6 * (1 - (Date.now() - e.t) / FRESH), hot: true }));
    const h = hour(), s = ST, M = mk();
    if (hasData()) {
      add('total', 'How are we doing overall today?', 3, null, true); add('total', 'What is my total balance across everything?', 1, null, true);
      if (h >= 5 && h < 12) add('time', 'Give me my morning briefing.', 3, null, true); else if (h >= 17 && h < 22) add('time', 'Give me an end-of-day recap.', 3, null, true); else add('time', 'What should I check before tomorrow?', 2);
      const d1 = s.pnl && s.pnl.d1;
      if (d1 && d1.usd != null) add('pnl', d1.usd < 0 ? 'Why is my balance down today?' : 'What drove my gains today?', 3, () => A.day());
      add('pnl', 'How did I do this week?', 2, null, true);
      const held = [...heldMap().values()].filter(x => !STABLE.has(String(x.symbol).toUpperCase()));
      shuf(held.slice(0, 5)).slice(0, 2).forEach(x => add('hold', `How much ${x.symbol} do I hold across everything?`, 2, () => A.hold(x.symbol)));
      add('hold', 'What is my biggest holding?', 2, () => A.biggest()); add('hold', 'Which assets am I most exposed to?', 1);
      if ((s.stable_pct || 0) >= 30) add('hold', 'Am I holding too much in stablecoins?', 2, null, true);
      const P = s.positions || [];
      shuf(P).slice(0, 2).forEach(p => add('pos', `What is my ${base(p.symbol)} position doing?`, 3, () => A.pos(base(p.symbol))));
      if (P.length) { add('pos', 'Which position is closest to liquidation?', 2, () => A.liq()); add('pos', 'Which position is doing best?', 2, () => A.bestPos(true)); add('pos', 'Do I have any open positions at risk?', 2, null, true) }
      const ac = s.accounts.filter(a => !a.error);
      shuf(ac).slice(0, 2).forEach(a => add('acct', `How is ${a.name} doing?`, 2, () => A.account(a.name)));
      if (ac.length > 1) add('acct', 'How are my accounts split?', 2, () => A.split());
      s.accounts.filter(a => a.error).slice(0, 1).forEach(a => add('err', `Why is ${a.name} not loading?`, 5, () => A.account(a.name)));
      add('conn', 'Which accounts are connected?', 1, () => A.connected()); add('conn', 'What else can I connect?', 1, () => A.more());
      const mv = (MKTS || []).filter(m => typeof m.change24h === 'number' && held.some(x => String(x.symbol).toUpperCase() === String(m.symbol).toUpperCase())).sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h))[0];
      if (mv) add('mover', `How is ${mv.symbol} doing today?`, 3, () => A.mover(mv.symbol));
      const days = (CALD && CALD.days) || {}; if (Object.keys(days).length >= 3) { add('cal', 'What was my best day this month?', 2, () => A.cal()); add('cal', 'How many green days this month?', 1, () => A.cal()) }
    }
    if ((MKTS || []).length) add('mkts', "What's moving in the market today?", 2, () => A.movers());
    const g = (SOC || []).filter(a => a.growth && a.growth.d7 && !a.growth.d7.partial).sort((a, b) => b.growth.d7.change - a.growth.d7.change);
    if (g.length) { shuf(g.slice(0, 3)).slice(0, 2).forEach(a => add('soc', `How is ${a.name} growing?`, 2, () => A.soc(a.name))); add('soc', 'Which social is growing fastest?', 2, () => A.socFast()); add('soc', 'How are my socials growing?', 1, null, true) }
    if (M && !M.error) { add('mkt', 'What is the market sentiment right now?', 3, () => A.mood()); add('mkt', 'What is the latest headline?', 2, () => A.headline()); add('mkt', 'What is the next big event?', 2, () => A.nextEvent()); add('mkt', 'Is crypto fearful or greedy today?', 2, () => A.mood()) }
    if (!ai) {                                      // no Claude key: keep nudging towards what Iris can do and how to unlock it
      if (ST.demo) add('help', 'Which exchanges and wallets can I connect?', 3, null, true);
      add('help', 'How do I add my Claude key?', hasData() ? 2 : 3, null, true); add('help', 'How does PnL work?', 1, null, true); add('help', 'Is it safe? Can it trade?', 1, null, true);
      if (!hasData()) { add('help', 'What is Iris?', 3, null, true); add('help', 'How do I get started?', 3, null, true) }
    } else { add('misc', 'What should I keep an eye on right now?', 1); add('misc', 'Summarize my portfolio in two sentences.', 1) }
    return out;
  }
  function pickOne(keep) {
    let pool = candidates().filter(x => !asked.includes(x.q) && !keep.some(k => k.q === x.q));
    const fresh = pool.filter(x => !keep.some(k => k.cat === x.cat)); if (fresh.length) pool = fresh;
    if (!pool.length) pool = candidates().filter(x => !keep.some(k => k.q === x.q));
    if (!pool.length) return null;
    let r = Math.random() * pool.reduce((a, x) => a + x.w, 0), pick = pool[0];
    for (const x of pool) { r -= x.w; if (r <= 0) { pick = x; break } }
    return pick;
  }
  function fill(b, x) {
    b.textContent = ''; b.className = 'bub' + (x.hot ? ' hot' : ''); b.type = 'button'; b.title = x.q;
    if (x.hot) { const d = document.createElement('span'); d.className = 'dot'; b.append(d) }
    b.append(document.createTextNode(x.q));
  }
  function paint() {
    const box = $('#sugg'); if (!box) return;
    box.textContent = ''; shown = [];
    for (let i = 0; i < 3; i++) { const x = pickOne(shown); if (!x) break; shown.push(x); const b = document.createElement('button'); fill(b, x); b.style.animationDelay = i * 110 + 'ms'; box.append(b) }
  }
  function swap(i, x) {
    const b = $('#sugg') && $('#sugg').children[i]; if (!b || !x) return;
    b.style.animation = 'none'; b.classList.add('swapping');
    setTimeout(() => { fill(b, x); b.classList.add('swapping'); void b.offsetWidth; b.classList.remove('swapping'); shown[i] = x }, 290);
  }
  function rotate() {
    if (!shown.length || chatBusy || document.activeElement === $('#msg') || $('#msg').value) return;
    let i = slot % shown.length;
    for (let k = 0; k < shown.length; k++) { const j = (slot + k) % shown.length; if (!(shown[j].hot && events.some(e => e.q === shown[j].q && Date.now() - e.t < FRESH))) { i = j; break } }
    slot = i + 1;
    const x = pickOne(shown.filter((_, j) => j !== i)); if (x) swap(i, x);
  }
  rotT = setInterval(() => { if (!document.hidden) rotate() }, 8000);

  /* ---------- the alerts toggle (in the gear menu) ---------- */
  const paintAl = () => { const b = $('#alBtn'); if (b) b.textContent = 'ALERTS: ' + (alertsOn ? 'ON' : 'OFF') };
  const alBtn = $('#alBtn');
  if (alBtn) alBtn.onclick = () => { alertsOn = !alertsOn; store.set('nx_alerts', alertsOn ? '1' : '0'); if (!alertsOn) queue.length = 0; paintAl() };
  paintAl();

  return {
    paint, onStatus, onSocials, briefing, alerting, hasData, skipBrief() { briefDone = true },
    event: addEvent, alert: enqueue, local, onMarkets, onMarket,
    asked(q) { asked.push(q); if (asked.length > 16) asked.shift() },
    isBriefingAsk: t => /\b(briefing|recap)\b/i.test(t) && hasData(),
  };
})();
