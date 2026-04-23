"""Market data adapters for multiple brokers/exchanges.

Adapters implement the MarketDataAdapter interface to provide
normalized candle data and bid/ask pricing regardless of source.
"""

from trading.market_data.adapters.base import (
    BidAskQuote,
    MarketDataAdapter,
)
from trading.market_data.adapters.ibkr_adapter import (
    create_ibkr_adapter,
)
from trading.market_data.adapters.pepperstone_adapter import (
    create_pepperstone_adapter,
)

__all__ = [
    "MarketDataAdapter",
    "BidAskQuote",
    "create_ibkr_adapter",
    "create_pepperstone_adapter",
]
