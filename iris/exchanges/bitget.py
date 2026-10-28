"""Bitget (API v2): spot balances + USDT-margined futures equity and open positions. BETA: read-only calls only."""
import time

from iris import net
from iris.exchanges.base import Exchange, hmac_b64
from iris.model import f, holding, make_account

BASE = "https://api.bitget.com"


def sign(secret: str, ts: str, method: str, path: str, query: str = "", body: str = "") -> str:
    """Bitget: base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + ('?' + query) + body))."""
    return hmac_b64(secret, ts + method.upper() + path + (("?" + query) if query else "") + body)


class Bitget(Exchange):
    id = "bitget"
    name = "Bitget"

    def _get(self, path: str, query: str = ""):
        ts = str(int(time.time() * 1000))
        headers = {"ACCESS-KEY": self.v["api_key"], "ACCESS-SIGN": sign(self.v["api_secret"], ts, "GET", path, query),
                   "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": self.v["passphrase"], "Content-Type": "application/json", "locale": "en-US"}
        body = net.get(BASE + path + (("?" + query) if query else ""), headers=headers)
        if str(body.get("code")) != "00000":
            raise net.ApiError(f"{body.get('msg', 'error')} (code {body.get('code')})")
        return body.get("data")

    def fetch(self) -> dict:
        holdings, positions, warnings = [], [], []
        for c in self._get("/api/v2/spot/account/assets") or []:
            amt = f(c.get("available")) + f(c.get("frozen")) + f(c.get("locked"))
            if amt > 0:
                holdings.append(holding(c.get("coin", "?"), amt, "spot"))
        if self.v.get("futures", "yes") != "no":
            try:
                for a in self._get("/api/v2/mix/account/accounts", "productType=USDT-FUTURES") or []:
                    eq = f(a.get("usdtEquity")) or f(a.get("accountEquity"))
                    if eq > 0:
                        holdings.append(holding("USDT", eq, "futures", usd=eq))
                for p in self._get("/api/v2/mix/position/all-position", "marginCoin=USDT&productType=USDT-FUTURES") or []:
                    size = f(p.get("total"))
                    if size == 0:
                        continue
                    positions.append({"exchange": self.name, "symbol": str(p.get("symbol", "")).replace("USDT", "") + "-PERP",
                                      "side": "long" if str(p.get("holdSide")) == "long" else "short", "size": size,
                                      "entry": f(p.get("openPriceAvg")), "mark": f(p.get("markPrice")), "leverage": f(p.get("leverage")),
                                      "upnl": round(f(p.get("unrealizedPL")), 2), "liq": f(p.get("liquidationPrice")) or None,
                                      "margin_mode": str(p.get("marginMode", ""))})
            except net.ApiError as e:
                warnings.append(f"Futures not read: {e}. Enable futures reading on the key, or set 'Include futures' to no.")
        warnings.append("Bitget support is new (beta). If something looks wrong, tell the developer.")
        return make_account("ex:bitget", self.name, "exchange", self.id, holdings, positions=positions, warnings=warnings)
