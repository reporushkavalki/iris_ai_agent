"""Bybit v5: unified (or classic) account balances + linear perpetual positions."""
import time
from urllib.parse import urlencode

from iris import net
from iris.exchanges.base import Exchange, hmac_hex, warn
from iris.model import f, holding, make_account

DEFAULT_BASE = "https://api.bybit.com"
RECV = "10000"


class Bybit(Exchange):
    id = "bybit"
    name = "Bybit"

    @property
    def base(self) -> str:
        return (self.v.get("base") or DEFAULT_BASE).rstrip("/")

    def _get(self, path: str, params: dict | None = None):
        qs = urlencode(params or {})
        ts = str(int(time.time() * 1000))
        sign = hmac_hex(self.v["api_secret"], ts + self.v["api_key"] + RECV + qs)
        headers = {"X-BAPI-API-KEY": self.v["api_key"], "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": RECV, "X-BAPI-SIGN": sign}
        body = net.get(f"{self.base}{path}" + (f"?{qs}" if qs else ""), headers=headers)
        if body.get("retCode") not in (0, "0", None):
            raise net.ApiError(f"{body.get('retMsg', 'error')} (code {body.get('retCode')})")
        return body.get("result") or {}

    def fetch(self) -> dict:
        holdings, positions, warnings = [], [], []
        result, last_err = None, None
        for acct_type in ("UNIFIED", "SPOT", "CONTRACT"):
            try:
                result = self._get("/v5/account/wallet-balance", {"accountType": acct_type})
                if result.get("list"):
                    break
            except net.ApiError as e:
                last_err = e
        if not result or not result.get("list"):
            raise last_err or net.ApiError("no balances returned")
        acct = result["list"][0]
        for c in acct.get("coin", []):
            amt = f(c.get("walletBalance"))
            if amt <= 0:
                continue
            usd = f(c["usdValue"]) if c.get("usdValue") not in (None, "") else "auto"
            holdings.append(holding(c["coin"], amt, "unified", usd=usd))
        # unrealised PnL of perpetuals is part of equity but not of any coin's wallet balance
        diff = f(acct.get("totalEquity")) - sum(h["usd"] or 0 for h in holdings)
        if acct.get("totalEquity") and abs(diff) > 0.01:
            holdings.append(holding("USDT", diff, "unrealised", usd=diff))
        try:
            data = self._get("/v5/position/list", {"category": "linear", "settleCoin": "USDT", "limit": 200})
            for p in data.get("list", []):
                size = f(p.get("size"))
                if size == 0:
                    continue
                positions.append({
                    "exchange": self.name, "symbol": str(p.get("symbol", "")).replace("USDT", "") + "-PERP",
                    "side": "long" if p.get("side") == "Buy" else "short", "size": size, "entry": f(p.get("avgPrice")),
                    "mark": f(p.get("markPrice")), "leverage": f(p.get("leverage")), "upnl": round(f(p.get("unrealisedPnl")), 2),
                    "liq": f(p.get("liqPrice")) or None, "margin_mode": "",
                })
        except net.ApiError as e:
            warnings.append(f"Positions not read: {e}")
        return make_account("ex:bybit", self.name, "exchange", self.id, holdings, positions=positions, warnings=warnings)

    def permissions(self) -> list[dict]:
        try:
            info = self._get("/v5/user/query-api")
        except net.ApiError:
            return []
        if str(info.get("readOnly")) == "0":
            return [warn("warn", "This key is not read-only (it can trade or transfer). Create a read-only key instead.")]
        return []
