/* Join the inner circle: a one-time payment in SOL opens a private Telegram group.
   The payment goes through the person's own wallet (see donate.js). The Iris server of the developer checks it on the chain and makes a
   join link that works only for the buyer's Telegram username. This page never holds a secret. */
const INNER = (() => {
  let info = { configured: false, price_sol: '0.2' }, busy = false, poll = null, uri = '';
  const msg = (t, cls) => { const m = $('#inMsg'); m.textContent = t; m.className = 'donmsg' + (cls ? ' ' + cls : '') };
  const view = s => { $('#inBuy').hidden = s !== 'buy'; $('#inDone').hidden = s !== 'done'; $('#inAd').hidden = s === 'done' };
  const stopPoll = () => { clearInterval(poll); poll = null };

  function showLink(link, who) {
    stopPoll(); $('#inWho').textContent = '@' + (who || ''); $('#inLink').textContent = link; $('#inOpen').href = link; view('done');
  }
  async function checkOnce() {
    const r = await api('/api/inner/check', {});
    if (r.paid && r.link) { showLink(r.link, r.username); return true }
    if (r.paid && !r.link) { stopPoll(); msg(r.note || 'Payment received, but the link could not be made. Tell the Iris developer.', 'err'); return true }
    return false;
  }
  function waitForPayment() {
    stopPoll(); let tries = 0; $('#inPaid').hidden = false;
    msg('Waiting for the payment to be confirmed on the Solana network (usually 15 to 40 seconds)...');
    poll = setInterval(async () => {
      if (++tries > 75) { stopPoll(); msg('Still waiting. If you approved the payment, press "I already paid, check again" in a minute.', ''); return }
      try { await checkOnce() } catch (e) { /* the network may blink: try again */ }
    }, 4000);
  }
  function walletUri(r) {
    return 'solana:' + r.recipient + '?amount=' + r.sol + '&reference=' + encodeURIComponent(r.reference) + '&label=' + encodeURIComponent('Iris inner circle') + '&message=' + encodeURIComponent('Inner circle for @' + r.username);
  }
  const userName = () => $('#inUser').value.trim().replace(/^@/, '');
  const goodUser = u => /^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(u);

  async function begin() {
    const u = userName();
    if (!goodUser(u)) { msg('Type your Telegram username, like @yourname (5 to 32 letters, digits or _).', 'err'); $('#inUser').focus(); return null }
    return api('/api/inner/start', { username: u });
  }
  async function pay() {
    if (busy) return; busy = true; $('#inGo').disabled = true;
    try {
      msg('Preparing your payment...');
      const r = await begin(); if (!r) return;
      uri = walletUri(r); $('#inUri').href = uri; msg('Waiting for your wallet to ask you to approve...');
      try { await DONATE.payTo(r.recipient, BigInt(r.lamports), r.reference) }
      catch (e) {
        const t = String((e && e.message) || e);
        if (t === 'nowallet') { msg('No Solana wallet found in this browser. Install Phantom, or use "Pay from a wallet app" below. We will keep watching for your payment.', 'err'); waitForPayment(); return }
        if (DONATE.rejected(e)) { msg('Cancelled. Nothing was sent.', ''); return }
        throw e;
      }
      waitForPayment();
    } catch (e) { msg(String((e && e.message) || e).slice(0, 220), 'err') }
    finally { busy = false; $('#inGo').disabled = !(info.configured && !(ST && ST.demo)) }
  }
  async function viaApp(ev) {       // a wallet on a phone: open the wallet app with the payment prepared
    if (uri) return;                // already prepared: let the link open
    ev.preventDefault();
    try { const r = await begin(); if (!r) return; uri = walletUri(r); $('#inUri').href = uri; waitForPayment(); location.href = uri } catch (e) { msg(String((e && e.message) || e).slice(0, 220), 'err') }
  }

  async function open() {
    $('#inner').hidden = false; uri = ''; $('#inUri').href = '#'; msg(''); view('buy'); $('#inPaid').hidden = true;
    const demo = !!(ST && ST.demo);
    try { info = await api('/api/inner') } catch (e) { /* keep what we know */ }
    $('#inGo').disabled = !info.configured || demo;
    $('#inGo').textContent = 'PAY ' + (info.price_sol || '0.2') + ' SOL WITH ' + (typeof DONATE !== 'undefined' ? DONATE.walletName() : 'PHANTOM');
    if (info.username) $('#inUser').value = '@' + info.username;
    if (info.link) { showLink(info.link, info.username); return }
    if (demo) msg('This is the demo, so nothing can be paid here. Download Iris to join.', '');
    else if (!info.configured) msg('The inner circle is not open yet. Check back soon.', '');
    else if (info.started) { $('#inPaid').hidden = false; msg('You started a payment earlier. If you paid, press "I already paid, check again".') }
    if (info.configured && !demo) $('#inUser').focus();
  }
  const close = () => { $('#inner').hidden = true; stopPoll() };

  $('#innerBtn').onclick = open; $('#inClose').onclick = close;
  $('#inner').addEventListener('pointerdown', e => { if (e.target.id === 'inner') close() });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#inner').hidden) close() });
  $('#inGo').onclick = pay;
  $('#inUser').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); if (!$('#inGo').disabled) pay() } });
  $('#inUri').onclick = viaApp;
  $('#inPaid').onclick = async e => { e.preventDefault(); msg('Checking...'); try { if (!(await checkOnce())) waitForPayment() } catch (x) { msg(String(x.message || x).slice(0, 200), 'err') } };
  $('#inCopy').onclick = async () => { try { await navigator.clipboard.writeText($('#inLink').textContent); $('#inCopy').textContent = 'COPIED'; setTimeout(() => { $('#inCopy').textContent = 'COPY' }, 1500) } catch (e) { /* select by hand */ } };
  return { open, close, walletUri };
})();
