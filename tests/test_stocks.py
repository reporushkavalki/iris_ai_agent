"""Stocks and commodities: the typed-in accounts, the Yahoo / Finnhub parsing, currencies, and how they join the portfolio (no real network)."""
import pytest
from fastapi.testclient import TestClient

import app as appmod
from iris import net, portfolio, pro, providers, stocks, stocks_store, tools, vault

client = TestClient(appmod.app, base_url="http://127.0.0.1:8765")


def chart(price, prev, currency="USD", name="Test Corp"):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "chartPreviousClose": prev, "currency": currency, "shortName": name}}], "error": None}}


@pytest.fixture(autouse=True)
def reset_stocks():
    stocks._cache.clear()
    stocks._fx.clear()
    pro.forget()
    yield


@pytest.fixture
def yahoo(monkeypatch):
    """Fake Yahoo: table maps a symbol (the last part of the URL) to a chart answer or an exception."""
    table, calls = {}, []

    def fake_get(url, **kw):
        sym = url.rsplit("/", 1)[-1]
        calls.append(sym)
        v = table.get(sym)
        if isinstance(v, Exception):
            raise v
        if v is None:
            return {"chart": {"result": None, "error": {"description": "No data found, symbol may be delisted"}}}
        return v
    monkeypatch.setattr(stocks.net, "get", fake_get)
    table["_calls"] = calls
    return table


# ---------- typing the holdings ----------
def test_parse_lines_and_commodity_names():
    items = stocks_store.parse_items("AAPL 10\nGold, 2.5\nneste.he: 100\n\nAAPL 5\nBTC-USD 0,5")
    assert {i["symbol"]: i["qty"] for i in items} == {"AAPL": 15.0, "GC=F": 2.5, "NESTE.HE": 100.0, "BTC-USD": 0.5}


@pytest.mark.parametrize("bad", ["", "AAPL", "AAPL ten", "AAPL -3", "AAPL 0", "A A 3", "$$$ 4", "x" * 20 + " 3"])
def test_bad_lines_are_refused_with_a_hint(bad):
    with pytest.raises(ValueError):
        stocks_store.parse_items(bad)


def test_store_add_lock_update_remove():
    stocks_store.add("Nordnet", "AAPL 10\nGOLD 1")
    assert stocks_store.load()[0]["locked"] is True
    with pytest.raises(ValueError):
        stocks_store.add("nordnet", "MSFT 1")            # same name
    with pytest.raises(ValueError):
        stocks_store.update_items("Nordnet", "MSFT 1")   # locked
    with pytest.raises(ValueError):
        stocks_store.remove("Nordnet")
    stocks_store.set_locked("Nordnet", False)
    stocks_store.update_items("Nordnet", "MSFT 3")
    assert stocks_store.as_text(stocks_store.load()[0]) == "MSFT 3"
    stocks_store.remove("Nordnet")
    assert stocks_store.load() == []


# ---------- prices ----------
def test_yahoo_quote_in_usd(yahoo):
    yahoo["AAPL"] = chart(200.0, 190.0)
    q = stocks.quote("AAPL")
    assert q["price_usd"] == 200.0 and q["change24h"] == 5.26 and q["source"] == "yahoo"


def test_euro_share_is_converted_to_dollars(yahoo):
    yahoo["NESTE.HE"] = chart(20.0, 21.0, "EUR")
    yahoo["EURUSD=X"] = chart(1.10, 1.09)
    q = stocks.quote("NESTE.HE")
    assert q["currency"] == "EUR" and q["price_usd"] == pytest.approx(22.0) and q["change24h"] == pytest.approx(-4.76, abs=0.01)


def test_london_pence_are_divided_by_100(yahoo):
    yahoo["VOD.L"] = chart(70.0, 69.0, "GBp")           # 70 pence
    yahoo["GBPUSD=X"] = chart(1.25, 1.25)
    assert stocks.quote("VOD.L")["price_usd"] == pytest.approx(0.875)


def test_commodity_names_work_through_the_tool(yahoo):
    yahoo["GC=F"] = chart(2400.0, 2380.0)
    out = tools.run_tool("get_quote", {"symbols": ["gold"]})[0]
    assert '"symbol": "GC=F"' in out and "2400" in out


def test_quotes_are_cached_and_a_failure_keeps_the_last_good_price(yahoo, monkeypatch):
    yahoo["AAPL"] = chart(200.0, 190.0)
    stocks.quote("AAPL")
    stocks.quote("AAPL")
    assert yahoo["_calls"].count("AAPL") == 1
    t0 = stocks._cache["AAPL"][0]
    stocks._cache["AAPL"] = (t0 - 500, stocks._cache["AAPL"][1], None)          # older than the cache time, still good
    yahoo["AAPL"] = net.ApiError("HTTP 429: slow down")
    q = stocks.quote("AAPL")
    assert q["price_usd"] == 200.0 and q["stale"] is True
    stocks._cache["AAPL"] = (t0 - 5000, stocks._cache["AAPL"][1], None)         # too old
    with pytest.raises(net.ApiError):
        stocks.quote("AAPL")


def test_unknown_symbol_is_an_error_not_a_crash(yahoo):
    with pytest.raises(net.ApiError):
        stocks.quote("NOPE")
    assert stocks.quotes(["NOPE"]) == {"NOPE": None}
    out = tools.run_tool("get_quote", {"symbols": ["NOPE"]})[0]
    assert "error" in out


