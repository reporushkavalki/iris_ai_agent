"""Everything the Connections screen can configure, described as data.

To add a field or a whole service, add an entry here (and a connector if it is new). The UI builds itself from this list.
Secret fields are masked in the browser and never sent back once saved.
"""
from iris import vault
from iris.config import UPGRADE_URL
from iris.help_text import HELP


def field(key, label, *, secret=True, required=True, placeholder="", default=None, options=None, help=""):
    return {"key": key, "label": label, "secret": secret, "required": required, "placeholder": placeholder,
            "default": default, "options": options, "help": help}


_YESNO = ["yes", "no"]
_RO = "Create the key as READ-ONLY (no trading, no withdrawals) and, if the exchange allows it, restrict it to your IP address."

PROVIDERS = [
    # ---- Iris Pro ----
    {"id": "pro", "group": "pro", "title": "Iris Pro license", "link": UPGRADE_URL,
     "blurb": "Paste the license key from your purchase email. Pro: every connection unlocked, no limit on accounts, the advanced Iris AI included (no Claude key needed), early access and the Inner Circle.",
     "fields": [field("license_key", "License key", placeholder="IRIS-XXXX-XXXX-XXXX-XXXX")]},
    # ---- AI ----
    {"id": "anthropic", "group": "ai", "title": "Claude AI (your own key)", "link": "https://console.anthropic.com/settings/keys",
     "blurb": "WITH IRIS PRO YOU NEED NO KEY: the advanced Iris AI is included. This card is for the free plan (your own Anthropic key, chat with Claude Haiku 5.5) or for Pro users who prefer their own key. Your key stays on this computer and is only sent to Anthropic.",
     "fields": [field("api_key", "Anthropic API key", placeholder="sk-ant-..."),
                field("model", "Model", secret=False, required=False, default="claude-sonnet-5-5",
                      options=["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
                      help="Free plan: always Haiku 5.5. With Iris Pro you choose: Sonnet is the all-rounder, Opus the most capable.")]},
    # ---- exchanges ----
    {"id": "binance", "group": "exchange", "title": "Binance", "link": "https://www.binance.com/en/my/settings/api-management",
     "blurb": "Spot balances and USD-M futures positions. " + _RO,
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"),
                field("futures", "Include futures", secret=False, required=False, default="yes", options=_YESNO)]},
    {"id": "bybit", "group": "exchange", "title": "Bybit", "link": "https://www.bybit.com/app/user/api-management",
     "blurb": "Unified account balances and perpetual positions. " + _RO,
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"),
                field("base", "API address", secret=False, required=False, default="https://api.bybit.com",
                      options=["https://api.bybit.com", "https://api.bytick.com", "https://api.bybit.eu", "https://api.bybit-tr.com"],
                      help="Change only if you use a regional Bybit site.")]},
    {"id": "okx", "group": "exchange", "title": "OKX", "link": "https://www.okx.com/account/my-api",
     "blurb": "Trading + funding account and open positions. " + _RO,
     "fields": [field("api_key", "API key"), field("api_secret", "Secret key"), field("passphrase", "Passphrase"),
                field("base", "API address", secret=False, required=False, default="https://www.okx.com",
                      options=["https://www.okx.com", "https://eea.okx.com", "https://us.okx.com"],
                      help="Change only for the EEA or US site.")]},
    {"id": "mexc", "group": "exchange", "title": "MEXC", "link": "https://www.mexc.com/user/openapi",
     "blurb": "Spot balances and futures. Use 'View account details' + 'View order details' only.",
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"),
                field("futures", "Include futures", secret=False, required=False, default="yes", options=_YESNO)]},
    {"id": "kraken", "group": "exchange", "title": "Kraken", "link": "https://www.kraken.com/u/security/api",
     "blurb": "Spot balances incl. staked assets. Permission needed: 'Query funds' only.",
     "fields": [field("api_key", "API key"), field("api_secret", "Private key")]},
    {"id": "bitget", "group": "exchange", "title": "Bitget (beta)", "link": "https://www.bitget.com/account/newapi",
     "blurb": "Spot balances and USDT futures. " + _RO,
     "fields": [field("api_key", "API key"), field("api_secret", "Secret key"), field("passphrase", "Passphrase"),
                field("futures", "Include futures", secret=False, required=False, default="yes", options=_YESNO)]},
    {"id": "kucoin", "group": "exchange", "title": "KuCoin (beta)", "link": "https://www.kucoin.com/account/api",
     "blurb": "Spot, trading and funding balances. Choose 'General' permission only (no trading, no transfer, no withdrawal).",
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"), field("passphrase", "API passphrase")]},
    {"id": "gate", "group": "exchange", "title": "Gate.io (beta)", "link": "https://www.gate.io/myaccount/apikeys",
     "blurb": "Spot balances and USDT futures margin. Give the key read-only permissions only.",
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"),
                field("futures", "Include futures", secret=False, required=False, default="yes", options=_YESNO)]},
    {"id": "alpaca", "group": "exchange", "title": "Alpaca (US stocks broker)", "link": "https://app.alpaca.markets/paper/dashboard/overview",
     "blurb": "Your US stock and crypto positions and cash. An Alpaca API key can also trade, so keep it private and use the paper account to try this out first. Iris only reads.",
     "fields": [field("api_key", "API key ID"), field("api_secret", "Secret key"),
                field("env", "Account", secret=False, required=False, default="live", options=["live", "paper"], help="'paper' is Alpaca's practice account.")]},
    {"id": "trading212", "group": "exchange", "title": "Trading 212 (stocks broker, beta)", "link": "https://www.trading212.com/",
     "blurb": "Your Trading 212 invested value and cash. Give the key read permissions only. Iris only reads.",
     "fields": [field("api_key", "API key"), field("api_secret", "API secret"),
                field("env", "Account", secret=False, required=False, default="live", options=["live", "demo"], help="'demo' is the practice account.")]},
    {"id": "coinbase", "group": "exchange", "title": "Coinbase (beta)", "link": "https://portal.cdp.coinbase.com/access/api",
     "blurb": "All your Coinbase balances. Create a CDP API key with the View permission only (no trade, no transfer), type ECDSA.",
     "fields": [field("api_key", "API key name", placeholder="organizations/.../apiKeys/..."), field("api_secret", "Private key", placeholder="-----BEGIN EC PRIVATE KEY----- ...")]},
    # ---- socials (credentials; accounts are added in the SOCIALS list) ----
    {"id": "youtube", "group": "social", "title": "YouTube", "link": "https://console.cloud.google.com/apis/credentials",
     "blurb": "Free. Enable 'YouTube Data API v3' in Google Cloud and create an API key. Then add channels below.",
     "fields": [field("api_key", "YouTube Data API key")]},
    {"id": "instagram", "group": "social", "title": "Instagram", "link": "https://developers.facebook.com/docs/instagram-platform/",
     "blurb": "Business or Creator accounts only. Needs a Meta access token; the account id is the numeric Instagram user id.",
     "fields": [field("access_token", "Access token"),
                field("host", "Token type", secret=False, required=False, default="graph.facebook.com",
                      options=["graph.facebook.com", "graph.instagram.com"],
                      help="graph.facebook.com = Facebook Login token, graph.instagram.com = Instagram Login token.")]},
    {"id": "x", "group": "social", "title": "X (Twitter)", "link": "https://developer.x.com/en/portal/dashboard",
     "blurb": "Needs an X developer app Bearer token. X's free tier allows very few reads, so refreshes may be rate-limited.",
     "fields": [field("bearer_token", "Bearer token")]},
    {"id": "telegram", "group": "social", "title": "Telegram", "link": "https://t.me/BotFather",
     "blurb": "Create a bot with @BotFather, add it to your channel or group, then add the @channel name below.",
     "fields": [field("bot_token", "Bot token")]},
    # ---- network / data ----
    {"id": "finnhub", "group": "network", "title": "Finnhub (optional, stock prices)", "link": "https://finnhub.io/register",
     "blurb": "Free key for steadier US stock quotes. Without it Iris uses Yahoo Finance's public prices, which can change or stop without notice.",
     "fields": [field("api_key", "Finnhub API key")]},
    {"id": "solana_rpc", "group": "network", "title": "Solana RPC (optional)", "link": "https://www.helius.dev/",
     "blurb": "The free public RPC is slow and rate-limited. Paste a free personal RPC URL (Helius, QuickNode, ...) for reliable Solana balances.",
     "fields": [field("url", "RPC URL", placeholder="https://mainnet.helius-rpc.com/?api-key=...")]},
]
BY_ID = {p["id"]: p for p in PROVIDERS}


def defaults(pid: str) -> dict:
    return {f["key"]: f["default"] for f in BY_ID[pid]["fields"] if f.get("default") is not None}


def values(pid: str) -> dict:
    """Saved values with defaults filled in (for connectors, never for the browser)."""
    return {**defaults(pid), **vault.get(pid)}


def is_configured(pid: str) -> bool:
    saved = vault.get(pid)
    return all(saved.get(f["key"]) for f in BY_ID[pid]["fields"] if f["required"])


def public_view(pid: str) -> dict:
    """What the browser sees: secrets replaced by a mask."""
    p = BY_ID[pid]
    saved = vault.get(pid)
    fields = []
    for f in p["fields"]:
        v = saved.get(f["key"])
        fields.append({**f, "set": bool(v), "value": (vault.mask(v) if f["secret"] else (v if v else f["default"] or "")) if v or not f["secret"] else ""})
    return {"id": pid, "group": p["group"], "title": p["title"], "link": p["link"], "blurb": p["blurb"], "fields": fields,
            "configured": is_configured(pid), "locked": vault.is_locked(pid), "help": HELP.get(pid)}
