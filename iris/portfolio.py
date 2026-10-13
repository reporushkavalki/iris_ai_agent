"""Collects every connected account, totals them, and keeps balance snapshots for charts and PnL.

PnL = balance now minus the balance at the start of the period, per account, counting only accounts that existed at
that moment. Deposits and withdrawals are not separated out (money you move in from outside counts as a gain).
Moves between two of your own tracked accounts cancel out.
"""
import json
import sqlite3
import threading
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta

from iris import model, net, prefs, prices, providers, vault
from iris.chains import fetch_wallet, wallets_store
from iris.config import PORTFOLIO_DB
from iris.exchanges import EXCHANGES

MIN_GAP = 300                      # seconds between saved snapshots
TTL = {"exchange": 30, "wallet": 60}
PERIODS = {"d1": (86400, 2 * 3600), "d7": (7 * 86400, 6 * 3600), "d30": (30 * 86400, 12 * 3600)}   # span, staleness tolerance
RANGES = {"1d": 86400, "1w": 7 * 86400, "1m": 30 * 86400, "3m": 90 * 86400}
STABLE_SYMBOLS = set(prices.STABLES) | {"EUR", "GBP"}

_lock = threading.Lock()
_dblock = threading.RLock()
_cache: dict = {}
_status_cache: dict = {"t": 0.0, "v": None}


# ---------- sources ----------
def sources() -> list[tuple]:
    """(account id, display name, kind, provider, fetch function) for everything the user connected."""
    out = []
    for ex_id, cls in EXCHANGES.items():
        if providers.is_configured(ex_id):
            vals = providers.values(ex_id)
            out.append((f"ex:{ex_id}", cls.name, "exchange", ex_id, lambda cls=cls, vals=vals: cls(vals).fetch()))
    for w in wallets_store.load():
        out.append((f"wallet:{w['name']}", w["name"], "wallet", w["chain"], lambda w=w: fetch_wallet(w)))
    return out


def _fetch_one(src: tuple, force: bool) -> dict:
    aid, name, kind, provider, fn = src
    now = time.time()
    with _lock:
        hit = _cache.get(aid)
    if hit and not force and now - hit["t"] < (TTL[kind] if not hit["acct"].get("error") else 10):
        return hit["acct"]
    try:
        acct = fn()
        good, good_t = acct, now
    except Exception as e:  # noqa: BLE001 - one broken account must never hide the others
        msg = vault.scrub(str(e) if isinstance(e, net.ApiError) else f"{type(e).__name__}: {e}")
        good, good_t = (hit or {}).get("good"), (hit or {}).get("good_t", 0)
        if good and now - good_t < 900:
            acct = {**good, "stale": True, "warnings": good["warnings"] + [f"Showing numbers from {int((now - good_t) // 60)} min ago: {msg}"]}
        else:
            acct = model.error_account(aid, name, kind, provider, msg)
    with _lock:
        _cache[aid] = {"t": now, "acct": acct, "good": good, "good_t": good_t}
    return acct


def collect(srcs: list[tuple], force: bool = False) -> list[dict]:
    if not srcs:
        return []
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(lambda s: _fetch_one(s, force), srcs))


