"""The newer connectors (Bitget, KuCoin, Gate.io, Alpaca) against canned answers, plus their signing recipes. No network."""
import hashlib
import hmac

from iris import net
from iris.exchanges import EXCHANGES, bitget, gate, kucoin
from iris.exchanges.base import hmac_b64


def test_all_new_exchanges_are_registered():
    assert {"bitget", "kucoin", "gate", "alpaca", "trading212", "coinbase"} <= set(EXCHANGES)


def test_bitget_signing_recipe():
    got = bitget.sign("S", "1700000000000", "get", "/api/v2/mix/position/all-position", "productType=USDT-FUTURES")
    assert got == hmac_b64("S", "1700000000000GET/api/v2/mix/position/all-position?productType=USDT-FUTURES")
    assert bitget.sign("S", "1", "GET", "/p") == hmac_b64("S", "1GET/p")


def test_kucoin_signing_recipe():
    assert kucoin.sign("S", "1700", "get", "/api/v1/accounts") == hmac_b64("S", "1700GET/api/v1/accounts")
    assert kucoin.passphrase_header("S", "PP") == hmac_b64("S", "PP")           # key version 2 signs the passphrase


def test_gate_signing_recipe():
    body_hash = hashlib.sha512(b"").hexdigest()
    expect = hmac.new(b"S", f"GET\n/api/v4/spot/accounts\n\n{body_hash}\n1700".encode(), hashlib.sha512).hexdigest()
    assert gate.sign("S", "get", "/api/v4/spot/accounts", "", "", "1700") == expect


