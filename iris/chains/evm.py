"""EVM wallets: native coin + a list of the most common tokens per network, over free public RPC endpoints.

Only tokens in TOKENS are read (an RPC node can't list every token a wallet holds). Add a line to include another one.
"""
from iris import net
from iris.model import f, holding, make_account

# network -> (native symbol, [rpc urls], [(symbol, contract, decimals)])
NETWORKS = {
    "ethereum": ("ETH", ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"], [
        ("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6), ("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        ("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", 18), ("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
        ("WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8), ("LINK", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18),
        ("UNI", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18), ("STETH", "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84", 18)]),
    "base": ("ETH", ["https://base-rpc.publicnode.com", "https://mainnet.base.org"], [
        ("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6), ("WETH", "0x4200000000000000000000000000000000000006", 18),
        ("DAI", "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb", 18), ("CBBTC", "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8)]),
    "arbitrum": ("ETH", ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"], [
        ("USDC", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6), ("USDT", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),
        ("WETH", "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18), ("ARB", "0x912CE59144191C1204E64559FE8253a0e49E6548", 18),
        ("WBTC", "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f", 8)]),
    "optimism": ("ETH", ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"], [
        ("USDC", "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6), ("USDT", "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58", 6),
        ("WETH", "0x4200000000000000000000000000000000000006", 18), ("OP", "0x4200000000000000000000000000000000000042", 18)]),
    "polygon": ("POL", ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"], [
        ("USDC", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6), ("USDT", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),
        ("WETH", "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", 18), ("WPOL", "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", 18)]),
    "bsc": ("BNB", ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed.binance.org"], [
        ("USDT", "0x55d398326f99059fF775485246999027B3197955", 18), ("USDC", "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18),
        ("WBNB", "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18), ("BTCB", "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c", 18),
        ("ETH", "0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18)]),
}
SYMBOL_FIX = {"WPOL": "POL"}


def _balances(network: str, address: str) -> list[tuple[str, float]]:
    native, urls, tokens = NETWORKS[network]
    batch = [{"jsonrpc": "2.0", "id": 0, "method": "eth_getBalance", "params": [address, "latest"]}]
    data = "0x70a08231" + address[2:].lower().rjust(64, "0")
    for i, (_, contract, _) in enumerate(tokens, start=1):
        batch.append({"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [{"to": contract, "data": data}, "latest"]})
    last = None
    for url in urls:
        try:
            res = net.post(url, json=batch, retries=1)
            if not isinstance(res, list):
                raise net.ApiError("unexpected RPC answer")
            by_id = {r.get("id"): r for r in res}
            out = []
            for i in range(len(batch)):
                r = by_id.get(i) or {}
                raw = r.get("result")
                if not isinstance(raw, str) or raw in ("0x", "0x0"):
                    continue
                dec = 18 if i == 0 else tokens[i - 1][2]
                amt = int(raw, 16) / 10 ** dec
                if amt > 0:
                    out.append(((native if i == 0 else tokens[i - 1][0]), amt))
            return out
        except (net.ApiError, ValueError) as e:
            last = e
    raise net.ApiError(f"{network}: {last}")


def fetch(name: str, address: str, networks: list[str]) -> dict:
    holdings, warnings = [], []
    failed = 0
    for network in networks:
        if network not in NETWORKS:
            continue
        try:
            for sym, amt in _balances(network, address):
                holdings.append(holding(SYMBOL_FIX.get(sym, sym), amt, network))
        except net.ApiError as e:
            failed += 1
            warnings.append(str(e))
    if failed and failed == len([n for n in networks if n in NETWORKS]):
        raise net.ApiError("; ".join(warnings))
    return make_account(f"wallet:{name}", name, "wallet", "evm", holdings, warnings=warnings,
                        network=", ".join(n.capitalize() for n in networks))
