"""DeFi data from DefiLlama's free public API: best yields, protocol sizes (TVL) and chain sizes. No key, read-only, Iris Pro.

This is market-wide data, not your own DeFi positions. Showing what one wallet has deposited needs a paid data service (Zerion, DeBank),
which Iris does not use. The AI can still say how a pool or protocol looks and what its yield is.

DefiLlama endpoints (free, no key): https://yields.llama.fi/pools, https://api.llama.fi/protocols, https://api.llama.fi/v2/chains
"""
import threading
import time

from iris import net

YIELDS_URL = "https://yields.llama.fi/pools"
PROTOCOLS_URL = "https://api.llama.fi/protocols"
CHAINS_URL = "https://api.llama.fi/v2/chains"
TTL = 1800                      # these lists are big and change slowly: reuse for 30 minutes
MAX_APY = 1000.0                # above this a "yield" is almost always a broken or tiny pool

_lock = threading.Lock()
_cache: dict = {}


def _fetch(url: str):
    with _lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    data = net.get(url)
    with _lock:
        _cache[url] = (time.time(), data)
    return data


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def top_yields(chain: str = "", project: str = "", stablecoin_only: bool = False, min_tvl_usd: float = 5_000_000, limit: int = 10) -> dict:
    raw = _fetch(YIELDS_URL)
    pools = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(pools, list):
        raise net.ApiError("DefiLlama did not return yield data")
    chain, project = chain.strip().lower(), project.strip().lower()
    rows = []
    for p in pools:
        apy, tvl = _num(p.get("apy")), _num(p.get("tvlUsd"))
        if apy <= 0 or apy > MAX_APY or tvl < min_tvl_usd:
            continue
        if chain and str(p.get("chain", "")).lower() != chain:
            continue
        if project and project not in str(p.get("project", "")).lower():
            continue
        if stablecoin_only and not p.get("stablecoin"):
            continue
        rows.append({"project": p.get("project"), "chain": p.get("chain"), "pool": p.get("symbol"), "apy_pct": round(apy, 2),
                     "apy_base_pct": round(_num(p.get("apyBase")), 2), "apy_reward_pct": round(_num(p.get("apyReward")), 2),
                     "tvl_usd": round(tvl), "stablecoin": bool(p.get("stablecoin")), "il_risk": p.get("ilRisk")})
    rows.sort(key=lambda r: -r["apy_pct"])
    return {"pools": rows[:max(1, min(int(limit or 10), 25))], "matched": len(rows),
            "note": "Yields change constantly. High APY usually means higher risk (reward tokens, impermanent loss, small or new pools). Not advice."}


def protocols(query: str = "", limit: int = 10) -> dict:
    raw = _fetch(PROTOCOLS_URL)
    if not isinstance(raw, list):
        raise net.ApiError("DefiLlama did not return protocol data")
    q = query.strip().lower()
    rows = [r for r in raw if isinstance(r, dict) and _num(r.get("tvl")) > 0 and (not q or q in str(r.get("name", "")).lower() or q in str(r.get("category", "")).lower())]
    rows.sort(key=lambda r: -_num(r.get("tvl")))
    out = [{"name": r.get("name"), "category": r.get("category"), "tvl_usd": round(_num(r.get("tvl"))), "change_1d_pct": r.get("change_1d"),
            "change_7d_pct": r.get("change_7d"), "chains": (r.get("chains") or [])[:6]} for r in rows[:max(1, min(int(limit or 10), 25))]]
    return {"protocols": out, "matched": len(rows)}


def chains(limit: int = 15) -> dict:
    raw = _fetch(CHAINS_URL)
    if not isinstance(raw, list):
        raise net.ApiError("DefiLlama did not return chain data")
    rows = sorted((r for r in raw if isinstance(r, dict) and _num(r.get("tvl")) > 0), key=lambda r: -_num(r.get("tvl")))
    return {"chains": [{"name": r.get("name"), "tvl_usd": round(_num(r.get("tvl")))} for r in rows[:max(1, min(int(limit or 15), 40))]]}
