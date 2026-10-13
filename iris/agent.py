"""The assistant: a Claude tool-use loop over the read-only tools in iris/tools.py."""
from datetime import datetime

import anthropic

from iris import providers, vault
from iris.tools import SCHEMAS, run_tool

MAX_STEPS = 8
MAX_HISTORY = 30

SYSTEM = """You are Iris, a calm, quick, friendly assistant inside a personal crypto dashboard.
You can see the user's connected exchanges, wallets (public addresses) and social accounts only through your tools, and everything is READ-ONLY:
you cannot trade, transfer or withdraw, and you must never ask for private keys, seed phrases or API secrets.
Always call a tool for live numbers; never guess balances, prices or follower counts. For total balance, PnL or allocation call get_portfolio;
for where an asset is held call get_holdings; for futures call get_positions; for market prices call get_prices; for audience growth call get_socials; for market sentiment, news, the Fed, CPI, jobs numbers or Fear & Greed call get_market_pulse and never invent news (if it has none, say so).
If a tool says nothing is connected, tell the user to open Connections (the gear button) or try the demo data.
If data comes from demo mode (demo_data true), say it is demo data.
PnL is the change in balance: money deposited or withdrawn counts as gain or loss; mention this once if it matters.
You describe and explain; you do not give financial advice or tell the user what to buy or sell. If asked, give the facts and the trade-offs, and say the decision is theirs.
Style: short and concrete (1-4 sentences unless asked for detail), plain text without markdown tables, say numbers naturally with $ and sensible rounding.
If a tool returns an error, say plainly what failed and what to check.
Current time: {now}."""


class Iris:
    def __init__(self):
        self.history: list[dict] = []
        self._client = None
        self._key = None

    def _client_for_key(self):
        key = vault.get("anthropic").get("api_key")
        if not key:
            raise PermissionError("no_key")
        if key != self._key:
            self._client, self._key = anthropic.Anthropic(api_key=key), key
        return self._client

    def _trim(self):
        while len(self.history) > MAX_HISTORY:
            self.history.pop(0)
        while self.history and not (self.history[0]["role"] == "user" and isinstance(self.history[0]["content"], str)):
            self.history.pop(0)      # restart on a plain user message so tool_use / tool_result stay paired

    def ask(self, text: str) -> str:
        client = self._client_for_key()
        model = providers.values("anthropic").get("model") or "claude-sonnet-5-5"
        self.history.append({"role": "user", "content": text})
        self._trim()
        system = SYSTEM.format(now=datetime.now().astimezone().strftime("%A %Y-%m-%d %H:%M %Z"))
        for _ in range(MAX_STEPS):
            resp = client.messages.create(model=model, max_tokens=1024, system=system, tools=SCHEMAS, messages=self.history)
            self.history.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text").strip()
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out, is_err = run_tool(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out, "is_error": is_err})
            self.history.append({"role": "user", "content": results})
        return "Sorry, I got stuck on that one. Try asking again."
