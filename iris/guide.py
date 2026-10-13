"""The built-in guide: answers a few common questions WITHOUT a Claude key (no internet, no cost).

It explains the app and, when there is data (or demo data), reads simple numbers from the dashboard.
Once a Claude key is saved, the real assistant takes over and the guide is not used.
"""
import re

NOTE = "Preview answer from the built-in guide. Add your Claude key under Connections to ask anything about your numbers."

INTRO = ("I'm Iris, your crypto control room. I run only on your computer. I show your balances across exchanges and wallets, "
         "your open futures positions, how your profit and loss moves, and how your social accounts grow. "
         "Everything is read-only, so I can never trade or move your money.")

START = ("Getting started takes three steps. First, press Try Demo Data to look around with made-up numbers. "
         "Second, open Connections and add what you use: a read-only exchange key or a public wallet address. Each one has a small i button that explains how to get the key. "
         "Third, add your Claude key so I can answer questions about your real numbers. You can skip any step.")

SAFE = ("Iris only reads. There is no code in it that can trade, transfer or withdraw. Your keys stay in a folder on this computer, "
        "locked after saving, and are sent only to the service they belong to. Always create read-only keys, and never paste a seed phrase or private key anywhere.")

CLAUDE = ("To talk to me about your real numbers you need a Claude API key. Go to console.anthropic.com, create a key, add a few dollars of credit, "
          "then open Connections, paste it under Claude AI assistant and press Save and Lock. Short questions cost a fraction of a cent. "
          "Until then I can explain the app, and answer simple number questions from the dashboard.")

CONNECT = ("Open Connections to add Binance, Bybit, OKX, MEXC or Kraken with a read-only key, or paste the public address of a Solana, Ethereum, Bitcoin or Hyperliquid wallet. "
           "Each card has a small i button with the exact steps. Add only what you use, and every section fills in as soon as it has data.")

SOCIAL = ("The Socials section tracks followers, growth over a day, a week and a month, and the likes of your latest posts. It supports YouTube, Instagram, X, Telegram and Discord. "
          "Add the platform key in Connections, then add your account under Tracked accounts. Growth numbers build up while Iris is running.")

PNL = ("Profit and loss is the change in your balance over a period, added up per account. Iris saves a snapshot every few minutes while it is running, "
       "so it needs some time to learn your history. New accounts count from the moment Iris first sees them, so a starting balance is never shown as profit.")

DEMO = ("Demo data fills the dashboard with made-up numbers so you can look around. Nothing real is read. Turn it on with Try Demo Data, and off again in Connections at the bottom.")

MARKETS = ("The markets panel follows the coins you hold, largest first. With no holdings yet it shows the eight biggest coins by market cap, with a 24 hour sparkline.")


def _has(t: str, *words: str) -> bool:
    return any(re.search(r"\b" + w, t) for w in words)


def _usd(v) -> str:
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def _signed(p: dict) -> str:
    if not p or p.get("usd") is None:
        return "still collecting"
    return f"{'+' if p['usd'] >= 0 else '-'}{_usd(abs(p['usd']))} ({p['pct']:+.2f}%)"


def answer(text: str, status: dict) -> str:
    return answer_focus(text, status)[0]


def answer_focus(text: str, status: dict) -> tuple[str, str | None]:
    """(reply, which part of the app it is about) so the page can softly highlight that part."""
    t = text.lower()
    total = status.get("total_usd") or 0
    have = bool(status.get("accounts")) and total > 0
    demo = status.get("demo")
    tag = " This is demo data." if demo else ""
    nodata = "Nothing is connected yet, so there are no numbers to show. Press Try Demo Data to see an example, or open Connections to add your accounts."

    if _has(t, "safe", "secur", "trade", "withdraw", "steal", "hack", "private", "risk to my", "read.only"):
        return SAFE, None
    if _has(t, "claude", "anthropic", "api key", "ai key", "real answer", "unlock"):
        return CLAUDE, "claude"
    if _has(t, "start", "begin", "set up", "setup", "how do i", "how to", "get going", "first"):
        return START, "start"
    if _has(t, "demo", "fake", "made.up", "example"):
        return DEMO, "demo"
    if _has(t, "social", "follower", "youtube", "instagram", "telegram", "discord", "subscriber"):
        return SOCIAL, "social"
    if _has(t, "connect", "exchange", "binance", "bybit", "okx", "mexc", "kraken", "wallet", "address", "add my"):
        return CONNECT, "connect"
    if _has(t, "pnl", "profit", "loss", "perform", "week", "month", "today", "how did i do", "gain"):
        if not have:
            return PNL + " " + nodata, "pnl"
        p = status.get("pnl", {})
        return f"Over the last day you are {_signed(p.get('d1'))}, over 7 days {_signed(p.get('d7'))}, and over 30 days {_signed(p.get('d30'))}.{tag}", "pnl"
    if _has(t, "position", "liquidat", "futures", "leverage", "perp"):
        if not have:
            return nodata, None
        pos = status.get("positions", [])
        if not pos:
            return "You have no open futures positions right now.", "positions"
        return f"You have {len(pos)} open position{'s' if len(pos) != 1 else ''}, with a combined unrealized profit and loss of {_usd(status.get('upnl_usd', 0))}.{tag}", "positions"
    if _has(t, "stable", "usdt", "usdc"):
        return (f"About {status.get('stable_pct', 0):.0f} percent of your balance is in stablecoins.{tag}", "stable") if have else (nodata, None)
    if _has(t, "biggest", "largest", "which account", "which of my accounts"):
        if not have:
            return nodata, None
        a = status["accounts"][0]
        return f"Your biggest account is {a['name']} with {_usd(a['total_usd'])}, which is {a.get('share_pct', 0):.0f} percent of the total.{tag}", "biggest"
    if _has(t, "market", "moving", "price"):
        return MARKETS, "markets"
    if _has(t, "balance", "total", "worth", "how much", "hold", "portfolio", "expos", "btc", "bitcoin", "summar"):
        if not have:
            return nodata, None
        top = ", ".join(f"{h['symbol']} {_usd(h['usd'])}" for h in status.get("holdings", [])[:3])
        return f"Your total balance is {_usd(total)} across {len(status['accounts'])} account{'s' if len(status['accounts']) != 1 else ''}. The largest holdings are {top}.{tag}", "balance"
    if _has(t, "what", "who", "about", "explain", "hello", "hi", "hey", "help", "can you", "do you"):
        return INTRO + " " + START, "intro"
    return "I'm the built-in guide, so I only know the basics until you add a Claude key. Try asking: what is Iris, how do I get started, is it safe, or what is my total balance.", None
