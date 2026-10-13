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