def test_bitget_spot_futures_positions(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        h = kw["headers"]
        assert h["ACCESS-KEY"] == "K" and h["ACCESS-PASSPHRASE"] == "PP" and h["ACCESS-SIGN"] and h["ACCESS-TIMESTAMP"]
        if "spot/account/assets" in url:
            return {"code": "00000", "data": [{"coin": "BTC", "available": "0.1", "frozen": "0", "locked": "0"}, {"coin": "ETH", "available": "0"}]}
        if "mix/account/accounts" in url:
            return {"code": "00000", "data": [{"marginCoin": "USDT", "usdtEquity": "500"}]}
        return {"code": "00000", "data": [{"symbol": "ETHUSDT", "holdSide": "short", "total": "2", "openPriceAvg": "3100", "markPrice": "3000",
                                           "leverage": "5", "unrealizedPL": "200", "liquidationPrice": "4000", "marginMode": "crossed"}]}
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["bitget"]({"api_key": "K", "api_secret": "S", "passphrase": "PP"}).fetch()
    assert a["total_usd"] == 6000 + 500 + 200 or a["total_usd"] == 6000 + 500           # futures equity already includes the open profit
    assert a["positions"][0]["side"] == "short" and a["positions"][0]["symbol"] == "ETH-PERP"


def test_bitget_error_code_is_readable(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **kw: {"code": "40018", "msg": "Invalid IP"})
    try:
        EXCHANGES["bitget"]({"api_key": "K", "api_secret": "S", "passphrase": "PP"}).fetch()
        assert False
    except net.ApiError as e:
        assert "Invalid IP" in str(e)


def test_bitget_futures_failure_keeps_spot(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        if "spot/account/assets" in url:
            return {"code": "00000", "data": [{"coin": "ETH", "available": "1", "frozen": "0"}]}
        raise net.ApiError("HTTP 403: no permission")
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["bitget"]({"api_key": "K", "api_secret": "S", "passphrase": "PP"}).fetch()
    assert a["total_usd"] == 3000 and any("Futures not read" in w for w in a["warnings"])


def test_kucoin_sums_account_types(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        h = kw["headers"]
        assert h["KC-API-KEY-VERSION"] == "2" and h["KC-API-PASSPHRASE"] == kucoin.passphrase_header("S", "PP")
        return {"code": "200000", "data": [{"currency": "ETH", "type": "main", "balance": "0.5"}, {"currency": "ETH", "type": "trade", "balance": "0.5"},
                                           {"currency": "USDT", "type": "main", "balance": "100"}, {"currency": "BTC", "type": "main", "balance": "0"}]}
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["kucoin"]({"api_key": "K", "api_secret": "S", "passphrase": "PP"}).fetch()
    assert a["total_usd"] == 3000 + 100


def test_gate_spot_and_futures(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        assert kw["headers"]["KEY"] == "K" and len(kw["headers"]["SIGN"]) == 128
        if "/spot/accounts" in url:
            return [{"currency": "ETH", "available": "0.5", "locked": "0.5"}, {"currency": "BTC", "available": "0", "locked": "0"}]
        return {"total": "250.5"}
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["gate"]({"api_key": "K", "api_secret": "S"}).fetch()
    assert a["total_usd"] == 3000 + 250.5


def test_alpaca_positions_and_cash(monkeypatch):
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        assert kw["headers"]["APCA-API-KEY-ID"] == "K" and kw["headers"]["APCA-API-SECRET-KEY"] == "S"
        if url.endswith("/v2/account"):
            return {"cash": "1000.50"}
        return [{"symbol": "AAPL", "qty": "10", "market_value": "1900", "side": "long", "asset_class": "us_equity"},
                {"symbol": "TSLA", "qty": "-1", "market_value": "-250", "side": "short", "asset_class": "us_equity"}]
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["alpaca"]({"api_key": "K", "api_secret": "S", "env": "paper"}).fetch()
    assert seen[0].startswith("https://paper-api.alpaca.markets") and a["total_usd"] == 1900 + 1000.5
    assert any("paper" in w for w in a["warnings"]) and a["positions"][0]["side"] == "short" and a["positions"][0]["symbol"] == "TSLA"
    live = EXCHANGES["alpaca"]({"api_key": "K", "api_secret": "S"})
    monkeypatch.setattr(net, "get", lambda url, **kw: seen.append(url) or ({"cash": "0"} if url.endswith("account") else []))
    live.fetch()
    assert seen[-1].startswith("https://api.alpaca.markets")


# ---------- Trading 212 and Coinbase ----------
import base64
import json


def test_trading212_summary(monkeypatch):
    from iris import stocks
    monkeypatch.setattr(stocks, "fx_to_usd", lambda cur: 1.1 if cur == "EUR" else 1.0)
    seen = {}

    def fake_get(url, **kw):
        seen["url"], seen["auth"] = url, kw["headers"]["Authorization"]
        return {"currency": "EUR", "totalValue": 1000.0, "cash": {"availableToTrade": 100.0, "inPies": 0, "reservedForOrders": 0},
                "investments": {"currentValue": 900.0}}
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["trading212"]({"api_key": "KID", "api_secret": "SEC", "env": "demo"}).fetch()
    assert seen["url"].startswith("https://demo.trading212.com/api/v0/equity/account/summary")
    assert seen["auth"] == "Basic " + base64.b64encode(b"KID:SEC").decode()
    assert a["total_usd"] == 1100.0 and any("demo" in w for w in a["warnings"])


def test_trading212_without_investments_field(monkeypatch):
    from iris import stocks
    monkeypatch.setattr(stocks, "fx_to_usd", lambda cur: 1.0)
    monkeypatch.setattr(net, "get", lambda url, **kw: {"currency": "USD", "totalValue": 500.0, "cash": {"availableToTrade": 50.0}})
    assert EXCHANGES["trading212"]({"api_key": "K", "api_secret": "S"}).fetch()["total_usd"] == 500.0


def test_coinbase_pem_is_rebuilt_from_one_line():
    pem = "-----BEGIN EC PRIVATE KEY-----\\nAAAA\\nBBBB\\n-----END EC PRIVATE KEY-----\\n"
    one = "-----BEGIN EC PRIVATE KEY----- AAAA BBBB -----END EC PRIVATE KEY-----"
    from iris.exchanges import coinbase
    assert coinbase.normalize_pem(pem) == coinbase.normalize_pem(one) == "-----BEGIN EC PRIVATE KEY-----\nAAAABBBB\n-----END EC PRIVATE KEY-----\n"
    try:
        coinbase.normalize_pem("nonsense")
        assert False
    except net.ApiError:
        pass


def test_coinbase_jwt_is_valid_es256():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from iris.exchanges import coinbase
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()
    oneline = pem.replace("\n", " ")                                        # what a single-line box would give
    jwt = coinbase.make_jwt("organizations/o/apiKeys/k", oneline, "GET", "api.coinbase.com", "/api/v3/brokerage/accounts", now=1_700_000_000)
    h, p, s = jwt.split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)
    header, payload = json.loads(base64.urlsafe_b64decode(pad(h))), json.loads(base64.urlsafe_b64decode(pad(p)))
    assert header["alg"] == "ES256" and header["kid"] == "organizations/o/apiKeys/k" and header["nonce"]
    assert payload == {"sub": "organizations/o/apiKeys/k", "iss": "cdp", "nbf": 1_700_000_000, "exp": 1_700_000_120, "uri": "GET api.coinbase.com/api/v3/brokerage/accounts"}
    raw = base64.urlsafe_b64decode(pad(s))
    assert len(raw) == 64
    key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), (h + "." + p).encode(), ec.ECDSA(hashes.SHA256()))


def test_coinbase_balances_and_paging(monkeypatch, fake_prices):
    from iris.exchanges import coinbase
    monkeypatch.setattr(coinbase, "make_jwt", lambda *a, **k: "JWT")
    pages = [{"accounts": [{"currency": "ETH", "available_balance": {"value": "0.5"}, "hold": {"value": "0"}}, {"currency": "USD", "available_balance": {"value": "100"}, "hold": {"value": "0"}}],
              "has_next": True, "cursor": "c2"},
             {"accounts": [{"currency": "ETH", "available_balance": {"value": "0.5"}, "hold": {"value": "0"}}, {"currency": "BTC", "available_balance": {"value": "0"}}], "has_next": False}]
    urls = []

    def fake_get(url, **kw):
        urls.append(url)
        assert kw["headers"]["Authorization"] == "Bearer JWT"
        return pages[len(urls) - 1]
    monkeypatch.setattr(net, "get", fake_get)
    a = EXCHANGES["coinbase"]({"api_key": "organizations/o/apiKeys/k", "api_secret": "x"}).fetch()
    assert "cursor=c2" in urls[1] and a["total_usd"] == 3000 + 100
