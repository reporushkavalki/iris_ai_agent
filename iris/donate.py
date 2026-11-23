"""Optional donation to the developer (SOL). Iris only prepares the payment: the person's own wallet (Phantom, ...)
shows the amount and address and asks for approval. Iris never holds or sees any key, and never sends anything itself.
"""
from iris import net
from iris.chains import solana

ADDRESS = "39oAW7hrufjNi6tm7bS35n3uRaxavV4hMD19y6UKyusU"


def available(st: dict) -> bool:
    """Never shown: Iris is a paid service, so it does not ask for donations. The rest of this module stays for now."""
    return False


def blockhash() -> dict:
    """A recent blockhash, which the wallet needs to build the transfer (the page cannot ask the RPC itself because of browser limits)."""
    res = solana.rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    v = res.get("value") or {}
    if not v.get("blockhash"):
        raise net.ApiError("the Solana network did not return a blockhash")
    return {"blockhash": v["blockhash"], "lastValidBlockHeight": v.get("lastValidBlockHeight")}
