"""Stock, ETF and commodity holdings typed in by hand, in data/stocks.json (no keys involved). New accounts start locked."""
import json
import os
import re
import threading

from iris.config import STOCKS_FILE

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,23}$")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-=^]{1,15}$")
LINE_RE = re.compile(r"^\s*([A-Za-z0-9.\-=^]{1,15})\s*[ \t,;:]\s*([0-9]+(?:[.,][0-9]+)?)\s*$")
MAX_ACCOUNTS = 20
MAX_ITEMS = 60
_lock = threading.RLock()

# Friendly names for the most common commodities (Yahoo's futures symbols). Amounts are in the contract unit
# (gold and silver: troy ounces, oil: barrels, gas: MMBtu, copper: pounds).
COMMODITIES = {"GOLD": "GC=F", "SILVER": "SI=F", "PLATINUM": "PL=F", "PALLADIUM": "PA=F", "COPPER": "HG=F",
               "OIL": "CL=F", "WTI": "CL=F", "BRENT": "BZ=F", "GAS": "NG=F", "NATGAS": "NG=F",
               "WHEAT": "ZW=F", "CORN": "ZC=F", "SOYBEANS": "ZS=F", "COFFEE": "KC=F", "SUGAR": "SB=F", "COCOA": "CC=F"}


def resolve(symbol: str) -> str:
    s = symbol.strip().upper()
    return COMMODITIES.get(s, s)


def parse_items(text: str) -> list[dict]:
    """'AAPL 10' per line (also 'AAPL, 10' or 'AAPL: 10'). Raises ValueError with a message for the user."""
    items: dict = {}
    for n, line in enumerate(str(text or "").splitlines(), 1):
        if not line.strip():
            continue
        m = LINE_RE.match(line)
        if not m:
            raise ValueError(f"Line {n} ('{line.strip()[:30]}') should look like: AAPL 10")
        sym = resolve(m.group(1))
        if not SYMBOL_RE.match(sym):
            raise ValueError(f"Line {n}: '{m.group(1)[:20]}' is not a valid symbol.")
        qty = float(m.group(2).replace(",", "."))
        if qty <= 0:
            raise ValueError(f"Line {n}: the amount must be more than zero.")
        items[sym] = round(items.get(sym, 0.0) + qty, 8)
    if not items:
        raise ValueError("Add at least one line such as: AAPL 10")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"At most {MAX_ITEMS} different symbols per account.")
    return [{"symbol": k, "qty": v} for k, v in items.items()]


def load() -> list[dict]:
    with _lock:
        try:
            raw = json.loads(STOCKS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not (isinstance(a, dict) and a.get("name") and isinstance(a.get("items"), list)):
            continue
        items = [{"symbol": str(i["symbol"]), "qty": float(i["qty"])} for i in a["items"]
                 if isinstance(i, dict) and SYMBOL_RE.match(str(i.get("symbol", ""))) and isinstance(i.get("qty"), (int, float)) and i["qty"] > 0]
        out.append({"name": str(a["name"]), "items": items, "locked": bool(a.get("locked", True))})
    return out


def _save(accts: list[dict]) -> None:
    tmp = STOCKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(accts, indent=2), encoding="utf-8")
    os.replace(tmp, STOCKS_FILE)


def add(name: str, text: str) -> dict:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Name: 1-24 letters, numbers, spaces, dots, dashes or underscores.")
    items = parse_items(text)
    with _lock:
        accts = load()
        if len(accts) >= MAX_ACCOUNTS:
            raise ValueError(f"At most {MAX_ACCOUNTS} stock accounts.")
        if any(a["name"].lower() == name.lower() for a in accts):
            raise ValueError("An account with that name already exists.")
        acct = {"name": name, "items": items, "locked": True}
        _save(accts + [acct])
        return acct


def update_items(name: str, text: str) -> dict:
    items = parse_items(text)
    with _lock:
        accts = load()
        hit = [a for a in accts if a["name"] == name]
        if not hit:
            raise ValueError("No such account.")
        if hit[0]["locked"]:
            raise ValueError("This account is locked. Unlock it first.")
        hit[0]["items"] = items
        _save(accts)
        return hit[0]


def set_locked(name: str, locked: bool) -> None:
    with _lock:
        accts = load()
        hit = [a for a in accts if a["name"] == name]
        if not hit:
            raise ValueError("No such account.")
        hit[0]["locked"] = bool(locked)
        _save(accts)


def remove(name: str) -> None:
    with _lock:
        accts = load()
        hit = [a for a in accts if a["name"] == name]
        if not hit:
            raise ValueError("No such account.")
        if hit[0]["locked"]:
            raise ValueError("This account is locked. Unlock it first.")
        _save([a for a in accts if a["name"] != name])


def as_text(acct: dict) -> str:
    return "\n".join(f"{i['symbol']} {i['qty']:g}" for i in acct["items"])
