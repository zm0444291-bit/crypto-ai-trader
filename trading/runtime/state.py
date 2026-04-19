"""In-memory runtime state for mode and lock management (paper-only)."""

from trading.execution.gate import TRADE_MODES, LiveTradingLock

# Module-level runtime state — not persisted across restarts in this milestone
_current_trade_mode: TRADE_MODES = "paper_auto"
_current_lock = LiveTradingLock(enabled=False)


def get_trade_mode() -> TRADE_MODES:
    """Return the current trade mode."""
    return _current_trade_mode


def get_live_trading_lock() -> LiveTradingLock:
    """Return the current live trading lock state."""
    return _current_lock
