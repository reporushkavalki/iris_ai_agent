"""Gate.io (API v4): spot balances + USDT futures margin balance. BETA: read-only calls only. Futures positions are not read yet."""
import hashlib
import hmac
import time

from iris import net
from iris.exchanges.base import Exchange
from iris.model import f, holding, make_account

BASE = "https://api.gateio.ws"


def sign(secret: str, method: str, path: str, query: str, body: str, ts: str) -> str:
    """Gate: HMAC-SHA512(secret, METHOD \\n /api/v4/path \\n query \\n hex(SHA512(body)) \\n timestamp-in-seconds)."""
    body_hash = hashlib.sha512(body.encode()).hexdigest()
    payload = "\n".join([method.upper(), path, query, body_hash, ts])
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha512).hexdigest()


class Gate(Exchange):
    id = "gate"
    name = "Gate.io"

    def _get(self, path: str, query: str = ""):
        full = "/api/v4" + path
        ts = str(int(time.time()))
        headers = {"KEY": self.v["api_key"], "SIGN": sign(self.v["api_secret"], "GET", full, query, "", ts), "Timestamp": ts, "Accept": "application/json"}
        return net.get(BASE + full + (("?" + query) if query else ""), headers=headers)

    def fetch(self) -> dict:
        holdings, warnings = [], []
        for a in self._get("/spot/accounts") or []:
            amt = f(a.get("available")) + f(a.get("locked"))
            if amt > 0:
                holdings.append(holding(a.get("currency", "?"), amt, "spot"))
        if self.v.get("futures", "yes") != "no":
            try:
                fa = self._get("/futures/usdt/accounts") or {}
                total = f(fa.get("total"))
                if total > 0:
                    holdings.append(holding("USDT", total, "futures", usd=total))
            except net.ApiError as e:
                warnings.append(f"Futures not read: {e}. Enable futures reading on the key, or set 'Include futures' to no.")
        warnings.append("Gate.io support is new (beta); futures positions are not listed yet.")
        return make_account("ex:gate", self.name, "exchange", self.id, holdings, warnings=warnings)
