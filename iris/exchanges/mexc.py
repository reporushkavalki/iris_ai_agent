"""MEXC: spot balances + futures equity and open positions (read-only)."""
import hashlib
import hmac
import time
from urllib.parse import urlencode

from iris import net
from iris.exchanges.base import Exchange, hmac_hex
from iris.model import f, holding, make_account

SPOT = "https://api.mexc.com"
FUTURES_BASES = ["https://contract.mexc.com", "https://api.mexc.com"]
STABLES = {"USDT", "USDC", "USD"}


class MEXC(Exchange):
    id = "mexc"
    name = "MEXC"

    def _spot(self, path: str):
        qs = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 10000})
        sig = hmac_hex(self.v["api_secret"], qs)
        return net.get(f"{SPOT}{path}?{qs}&signature={sig}", headers={"X-MEXC-APIKEY": self.v["api_key"]})

    def _futures(self, path: str):
        key, secret = self.v["api_key"], self.v["api_secret"]
        ts = str(int(time.time() * 1000))
        sig = hmac.new(secret.encode(), (key + ts).encode(), hashlib.sha256).hexdigest()   # no params on these calls
        err = None
        for base in FUTURES_BASES:
            try:
                body = net.get(base + path, headers={"ApiKey": key, "Request-Time": ts, "Signature": sig})
                if not body.get("success", False):
                    raise net.ApiError(f"{body.get('message')} (code {body.get('code')})")
                return body["data"]
            except net.ApiError as e:
                err = e
        raise err

    def fetch(self) -> dict:
        holdings, positions, warnings = [], [], []
        for b in self._spot("/api/v3/account").get("balances", []):
            amt = f(b.get("free")) + f(b.get("locked"))
            if amt > 0:
                holdings.append(holding(b["asset"], amt, "spot"))
        if self.v.get("futures", "yes") != "no":
            try:
                equity = sum(f(a.get("equity")) for a in self._futures("/api/v1/private/account/assets") if a.get("currency") in STABLES)
                if equity > 0:
                    holdings.append(holding("USDT", equity, "futures", usd=equity))
                for p in self._futures("/api/v1/private/position/open_positions"):
                    if p.get("state") == 3 or not f(p.get("holdVol")):
                        continue
                    positions.append({
                        "exchange": self.name, "symbol": str(p.get("symbol", "")).replace("_USDT", "-PERP"),
                        "side": "long" if p.get("positionType") == 1 else "short", "size": f(p.get("holdVol")),
                        "entry": f(p.get("holdAvgPrice")), "mark": 0.0, "leverage": f(p.get("leverage")),
                        "upnl": round(f(p.get("unRealizedPnl")), 2), "liq": f(p.get("liquidatePrice")) or None,
                        "margin_mode": "isolated" if p.get("openType") == 1 else "cross",
                    })
            except net.ApiError as e:
                warnings.append(f"Futures not read: {e}. Give the key futures 'view' permission, or set 'Include futures' to no.")
        return make_account("ex:mexc", self.name, "exchange", self.id, holdings, positions=positions, warnings=warnings)