def test_finnhub_is_used_for_plain_us_symbols_when_a_key_exists(yahoo, monkeypatch):
    vault.save("finnhub", {"api_key": "fh-key-1234567890"})
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        if "finnhub" in url:
            return {"c": 201.5, "pc": 200.0}
        return chart(1, 1)
    monkeypatch.setattr(stocks.net, "get", fake_get)
    q = stocks.quote("AAPL")
    assert q["source"] == "finnhub" and q["price_usd"] == 201.5 and q["change24h"] == 0.75
    q2 = stocks.quote("NESTE.HE")                       # not a plain US symbol: Yahoo
    assert q2["source"] == "yahoo"
    assert all("fh-key" not in u for u in seen)          # the key travels as a parameter, never in the address


def test_finnhub_failure_falls_back_to_yahoo(yahoo, monkeypatch):
    vault.save("finnhub", {"api_key": "fh-key-1234567890"})
    yahoo["MSFT"] = chart(400.0, 400.0)

    def fake_get(url, **kw):
        if "finnhub" in url:
            return {"c": 0, "pc": 0}                    # unknown symbol for Finnhub
        return yahoo["MSFT"]
    monkeypatch.setattr(stocks.net, "get", fake_get)
    assert stocks.quote("MSFT")["source"] == "yahoo"


# ---------- accounts and the portfolio ----------
def test_account_totals_and_warnings(yahoo):
    yahoo["AAPL"] = chart(200.0, 190.0)
    yahoo["GC=F"] = chart(2400.0, 2380.0)
    acct = stocks.fetch_account({"name": "Broker", "items": [{"symbol": "AAPL", "qty": 10}, {"symbol": "GC=F", "qty": 2}, {"symbol": "ZZZZ", "qty": 5}]})
    assert acct["kind"] == "stocks" and acct["id"] == "stocks:Broker"
    assert acct["total_usd"] == pytest.approx(2000 + 4800)
    assert acct["unpriced"] == ["ZZZZ"] and any("ZZZZ" in w for w in acct["warnings"]) and any("Yahoo" in w for w in acct["warnings"])
    assert [h["symbol"] for h in acct["holdings"]] == ["GC=F", "AAPL"]


def test_stock_account_joins_the_dashboard_with_crypto(yahoo, fake_prices, monkeypatch):
    yahoo["AAPL"] = chart(200.0, 190.0)
    stocks_store.add("Broker", "AAPL 10")
    monkeypatch.setattr(portfolio.wallets_store, "load", lambda: [])
    r = client.post("/api/connections/kraken", json={"values": {"api_key": "k" * 12, "api_secret": "s" * 12}})
    assert r.status_code == 200
    from iris import model
    from iris.exchanges import kraken
    monkeypatch.setattr(kraken.Kraken, "fetch", lambda self: model.make_account("ex:kraken", "Kraken", "exchange", "kraken", [model.holding("BTC", 0.1, "spot")]))
    st = portfolio.status(force=True)
    assert st["total_usd"] == pytest.approx(6000 + 2000)
    assert {a["kind"] for a in st["accounts"]} == {"exchange", "stocks"}
    syms = {h["symbol"] for h in st["holdings"]}
    assert {"BTC", "AAPL"} <= syms


def test_a_broken_stock_account_does_not_hide_the_others(yahoo, fake_prices):
    stocks_store.add("Broker", "NOPE 10")
    st = portfolio.status(force=True)
    a = st["accounts"][0]
    assert a["kind"] == "stocks" and a["total_usd"] == 0 and a["unpriced"] == ["NOPE"]


# ---------- the API and the free limit ----------
def test_api_add_list_lock_remove(yahoo):
    r = client.post("/api/stocks", json={"name": "Nordnet", "text": "AAPL 10\nGOLD 1"})
    assert r.status_code == 200 and r.json()["stock_accounts"][0]["text"] == "AAPL 10\nGC=F 1"
    assert client.post("/api/stocks", json={"name": "Bad", "text": "AAPL"}).status_code == 400
    assert client.post("/api/stocks/remove", json={"name": "Nordnet"}).status_code == 400            # locked
    assert client.post("/api/stocks/lock", json={"name": "Nordnet", "locked": False}).status_code == 200
    r = client.post("/api/stocks/update", json={"name": "Nordnet", "text": "MSFT 2"})
    assert r.status_code == 200 and r.json()["stock_accounts"][0]["items"][0]["symbol"] == "MSFT"
    assert client.post("/api/stocks/remove", json={"name": "Nordnet"}).json()["stock_accounts"] == []


def test_stock_accounts_count_toward_the_free_limit():
    for i in range(5):
        assert client.post("/api/stocks", json={"name": f"S{i}", "text": "AAPL 1"}).status_code == 200
    r = client.post("/api/stocks", json={"name": "S9", "text": "AAPL 1"})
    assert r.status_code == 402 and len(stocks_store.load()) == 5


def test_finnhub_and_pro_cards_exist_with_help():
    ids = {p["id"] for p in providers.PROVIDERS}
    assert {"pro", "finnhub"} <= ids
    pub = {p["id"]: p for p in client.get("/api/connections").json()["providers"]}
    assert pub["pro"]["group"] == "pro" and pub["finnhub"]["help"]["steps"]
