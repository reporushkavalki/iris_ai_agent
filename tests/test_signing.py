"""Request signing checked against the examples published in each exchange's documentation."""
from iris.exchanges.base import hmac_b64, hmac_hex
from iris.exchanges.kraken import normalise_asset, sign


def test_binance_signature_matches_docs_example():
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    qs = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert hmac_hex(secret, qs) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_kraken_signature_matches_docs_example():
    secret = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
    payload = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
    assert sign("/0/private/AddOrder", 1616492376594, payload, secret) == \
        "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="


def test_okx_signature_is_base64_hmac():
    sig = hmac_b64("secret", "2020-12-08T09:08:57.715ZGET/api/v5/account/balance")
    assert len(sig) == 44 and sig.endswith("=")


def test_kraken_asset_names():
    assert normalise_asset("XXBT") == "BTC" and normalise_asset("ZUSD") == "USD"
    assert normalise_asset("DOT.S") == "DOT" and normalise_asset("ETH2.S") == "ETH" and normalise_asset("SOL") == "SOL"
