"""Hyperliquid (beta): perps account value + spot balances for a PUBLIC address. No API key needed.

Note: accounts in Hyperliquid's unified mode may show collateral in both places; if the total looks doubled, tell us.
"""
from iris import net
from iris.model import f, holding, make_account

INFO = "https://api.hyperliquid.xyz/info"


def fetch(name: str, address: str) -> dict:
    perp = net.post(INFO, json={"type": "clearinghouseState", "user": address})
    holdings, positions = [], []
    value = f((perp.get("marginSummary") or {}).get("accountValue"))
    if value > 0:
        holdings.append(holding("USDC", value, "perps", usd=value))
    for ap in perp.get("assetPositions", []):
        p = ap.get("position") or {}
        szi = f(p.get("szi"))
        if szi == 0:
            continue
        lev = p.get("leverage") or {}
        positions.append({
            "exchange": "Hyperliquid", "symbol": f"{p.get('coin', '?')}-PERP", "side": "long" if szi > 0 else "short",
            "size": abs(szi), "entry": f(p.get("entryPx")), "mark": 0.0, "leverage": f(lev.get("value")),
            "upnl": round(f(p.get("unrealizedPnl")), 2), "liq": f(p.get("liquidationPx")) or None, "margin_mode": lev.get("type", ""),
        })
    try:
        spot = net.post(INFO, json={"type": "spotClearinghouseState", "user": address})
        for b in spot.get("balances", []):
            amt = f(b.get("total"))
            if amt > 0:
                holdings.append(holding(b.get("coin", "?"), amt, "spot", usd=amt if b.get("coin") in ("USDC", "USDH") else "auto"))
    except net.ApiError:
        pass
    return make_account(f"wallet:{name}", name, "wallet", "hyperliquid", holdings, positions=positions, network="Hyperliquid")
