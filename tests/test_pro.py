"""Iris Pro: license check, offline grace, the 5-account free limit and the hosted AI (no real network anywhere)."""
import json
import time

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

import app as appmod
from iris import agent, net, pro, vault
from iris.chains import wallets_store

client = TestClient(appmod.app, base_url="http://127.0.0.1:8765")
KEY = "IRIS-ABCD-EFGH-IJKL-MNOP"
SOL = "So11111111111111111111111111111111111111112"


def addr(i):
    """A valid-looking Solana address (base58 has no 0, O, I or l)."""
    return "A" * 43 + "123456789"[i]


@pytest.fixture(autouse=True)
def fresh_pro():
    pro.forget()
    yield
    pro.forget()


def server(monkeypatch, answer):
    """Fake Pro server. `answer` is a dict (returned) or an Exception (raised)."""
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw.get("json")))
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(pro.net, "post", fake_post)
    return calls


def save_key():
    vault.save("pro", {"license_key": KEY})


GOOD = {"valid": True, "expires": "2027-01-01", "ai": {"enabled": True, "used_pct": 12, "exhausted": False, "resets": "2026-11-01"}}


def test_free_by_default_and_no_network_without_a_key(monkeypatch):
    calls = server(monkeypatch, GOOD)
    st = pro.status(force=True)
    assert st["plan"] == "free" and st["account_limit"] == 5 and not calls
    assert pro.is_pro() is False and pro.ai_ready() is False


def test_valid_license_makes_pro_and_is_remembered_on_disk(monkeypatch):
    save_key()
    calls = server(monkeypatch, GOOD)
    st = pro.refresh()
    assert st["plan"] == "pro" and st["active"] and st["account_limit"] is None and st["ai"]["used_pct"] == 12
    assert calls[0][0].endswith("/license/status") and calls[0][1] == {"key": KEY}
    pro._mem.update(t=0.0, fp="", v=None)                 # a restart: the memory is empty, the file remains
    assert pro.cached_status()["active"] is True and pro.ai_ready() is True


