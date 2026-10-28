"""Alpaca (US stocks and crypto broker): positions and cash, read-only. Choose 'paper' for a paper-trading account."""
from iris import net
from iris.exchanges.base import Exchange
from iris.model import f, holding, make_account

HOSTS = {"live": "https://api.alpaca.markets", "paper": "https://paper-api.alpaca.markets"}


class Alpaca(Exchange):
    id = "alpaca"
    name = "Alpaca"

    def _get(self, path: str):
        base = HOSTS.get(self.v.get("env") or "live", HOSTS["live"])
        return net.get(base + path, headers={"APCA-API-KEY-ID": self.v["api_key"], "APCA-API-SECRET-KEY": self.v["api_secret"]})

    def fetch(self) -> dict:
        acct = self._get("/v2/account")
        holdings, positions = [], []
        shorts = 0
        for p in self._get("/v2/positions") or []:
            usd = f(p.get("market_value"))
            if p.get("side") == "short" or f(p.get("qty")) < 0:
                shorts += 1          # a short is a debt, not a holding: shown as a position row, not added to the total
                positions.append({"exchange": self.name, "symbol": str(p.get("symbol", "?")), "side": "short", "size": abs(f(p.get("qty"))),
                                  "entry": f(p.get("avg_entry_price")), "mark": f(p.get("current_price")), "leverage": 1,
                                  "upnl": round(f(p.get("unrealized_pl")), 2), "liq": None, "margin_mode": ""})
                continue
            sym = str(p.get("symbol", "?")).replace("/", "")
            if sym.endswith("USD") and p.get("asset_class") == "crypto":
                sym = sym[:-3]
            holdings.append(holding(sym, f(p.get("qty")), "shares" if p.get("asset_class") != "crypto" else "crypto", usd=usd))
        cash = f(acct.get("cash"))
        if cash:
            holdings.append(holding("USD", cash, "cash", usd=cash))
        warns = []
        if shorts:
            warns.append(f"{shorts} short position(s) are listed under positions and are not counted in the balance.")
        if self.v.get("env") == "paper":
            warns.append("This is a paper-trading account (practice money).")
        return make_account("ex:alpaca", self.name, "exchange", self.id, holdings, positions=positions, warnings=warns)
