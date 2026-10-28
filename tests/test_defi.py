"""DeFi data (DefiLlama) with canned answers, and the Pro gate. No network."""
import json

import pytest

from iris import defi, net, pro, tools

POOLS = {"status": "success", "data": [
    {"chain": "Ethereum", "project": "aave-v3", "symbol": "USDC", "tvlUsd": 900_000_000, "apy": 4.5, "apyBase": 4.5, "apyReward": None, "stablecoin": True, "ilRisk": "no"},
    {"chain": "Solana", "project": "kamino-lend", "symbol": "SOL", "tvlUsd": 300_000_000, "apy": 7.0, "apyBase": 5, "apyReward": 2, "stablecoin": False, "ilRisk": "no"},
    {"chain": "Ethereum", "project": "tiny", "symbol": "X", "tvlUsd": 1000, "apy": 900, "stablecoin": False},          # too small
    {"chain": "Ethereum", "project": "broken", "symbol": "Y", "tvlUsd": 50_000_000, "apy": 99999, "stablecoin": False},  # absurd apy
    {"chain": "Ethereum", "project": "lido", "symbol": "STETH", "tvlUsd": 20_000_000_000, "apy": 3.1, "stablecoin": False, "ilRisk": "no"}]}


@pytest.fixture(autouse=True)
def clean():
    defi._cache.clear()
    yield
    defi._cache.clear()


def fake(monkeypatch, payloads):
    calls = []

    def g(url, **kw):
        calls.append(url)
        return payloads[url]
    monkeypatch.setattr(net, "get", g)
    return calls


def test_yields_filtered_sorted_and_junk_removed(monkeypatch):
    fake(monkeypatch, {defi.YIELDS_URL: POOLS})
    r = defi.top_yields()
    assert [p["project"] for p in r["pools"]] == ["kamino-lend", "aave-v3", "lido"] and r["matched"] == 3
    assert [p["project"] for p in defi.top_yields(chain="ethereum", stablecoin_only=True)["pools"]] == ["aave-v3"]
    assert [p["project"] for p in defi.top_yields(project="LIDO")["pools"]] == ["lido"]
    assert "Not advice" in r["note"]


def test_lists_are_cached(monkeypatch):
    calls = fake(monkeypatch, {defi.YIELDS_URL: POOLS})
    defi.top_yields(); defi.top_yields(chain="Solana")
    assert len(calls) == 1


def test_protocols_and_chains(monkeypatch):
    fake(monkeypatch, {defi.PROTOCOLS_URL: [{"name": "Aave", "category": "Lending", "tvl": 2e10, "change_1d": 0.5, "change_7d": -1.2, "chains": ["Ethereum"]},
                                            {"name": "Uniswap", "category": "Dexs", "tvl": 5e9, "chains": []}, {"name": "Dead", "tvl": 0}],
                         defi.CHAINS_URL: [{"name": "Ethereum", "tvl": 7e10}, {"name": "Solana", "tvl": 9e9}]})
    p = defi.protocols()
    assert [x["name"] for x in p["protocols"]] == ["Aave", "Uniswap"]
    assert [x["name"] for x in defi.protocols("dexs")["protocols"]] == ["Uniswap"]
    assert defi.chains()["chains"][0]["name"] == "Ethereum"


def test_bad_answer_is_a_readable_error(monkeypatch):
    fake(monkeypatch, {defi.YIELDS_URL: {"unexpected": True}})
    with pytest.raises(net.ApiError):
        defi.top_yields()


def test_tool_is_pro_only(monkeypatch):
    fake(monkeypatch, {defi.YIELDS_URL: POOLS})
    out, err = tools.run_tool("get_defi", {"kind": "yields"})
    assert "Iris Pro" in json.loads(out)["error"]
    monkeypatch.setattr(pro, "is_pro", lambda: True)
    out, err = tools.run_tool("get_defi", {"kind": "yields", "chain": "Solana"})
    assert json.loads(out)["pools"][0]["project"] == "kamino-lend"


def test_tool_error_does_not_crash(monkeypatch):
    monkeypatch.setattr(pro, "is_pro", lambda: True)

    def boom(url, **kw):
        raise net.ApiError("network error")
    monkeypatch.setattr(net, "get", boom)
    out, err = tools.run_tool("get_defi", {"kind": "chains"})
    assert "network error" in json.loads(out)["error"]
