from iris.chains import bitcoin, evm, hyperliquid, solana


def fetch_wallet(w: dict) -> dict:
    """w: {'name','address','chain','networks'} from wallets_store."""
    chain = w["chain"]
    if chain == "solana":
        return solana.fetch(w["name"], w["address"])
    if chain == "evm":
        return evm.fetch(w["name"], w["address"], w.get("networks") or ["ethereum", "base", "arbitrum"])
    if chain == "bitcoin":
        return bitcoin.fetch(w["name"], w["address"])
    if chain == "hyperliquid":
        return hyperliquid.fetch(w["name"], w["address"])
    raise ValueError(f"unknown chain {chain}")
