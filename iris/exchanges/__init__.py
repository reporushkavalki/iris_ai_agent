"""Exchange registry. To add one: write a class like binance.Binance and list it here and in iris/providers.py."""
from iris.exchanges.alpaca import Alpaca
from iris.exchanges.binance import Binance
from iris.exchanges.bitget import Bitget
from iris.exchanges.bybit import Bybit
from iris.exchanges.coinbase import Coinbase
from iris.exchanges.gate import Gate
from iris.exchanges.kraken import Kraken
from iris.exchanges.kucoin import KuCoin
from iris.exchanges.mexc import MEXC
from iris.exchanges.okx import OKX
from iris.exchanges.trading212 import Trading212

EXCHANGES = {c.id: c for c in (Binance, Bybit, OKX, MEXC, Kraken, Bitget, KuCoin, Gate, Alpaca, Trading212, Coinbase)}
