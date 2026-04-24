"""Runtime state backed by SQLite (paper-only milestone)."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from trading.execution.gate import TRADE_MODES

if TYPE_CHECKING:

    from trading.execution.gate import LiveTradingLock

# Default values when DB is empty or unavailable
_DEFAULT_MODE: TRADE_MODES = "paper_auto"


def get_trade_mode(session_factory: Callable[[], Session]) -> TRADE_MODES:
    """Return the persisted trade mode for the given session factory.

    Uses RuntimeControlRepository to read from the database.
    Returns "paper_auto" if no row exists.
    """
    from trading.storage.repositories import RuntimeControlRepository

    with session_factory() as session:
        repo = RuntimeControlRepository(session)
        return repo.get_trade_mode(default=_DEFAULT_MODE)


def get_live_trading_lock(session_factory: Callable[[], Session]) -> "LiveTradingLock":
    """Return the persisted live trading lock for the given session factory.

    Uses RuntimeControlRepository to read from the database.
    Returns LiveTradingLock(enabled=False) if no row exists.
    """
    from trading.storage.repositories import RuntimeControlRepository

    with session_factory() as session:
        repo = RuntimeControlRepository(session)
        return repo.get_live_trading_lock()
