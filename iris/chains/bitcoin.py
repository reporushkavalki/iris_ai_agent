"""Bitcoin address balance via the free mempool.space API."""
from iris import net
from iris.model import f, holding, make_account


def fetch(name: str, address: str) -> dict:
    d = net.get(f"https://mempool.space/api/address/{address}")
    sats = 0
    for part in ("chain_stats", "mempool_stats"):
        s = d.get(part) or {}
        sats += int(s.get("funded_txo_sum", 0)) - int(s.get("spent_txo_sum", 0))
    return make_account(f"wallet:{name}", name, "wallet", "bitcoin", [holding("BTC", sats / 1e8, "wallet")], network="Bitcoin")
