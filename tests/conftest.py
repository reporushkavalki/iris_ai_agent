import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="iris-test-")
os.environ["IRIS_DATA_DIR"] = _tmp          # tests never touch the real ./data folder
os.environ["IRIS_PORT"] = "8765"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data():
    for p in Path(_tmp).glob("*"):
        p.unlink()
    from iris import portfolio, prices, socials
    portfolio._cache.clear()
    portfolio._status_cache.update(t=0.0, v=None)
    socials._cache.clear()
    prices._tickers.update(t=0.0, p={})
    prices._markets.clear()
    yield


@pytest.fixture
def fake_prices(monkeypatch):
    from iris import prices
    table = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0, "BNB": 600.0, **prices.STABLES}
    monkeypatch.setattr(prices, "all_prices", lambda: table)
    return table
