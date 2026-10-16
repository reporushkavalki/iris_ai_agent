import json

import pytest

from iris import vault
from iris.chains import wallets_store as ws
from iris.config import VAULT_FILE


def test_vault_locks_after_save_and_masks():
    vault.save("binance", {"api_key": "AAAAAAAAAAAA1234", "api_secret": "SECRETSECRET9999"})
    assert vault.is_locked("binance")
    with pytest.raises(PermissionError):
        vault.save("binance", {"api_key": "other"})
    with pytest.raises(PermissionError):
        vault.remove("binance")
    vault.set_locked("binance", False)
    vault.save("binance", {"api_key": ""}, lock=True)            # blank keeps the old value
    assert vault.get("binance")["api_key"] == "AAAAAAAAAAAA1234"
    assert vault.mask("AAAAAAAAAAAA1234") == "••••1234" and vault.mask("short") == "••••"
    vault.set_locked("binance", False)
    vault.remove("binance")
    assert not vault.exists("binance")


def test_scrub_removes_secrets_and_url_keys():
    vault.save("x", {"bearer_token": "TOPSECRETTOKEN123"})
    out = vault.scrub("failed for TOPSECRETTOKEN123 at https://rpc.example/?api-key=abc123&x=1 sk-ant-api03-ZZZ")
    assert "TOPSECRETTOKEN123" not in out and "abc123" not in out and "ZZZ" not in out


def test_vault_file_is_json_in_data_dir():
    vault.save("kraken", {"api_key": "k" * 12, "api_secret": "s" * 12})
    assert json.loads(VAULT_FILE.read_text())["kraken"]["locked"] is True


