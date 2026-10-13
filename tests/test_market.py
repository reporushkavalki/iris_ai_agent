"""The market pulse parsing, importance scoring and de-duplication. Offline: no network is touched."""
import time

from iris import market

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Fed holds interest rates steady, Powell signals patience</title><link>https://example.com/a</link><guid>a</guid><pubDate>{now}</pubDate></item>
<item><title>Bitcoin ETF sees record inflows</title><link>https://example.com/b</link><guid>b</guid><pubDate>{now}</pubDate></item>
</channel></rss>"""


def _rfc(ts):
    from email.utils import formatdate
    return formatdate(ts, usegmt=True)


def test_parse_feed():
    items = market._parse_feed(RSS.replace(b"{now}", _rfc(time.time()).encode()), "Test", "crypto")
    assert [i["title"][:3] for i in items] == ["Fed", "Bit"]
    assert items[0]["link"] == "https://example.com/a" and items[0]["ts"] > 0


def test_importance_levels():
    assert market.importance("FOMC holds federal funds rate unchanged", "Fed", "official") == 3
    assert market.importance("Exchange hacked, $50M drained") == 3
    assert market.importance("Local bakery opens new shop") == 1
    assert market.importance("Fed announces enforcement action against a bank", "Fed", "official") == 1


def test_tone_uses_whole_words():
    assert market.tone("Bitcoin surges to a record high") > 0
    assert market.tone("Exchange hacked, funds drained") < 0
    assert market.tone("Urban planning conference in Berlin") == 0     # 'ban' inside 'urban' must not count


def test_similar_stories_merge():
    assert market._similar("Fed holds rates steady, Powell signals patience", "Fed holds rates steady as Powell signals patience")
    assert not market._similar("Fed holds rates steady", "Solana network upgrade ships")


def test_pulse_with_dead_sources(monkeypatch):
    """Every source failing must still give a valid, empty picture instead of an exception."""
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(market, "_get", boom)
    market._store.clear()
    p = market.pulse()
    assert p["news"] == [] and p["mood"]["score"] is None and "x" not in p and p["errors"]
    assert market.get_market_pulse()["mood"]["score"] is None
