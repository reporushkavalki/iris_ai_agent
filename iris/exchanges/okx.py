"""OKX v5: trading account (with open positions) and funding account."""
from datetime import datetime, timezone

from iris import net
from iris.exchanges.base import Exchange, hmac_b64, warn
from iris.model import f, holding, make_account

DEFAULT_BASE = "https://www.okx.com"


class OKX(Exchange):
    id = "okx"
    name = "OKX"

    @property
    def base(self) -> str:
        return (self.v.get("base") or DEFAULT_BASE).rstrip("/")

    def _get(self, path: str):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        headers = {
            "OK-ACCESS-KEY": self.v["api_key"], "OK-ACCESS-SIGN": hmac_b64(self.v["api_secret"], ts + "GET" + path),
            "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.v["passphrase"], "Content-Type": "application/json",
        }
        body = net.get(self.base + path, headers=headers)
        if str(body.get("code", "0")) != "0":
            raise net.ApiError(f"{body.get('msg') or 'error'} (code {body.get('code')})")
        return body.get("data") or []

    def fetch(self) -> dict:
        holdings, positions, warnings = [], [], []
        data = self._get("/api/v5/account/balance")
        for d in (data[0].get("details", []) if data else []):
            usd = f(d.get("eqUsd"))
            amt = f(d.get("eq"))
            if amt > 0:
                holdings.append(holding(d["ccy"], amt, "trading", usd=usd if d.get("eqUsd") not in (None, "") else "auto"))
        try:
            for d in self._get("/api/v5/asset/balances"):
                amt = f(d.get("bal"))
                if amt > 0:
                    holdings.append(holding(d["ccy"], amt, "funding"))
        except net.ApiError as e:
            warnings.append(f"Funding account not read: {e}")
        try:
            for p in self._get("/api/v5/account/positions"):
                pos = f(p.get("pos"))
                if pos == 0:
                    continue
                side = p.get("posSide")
                if side not in ("long", "short"):
                    side = "long" if pos > 0 else "short"
                positions.append({
                    "exchange": self.name, "symbol": str(p.get("instId", "")).replace("-USDT-SWAP", "-PERP").replace("-SWAP", "-PERP"),
                    "side": side, "size": abs(pos), "entry": f(p.get("avgPx")), "mark": f(p.get("markPx")),
                    "leverage": f(p.get("lever")), "upnl": round(f(p.get("upl")), 2), "liq": f(p.get("liqPx")) or None,
                    "margin_mode": p.get("mgnMode", ""),
                })
        except net.ApiError as e:
            warnings.append(f"Positions not read: {e}")
        return make_account("ex:okx", self.name, "exchange", self.id, holdings, positions=positions, warnings=warnings)

    def permissions(self) -> list[dict]:
        try:
            cfg = self._get("/api/v5/account/config")
        except net.ApiError:
            return []
        perm = str((cfg[0] if cfg else {}).get("perm", ""))
        out = []
        if "withdraw" in perm:
            out.append(warn("danger", "This key can WITHDRAW funds. Create a new key with 'Read only' permission."))
        elif "trade" in perm:
            out.append(warn("warn", "This key can trade. Iris never trades, but a 'Read only' key is safer."))
        return out
