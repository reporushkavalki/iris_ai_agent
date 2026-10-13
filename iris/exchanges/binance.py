"""Binance: spot balances + USD-M futures (margin balance and open positions). Funding / Earn wallets are not included."""
import time
from urllib.parse import urlencode

from iris import net, prices
from iris.exchanges.base import Exchange, hmac_hex, warn
from iris.model import f, holding, make_account

SPOT = "https://api.binance.com"
FUT = "https://fapi.binance.com"


class Binance(Exchange):
    id = "binance"
    name = "Binance"

    def _signed(self, base: str, path: str, params: dict | None = None):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 10000
        qs = urlencode(p)
        sig = hmac_hex(self.v["api_secret"], qs)
        return net.get(f"{base}{path}?{qs}&signature={sig}", headers={"X-MBX-APIKEY": self.v["api_key"]})

    def _spot_symbol(self, asset: str) -> str:
        # Simple Earn flexible balances show up as LDUSDT, LDBTC ... (but LDO is a real token)
        if asset.startswith("LD") and len(asset) > 3 and prices.price(asset) is None and prices.price(asset[2:]) is not None:
            return asset[2:]
        return asset

    def fetch(self) -> dict:
        holdings, warnings, positions = [], [], []
        acct = self._signed(SPOT, "/api/v3/account")
        for b in acct.get("balances", []):
            amt = f(b.get("free")) + f(b.get("locked"))
            if amt > 0:
                holdings.append(holding(self._spot_symbol(b["asset"]), amt, "spot"))

        if self.v.get("futures", "yes") != "no":
            try:
                try:
                    fa = self._signed(FUT, "/fapi/v3/account")
                except net.ApiError:
                    fa = self._signed(FUT, "/fapi/v2/account")
                margin = f(fa.get("totalMarginBalance"))
                if margin > 0:
                    holdings.append(holding("USDT", margin, "futures", usd=margin))
                try:
                    risk = self._signed(FUT, "/fapi/v3/positionRisk")
                except net.ApiError:
                    risk = self._signed(FUT, "/fapi/v2/positionRisk")
                for p in risk:
                    amt = f(p.get("positionAmt"))
                    if amt == 0:
                        continue
                    positions.append({
                        "exchange": self.name, "symbol": str(p.get("symbol", "")).replace("USDT", "") + "-PERP",
                        "side": "long" if amt > 0 else "short", "size": abs(amt), "entry": f(p.get("entryPrice")),
                        "mark": f(p.get("markPrice")), "leverage": f(p.get("leverage")),
                        "upnl": round(f(p.get("unRealizedProfit")), 2), "liq": f(p.get("liquidationPrice")) or None,
                        "margin_mode": p.get("marginType", ""),
                    })
            except net.ApiError as e:
                warnings.append(f"Futures not read: {e}. Enable futures on the key, or set 'Include futures' to no.")
        return make_account("ex:binance", self.name, "exchange", self.id, holdings, positions=positions, warnings=warnings)

    def permissions(self) -> list[dict]:
        out = []
        try:
            r = self._signed(SPOT, "/sapi/v1/account/apiRestrictions")
        except net.ApiError:
            return out
        if r.get("enableWithdrawals"):
            out.append(warn("danger", "This key can WITHDRAW funds. Delete it and create a new one with withdrawals switched off."))
        if r.get("enableSpotAndMarginTrading"):
            out.append(warn("warn", "This key can place spot/margin trades. Iris never trades, but a read-only key is safer."))
        if r.get("enableFutures"):
            out.append(warn("info", "Futures access is enabled (Binance has no read-only futures switch). Restrict the key to your IP address."))
        return out
