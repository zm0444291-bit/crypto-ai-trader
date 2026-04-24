"""ShortTermSystem — orchestrator for short-term gold trading on 1h data.

Integrates:
  • PatternDetector  — identifies 4 short-term patterns
  • SessionFilter    — restricts entries to high-probability windows
  • ShortTermSignalGenerator — BB + RSI + EMA combo

Position management:
  • Max 1 open position at a time
  • Max 2 trades per calendar day
  • Daily loss limit → skip rest of day
  • 8-bar hard time exit
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from trading.strategies.active.pattern_detector import PatternDetector
from trading.strategies.active.session_filter import SessionFilter
from trading.strategies.active.short_term_signal_generator import ShortTermSignalGenerator
from trading.strategies.base import Signal


class ShortTermSystem:
    """Short-term trading system for XAUUSD 1h data."""

    STRATEGY_NAME = "short_term_system"

    def __init__(
        self,
        bb_period: int = 8,
        bb_std: float = 2.0,
        atr_period: int = 14,
        rsi_period: int = 14,
        ema_fast: int = 15,
        ema_slow: int = 50,
        risk_pct: float = 2.0,
        max_daily_loss_pct: float = 3.0,
        max_trades_per_day: int = 2,
        max_bars_held: int = 8,
    ) -> None:
        # Components (create filter first, then pass to generator)
        session_filter = SessionFilter()
        pattern_detector = PatternDetector(
            atr_period=atr_period, bb_period=bb_period, bb_std=bb_std
        )
        self.generator = ShortTermSignalGenerator(
            bb_period=bb_period,
            bb_std=bb_std,
            atr_period=atr_period,
            rsi_period=rsi_period,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            risk_pct=risk_pct,
            max_daily_loss_pct=max_daily_loss_pct,
            session_filter=session_filter,
            pattern_detector=pattern_detector,
        )

        # External state (managed by backtest engine)
        self._in_position: dict[str, bool] = {}
        self._entry_price: dict[str, float] = {}
        self._entry_bar: dict[str, int] = {}
        self._daily_pnl: dict[str, float] = {}
        self._daily_trades: dict[str, int] = {}
        self._daily_loss: dict[str, float] = {}

        # Internal symbol tracker
        self._symbol: str = "XAUUSD"
        self._bar_count: int = 0

    # ------------------------------------------------------------------
    # Per-bar update (call this before generate_signals each bar)
    # ------------------------------------------------------------------

    def on_bar(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> list[Signal]:
        """Process a new bar and return any signals.

        Call this bar-by-bar from the backtest engine.
        """
        self._bar_count += 1
        date_key = str(timestamp.date())

        # Daily guards
        if self._daily_loss.get(date_key, 0) >= 3.0:
            return []
        if self._daily_trades.get(date_key, 0) >= 2:
            return []

        in_pos = self._in_position.get(symbol, False)

        # ── Check for exit signals ───────────────────────────────────
        if in_pos:
            entry = self._entry_price.get(symbol, close)
            bars_held = self._bar_count - self._entry_bar.get(symbol, self._bar_count)
            sig = self._should_exit(symbol, date_key, close, entry, bars_held)
            if sig:
                return [sig]

        return []

    def _should_exit(
        self,
        symbol: str,
        date_key: str,
        close: float,
        entry: float,
        bars_held: int,
    ) -> Signal | None:
        """Evaluate exit conditions for an open position."""
        in_pos = self._in_position.get(symbol, False)
        if not in_pos:
            return None

        # Hard 8-bar exit
        if bars_held >= 8:
            return self._close_position(symbol, date_key, close, entry)

        return None

    def _close_position(
        self, symbol: str, date_key: str, close: float, entry: float
    ) -> Signal:
        self._in_position[symbol] = False
        pnl_pct = (close - entry) / entry * 100
        self._daily_pnl[date_key] = self._daily_pnl.get(date_key, 0) + pnl_pct
        if pnl_pct < 0:
            self._daily_loss[date_key] = self._daily_loss.get(date_key, 0) + abs(pnl_pct)
        return Signal(qty=Decimal("1"), side="sell", entry_atr=None)

    # ------------------------------------------------------------------
    # Batch generate (convenience for backtest)
    # ------------------------------------------------------------------

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """Return signals by scanning the full DataFrame.

        State is updated internally — call once per backtest run.
        """
        self._bar_count = 0
        self._in_position = {}
        self._entry_price = {}
        self._entry_bar = {}
        self._daily_pnl = {}
        self._daily_trades = {}
        self._daily_loss = {}

        signals = self.generator.generate_signals(symbol, df)

        # Sync position state into system
        for sig in signals:
            if sig.side == "buy":
                self._in_position[symbol] = True
                last_ts = df["timestamp"].iloc[-1]
                self._entry_price[symbol] = float(df[df["timestamp"] == last_ts]["close"].iloc[0])

        return signals

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def pattern_detector(self) -> PatternDetector:
        return self.generator.pattern_detector

    @property
    def session_filter(self) -> SessionFilter:
        return self.generator.session_filter

    def stats(self) -> dict[str, Any]:
        return {
            "total_trades": sum(self._daily_trades.values()),
            "daily_pnl": dict(self._daily_pnl),
            "max_daily_loss": max(self._daily_loss.values()) if self._daily_loss else 0.0,
        }
