"""Exchange registry. To add one: write a class like binance.Binance and list it here and in iris/providers.py."""
from iris.exchanges.binance import Binance
from iris.exchanges.bybit import Bybit
from iris.exchanges.kraken import Kraken
from iris.exchanges.mexc import MEXC
from iris.exchanges.okx import OKX

EXCHANGES = {c.id: c for c in (Binance, Bybit, OKX, MEXC, Kraken)}
