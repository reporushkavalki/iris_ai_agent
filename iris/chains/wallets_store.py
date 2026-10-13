"""Tracked wallets (PUBLIC addresses only) in data/wallets.json. New wallets start locked, so they can't be removed by accident."""
import json
import os
import re
import threading

from iris.config import WALLETS_FILE

CHAINS = {
    "solana": "Solana",
    "evm": "Ethereum & EVM (Base, Arbitrum, ...)",
    "bitcoin": "Bitcoin",
    "hyperliquid": "Hyperliquid (beta)",
}
EVM_NETWORKS = ["ethereum", "base", "arbitrum", "optimism", "polygon", "bsc"]
DEFAULT_EVM = ["ethereum", "base", "arbitrum"]

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,23}$")
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
BTC_RE = re.compile(r"^(bc1[ac-hj-np-z02-9]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
MAX_WALLETS = 30
_lock = threading.RLock()


def validate_address(chain: str, address: str) -> str:
    """Returns the cleaned address or raises ValueError with a message meant for the user."""
    a = (address or "").strip()
    if " " in a or "\n" in a:
        raise ValueError("That looks like a seed phrase. NEVER paste a seed phrase or private key here: only public addresses.")
    if re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", a):
        raise ValueError("That looks like a PRIVATE KEY. Never paste it anywhere. Use your public address (0x + 40 characters).")
    if chain == "solana":
        if len(a) > 44:
            raise ValueError("That is too long for a Solana address and may be a private key. Use the public address (32-44 characters).")
        ok = SOL_RE.match(a)
    elif chain in ("evm", "hyperliquid"):
        ok = EVM_RE.match(a)
    elif chain == "bitcoin":
        ok = BTC_RE.match(a)
    else:
        raise ValueError("Choose a network.")
    if not ok:
        raise ValueError(f"That doesn't look like a valid {CHAINS.get(chain, chain)} address.")
    return a


def load() -> list[dict]:
    with _lock:
        try:
            items = json.loads(WALLETS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    out = []
    for i in items if isinstance(items, list) else []:
        if isinstance(i, dict) and i.get("name") and i.get("address") and i.get("chain") in CHAINS:
            out.append({"name": str(i["name"]), "address": str(i["address"]), "chain": i["chain"],
                        "networks": [n for n in i.get("networks", []) if n in EVM_NETWORKS] or DEFAULT_EVM,
                        "locked": bool(i.get("locked", True))})
    return out


def _save(items: list[dict]) -> None:
    tmp = WALLETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, WALLETS_FILE)


def add(name: str, address: str, chain: str, networks: list[str] | None = None) -> dict:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Name: 1-24 letters, numbers, spaces, dots, dashes or underscores.")
    address = validate_address(chain, address)
    nets = [n for n in (networks or []) if n in EVM_NETWORKS] or DEFAULT_EVM
    with _lock:
        items = load()
        if len(items) >= MAX_WALLETS:
            raise ValueError(f"At most {MAX_WALLETS} wallets.")
        for w in items:
            if w["name"].lower() == name.lower():
                raise ValueError(f"A wallet named {w['name']} already exists.")
            if w["address"].lower() == address.lower() and w["chain"] == chain:
                raise ValueError(f"That address is already tracked as {w['name']}.")
        item = {"name": name, "address": address, "chain": chain, "networks": nets if chain == "evm" else [], "locked": True}
        _save(items + [item])
        return item


def set_locked(name: str, locked: bool) -> None:
    with _lock:
        items = load()
        hit = [i for i in items if i["name"] == name]
        if not hit:
            raise ValueError("No such wallet.")
        hit[0]["locked"] = bool(locked)
        _save(items)


def remove(name: str) -> None:
    with _lock:
        items = load()
        hit = [i for i in items if i["name"] == name]
        if not hit:
            raise ValueError("No such wallet.")
        if hit[0]["locked"]:
            raise ValueError("This wallet is locked. Unlock it first.")
        _save([i for i in items if i["name"] != name])
