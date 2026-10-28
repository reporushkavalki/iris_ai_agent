"""Stock, ETF and commodity prices, read-only and without an account.

* Yahoo Finance's public chart endpoint (no key). It covers shares worldwide, ETFs and commodity futures (GC=F gold, CL=F oil ...).
  It is NOT an official API: it can change or limit requests without notice, so every price is cached and a failed symbol is
  shown as 'no price' instead of breaking the dashboard. Prices are often delayed 15 minutes. Iris only calls it from this computer.
* Finnhub (optional, free key, US shares): steadier quotes when a key is saved under Connections.

quote("AAPL") -> {"symbol", "name", "price", "currency", "price_usd", "change24h"}
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from iris import model, net, providers
from iris.stocks_store import resolve

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
FINNHUB = "https://finnhub.io/api/v1/quote"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Iris-Retail/1.0; local dashboard)", "Accept": "application/json"}
TTL = 120                        # seconds a quote is reused
GOOD_FOR = 900                   # a failing symbol keeps its last good price this long
SUBUNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}   # prices quoted in pence / cents

_lock = threading.Lock()
_cache: dict = {}                # symbol -> (time, quote or None, error)
_fx: dict = {}                   # currency -> (time, usd per unit)


def _yahoo_chart(symbol: str) -> dict:
    body = net.get(YAHOO + symbol, params={"range": "5d", "interval": "1d"}, headers=HEADERS, retries=1)
    res = ((body.get("chart") or {}).get("result") or [None])[0]
    if not res:
        err = (body.get("chart") or {}).get("error") or {}
        raise net.ApiError(str(err.get("description") or "no data for this symbol"))
    return res


def fx_to_usd(currency: str) -> float:
    cur = (currency or "USD").upper()
    if cur == "USD":
        return 1.0
    with _lock:
        hit = _fx.get(cur)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    res = _yahoo_chart(f"{cur}USD=X")
    rate = float((res.get("meta") or {}).get("regularMarketPrice") or 0)
    if rate <= 0:
        raise net.ApiError(f"no exchange rate for {cur}")
    with _lock:
        _fx[cur] = (time.time(), rate)
    return rate


def _from_yahoo(symbol: str) -> dict:
    res = _yahoo_chart(symbol)
    meta = res.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        closes = [c for c in (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        price = closes[-1] if closes else None
    if price is None or float(price) <= 0:
        raise net.ApiError("no price for this symbol")
    price = float(price)
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    cur = meta.get("currency") or "USD"
    factor = 1.0
    if cur in SUBUNITS:
        cur, div = SUBUNITS[cur]
        price, prev, factor = price / div, (float(prev) / div if prev else None), 1.0
    usd = price * fx_to_usd(cur) * factor
    chg = round((price / float(prev) - 1) * 100, 2) if prev and float(prev) > 0 else None
    return {"symbol": symbol, "name": str(meta.get("shortName") or meta.get("longName") or symbol)[:40], "price": round(price, 4),
            "currency": cur, "price_usd": usd, "change24h": chg, "source": "yahoo"}


def _from_finnhub(symbol: str, key: str) -> dict:
    d = net.get(FINNHUB, params={"symbol": symbol, "token": key}, retries=1)
    c = float(d.get("c") or 0)
    if c <= 0:
        raise net.ApiError("Finnhub has no price for this symbol")
    pc = float(d.get("pc") or 0)
    return {"symbol": symbol, "name": symbol, "price": c, "currency": "USD", "price_usd": c,
            "change24h": round((c / pc - 1) * 100, 2) if pc > 0 else None, "source": "finnhub"}


def _us_plain(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{1,5}", symbol))


def quote(symbol: str) -> dict:
    """Cached quote. Raises net.ApiError when there is no price and no recent good one."""
    sym = resolve(symbol)
    now = time.time()
    with _lock:
        hit = _cache.get(sym)
    if hit and now - hit[0] < TTL and hit[1] is not None:
        return hit[1]
    key = providers.values("finnhub").get("api_key") if providers.is_configured("finnhub") else ""
    q, err = None, None
    try:
        if key and _us_plain(sym):
            try:
                q = _from_finnhub(sym, key)
            except net.ApiError:
                q = _from_yahoo(sym)
        else:
            q = _from_yahoo(sym)
    except (net.ApiError, ValueError, TypeError, KeyError) as e:
        err = e
    if q is None:
        if hit and hit[1] is not None and now - hit[0] < GOOD_FOR:
            return {**hit[1], "stale": True}
        raise net.ApiError(f"{sym}: {err}" if err else f"{sym}: no price")
    with _lock:
        _cache[sym] = (now, q, None)
    return q


def quotes(symbols: list[str]) -> dict:
    """{symbol: quote or None} for several symbols at once."""
    syms = list(dict.fromkeys(resolve(s) for s in symbols))[:60]

    def one(s):
        try:
            return s, quote(s)
        except (net.ApiError, ValueError, TypeError):
            return s, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, syms))


def fetch_account(acct: dict) -> dict:
    """A hand-typed stock account -> the normalised account every other part of Iris understands."""
    qs = quotes([i["symbol"] for i in acct["items"]])
    holdings, missing = [], []
    for i in acct["items"]:
        q = qs.get(resolve(i["symbol"]))
        if q is None:
            missing.append(i["symbol"])
            holdings.append(model.holding(i["symbol"], i["qty"], "shares", usd=None))
        else:
            holdings.append(model.holding(i["symbol"], i["qty"], "shares", usd=i["qty"] * q["price_usd"]))
    warns = []
    if missing:
        warns.append("No price found for: " + ", ".join(missing[:8]) + ". Check the symbol (Yahoo style, e.g. NESTE.HE, GC=F).")
    if any((qs.get(resolve(i["symbol"])) or {}).get("source") == "yahoo" for i in acct["items"]):
        warns.append("Prices from Yahoo Finance, often delayed by about 15 minutes.")
    return model.make_account(f"stocks:{acct['name']}", acct["name"], "stocks", "stocks", holdings, warnings=warns)