# ---------- snapshots ----------
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(PORTFOLIO_DB)
    c.execute("CREATE TABLE IF NOT EXISTS snaps(ts REAL PRIMARY KEY, accounts TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return c


def _floor(c) -> float:
    row = c.execute("SELECT v FROM meta WHERE k='reset'").fetchone()
    try:
        return float(row[0]) if row else 0.0
    except ValueError:
        return 0.0


def reset() -> None:
    """Start PnL and charts fresh from now."""
    with _dblock, closing(_db()) as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES ('reset', ?)", (str(time.time()),))
        c.commit()
    _status_cache["t"] = 0


def snapshot(values: dict) -> None:
    if not values:
        return
    now = time.time()
    with _dblock, closing(_db()) as c:
        fl = _floor(c)
        last = c.execute("SELECT MAX(ts) FROM snaps").fetchone()[0]
        if last is None or now - last >= MIN_GAP or last < fl:
            c.execute("INSERT OR REPLACE INTO snaps VALUES (?,?)", (max(now, fl), json.dumps(values)))
            c.commit()


def _rows(c, lo: float, hi: float | None = None) -> list[tuple]:
    q, a = "SELECT ts, accounts FROM snaps WHERE ts>=?", [max(lo, _floor(c))]
    if hi is not None:
        q += " AND ts<?"
        a.append(hi)
    out = []
    for ts, js in c.execute(q + " ORDER BY ts", a):
        try:
            out.append((ts, json.loads(js)))
        except ValueError:
            continue
    return out


def _series(rows: list[tuple]) -> dict:
    s: dict = {}
    for ts, accts in rows:
        for aid, v in accts.items():
            t, vals = s.setdefault(aid, ([], []))
            t.append(ts)
            vals.append(v)
    return s


def _baseline(series: dict, aid: str, start: float, stale: float):
    t, v = series.get(aid, ([], []))
    if not t:
        return None
    i = bisect_right(t, start)
    if i > 0 and start - t[i - 1] <= stale:
        return t[i - 1], v[i - 1]
    if i < len(t):
        return t[i], v[i]
    return t[i - 1], v[i - 1]


def compute_pnl(current: dict) -> dict:
    now = time.time()
    with _dblock, closing(_db()) as c:
        series = _series(_rows(c, now - 32 * 86400))
        first = c.execute("SELECT MIN(ts) FROM snaps WHERE ts>=?", (_floor(c),)).fetchone()[0]
    out = {}
    for key, (span, stale) in PERIODS.items():
        start = now - span
        cur = base = 0.0
        latest = None
        for aid, val in current.items():
            b = _baseline(series, aid, start, stale)
            if b:
                cur += val
                base += b[1]
                latest = max(latest or 0, b[0])
        if latest is None:
            out[key] = None
            continue
        d = cur - base
        since = datetime.fromtimestamp(latest)
        out[key] = {"usd": round(d, 2), "pct": round(d / base * 100, 2) if base > 0 else None,
                    "partial": latest > start + stale,
                    "since": since.strftime("%H:%M") if since.date() == datetime.now().date() else since.strftime("%a %d %b %H:%M")}
    out["tracking_since"] = datetime.fromtimestamp(first).strftime("%Y-%m-%d %H:%M") if first else None
    return out


def history(range_key: str = "1d", max_points: int = 240) -> dict:
    span = RANGES.get(range_key)
    if span is None:
        raise ValueError("range must be one of " + ", ".join(RANGES))
    if prefs.demo_on():
        from iris import demo
        return demo.history(range_key)
    ids = {s[0] for s in sources()}
    now = time.time()
    with _dblock, closing(_db()) as c:
        fl = _floor(c)
        lo = max(now - span, fl)
        prev = None if fl > now - span else c.execute("SELECT ts, accounts FROM snaps WHERE ts<? ORDER BY ts DESC LIMIT 1", (now - span,)).fetchone()
        rows = _rows(c, lo)
    if prev:
        try:
            rows = [(prev[0], json.loads(prev[1]))] + rows
        except ValueError:
            pass
    last: dict = {}
    pts = []
    for ts, accts in rows:                      # forward-fill: an account that failed once doesn't make the chart dip
        last.update({k: v for k, v in accts.items() if k in ids})
        if last:
            pts.append([max(ts, now - span), round(sum(last.values()), 2)])
    if len(pts) > max_points:
        step = len(pts) / max_points
        pts = [pts[min(len(pts) - 1, int((i + 1) * step) - 1)] for i in range(max_points)]
    return {"range": range_key, "points": pts, "start": max(now - span, fl), "end": now}


def calendar(month: str | None = None) -> dict:
    if prefs.demo_on():
        from iris import demo
        return demo.calendar(month)
    today = datetime.now()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        first = datetime(y, m, 1)
    except (ValueError, AttributeError):
        y, m, first = today.year, today.month, datetime(today.year, today.month, 1)
    nxt = datetime(y + (m == 12), m % 12 + 1, 1)
    with _dblock, closing(_db()) as c:
        rows = _rows(c, (first - timedelta(days=9)).timestamp(), nxt.timestamp())
    day_first: dict = {}
    day_end: dict = {}
    for ts, accts in rows:
        d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        for aid, v in accts.items():
            day_first.setdefault(aid, {}).setdefault(d, v)
            day_end.setdefault(aid, {})[d] = v
    days: dict = {}
    d = first
    while d < nxt and d.date() <= today.date():
        key, prev = d.strftime("%Y-%m-%d"), (d - timedelta(days=1)).strftime("%Y-%m-%d")
        total, partial, seen = 0.0, False, False
        for aid, ends in day_end.items():
            if key not in ends:
                continue
            if prev in ends:
                base = ends[prev]
            else:
                base, partial = day_first[aid][key], True
            total += ends[key] - base
            seen = True
        if seen:
            days[key] = {"usd": round(total, 2), "partial": partial}
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "days": days, "total": round(sum(v["usd"] for v in days.values()), 2),
            "today": today.strftime("%Y-%m-%d")}


