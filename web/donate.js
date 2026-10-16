/* Optional donation to the developer, in SOL. Shown only once something real is connected.
   Iris never sees a key: it builds a plain SOL transfer and hands it to the person's own wallet (Phantom, or any wallet that
   supports the Wallet Standard), which shows the amount and address and asks for approval. */
const DONATE = (() => {
  const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  let ADDR = null, busy = false;

  function b58dec(s) {
    let n = 0n;
    for (const c of s) { const i = B58.indexOf(c); if (i < 0) throw new Error('bad address'); n = n * 58n + BigInt(i) }
    let h = n.toString(16); if (h.length % 2) h = '0' + h;
    const body = n === 0n ? [] : h.match(/../g).map(x => parseInt(x, 16));
    let z = 0; for (const c of s) { if (c === '1') z++; else break }
    return Uint8Array.from([...new Array(z).fill(0), ...body]);
  }
  function b58enc(u8) {
    let n = 0n; for (const b of u8) n = n * 256n + BigInt(b);
    let out = ''; while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n }
    for (const b of u8) { if (b === 0) out = '1' + out; else break }
    return out;
  }
  function le64(v) { const o = new Uint8Array(8); let x = BigInt(v); for (let i = 0; i < 8; i++) { o[i] = Number(x & 0xffn); x >>= 8n } return o }

  /* "0.1" -> lamports (exact, no floating point); null when it is not a sensible amount */
  function lamports(text) {
    const t = String(text || '').trim().replace(',', '.');
    if (!/^\d{0,6}(\.\d{0,9})?$/.test(t) || t === '' || t === '.') return null;
    const [w, f = ''] = t.split('.');
    const v = BigInt(w || '0') * 1000000000n + BigInt((f + '000000000').slice(0, 9));
    return v > 0n && v <= 100000n * 1000000000n ? v : null;
  }

  /* a legacy transaction with one System Program transfer: from -> to, fee paid by "from"; the wallet adds its signature.
     ref (optional, 32 bytes): a read-only "reference" account added to the transfer (Solana Pay style) so the payment can be found on the chain later */
  function buildTx(from, to, blockhash, lam, ref) {
    const head = ref ? [1, 0, 2, 4] : [1, 0, 1, 3], keys = ref ? [...from, ...to, ...new Uint8Array(32), ...ref] : [...from, ...to, ...new Uint8Array(32)];
    const ix = ref ? [1, 2, 3, 0, 1, 3, 12] : [1, 2, 2, 0, 1, 12];
    const msg = [...head, ...keys, ...blockhash, ...ix, 2, 0, 0, 0, ...le64(lam)];
    return Uint8Array.from([1, ...new Uint8Array(64), ...msg]);
  }

  const msg = (t, cls) => { const m = $('#donMsg'); m.textContent = t; m.className = 'donmsg' + (cls ? ' ' + cls : '') };
  const done = sig => {
    const m = $('#donMsg'); m.className = 'donmsg ok'; m.textContent = 'Thank you! Your donation was sent. ';
    const a = document.createElement('a'); a.href = 'https://solscan.io/tx/' + encodeURIComponent(sig); a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'View the transaction';
    m.appendChild(a);
  };

  /* ---- wallets ---- */
  function phantom() {
    const p = (window.phantom && window.phantom.solana) || window.solana;
    return p && p.isPhantom ? p : null;
  }
  function stdWallets() {              // Wallet Standard: other Solana wallets (Solflare, Backpack ...) announce themselves
    const found = [], api = { register(...w) { found.push(...w); return () => {} } };
    try { window.dispatchEvent(new CustomEvent('wallet-standard:app-ready', { detail: api })) } catch (e) { /* ignore */ }
    try { window.addEventListener('wallet-standard:register-wallet', e => { try { e.detail(api) } catch (x) { /* ignore */ } }, { once: true }) } catch (e) { /* ignore */ }
    return found.filter(w => w.features && w.features['solana:signAndSendTransaction'] && w.features['standard:connect']);
  }
  function walletName() {
    if (phantom()) return 'PHANTOM';
    const w = stdWallets()[0]; return w ? String(w.name || 'WALLET').toUpperCase() : 'PHANTOM';
  }
  const rejected = e => e && (e.code === 4001 || /reject|denied|declin|cancel/i.test(String(e.message || e)));

  async function viaPhantom(p, lam, to, ref) {
    const r = await p.connect();
    const from = b58dec(String((r && r.publicKey) || p.publicKey));
    const bh = await api('/api/donate/blockhash');
    const tx = buildTx(from, b58dec(to), b58dec(bh.blockhash), lam, ref ? b58dec(ref) : null);
    const out = await p.request({ method: 'signAndSendTransaction', params: { message: b58enc(tx) } });
    return out.signature || out;
  }
  async function viaStandard(w, lam, to, ref) {
    const { accounts } = await w.features['standard:connect'].connect();
    const acc = accounts && accounts[0]; if (!acc) throw new Error('no account selected');
    const bh = await api('/api/donate/blockhash');
    const tx = buildTx(Uint8Array.from(acc.publicKey), b58dec(to), b58dec(bh.blockhash), lam, ref ? b58dec(ref) : null);
    const [res] = await w.features['solana:signAndSendTransaction'].signAndSendTransaction({ account: acc, transaction: tx, chain: 'solana:mainnet' });
    return b58enc(res.signature);
  }

  /* sends lam lamports to "to" through the person's own wallet (it asks them to approve). ref: optional reference address. Returns the signature. */
  async function payTo(to, lam, ref) {
    let sig = null, last = null;
    const p = phantom();
    if (p) { try { sig = await viaPhantom(p, lam, to, ref) } catch (e) { if (rejected(e)) throw e; last = e } }
    if (!sig) { const w = stdWallets()[0]; if (w) sig = await viaStandard(w, lam, to, ref); else if (last) throw last }
    if (!sig) throw new Error('nowallet');
    return String(sig);
  }

  async function go() {
    if (busy) return;
    const lam = lamports($('#donAmt').value);
    if (!lam) { msg('Type an amount in SOL first, for example 0.1', 'err'); $('#donAmt').focus(); return }
    busy = true; $('#donGo').disabled = true; msg('Waiting for your wallet to ask you to approve...');
    try {
      done(await payTo(ADDR, lam, null));
    } catch (e) {
      const t = String((e && e.message) || e);
      if (t === 'nowallet') msg('No Solana wallet extension found here. In a normal browser, install Phantom; otherwise use "Open in any Solana wallet app" below, or copy the address.', 'err');
      else if (rejected(e)) msg('Cancelled. Nothing was sent.', '');
      else msg('Could not start the payment (' + t.slice(0, 120) + '). You can still use the wallet link or copy the address below.', 'err');
    } finally { busy = false; $('#donGo').disabled = false }
  }

  function uri() {
    const l = lamports($('#donAmt').value), a = l ? (Number(l) / 1e9).toString() : '';
    return 'solana:' + ADDR + '?label=' + encodeURIComponent('Iris development') + (a ? '&amount=' + a : '');
  }
  function open() {
    if (!ADDR) return;
    $('#donAddr').textContent = ADDR; $('#donGo').textContent = 'DONATE WITH ' + walletName(); msg('');
    $('#donUri').href = uri(); $('#donate').hidden = false; $('#donAmt').focus();
  }
  const close = () => { $('#donate').hidden = true };

  $('#donBtn').onclick = open; $('#donClose').onclick = close;
  $('#donate').addEventListener('pointerdown', e => { if (e.target.id === 'donate') close() });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#donate').hidden) close() });
  $('#donGo').onclick = go;
  $('#donAmt').addEventListener('input', () => { $('#donUri').href = uri(); if ($('#donMsg').classList.contains('err')) msg('') });
  $('#donAmt').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go() } });
  document.querySelectorAll('#donate .chip').forEach(b => b.onclick = () => { $('#donAmt').value = b.dataset.amt; $('#donUri').href = uri(); msg('') });
  $('#donCopy').onclick = async () => {
    try { await navigator.clipboard.writeText(ADDR); msg('Address copied.', 'ok') } catch (e) { msg('Select the address and copy it by hand.', 'err') }
  };

  return {
    sync(s) { ADDR = s.donate || null; $('#donBtn').hidden = !ADDR; if (!ADDR && !$('#donate').hidden) close() },
    payTo, walletName, rejected,
    _t: { b58dec, b58enc, buildTx, lamports },
  };
})();