def test_invalid_license_is_free_and_has_no_grace(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    server(monkeypatch, {"valid": False, "reason": "This license has expired."})
    st = pro.refresh()
    assert st["plan"] == "free" and "expired" in st["reason"]
    pro._mem.update(t=0.0, fp="", v=None)
    assert pro.cached_status()["active"] is False          # the "no" is remembered too


def test_server_down_keeps_pro_for_a_week_then_stops(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    server(monkeypatch, net.ApiError("network error (ConnectError); check your internet connection"))
    st = pro.refresh()
    assert st["active"] and st["offline"] is True
    saved = json.loads(pro.PRO_FILE.read_text())
    saved["checked"] = time.time() - 8 * 86400
    pro.PRO_FILE.write_text(json.dumps(saved))
    assert pro.refresh()["active"] is False
    server(monkeypatch, net.ApiError("HTTP 403: nope"))
    assert pro.refresh()["active"] is False


def test_the_key_never_reaches_the_browser(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    for path in ("/api/pro", "/api/connections", "/api/status"):
        assert KEY not in client.get(path).text, path


def test_saving_the_license_in_connections_checks_it_at_once(monkeypatch):
    calls = server(monkeypatch, GOOD)
    r = client.post("/api/connections/pro", json={"values": {"license_key": KEY}})
    assert r.status_code == 200 and calls
    pv = r.json()["pro"]
    assert pv["plan"] == "pro" and pv["has_key"] is True and "license_key" not in json.dumps(pv)
    assert client.get("/api/status").json()["ai_ready"] is True


def test_free_plan_stops_at_five_accounts_and_pro_does_not(monkeypatch):
    for i in range(5):
        r = client.post("/api/wallets", json={"name": f"W{i}", "address": addr(i), "chain": "solana"})
        assert r.status_code == 200, r.text
    r = client.post("/api/wallets", json={"name": "W9", "address": "B" * 44, "chain": "solana"})
    assert r.status_code == 402 and "free plan" in r.json()["detail"] and "Pro" in r.json()["detail"]
    assert len(wallets_store.load()) == 5
    server(monkeypatch, GOOD)
    client.post("/api/connections/pro", json={"values": {"license_key": KEY}})
    r = client.post("/api/wallets", json={"name": "W9", "address": "B" * 44, "chain": "solana"})
    assert r.status_code == 200 and len(wallets_store.load()) == 6


def test_the_limit_counts_exchanges_and_never_removes_what_exists():
    for i in range(4):
        wallets_store.add(f"W{i}", addr(i), "solana")
    assert client.post("/api/connections/kraken", json={"values": {"api_key": "k" * 12, "api_secret": "s" * 12}}).status_code == 200
    assert pro.count_accounts() == 5
    r = client.post("/api/wallets", json={"name": "W9", "address": "B" * 44, "chain": "solana"})
    assert r.status_code == 402
    # editing an account that is already connected is always allowed
    client.post("/api/connections/kraken/lock", json={"locked": False})
    assert client.post("/api/connections/kraken", json={"values": {"api_key": "n" * 12}}).status_code == 200
    # non-exchange keys (Claude, YouTube ...) are not accounts
    assert client.post("/api/connections/anthropic", json={"values": {"api_key": "sk-ant-" + "a" * 20}}).status_code == 200


def test_demo_mode_ignores_the_limit():
    from iris import prefs
    for i in range(5):
        wallets_store.add(f"W{i}", addr(i), "solana")
    prefs.set_value("demo", True)
    pro.check_can_add()


# ---------- the hosted AI ----------
class FakeMessages:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome):
        self.messages = FakeMessages(outcome)


class Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class Resp:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [Block(text)]


def http_error(code, message):
    req = httpx.Request("POST", "https://iris-pro.example/ai/v1/messages")
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": message}}
    resp = httpx.Response(code, request=req, json=body)
    cls = {401: anthropic.AuthenticationError, 403: anthropic.PermissionDeniedError, 429: anthropic.RateLimitError}.get(code, anthropic.APIStatusError)
    return cls(message, response=resp, body=body)


def test_own_claude_key_is_used_before_the_hosted_ai(monkeypatch):
    vault.save("anthropic", {"api_key": "sk-ant-" + "a" * 20})
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    ir = agent.Iris()
    c, model, hosted = ir._client_for_key()
    assert hosted is False and model == "claude-sonnet-5-5"


def test_hosted_ai_is_used_without_own_key(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    fake = FakeClient(Resp("Hello from the hosted AI"))
    monkeypatch.setattr(pro, "hosted_client", lambda: fake)
    ir = agent.Iris()
    assert ir.ask("hi") == "Hello from the hosted AI"
    assert fake.messages.calls[0]["model"] == "iris-pro" and fake.messages.calls[0]["max_tokens"] <= 1024


def test_hosted_client_points_at_the_pro_server_with_the_license_as_key():
    save_key()
    c = pro.hosted_client()
    assert str(c.base_url).rstrip("/") == pro.PRO_URL + "/ai" and c.api_key == KEY


def test_exhausted_allowance_falls_back_to_the_guide(monkeypatch):
    save_key()
    server(monkeypatch, {**GOOD, "ai": {"enabled": True, "used_pct": 100, "exhausted": True, "resets": "2026-11-01"}})
    pro.refresh()
    assert pro.ai_ready() is False
    r = client.post("/api/chat", json={"text": "what can you do?"})
    assert r.status_code == 200 and r.json().get("guide") is True


def test_allowance_message_reaches_the_chat_and_the_question_is_dropped(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    msg = "Your Iris AI allowance for this month is used up. It resets on 1 Nov."
    fake = FakeClient(http_error(429, msg))
    monkeypatch.setattr(pro, "hosted_client", lambda: fake)
    appmod._agent = None
    r = client.post("/api/chat", json={"text": "how am I doing?"}).json()
    assert r["error"] is True and "allowance" in r["reply"] and "1 Nov" in r["reply"]
    assert appmod._agent.history == []


def test_license_refused_by_the_ai_server(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    fake = FakeClient(http_error(401, "This license key was not accepted."))
    monkeypatch.setattr(pro, "hosted_client", lambda: fake)
    appmod._agent = None
    r = client.post("/api/chat", json={"text": "hello"}).json()
    assert "license" in r["reply"].lower() and r["error"] is True


def test_errors_of_your_own_key_are_not_rewritten(monkeypatch):
    vault.save("anthropic", {"api_key": "sk-ant-" + "a" * 20})
    fake = FakeClient(http_error(429, "rate limited by anthropic"))
    monkeypatch.setattr(agent.anthropic, "Anthropic", lambda api_key: fake)
    appmod._agent = None
    r = client.post("/api/chat", json={"text": "hello"}).json()
    assert r["error"] is True and "allowance" not in r["reply"]


def test_connection_test_for_pro(monkeypatch):
    save_key()
    server(monkeypatch, GOOD)
    r = client.post("/api/connections/pro/test").json()
    assert r["ok"] and "active" in r["message"] and "12%" in r["message"]
    server(monkeypatch, {"valid": False, "reason": "License not found."})
    r = client.post("/api/connections/pro/test").json()
    assert r["ok"] is False and "not found" in r["message"].lower()


# ---------- the lock: what the free plan includes ----------
def test_free_plan_lists_locked_connections_and_blocks_saving_them(monkeypatch):
    data = client.get("/api/connections").json()
    by = {p["id"]: p for p in data["providers"]}
    assert not by["kraken"]["needs_pro"] and not by["anthropic"]["needs_pro"]
    for pid in ("binance", "bybit", "okx", "mexc", "bitget", "kucoin", "gate", "alpaca", "trading212", "coinbase", "youtube", "x", "telegram", "finnhub", "solana_rpc"):
        assert by[pid]["needs_pro"], pid
    r = client.post("/api/connections/okx", json={"values": {"api_key": "K" * 12, "api_secret": "S" * 12, "passphrase": "P" * 8}})
    assert r.status_code == 402 and "Iris Pro" in r.json()["detail"] and not vault.exists("okx")
    r = client.post("/api/connections/finnhub", json={"values": {"api_key": "K" * 12}})
    assert r.status_code == 402
    r = client.post("/api/social-accounts", json={"name": "Me", "platform": "discord", "handle": "x"})
    assert r.status_code in (400, 402) and not client.get("/api/connections").json()["social_accounts"]


def test_free_connections_still_save():
    r = client.post("/api/connections/kraken", json={"values": {"api_key": "K" * 12, "api_secret": "S" * 12}})
    assert r.status_code == 200
    vault.set_locked("kraken", False); vault.remove("kraken")
    r = client.post("/api/connections/binance", json={"values": {"api_key": "K" * 12, "api_secret": "S" * 12}})
    assert r.status_code == 402 and "Binance" in r.json()["detail"]


def test_pro_unlocks_everything(monkeypatch):
    server(monkeypatch, {"valid": True, "active": True, "plan": "pro", "ai": {"enabled": True, "used_pct": 1}})
    client.post("/api/connections/pro", json={"values": {"license_key": KEY}})
    by = {p["id"]: p for p in client.get("/api/connections").json()["providers"]}
    assert not any(p["needs_pro"] for p in by.values())
    r = client.post("/api/connections/okx", json={"values": {"api_key": "K" * 12, "api_secret": "S" * 12, "passphrase": "P" * 8}})
    assert r.status_code == 200
    vault.set_locked("okx", False); vault.remove("okx")


def test_a_connection_saved_earlier_keeps_working_without_pro():
    vault.save("okx", {"api_key": "K" * 12, "api_secret": "S" * 12, "passphrase": "P" * 8})
    try:
        by = {p["id"]: p for p in client.get("/api/connections").json()["providers"]}
        assert not by["okx"]["needs_pro"]
    finally:
        vault.set_locked("okx", False); vault.remove("okx")


def test_free_plan_chats_with_haiku_and_pro_may_choose(monkeypatch):
    vault.save("anthropic", {"api_key": "sk-ant-" + "a" * 20, "model": "claude-opus-5-5"})
    assert pro.own_key_model() == "claude-haiku-5-5"            # free: always Haiku, whatever was saved
    save_key()
    server(monkeypatch, GOOD)
    pro.refresh()
    assert pro.own_key_model() == "claude-opus-5-5"             # Pro: their choice
