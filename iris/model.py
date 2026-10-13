"""The shape every account (exchange or wallet) is normalised to, so the dashboard and the AI treat them alike."""
import re

from iris import prices


def clean_symbol(s) -> str:
    """Token symbols come from third parties; keep them short and harmless (they also reach the AI)."""
    return re.sub(r"[^A-Za-z0-9$._\-]", "", str(s or ""))[:12] or "?"


def holding(symbol: str, amount: float, where: str = "", usd: float | None = "auto") -> dict:
    """One asset line. usd='auto' prices it from the public tickers; None means 'no price known'."""
    symbol = clean_symbol(symbol)
    if usd == "auto":
        usd = prices.value(symbol, amount)
    return {"symbol": symbol, "amount": amount, "usd": None if usd is None else round(float(usd), 2), "where": where}


def make_account(aid: str, name: str, kind: str, provider: str, holdings: list[dict], *, positions=None,
                 warnings=None, network: str = "") -> dict:
    priced = sorted((h for h in holdings if h["usd"] is not None and h["usd"] >= 0.01), key=lambda h: -h["usd"])
    unpriced = [h["symbol"] for h in holdings if h["usd"] is None and h["amount"]]
    positions = positions or []
    return {
        "id": aid, "name": name, "kind": kind, "provider": provider, "network": network,
        "total_usd": round(sum(h["usd"] for h in priced), 2),
        "holdings": priced, "unpriced": unpriced[:12], "positions": positions,
        "upnl_usd": round(sum(p.get("upnl", 0) or 0 for p in positions), 2),
        "warnings": warnings or [], "error": None, "stale": False,
    }


def error_account(aid: str, name: str, kind: str, provider: str, message: str) -> dict:
    return {"id": aid, "name": name, "kind": kind, "provider": provider, "network": "", "total_usd": None,
            "holdings": [], "unpriced": [], "positions": [], "upnl_usd": 0, "warnings": [], "error": message, "stale": False}


def f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default
