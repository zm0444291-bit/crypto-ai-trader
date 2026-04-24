"""StrategySelector — regime-based strategy routing with unified position management.

Architecture:
    - Position state is managed HERE (not in individual strategies)
    - Each bar: detect regime → ask appropriate strategy for signal
    - If already in position, only emit EXIT signals (no new entries)
    - If not in position, only emit ENTRY signals (no exits)
    - Strategies are stateless signal generators (no _in_position)

Regime → Strategy mapping:
    trend    → BreakoutStrategy
    range    → MeanReversionStrategy
    volatile → BreakoutStrategy
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd

from trading.events.economic_calendar import EconomicCalendar
from trading.features.builder import CandleFeatures
from trading.strategies.active.breakout import BreakoutStrategy
from trading.strategies.active.market_regime import detect_market_regime
from trading.strategies.active.mean_reversion import MeanReversionStrategy
from trading.strategies.base import Signal, TradeCandidate


class StrategySelector:
    """Routes market data to the appropriate strategy based on detected regime.

    Position state is managed at this layer (shared across all strategies).
    Each strategy is stateless — it only reacts to price data, not position state.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        regime_adx_threshold: float = 25.0,
        bb_narrow_threshold: float = 0.04,
        min_confidence: float = 0.6,
        economic_calendar: EconomicCalendar | None = None,
    ) -> None:
        self.symbols = symbols or ["XAUUSD"]
        self.regime_adx_threshold = regime_adx_threshold
        self.bb_narrow_threshold = bb_narrow_threshold
        self.min_confidence = min_confidence
        self._economic_calendar = economic_calendar

        # Stateles strategy instances (no internal position state)
        self._breakout = BreakoutStrategy(
            lookback=20,
            regime_adx_threshold=regime_adx_threshold,
            min_confidence=min_confidence,
            trailing_stop_pct=0.02,
            max_holding_bars=96,
        )
        self._mean_reversion = MeanReversionStrategy(
            bb_period=20,
            bb_std=2.0,
            regime_adx_threshold=regime_adx_threshold,
            min_confidence=min_confidence,
        )

        # Per-symbol regime cache
        self._regime_cache: dict[str, str] = {}

        # SHARED position state (the source of truth — not in strategies)
        self._in_position: dict[str, bool] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Position state management
    # ─────────────────────────────────────────────────────────────────────────

    def set_position_state(self, symbol: str, in_position: bool) -> None:
        """Called by the backtest engine after each trade execution."""
        self._in_position[symbol] = in_position

    def is_in_position(self, symbol: str) -> bool:
        """Check if we currently hold a position for this symbol."""
        return self._in_position.get(symbol, False)

    # ─────────────────────────────────────────────────────────────────────────
    # Regime detection
    # ─────────────────────────────────────────────────────────────────────────

    def detect_regime(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
    ) -> str:
        """Detect market regime using ADX + Bollinger Bandwidth."""
        result = detect_market_regime(
            high=high,
            low=low,
            close=close,
            adx_period=14,
            bb_period=20,
            bb_std=2.0,
            adx_strong_threshold=self.regime_adx_threshold,
            bb_narrow_threshold=self.bb_narrow_threshold,
        )
        return result["regime"]

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_dataframe(self, features: list[CandleFeatures]) -> pd.DataFrame:
        """Convert CandleFeatures list to DataFrame for strategy input."""
        if not features:
            return pd.DataFrame()

        rows = []
        for f in features:
            rows.append(
                {
                    "timestamp": f.candle_time,
                    "open": float(f.close),
                    "high": float(f.high) if f.high is not None else float(f.close),
                    "low": float(f.low) if f.low is not None else float(f.close),
                    "close": float(f.close),
                    "volume": 1.0,
                }
            )
        df = pd.DataFrame(rows)
        df.set_index("timestamp", inplace=True)
        return df

    def _signal_to_candidate(
        self,
        signal: Signal,
        symbol: str,
        regime: str,
        features: list[CandleFeatures],
        now: datetime,
    ) -> TradeCandidate | None:
        """Convert a Signal to a TradeCandidate."""
        if not features:
            return None

        latest = features[-1]
        atr_val: Decimal = latest.atr_14 if latest.atr_14 is not None else Decimal("20")

        entry_reference = latest.close
        stop_reference = entry_reference - (atr_val * Decimal("2"))

        if stop_reference <= 0:
            return None

        return TradeCandidate(
            strategy_name=f"{signal.side}_{regime}",
            symbol=symbol,
            side="BUY" if signal.side.lower() == "buy" else "SELL",
            entry_reference=entry_reference,
            stop_reference=stop_reference,
            rule_confidence=Decimal(str(self.min_confidence)),
            reason=f"{signal.side} via {regime} regime",
            created_at=now,
        )

    def _is_entry_session(self, dt: datetime) -> bool:
        """Return True if new entries are allowed at the given UTC time.

        Session rules (UTC):
            US    session: 13:30–21:00 UTC  (peak XAUUSD volume)
            Asian session: 23:00–08:00 UTC  (moderate moves, lower spread)
            Blocked: weekdays 08:00–13:29 UTC + weekdays after 21:00 UTC
            Sunday: only allow 23:00–23:59 UTC (Asian open)
            Saturday: always blocked
        """
        # Saturday — always blocked
        if dt.weekday() == 5:
            return False
        # Sunday — only allow during Asian session (23:00–23:59 UTC)
        if dt.weekday() == 6:
            return dt.hour >= 23
        # Monday–Friday rules:
        # Block during crossover (08:00–13:29 UTC)
        if 8 <= dt.hour < 13 or (dt.hour == 13 and dt.minute == 0):
            return False
        # Block after US close (21:00+ UTC)
        if dt.hour > 21 or (dt.hour == 21 and dt.minute > 0):
            return False
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    def select_candidate(
        self,
        symbol: str,
        features_15m: list[CandleFeatures],
        features_1h: list[CandleFeatures],
        features_4h: list[CandleFeatures],
        now: datetime,
    ) -> TradeCandidate | None:
        """Detect regime and return the appropriate trading candidate.

        Pipeline:
            1. Detect regime from 15m candles
            2. Get signals from the appropriate strategy
            3. Filter signals based on current position state:
               - If IN position: only accept SELL (exit) signals
               - If OUT position: only accept BUY (entry) signals
            4. Return best candidate or None
        """
        if not features_15m:
            return None

        in_pos = self.is_in_position(symbol)

        # Build price series for regime detection
        high_15m = pd.Series(
            [float(f.high) if f.high is not None else float(f.close) for f in features_15m]
        )
        low_15m = pd.Series(
            [float(f.low) if f.low is not None else float(f.close) for f in features_15m]
        )
        close_15m = pd.Series([float(f.close) for f in features_15m])

        regime = self.detect_regime(high=high_15m, low=low_15m, close=close_15m)
        self._regime_cache[symbol] = regime

        # Build DataFrame for strategies
        df = self._build_dataframe(features_15m)
        if df.empty:
            return None

        # Select appropriate strategy
        if regime == "range":
            strategy: BreakoutStrategy | MeanReversionStrategy = self._mean_reversion
        else:  # trend or volatile
            strategy = self._breakout

        # Get signals from strategy
        signals = strategy.generate_signals(symbol, df)

        # ── Filter signals by position state ────────────────────────────────
        # Only accept signals consistent with current position state:
        #   - If in_pos == False: only BUY signals (entry)
        #   - If in_pos == True: only SELL signals (exit)
        candidates: list[TradeCandidate] = []
        for sig in signals:
            if in_pos and sig.side.lower() == "buy":
                # Already in position — ignore entry signal
                continue
            if not in_pos and sig.side.lower() == "sell":
                # Not in position — ignore exit signal
                continue

            # ── Session filter for ENTRY signals ──────────────────────────────
            # Only allow new entries during high-volatility sessions:
            #   US  session: 13:30–21:00 UTC (XAUUSD peak volume)
            #   Asian session: 02:00–08:00 UTC (moderate moves, lower spread)
            # Entries blocked during: crossover hours (08:00–13:30 UTC) + weekends
            if sig.side.lower() == "buy" and not self._is_entry_session(now):
                continue

            # ── Economic calendar filter for ENTRY signals ───────────────────
            # Block entries during high/medium impact news windows:
            #   HIGH impact: 30 min before + 30 min after
            #   MEDIUM impact: 15 min before + 15 min after
            if sig.side.lower() == "buy" and self._economic_calendar is not None:
                if self._economic_calendar.is_trading_blocked(now, symbol):
                    continue

            cand = self._signal_to_candidate(sig, symbol, regime, features_15m, now)
            if cand:
                candidates.append(cand)

        # Debug print every N calls
        if not hasattr(self, "_select_call_count"):
            self._select_call_count = 0
        self._select_call_count += 1
        if self._select_call_count <= 5:
            print(
                f"    [SELECT] call={self._select_call_count} ts={now} in_pos={in_pos}"
                f" regime={regime} signals={len(signals)} candidates={len(candidates)}"
            )

        if not candidates:
            return None

        # Return highest confidence candidate
        best = max(candidates, key=lambda c: c.rule_confidence)
        return best

    def get_regime(self, symbol: str) -> str:
        """Return the last detected regime for a symbol."""
        return self._regime_cache.get(symbol, "unknown")
