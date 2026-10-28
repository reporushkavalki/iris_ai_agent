"""Demo mode: made-up numbers so you can look around (and take screenshots) without connecting anything.

Nothing here touches the network, your vault or your snapshots. All names and amounts are invented.
"""
import math
import random
import time
from datetime import datetime, timedelta

HOURS = 24 * 400
_series: list | None = None


def _hourly() -> list:
    """[(timestamp, total_usd)] for 400 days, a seeded random walk that ends at today's demo total."""
    global _series
    if _series is None:
        rnd = random.Random(7)
        end = int(time.time() // 3600 * 3600)
        walk, x = [], 0.0
        for _ in range(HOURS):
            x += rnd.gauss(0.0004, 0.0042)
            walk.append(x)
        _series = [(end - (HOURS - 1 - i) * 3600, round(_TOTAL * math.exp(w - walk[-1]), 2)) for i, w in enumerate(walk)]
    return _series


def _acct(aid, name, kind, provider, network, holdings, positions=(), warnings=()):
    hs = [{"symbol": s, "amount": a, "usd": u, "where": w} for s, a, u, w in holdings]
    total = round(sum(h["usd"] for h in hs), 2)
    return {"id": aid, "name": name, "kind": kind, "provider": provider, "network": network, "total_usd": total,
            "holdings": hs, "unpriced": [], "positions": list(positions), "upnl_usd": round(sum(p["upnl"] for p in positions), 2),
            "warnings": list(warnings), "error": None, "stale": False}


def _accounts() -> list[dict]:
    return [
        _acct("ex:binance", "Binance (demo)", "exchange", "binance", "", [
            ("BTC", 0.085, 5700.0, "spot"), ("ETH", 1.9, 6090.0, "spot"), ("BNB", 3.2, 2100.0, "spot"), ("USDT", 4530.0, 4530.0, "futures")],
              positions=[{"exchange": "Binance", "symbol": "BTC-PERP", "side": "long", "size": 0.12, "entry": 66100.0, "mark": 67050.0, "leverage": 5, "upnl": 114.0, "liq": 58400.0, "margin_mode": "cross"},
                         {"exchange": "Binance", "symbol": "ETH-PERP", "side": "short", "size": 1.5, "entry": 3260.0, "mark": 3205.0, "leverage": 3, "upnl": 82.5, "liq": 4010.0, "margin_mode": "isolated"}]),
        _acct("ex:bybit", "Bybit (demo)", "exchange", "bybit", "", [("USDT", 3980.0, 3980.0, "unified"), ("SOL", 11.5, 1840.0, "unified"), ("XRP", 1200.0, 640.0, "unified")],
              positions=[{"exchange": "Bybit", "symbol": "SOL-PERP", "side": "long", "size": 40.0, "entry": 158.0, "mark": 154.5, "leverage": 4, "upnl": -140.0, "liq": 121.0, "margin_mode": "cross"}]),
        _acct("wallet:Main SOL", "Main SOL", "wallet", "solana", "Solana", [("SOL", 38.2, 6110.0, "wallet"), ("JUP", 2400.0, 1920.0, "wallet"), ("BONK", 41000000.0, 980.0, "wallet"), ("USDC", 860.0, 860.0, "wallet")]),
        _acct("wallet:ETH Vault", "ETH Vault", "wallet", "evm", "Ethereum, Base, Arbitrum", [
            ("ETH", 2.6, 8330.0, "ethereum"), ("USDC", 2400.0, 2400.0, "base"), ("ARB", 1800.0, 1050.0, "arbitrum"), ("LINK", 40.0, 670.0, "ethereum")]),
        _acct("wallet:Cold BTC", "Cold BTC", "wallet", "bitcoin", "Bitcoin", [("BTC", 0.46, 30850.0, "wallet")]),
        _acct("stocks:Nordnet", "Nordnet (demo)", "stocks", "stocks", "", [("AAPL", 25.0, 5400.0, "shares"), ("NESTE.HE", 120.0, 2150.0, "shares"), ("GC=F", 1.5, 3600.0, "commodity")]),
    ]


_TOTAL = sum(a["total_usd"] for a in _accounts())


def status() -> dict:
    from iris import portfolio
    accts = _accounts()
    total = round(sum(a["total_usd"] for a in accts), 2)
    assets, by_acct, table = portfolio._allocation(accts, total)
    series = _hourly()
    now_v = series[-1][1]
    pnl = {}
    for key, hours in (("d1", 24), ("d7", 24 * 7), ("d30", 24 * 30)):
        base = series[-1 - hours][1]
        pnl[key] = {"usd": round(now_v - base, 2), "pct": round((now_v / base - 1) * 100, 2), "partial": False, "since": "demo"}
    pnl["tracking_since"] = None
    positions = sorted((dict(p, account=a["name"]) for a in accts for p in a["positions"]), key=lambda p: -abs(p["upnl"]))
    out_accts = []
    for a in sorted(accts, key=lambda a: -a["total_usd"]):
        out_accts.append({k: a[k] for k in ("id", "name", "kind", "provider", "network", "total_usd", "unpriced", "upnl_usd", "warnings", "error", "stale")}
                         | {"share_pct": round(a["total_usd"] / total * 100, 1), "top": [{"symbol": h["symbol"], "usd": h["usd"]} for h in a["holdings"][:4]],
                            "n_assets": len(a["holdings"])})
    return {"demo": True, "generated": time.time(), "configured": True, "total_usd": total, "pnl": pnl,
            "upnl_usd": round(sum(a["upnl_usd"] for a in accts), 2), "incomplete": False, "accounts": out_accts,
            "allocation": {"assets": assets, "accounts": by_acct}, "holdings": table, "positions": positions,
            "stable_pct": round(sum(e["usd"] for e in table if e["symbol"] in ("USDT", "USDC")) / total * 100, 1)}


def history(range_key: str) -> dict:
    span = {"1d": 24, "1w": 24 * 7, "1m": 24 * 30, "3m": 24 * 90}[range_key]
    pts = [[t, v] for t, v in _hourly()[-span:]]
    if len(pts) > 240:
        step = len(pts) / 240
        pts = [pts[min(len(pts) - 1, int((i + 1) * step) - 1)] for i in range(240)]
    return {"range": range_key, "points": pts, "start": pts[0][0], "end": pts[-1][0]}


def calendar(month: str | None) -> dict:
    today = datetime.now()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        first = datetime(y, m, 1)
    except (ValueError, AttributeError):
        first = datetime(today.year, today.month, 1)
    nxt = datetime(first.year + (first.month == 12), first.month % 12 + 1, 1)
    ends: dict = {}
    for t, v in _hourly():
        ends[datetime.fromtimestamp(t).strftime("%Y-%m-%d")] = v
    days, d = {}, first
    while d < nxt and d.date() <= today.date():
        k, p = d.strftime("%Y-%m-%d"), (d - timedelta(days=1)).strftime("%Y-%m-%d")
        if k in ends and p in ends:
            days[k] = {"usd": round(ends[k] - ends[p], 2), "partial": False}
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "days": days, "total": round(sum(v["usd"] for v in days.values()), 2), "today": today.strftime("%Y-%m-%d")}


