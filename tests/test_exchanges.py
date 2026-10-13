"""Connectors against canned API answers (no network, no keys)."""
from iris import net
from iris.exchanges import EXCHANGES
from iris.exchanges import binance as bn


def test_binance_spot_and_futures(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        assert kw["headers"]["X-MBX-APIKEY"] == "KEY" and "signature=" in url and "timestamp=" in url
        if "/api/v3/account" in url:
            return {"balances": [{"asset": "BTC", "free": "0.1", "locked": "0.05"}, {"asset": "USDT", "free": "100", "locked": "0"},
                                 {"asset": "LDUSDT", "free": "50", "locked": "0"}, {"asset": "DOGE", "free": "0", "locked": "0"}]}
        if "/fapi/v3/account" in url:
            return {"totalMarginBalance": "1000.5"}
        if "/fapi/v3/positionRisk" in url:
            return [{"symbol": "ETHUSDT", "positionAmt": "-2", "entryPrice": "3100", "markPrice": "3000", "unRealizedProfit": "200",
                     "liquidationPrice": "4000", "leverage": "5", "marginType": "cross"}, {"symbol": "BTCUSDT", "positionAmt": "0"}]
        raise AssertionError(url)
    monkeypatch.setattr(net, "get", fake_get)
    acct = EXCHANGES["binance"]({"api_key": "KEY", "api_secret": "SECRET", "futures": "yes"}).fetch()
    assert acct["total_usd"] == 0.15 * 60000 + 100 + 50 + 1000.5      # LDUSDT counted as USDT (Simple Earn)
    assert acct["positions"][0]["side"] == "short" and acct["positions"][0]["upnl"] == 200 and acct["upnl_usd"] == 200
    assert len(acct["positions"]) == 1 and not acct["warnings"]


def test_binance_futures_failure_does_not_lose_spot(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        if "/api/v3/account" in url:
            return {"balances": [{"asset": "ETH", "free": "1", "locked": "0"}]}
        raise net.ApiError("HTTP 401: Invalid API-key, IP, or permissions for action. (code -2015)")
    monkeypatch.setattr(net, "get", fake_get)
    acct = EXCHANGES["binance"]({"api_key": "KEY", "api_secret": "SECRET"}).fetch()
    assert acct["total_usd"] == 3000 and "Futures not read" in acct["warnings"][0]


def test_binance_permission_warnings(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **kw: {"enableWithdrawals": True, "enableSpotAndMarginTrading": True, "enableFutures": False})
    w = EXCHANGES["binance"]({"api_key": "K", "api_secret": "S"}).permissions()
    assert [x["level"] for x in w] == ["danger", "warn"]


def test_bybit_unified(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        h = kw["headers"]
        assert h["X-BAPI-API-KEY"] == "K" and len(h["X-BAPI-SIGN"]) == 64
        if "wallet-balance" in url:
            return {"retCode": 0, "result": {"list": [{"totalEquity": "1210.00", "coin": [
                {"coin": "USDT", "walletBalance": "1000", "usdValue": "1000"}, {"coin": "SOL", "walletBalance": "1", "usdValue": "150"}]}]}}
        return {"retCode": 0, "result": {"list": [{"symbol": "SOLUSDT", "side": "Buy", "size": "2", "avgPrice": "140", "markPrice": "150",
                                                    "leverage": "3", "unrealisedPnl": "20", "liqPrice": "100"}]}}
    monkeypatch.setattr(net, "get", fake_get)
    acct = EXCHANGES["bybit"]({"api_key": "K", "api_secret": "S"}).fetch()
    assert acct["total_usd"] == 1210.0                                  # 1150 in coins + 60 unrealised
    assert acct["positions"][0]["side"] == "long" and acct["positions"][0]["symbol"] == "SOL-PERP"


def test_okx_balance_positions(monkeypatch, fake_prices):
    def fake_get(url, **kw):
        assert kw["headers"]["OK-ACCESS-PASSPHRASE"] == "PP"
        if "account/balance" in url:
            return {"code": "0", "data": [{"details": [{"ccy": "BTC", "eq": "0.1", "eqUsd": "6000"}, {"ccy": "USDT", "eq": "500", "eqUsd": "500"}]}]}
        if "asset/balances" in url:
            return {"code": "0", "data": [{"ccy": "ETH", "bal": "1"}]}
        return {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "posSide": "net", "pos": "-3", "avgPx": "61000", "markPx": "60000", "upl": "30", "lever": "10", "liqPx": "70000", "mgnMode": "cross"}]}
    monkeypatch.setattr(net, "get", fake_get)
    acct = EXCHANGES["okx"]({"api_key": "K", "api_secret": "S", "passphrase": "PP"}).fetch()
    assert acct["total_usd"] == 6000 + 500 + 3000
    assert acct["positions"][0]["side"] == "short" and acct["positions"][0]["symbol"] == "BTC-PERP"


def test_kraken_balance(monkeypatch, fake_prices):
    monkeypatch.setattr(net, "post", lambda url, **kw: {"error": [], "result": {"XXBT": "0.5", "ZUSD": "100", "ETH.F": "1", "XETH": "1"}})
    acct = EXCHANGES["kraken"]({"api_key": "K", "api_secret": "c2VjcmV0"}).fetch()
    assert acct["total_usd"] == 30000 + 100 + 6000


def test_kraken_error_is_readable(monkeypatch):
    monkeypatch.setattr(net, "post", lambda url, **kw: {"error": ["EAPI:Invalid key"]})
    try:
        EXCHANGES["kraken"]({"api_key": "K", "api_secret": "c2VjcmV0"}).fetch()
        assert False
    except net.ApiError as e:
        assert "Invalid key" in str(e)
