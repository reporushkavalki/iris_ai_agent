"""Solana wallet: SOL + SPL tokens, priced with DexScreener (thin-liquidity tokens are counted but not valued)."""
import time

from iris import net, prices, vault
from iris.model import f, holding, make_account

TOKEN_PROGRAMS = ["TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"]
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
WSOL = "So11111111111111111111111111111111111111112"
MIN_LIQUIDITY_USD = 5000
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def rpc_url() -> str:
    return vault.get("solana_rpc").get("url") or PUBLIC_RPC


def rpc(method: str, params: list):
    for attempt in range(4):
        try:
            body = net.post(rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, retries=0)
        except net.ApiError as e:
            if "429" in str(e) and attempt < 3:      # public RPC rate limit: back off
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        if "error" in body:
            err = body["error"]
            raise net.ApiError(err.get("message", str(err)) if isinstance(err, dict) else str(err))
        return body["result"]
    raise net.ApiError("RPC rate-limited (429). Add a free RPC URL (Helius, QuickNode ...) under Connections > Solana RPC.")


def token_prices(mints: list[str]) -> dict:
    out: dict = {}
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        try:
            data = net.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk), retries=1)
        except net.ApiError:
            continue
        for p in data if isinstance(data, list) else (data.get("pairs") or []):
            base = p.get("baseToken") or {}
            mint = base.get("address")
            if mint not in chunk:
                continue
            try:
                px, liq = float(p.get("priceUsd")), float((p.get("liquidity") or {}).get("usd") or 0)
            except (TypeError, ValueError):
                continue
            if mint not in out or liq > out[mint]["liquidity"]:
                out[mint] = {"symbol": base.get("symbol") or mint[:4], "price": px, "liquidity": liq}
    return out


def fetch(name: str, address: str) -> dict:
    sol = rpc("getBalance", [address])["value"] / 1e9
    held: dict[str, float] = {}
    for program in TOKEN_PROGRAMS:
        res = rpc("getTokenAccountsByOwner", [address, {"programId": program}, {"encoding": "jsonParsed"}])
        for acc in res["value"]:
            info = acc["account"]["data"]["parsed"]["info"]
            amt = f(info["tokenAmount"].get("uiAmount"))
            if amt > 0:
                held[info["mint"]] = held.get(info["mint"], 0) + amt
    tp = token_prices([m for m in held if m not in (USDC, USDT)])
    holdings = [holding("SOL", sol, "wallet")]
    unpriced = 0
    for mint, amt in held.items():
        if mint in (USDC, USDT):
            holdings.append(holding("USDC" if mint == USDC else "USDT", amt, "wallet", usd=amt))
        elif mint in tp and tp[mint]["liquidity"] >= MIN_LIQUIDITY_USD:
            holdings.append(holding(tp[mint]["symbol"], amt, "wallet", usd=amt * tp[mint]["price"]))
        else:
            unpriced += 1
    acct = make_account(f"wallet:{name}", name, "wallet", "solana", holdings, network="Solana")
    if unpriced:
        acct["unpriced"] = [f"{unpriced} thin-liquidity token(s)"]
    return acct
