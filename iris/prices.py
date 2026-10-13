"""Public market prices (no key needed): Binance and MEXC spot tickers, merged.

price("BTC") -> USD price or None.  market("ETH") -> price, 24h change and a 24h sparkline.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from iris import net

# (base url, 1-hour candle name). Binance first; MEXC fills in the smaller coins.
BASES = [("https://api.binance.com", "1h"), ("https://api.mexc.com", "60m")]

STABLES = {"USDT": 1.0, "USDC": 1.0, "USD": 1.0, "DAI": 1.0, "FDUSD": 1.0, "TUSD": 1.0,
           "USDE": 1.0, "PYUSD": 1.0, "USDD": 1.0, "USDS": 1.0, "BUSD": 1.0, "USDG": 1.0}
ALIASES = {"WETH": "ETH", "WBTC": "BTC", "CBBTC": "BTC", "BTCB": "BTC", "WBNB": "BNB", "STETH": "ETH",
           "WSOL": "SOL", "XBT": "BTC", "XDG": "DOGE", "MATIC": "POL", "WMATIC": "POL", "BETH": "ETH"}

_lock = threading.Lock()
_tickers: dict = {"t": 0.0, "p": {}}
_markets: dict = {}


def norm(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    return ALIASES.get(s, s)


def all_prices() -> dict:
    """{'BTC': 67000.0, ...}; cached 30 s. Keeps the last good copy if both APIs are down."""
    with _lock:
        if time.time() - _tickers["t"] < 30 and _tickers["p"]:
            return _tickers["p"]
    merged: dict = {}
    for base, _ in reversed(BASES):      # lowest priority first, so Binance overwrites MEXC
        try:
            for row in net.get(base + "/api/v3/ticker/price", retries=1):
                sym = row.get("symbol", "")
                if sym.endswith("USDT"):
                    try:
                        merged[sym[:-4]] = float(row["price"])
                    except (TypeError, ValueError, KeyError):
                        pass
        except net.ApiError:
            continue
    with _lock:
        if merged:
            merged.update(STABLES)
            _tickers.update(t=time.time(), p=merged)
        else:
            _tickers["t"] = time.time() - 20   # retry in ~10 s
        return _tickers["p"]


def price(symbol: str) -> float | None:
    s = norm(symbol)
    if s in STABLES:
        return 1.0
    return all_prices().get(s)


def value(symbol: str, amount: float) -> float | None:
    p = price(symbol)
    return None if p is None else amount * p


def market(symbol: str) -> dict | None:
    """Price, 24h change in percent and 24 hourly closes. Cached 2 minutes."""
    s = norm(symbol)
    hit = _markets.get(s)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    out = None
    for base, interval in BASES:
        try:
            rows = net.get(f"{base}/api/v3/klines", params={"symbol": f"{s}USDT", "interval": interval, "limit": 24}, retries=1)
            closes = [float(r[4]) for r in rows]
            if len(closes) >= 2:
                first = float(rows[0][1])
                out = {"symbol": s, "price": closes[-1], "change24h": round((closes[-1] / first - 1) * 100, 2) if first else 0.0,
                       "spark": closes}
                break
        except (net.ApiError, ValueError, IndexError, TypeError):
            continue
    _markets[s] = (time.time(), out)
    return out


def markets(symbols: list[str]) -> list[dict]:
    symbols = list(dict.fromkeys(norm(s) for s in symbols))[:12]
    with ThreadPoolExecutor(max_workers=6) as ex:
        return [m for m in ex.map(market, symbols) if m]
