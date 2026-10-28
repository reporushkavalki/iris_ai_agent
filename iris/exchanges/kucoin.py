"""KuCoin: spot, trading and funding balances (all account types, summed per coin). BETA: read-only calls only. Futures are not read yet."""
import time

from iris import net
from iris.exchanges.base import Exchange, hmac_b64
from iris.model import f, holding, make_account

BASE = "https://api.kucoin.com"


def sign(secret: str, ts: str, method: str, endpoint: str, body: str = "") -> str:
    """KuCoin: base64(HMAC-SHA256(secret, timestamp + METHOD + endpoint (with query) + body))."""
    return hmac_b64(secret, ts + method.upper() + endpoint + body)


def passphrase_header(secret: str, passphrase: str) -> str:
    """API key version 2: the passphrase itself is signed, base64(HMAC-SHA256(secret, passphrase))."""
    return hmac_b64(secret, passphrase)


class KuCoin(Exchange):
    id = "kucoin"
    name = "KuCoin"

    def _get(self, endpoint: str):
        ts = str(int(time.time() * 1000))
        headers = {"KC-API-KEY": self.v["api_key"], "KC-API-SIGN": sign(self.v["api_secret"], ts, "GET", endpoint),
                   "KC-API-TIMESTAMP": ts, "KC-API-PASSPHRASE": passphrase_header(self.v["api_secret"], self.v["passphrase"]),
                   "KC-API-KEY-VERSION": "2"}
        body = net.get(BASE + endpoint, headers=headers)
        if str(body.get("code")) != "200000":
            raise net.ApiError(f"{body.get('msg', 'error')} (code {body.get('code')})")
        return body.get("data")

    def fetch(self) -> dict:
        merged: dict[str, float] = {}
        for a in self._get("/api/v1/accounts") or []:
            amt = f(a.get("balance"))
            if amt > 0:
                cur = str(a.get("currency", "?"))
                merged[cur] = merged.get(cur, 0.0) + amt
        holdings = [holding(sym, amt, "spot") for sym, amt in merged.items()]
        warns = ["KuCoin support is new (beta); futures accounts are not read yet."]
        return make_account("ex:kucoin", self.name, "exchange", self.id, holdings, warnings=warns)
