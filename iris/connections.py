"""'Test connection' for every provider on the Connections screen. Returns {'ok': bool, 'message': str, 'notes': [...]}."""
from iris import net, providers, vault
from iris.exchanges import EXCHANGES


def _fmt_usd(x) -> str:
    return f"${x:,.2f}"


def test(pid: str) -> dict:
    if pid not in providers.BY_ID:
        raise KeyError("unknown connection")
    if not providers.is_configured(pid):
        return {"ok": False, "message": "Nothing saved yet.", "notes": []}
    vals = providers.values(pid)
    try:
        if pid in EXCHANGES:
            ex = EXCHANGES[pid](vals)
            acct = ex.fetch()
            perms = ex.permissions()
            notes = [w["text"] for w in perms]
            danger = any(w["level"] == "danger" for w in perms)
            return {"ok": True, "message": f"Connected. {_fmt_usd(acct['total_usd'])} across {len(acct['holdings'])} assets.",
                    "notes": acct["warnings"] + notes, "danger": danger}
        if pid == "pro":
            from iris import pro
            st = pro.status(force=True)
            if not st["active"]:
                return {"ok": False, "message": st["reason"] or "This license is not active.", "notes": []}
            ai = st.get("ai") or {}
            left = f" AI allowance used this month: {ai['used_pct']}%." if isinstance(ai.get("used_pct"), (int, float)) else ""
            return {"ok": True, "message": "Iris Pro is active." + left, "notes": ["No internet to the Pro server right now: using the last check."] if st.get("offline") else []}
        if pid == "finnhub":
            from iris import stocks
            q = stocks._from_finnhub("AAPL", vals["api_key"])
            return {"ok": True, "message": f"Finnhub key works (AAPL ${q['price']:.2f}).", "notes": []}
        if pid == "anthropic":
            import anthropic
            anthropic.Anthropic(api_key=vals["api_key"]).models.list(limit=1)
            return {"ok": True, "message": "Key accepted by Anthropic.", "notes": []}
        if pid == "youtube":
            net.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "id", "id": "UC_x5XG1OV2P6uZZ5FSM9Ttw", "key": vals["api_key"]})
            return {"ok": True, "message": "YouTube key works.", "notes": []}
        if pid == "telegram":
            me = net.get(f"https://api.telegram.org/bot{vals['bot_token']}/getMe")
            return {"ok": bool(me.get("ok")), "message": f"Bot @{(me.get('result') or {}).get('username', '?')} is valid.", "notes": []}
        if pid == "x":
            net.get("https://api.twitter.com/2/users/by/username/XDevelopers", headers={"Authorization": "Bearer " + vals["bearer_token"]})
            return {"ok": True, "message": "X token works.", "notes": []}
        if pid == "instagram":
            net.get(f"https://{vals.get('host', 'graph.facebook.com')}/v21.0/me", params={"fields": "id", "access_token": vals["access_token"]})
            return {"ok": True, "message": "Instagram token works.", "notes": []}
        if pid == "solana_rpc":
            net.post(vals["url"], json={"jsonrpc": "2.0", "id": 1, "method": "getVersion"}, retries=0)
            return {"ok": True, "message": "RPC answers.", "notes": []}
    except Exception as e:  # noqa: BLE001 - always return something readable
        return {"ok": False, "message": vault.scrub(str(e) if isinstance(e, net.ApiError) else f"{type(e).__name__}: {e}"), "notes": []}
    return {"ok": False, "message": "No test available.", "notes": []}
