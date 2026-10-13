"""Kraken spot balances (incl. staked assets and fiat)."""
import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

from iris import net
from iris.exchanges.base import Exchange
from iris.model import f, holding, make_account

BASE = "https://api.kraken.com"
LEGACY = {"XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XLTC": "LTC", "XXRP": "XRP", "XXLM": "XLM", "XXMR": "XMR",
          "XETC": "ETC", "XZEC": "ZEC", "XXDG": "DOGE", "XDG": "DOGE", "XREP": "REP", "XMLN": "MLN",
          "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP", "ZCAD": "CAD", "ZJPY": "JPY", "ZAUD": "AUD"}


def sign(path: str, nonce: int | str, postdata: str, secret_b64: str) -> str:
    """Kraken: base64(HMAC-SHA512(base64decode(secret), path + SHA256(nonce + postdata)))."""
    digest = hashlib.sha256((str(nonce) + postdata).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), path.encode() + digest, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def normalise_asset(a: str) -> str:
    a = a.split(".")[0]          # BTC.F, DOT.S, ETH2.S ... (earn / staking variants)
    if a == "ETH2":
        return "ETH"
    return LEGACY.get(a, a)


class Kraken(Exchange):
    id = "kraken"
    name = "Kraken"

    def fetch(self) -> dict:
        path = "/0/private/Balance"
        nonce = int(time.time() * 1000)
        data = urlencode({"nonce": nonce})
        headers = {"API-Key": self.v["api_key"], "API-Sign": sign(path, nonce, data, self.v["api_secret"]),
                   "Content-Type": "application/x-www-form-urlencoded"}
        body = net.post(BASE + path, headers=headers, data=data)
        if body.get("error"):
            raise net.ApiError("; ".join(body["error"]))
        merged: dict[str, float] = {}
        for asset, amount in (body.get("result") or {}).items():
            amt = f(amount)
            if amt > 0:
                sym = normalise_asset(asset)
                merged[sym] = merged.get(sym, 0.0) + amt
        holdings = [holding(sym, amt, "spot") for sym, amt in merged.items()]
        return make_account("ex:kraken", self.name, "exchange", self.id, holdings)
