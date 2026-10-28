"""Trading 212 (stocks / ETF broker): account value and cash, read-only. BETA.

Auth is HTTP Basic: base64(API key id : API secret). Hosts: live.trading212.com (real money) and demo.trading212.com (practice).
Only GET /equity/account/summary is read: the total value, the cash part and the invested part, in the account's own currency (converted to USD here).
Individual positions are not listed yet.
"""
import base64

from iris import net, stocks
from iris.exchanges.base import Exchange
from iris.model import f, holding, make_account

HOSTS = {"live": "https://live.trading212.com/api/v0", "demo": "https://demo.trading212.com/api/v0"}


def basic(key: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()


class Trading212(Exchange):
    id = "trading212"
    name = "Trading 212"

    def fetch(self) -> dict:
        base = HOSTS.get(self.v.get("env") or "live", HOSTS["live"])
        s = net.get(base + "/equity/account/summary", headers={"Authorization": basic(self.v["api_key"], self.v["api_secret"])})
        if not isinstance(s, dict):
            raise net.ApiError("Trading 212 returned something unexpected")
        cur = str(s.get("currency") or "EUR").upper()
        cash_part = s.get("cash")
        cash = sum(f(v) for k, v in cash_part.items() if k in ("availableToTrade", "inPies", "reservedForOrders")) if isinstance(cash_part, dict) else 0.0
        total = f(s.get("totalValue"))
        inv = s.get("investments")
        invested = f(inv.get("currentValue")) if isinstance(inv, dict) else 0.0
        if total <= 0:
            total = cash + invested
        elif invested <= 0:
            invested = max(0.0, total - cash)
        try:
            rate = stocks.fx_to_usd(cur)
        except net.ApiError:
            raise net.ApiError(f"No exchange rate for {cur} right now, try again in a minute")
        holdings = []
        if invested > 0:
            holdings.append(holding("STOCKS", invested, "invested", usd=invested * rate))
        if cash > 0:
            holdings.append(holding(cur, cash, "cash", usd=cash * rate))
        warns = ["Trading 212 support is new (beta): it shows your invested value and cash, not single positions yet."]
        if self.v.get("env") == "demo":
            warns.append("This is a practice (demo) account.")
        return make_account("ex:trading212", self.name, "exchange", self.id, holdings, warnings=warns)