# ---------- the dashboard payload ----------
def _allocation(accts: list[dict], total: float) -> tuple[list, list, list]:
    by_asset: dict = {}
    for a in accts:
        for h in a["holdings"]:
            e = by_asset.setdefault(h["symbol"], {"symbol": h["symbol"], "amount": 0.0, "usd": 0.0, "in": []})
            e["amount"] += h["amount"]
            e["usd"] += h["usd"]
            e["in"].append({"account": a["name"], "usd": round(h["usd"], 2), "where": h.get("where", "")})
    table = sorted(by_asset.values(), key=lambda e: -e["usd"])
    for e in table:
        e["usd"] = round(e["usd"], 2)
        e["pct"] = round(e["usd"] / total * 100, 2) if total else 0
        e["in"].sort(key=lambda x: -x["usd"])
    top, rest = table[:8], table[8:]
    assets = [{"label": e["symbol"], "usd": e["usd"]} for e in top]
    if rest:
        assets.append({"label": "Other", "usd": round(sum(e["usd"] for e in rest), 2)})
    by_acct = [{"label": a["name"], "usd": a["total_usd"]} for a in sorted(accts, key=lambda a: -a["total_usd"]) if a["total_usd"] > 0]
    return assets, by_acct, table[:60]


def build(all_accts: list[dict]) -> dict:
    ok = [a for a in all_accts if a.get("total_usd") is not None]
    total = round(sum(a["total_usd"] for a in ok), 2)
    assets, by_acct, table = _allocation(ok, total)
    positions = []
    for a in ok:
        for p in a["positions"]:
            positions.append({**p, "account": a["name"]})
    positions.sort(key=lambda p: -abs(p.get("upnl") or 0))
    snapshot({a["id"]: a["total_usd"] for a in ok})
    accounts = []
    for a in sorted(all_accts, key=lambda a: -(a.get("total_usd") or 0)):
        accounts.append({k: a[k] for k in ("id", "name", "kind", "provider", "network", "total_usd", "unpriced", "upnl_usd", "warnings", "error", "stale")}
                        | {"share_pct": round(a["total_usd"] / total * 100, 1) if a.get("total_usd") and total else 0,
                           "top": [{"symbol": h["symbol"], "usd": h["usd"]} for h in (a["holdings"][:4])],
                           "n_assets": len(a["holdings"])})
    return {
        "demo": False, "generated": time.time(), "configured": True, "total_usd": total,
        "pnl": compute_pnl({a["id"]: a["total_usd"] for a in ok}), "upnl_usd": round(sum(a["upnl_usd"] for a in ok), 2),
        "incomplete": len(ok) < len(all_accts), "accounts": accounts,
        "allocation": {"assets": assets, "accounts": by_acct}, "holdings": table, "positions": positions[:40],
        "stable_pct": round(sum(e["usd"] for e in table if e["symbol"] in STABLE_SYMBOLS) / total * 100, 1) if total else 0,
    }


def status(force: bool = False) -> dict:
    if prefs.demo_on():
        from iris import demo
        return demo.status()
    with _lock:
        c = _status_cache
        if not force and c["v"] is not None and time.time() - c["t"] < 5:
            return c["v"]
    srcs = sources()
    if not srcs:
        v = {"demo": False, "generated": time.time(), "configured": False, "total_usd": 0, "pnl": {}, "accounts": [], "allocation": {"assets": [], "accounts": []},
             "holdings": [], "positions": [], "upnl_usd": 0, "incomplete": False, "stable_pct": 0}
    else:
        v = build(collect(srcs, force))
    with _lock:
        _status_cache.update(t=time.time(), v=v)
    return v


# Shown only while there is nothing to follow yet (largest coins by market cap, stablecoins left out).
TOP_COINS = ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "TRX", "ADA"]


def watch_symbols(st: dict | None = None) -> list[str]:
    """The MARKETS panel follows what you hold (largest first, up to 8). With no holdings it shows the top coins by market cap."""
    syms: list[str] = []
    for h in (st or {}).get("holdings", []):
        s = prices.norm(h["symbol"])
        if s not in STABLE_SYMBOLS and s not in syms and prices.price(s) is not None:
            syms.append(s)
        if len(syms) >= 8:
            break
    return syms or list(TOP_COINS)