@pytest.mark.parametrize("chain,addr", [
    ("solana", "So11111111111111111111111111111111111111112"),
    ("evm", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    ("bitcoin", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"),
    ("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
    ("hyperliquid", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
])
def test_valid_addresses(chain, addr):
    assert ws.validate_address(chain, addr) == addr


@pytest.mark.parametrize("chain,bad", [
    ("evm", "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"),
    ("evm", "0x" + "ab" * 32),
    ("evm", "ab" * 32),
    ("solana", "5" * 88),
    ("solana", "not-an-address"),
    ("bitcoin", "0x1234"),
])
def test_rejects_seed_phrases_private_keys_and_junk(chain, bad):
    with pytest.raises(ValueError):
        ws.validate_address(chain, bad)


def test_wallet_lifecycle():
    w = ws.add("Main", "So11111111111111111111111111111111111111112", "solana")
    assert w["locked"]
    with pytest.raises(ValueError):
        ws.add("main", "So11111111111111111111111111111111111111112", "solana")   # duplicate name
    with pytest.raises(ValueError):
        ws.remove("Main")                                                          # locked
    ws.set_locked("Main", False)
    ws.remove("Main")
    assert ws.load() == []


# ---------- encrypted vault, data folder, desktop-app token ----------
import base64 as _b64


def _fake_os_crypto(monkeypatch):
    """Stand-in for Windows DPAPI so the encrypted path is exercised on any machine."""
    from iris import secure
    monkeypatch.setattr(secure, "available", lambda: True)
    monkeypatch.setattr(secure, "protect", lambda b: b"ENC1" + bytes(x ^ 0x5A for x in b))
    def unprotect(b):
        if not b.startswith(b"ENC1"):
            raise OSError("not ours")
        return bytes(x ^ 0x5A for x in b[4:])
    monkeypatch.setattr(secure, "unprotect", unprotect)


def test_vault_encrypted_at_rest_and_roundtrips(monkeypatch):
    _fake_os_crypto(monkeypatch)
    vault.save("kraken", {"api_key": "KEY-ABCDEFGH-1234", "api_secret": "SECRET-XYZ-98765"})
    raw = VAULT_FILE.read_text()
    assert "KEY-ABCDEFGH" not in raw and "SECRET-XYZ" not in raw      # nothing readable on disk
    assert json.loads(raw)["enc"] == "dpapi"
    assert vault.get("kraken")["api_key"] == "KEY-ABCDEFGH-1234"
    assert vault.is_locked("kraken")


def test_plain_vault_is_upgraded_to_encrypted(monkeypatch):
    VAULT_FILE.write_text(json.dumps({"kraken": {"values": {"api_key": "PLAINKEY-12345678"}, "locked": True}}))
    _fake_os_crypto(monkeypatch)
    assert vault.get("kraken")["api_key"] == "PLAINKEY-12345678"      # still works
    assert "PLAINKEY" not in VAULT_FILE.read_text()                   # and is now encrypted


def test_unreadable_vault_is_moved_aside_not_overwritten(monkeypatch):
    _fake_os_crypto(monkeypatch)
    bad = {"v": 1, "enc": "dpapi", "data": _b64.b64encode(b"saved on another pc").decode()}
    VAULT_FILE.write_text(json.dumps(bad))
    assert vault.get("kraken") == {}
    assert vault.PROBLEM["message"]
    vault.save("kraken", {"api_key": "NEWKEY-12345678"})
    kept = list(VAULT_FILE.parent.glob("vault.unreadable-*.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text()) == bad  # the old file survives untouched
    assert vault.get("kraken")["api_key"] == "NEWKEY-12345678"
    assert vault.PROBLEM["message"] == ""


def test_broken_os_crypto_falls_back_to_plain_but_works(monkeypatch):
    from iris import secure
    monkeypatch.setattr(secure, "available", lambda: True)
    monkeypatch.setattr(secure, "protect", lambda b: b"garbage")
    monkeypatch.setattr(secure, "unprotect", lambda b: b"different")   # round-trip check fails
    vault.save("kraken", {"api_key": "KEY-12345678"})
    assert vault.get("kraken")["api_key"] == "KEY-12345678"


def test_plain_vault_still_works_without_os_crypto():
    vault.save("kraken", {"api_key": "KEY-12345678"})
    assert json.loads(VAULT_FILE.read_text())["kraken"]["values"]["api_key"] == "KEY-12345678"


def test_import_data_copies_without_overwriting(tmp_path):
    import sqlite3
    from iris import config
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(); new.mkdir()
    (old / "vault.json").write_text("{}")
    (old / "wallets.json").write_text('{"a": 1}')
    (old / "say.log").write_text("log")
    (old / ".shortcut").write_text("x")
    db = sqlite3.connect(old / "portfolio.db"); db.execute("create table t(x)"); db.execute("insert into t values (7)"); db.commit(); db.close()
    (new / "wallets.json").write_text('{"keep": 1}')
    res = config.import_data(old, new)
    assert sorted(res["copied"]) == ["portfolio.db", "vault.json"]
    assert res["skipped"] == ["wallets.json"]
    assert (new / "wallets.json").read_text() == '{"keep": 1}'
    assert not (new / "say.log").exists() and not (new / ".shortcut").exists()
    assert sqlite3.connect(new / "portfolio.db").execute("select x from t").fetchone() == (7,)


def test_user_data_dir_is_outside_the_program_folder():
    from iris import config
    assert config.ROOT not in config.user_data_dir().parents


def test_desktop_token_gates_the_api(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    monkeypatch.setattr(appmod, "TOKEN", "s3cret-token")
    c = TestClient(appmod.app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/health").status_code == 403                       # no cookie
    r = c.get("/?t=wrong", follow_redirects=False)
    assert r.status_code == 200 and "iris_t" not in r.headers.get("set-cookie", "")
    r = c.get("/?t=s3cret-token", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/" and "iris_t=s3cret-token" in r.headers["set-cookie"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert c.get("/api/health").status_code == 200                       # cookie now stored
    assert c.get("/api/health", headers={"origin": "https://evil.example"}).status_code == 403


def test_no_token_means_old_behaviour(monkeypatch):
    from fastapi.testclient import TestClient
    import app as appmod
    monkeypatch.setattr(appmod, "TOKEN", "")
    c = TestClient(appmod.app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/health").status_code == 200
