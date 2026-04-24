"""
CompositeTradingSystem — orchestrates all layers into a single coherent system.

Architecture:
  1. Regime Detector    → 4-state market classification
  2. Strategy Signals   → 5 strategies (BB, EMA, MACD, RSI, Donchian)
  3. Strategy Allocator → regime-weighted signal aggregation
  4. Risk Filter       → event/vol/consecutive-loss filters
  5. Execution Adapter → converts final signals to engine-compatible format

Usage:
  system = CompositeTradingSystem(symbol="XAUUSD")
  signal = system.generate_signals(symbol, df)
  # signal is a list[Signal] ready for the BacktestEngine
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import ClassVar

import pandas as pd

from trading.strategies.active.regime_detector import (
    RegimeReport,
    detect_regime,
)
from trading.strategies.active.risk_filter import RiskFilter, RiskFilterConfig
from trading.strategies.active.strategy_allocator import StrategyAllocator
from trading.strategies.base import Signal


@dataclass(kw_only=True)
class SystemConfig:
    """Top-level configuration for the composite system."""
    # Risk settings
    risk_per_trade_pct: float = 0.01  # 1% of equity per trade
    max_daily_loss_pct: float = 0.03  # 3% daily loss cap

    # Event calendar path
    economic_calendar_path: str = "config/economic_calendar.yaml"

    # ATR settings for stop/target
    stop_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.5


@dataclass
class CompositeTradingSystem:
    """
    Multi-strategy adaptive trading system.

    Combines regime detection, 5 strategy signals, dynamic allocation,
    and risk filtering into a single signal generator.
    """

    symbol: str
    config: SystemConfig = field(default_factory=SystemConfig)

    # Sub-systems
    _allocator: StrategyAllocator = field(default_factory=StrategyAllocator)
    _risk_filter: RiskFilter = field(default_factory=RiskFilter)
    _last_regime: RegimeReport | None = field(default=None, init=False)

    STRATEGY_NAME: ClassVar[str] = "composite_system"

    # Track if we're in a position (for engine compatibility)
    _in_position: bool = field(default=False, init=False)
    _entry_price: float = field(default=0.0, init=False)
    _entry_atr: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        # Load economic calendar if file exists
        calendar_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            self.config.economic_calendar_path
        )
        if os.path.exists(calendar_path):
            self._risk_filter.load_economic_calendar(calendar_path)

        # Apply config to risk filter
        self._risk_filter.config = RiskFilterConfig(
            daily_loss_cap_pct=self.config.max_daily_loss_pct,
            event_window_before_hours=2.0,
            event_window_after_hours=1.0,
            event_multiplier=0.25,
            high_vol_multiplier=0.5,
            consecutive_loss_cap=3,
            loss_streak_multiplier=0.5,
            atr_high_pct=0.80,
        )

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """
        Main entry point — called by BacktestEngine every bar.

        Returns a list of Signal objects (empty list = no action).
        """
        if symbol != self.symbol:
            return []

        if len(df) < 50:
            return []

        # ── Layer 1: Regime Detection ────────────────────────────────────────
        regime = detect_regime(
            df["high"], df["low"], df["close"],
            ema_fast_period=10,
            ema_slow_period=30,
            adx_period=14,
            atr_period=14,
            atr_lookback=100,
        )
        self._last_regime = regime

        # ── Layer 2: Strategy Allocation ────────────────────────────────────
        allocation = self._allocator.allocate(df, regime)

        # Skip if no actionable signal
        if allocation.final_confidence <= 0.05:
            return []

        # ── Layer 3: Risk Filter ────────────────────────────────────────────
        current_time = self._extract_time(df)
        filter_result = self._risk_filter.filter_signal(
            side=allocation.final_side.value,
            confidence=allocation.final_confidence,
            max_position_pct=regime.max_position_pct,
            atr_pct_rank=regime.atr_pct_rank,
            current_time=current_time,
        )

        if not filter_result["allowed"]:
            return []

        # Apply position multiplier
        adjusted_size = Decimal(str(round(filter_result["position_multiplier"], 2)))
        if adjusted_size == 0:
            adjusted_size = Decimal("1")  # minimum

        # ── Generate Engine Signals ─────────────────────────────────────────
        signals: list[Signal] = []

        if allocation.final_side.value == "BUY" and not self._in_position:
            # Calculate ATR for stop
            atr = self._compute_atr(df)
            self._in_position = True
            self._entry_price = float(df["close"].iloc[-1])
            self._entry_atr = atr

            signals.append(Signal(
                qty=adjusted_size,
                side="buy",
                entry_atr=atr,
            ))

        elif allocation.final_side.value == "SELL" and self._in_position:
            # Close existing position
            self._in_position = False
            self._entry_price = 0.0
            self._entry_atr = 0.0
            signals.append(Signal(
                qty=Decimal("1"),
                side="sell",
                entry_atr=None,
            ))

        elif allocation.final_side.value == "FLAT" and self._in_position:
            # Time-based or regime-based exit — close position
            self._in_position = False
            self._entry_price = 0.0
            self._entry_atr = 0.0
            signals.append(Signal(
                qty=Decimal("1"),
                side="sell",
                entry_atr=None,
            ))

        return signals

    def _extract_time(self, df: pd.DataFrame) -> datetime:
        """Extract datetime from DataFrame index or timestamp column."""
        ts = df.index[-1] if df.index.size > 0 else None
        if ts is None:
            return datetime.now(timezone.utc)
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, pd.Timestamp):
            return ts.to_pydatetime()
        return datetime.now(timezone.utc)

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

    def record_outcome(self, won: bool, pnl_pct: float) -> None:
        """Called externally when a trade closes — updates risk filter state."""
        self._risk_filter.record_trade_result(won, pnl_pct)

    def reset(self, symbol: str | None = None) -> None:
        """Reset all state between backtest runs."""
        self._in_position = False
        self._entry_price = 0.0
        self._entry_atr = 0.0
        self._allocator.reset()
        self._risk_filter._consecutive_losses = 0
        self._risk_filter._daily_pnl = 0.0

    def get_last_regime(self) -> RegimeReport | None:
        """Return the most recent regime detection result."""
        return self._last_regime

    def __repr__(self) -> str:
        return f"CompositeTradingSystem(symbol={self.symbol})"
