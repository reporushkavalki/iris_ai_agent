"""The AI's tools. All read-only: there is no function that trades, transfers or withdraws."""
import json

from iris import market, portfolio, prices, socials, vault


def _schema(name, description, props=None, required=None):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {}, "required": required or []}}


SCHEMAS = [
    _schema("get_portfolio", "Total balance in USD across all connected exchanges and wallets, PnL for 24h / 7d / 30d, each account's value and share, "
            "top assets, unrealised PnL of open positions and the stablecoin share. Use for 'how am I doing' and 'what do I have'.",
            {"refresh": {"type": "boolean", "description": "Force a fresh read instead of the last few seconds' cache."}}),
    _schema("get_holdings", "Where a specific asset is held (which exchange or wallet, how much, USD value). Without a symbol: the biggest assets overall.",
            {"symbol": {"type": "string", "description": "e.g. BTC, ETH, SOL"}}),
    _schema("get_positions", "Open futures/perpetual positions across all exchanges: side, size, entry, mark, leverage, liquidation price, unrealised PnL."),
    _schema("get_prices", "Live price, 24h change and a mini trend for up to 10 coins (public market data).",
            {"symbols": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['BTC','ETH']"}}, ["symbols"]),
    _schema("get_pnl_calendar", "Balance change per day for a month (deposits/withdrawals count as change).",
            {"month": {"type": "string", "description": "YYYY-MM, default current month"}}),
    _schema("get_market_pulse", "Market and crypto pulse from free public sources: the latest important news and data releases (Fed, BLS CPI/jobs numbers, SEC, crypto news), "
            "upcoming high-impact events such as FOMC meetings, CPI and jobs reports with forecasts, the Fear & Greed index, trending coins, Reddit mood and an overall mood score. "
            "Use it for sentiment, news, 'what is moving the market' and 'what is coming up' questions."),
    _schema("get_socials", "The user's tracked social accounts: followers, growth over 24h / 7d / 30d and likes/views of recent posts."),
]


def _round(x, n=2):
    return None if x is None else round(x, n)


def get_portfolio(refresh: bool = False) -> dict:
    st = portfolio.status(force=bool(refresh))
    if not st.get("configured"):
        return {"error": "Nothing is connected yet. Open Connections (the gear) to add an exchange API key or a wallet address, or try demo data."}
    return {
        "demo_data": st["demo"], "total_usd": st["total_usd"], "pnl": st["pnl"], "unrealised_pnl_open_positions_usd": st["upnl_usd"],
        "stablecoin_share_pct": st["stable_pct"], "some_accounts_failed": st["incomplete"],
        "accounts": [{"name": a["name"], "type": a["kind"], "usd": a["total_usd"], "share_pct": a["share_pct"], "error": a["error"], "stale": a["stale"]}
                     for a in st["accounts"]],
        "top_assets": [{"symbol": h["symbol"], "usd": h["usd"], "pct": h["pct"]} for h in st["holdings"][:12]],
        "note": "PnL is the change in balance; deposits and withdrawals from outside count as gains/losses.",
    }


def get_holdings(symbol: str = "") -> dict:
    st = portfolio.status()
    rows = st.get("holdings", [])
    if symbol:
        want = prices.norm(symbol)
        rows = [h for h in rows if prices.norm(h["symbol"]) == want]
        if not rows:
            return {"symbol": want, "found": False, "note": "Not held in any connected account (small or unpriced balances may be hidden)."}
    return {"holdings": [{"symbol": h["symbol"], "amount": h["amount"], "usd": h["usd"], "pct_of_portfolio": h["pct"], "in": h["in"][:6]} for h in rows[:25]]}


def get_positions() -> dict:
    st = portfolio.status()
    return {"open_positions": [{k: p.get(k) for k in ("account", "exchange", "symbol", "side", "size", "entry", "mark", "leverage", "liq", "upnl", "margin_mode")}
                               for p in st.get("positions", [])], "total_unrealised_pnl_usd": st.get("upnl_usd", 0)}


def get_prices(symbols: list) -> dict:
    from iris import prefs
    if prefs.demo_on():
        from iris import demo
        return {"markets": demo.markets()}
    rows = prices.markets([str(s) for s in symbols][:10])
    return {"markets": [{"symbol": r["symbol"], "price": r["price"], "change_24h_pct": r["change24h"]} for r in rows]}


def get_pnl_calendar(month: str = "") -> dict:
    return portfolio.calendar(month or None)


def get_socials() -> dict:
    rows = socials.read_all()
    if not rows:
        return {"error": "No social accounts tracked yet. Add them in the SOCIALS section."}
    return {"accounts": [{"name": r["name"], "platform": r["platform_label"], "followers": r["followers"],
                          "growth": {k: v for k, v in (r.get("growth") or {}).items() if k != "spark"}, "stats": r["stats"],
                          "recent_posts": [{k: p.get(k) for k in ("title", "likes", "views", "comments")} for p in r["posts"][:5]], "error": r["error"]}
                         for r in rows]}


def get_market_pulse() -> dict:
    return market.get_market_pulse()


FUNCS = {"get_market_pulse": get_market_pulse, "get_portfolio": get_portfolio, "get_holdings": get_holdings, "get_positions": get_positions, "get_prices": get_prices,
         "get_pnl_calendar": get_pnl_calendar, "get_socials": get_socials}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """(json text, is_error). Errors go back to the model so it can explain them in plain words."""
    if name not in FUNCS:
        return json.dumps({"error": f"unknown tool {name}"}), True
    try:
        return json.dumps(FUNCS[name](**(args or {})), default=str), False
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": vault.scrub(f"{type(e).__name__}: {e}")}), True