def markets() -> list[dict]:
    rows = [("BTC", 67050.0, 1.4), ("ETH", 3205.0, -0.8), ("SOL", 154.5, 3.2), ("BNB", 656.0, 0.3), ("XRP", 0.53, -2.1), ("LINK", 16.7, 4.6)]
    out = []
    for i, (s, p, ch) in enumerate(rows):
        spark = [round(p * (1 - ch / 100) * (1 + (ch / 100) * k / 23 + 0.006 * math.sin(k * 0.9 + i * 2)), 4) for k in range(24)]
        out.append({"symbol": s, "price": p, "change24h": ch, "spark": spark})
    return out


def _spark(base: int, growth: float, seed: int) -> list[int]:
    rnd = random.Random(seed)
    return [int(base * (1 + growth * k / 29 + rnd.uniform(-0.002, 0.002))) for k in range(30)]


def socials() -> list[dict]:
    def g(now, d1, d7, d30, seed):
        pct = lambda d, base: round(d / base * 100, 2)
        return {"d1": {"change": d1, "pct": pct(d1, now - d1), "partial": False}, "d7": {"change": d7, "pct": pct(d7, now - d7), "partial": False},
                "d30": {"change": d30, "pct": pct(d30, now - d30), "partial": False}, "spark": _spark(now - d30, d30 / (now - d30), seed)}

    def post(title, **m):
        return {"title": title, "url": None, "ts": None, **m}
    base = {"error": None}
    return [
        {**base, "name": "Trading channel", "platform": "youtube", "platform_label": "YouTube", "handle": "@demo", "title": "Demo Trading Channel", "followers": 48210,
         "stats": {"views": 3120450, "videos": 142}, "url": None, "growth": g(48210, 38, 276, 1130, 1),
         "posts": [post("How I read funding rates (live example)", views=18420, likes=1310, comments=96), post("BTC weekly outlook", views=9860, likes=702, comments=41), post("Risk management in 10 minutes", views=24100, likes=2050, comments=133)]},
        {**base, "name": "Instagram", "platform": "instagram", "platform_label": "Instagram", "handle": "1784", "title": "@demo.trader", "followers": 21480,
         "stats": {"following": 312, "posts": 389}, "url": None, "growth": g(21480, 21, 140, 590, 2),
         "posts": [post("Weekly recap carousel", likes=842, comments=37), post("Chart of the day", likes=615, comments=22)]},
        {**base, "name": "X account", "platform": "x", "platform_label": "X", "handle": "demo", "title": "Demo Trader", "followers": 12940,
         "stats": {"following": 540, "posts": 4210}, "url": None, "growth": g(12940, -6, 82, 310, 3),
         "posts": [post("Funding flipped negative, watch the squeeze", likes=486, views=21800, comments=14), post("My 3 rules for sizing positions", likes=912, views=40100, comments=51)]},
        {**base, "name": "Telegram", "platform": "telegram", "platform_label": "Telegram", "handle": "@demo", "title": "Demo Signals", "followers": 6330,
         "stats": {}, "url": None, "growth": g(6330, 12, 61, 220, 4), "posts": []},
        {**base, "name": "Discord", "platform": "discord", "platform_label": "Discord", "handle": "demo", "title": "Demo Community", "followers": 2105,
         "stats": {"online now": 318}, "url": None, "growth": g(2105, 4, 23, 96, 5), "posts": []},
    ]
