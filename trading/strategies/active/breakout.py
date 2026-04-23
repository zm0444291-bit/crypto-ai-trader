"""BreakoutStrategy — Donchian Channel breakout strategy.

Entry logic:
  - LONG: price breaks above the highest high of the last ``lookback`` bars.
  - EXIT: price falls below the lowest low of the last ``lookback`` bars.

Designed to capture momentum breakouts; only enters during TREND or VOLATILE regimes.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading.strategies.active.market_regime import detect_market_regime
from trading.strategies.base import Signal


class BreakoutStrategy:
    """Donchian Channel breakout strategy.

    Parameters
    ----------
    lookback : int
        Number of bars to look back for highest high / lowest low (default 20).
    regime_adx_threshold : float
        ADX below this = range regime; strategy refuses to enter in range (default 20.0).
    min_confidence : float
        Minimum rule confidence to emit a candidate (0–1, default 0.65).
    """

    STRATEGY_NAME = "breakout"

    def __init__(
        self,
        lookback: int = 20,
        regime_adx_threshold: float = 20.0,
        min_confidence: float = 0.65,
        max_holding_bars: int = 48,
        trailing_stop_pct: float = 0.02,
    ) -> None:
        self.lookback = lookback
        self.regime_adx_threshold = regime_adx_threshold
        self.min_confidence = min_confidence
        self.max_holding_bars = max_holding_bars
        self.trailing_stop_pct = trailing_stop_pct
        self._in_position: dict[str, bool] = {}
        self._bars_held: dict[str, int] = {}  # bars held while IN position
        self._high_since_entry: dict[str, float] = {}  # for trailing stop

    # ------------------------------------------------------------------
    # Public API — BacktestEngine calls this
    # ------------------------------------------------------------------
    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """Return list of Signals for ``symbol`` from the given OHLCV DataFrame.

        The DataFrame must contain at least: high, low, close, volume, timestamp.
        """
        if len(df) < self.lookback + 2:
            return []

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        # ── Detect market regime ──────────────────────────────────────────
        regime_info = detect_market_regime(
            high=high,
            low=low,
            close=close,
            adx_period=14,
            bb_period=20,
            bb_std=2.0,
        )
        if regime_info["regime"] == "range":
            # Range market — no breakout entries; exit if in position
            if self._in_position.get(symbol, False):
                self._in_position[symbol] = False
                return [Signal(qty=Decimal("1"), side="sell", entry_atr=None)]
            return []

        # ── Donchian Channel ──────────────────────────────────────────────
        high_vals = high.values
        low_vals = low.values
        close_vals = close.values

        in_pos = self._in_position.get(symbol, False)

        # Highest high and lowest low over lookback bars (excluding current bar)
        lookback_highs = high_vals[-self.lookback - 1 : -1]
        lookback_lows = low_vals[-self.lookback - 1 : -1]

        if len(lookback_highs) == 0 or len(lookback_lows) == 0:
            return []

        channel_high = float(lookback_highs.max())  # type: ignore[union-attr]
        channel_low = float(lookback_lows.min())  # type: ignore[union-attr]

        # Current bar values
        close_last = close_vals[-1]
        close_prev = close_vals[-2]
        high_last = high_vals[-1]
        low_last = low_vals[-1]

        signals: list[Signal] = []

        # ── In position: update trailing stop & check exits ─────────────────
        if in_pos:
            # Increment bars held counter
            self._bars_held[symbol] = self._bars_held.get(symbol, 0) + 1

            # Update trailing stop high water mark
            self._high_since_entry[symbol] = max(
                self._high_since_entry.get(symbol, close_last), high_last
            )

            exit_taken = False

            # Trailing stop exit: price falls below (1 - trailing_stop_pct) of high since entry
            if self.trailing_stop_pct > 0:
                stop_level = self._high_since_entry[symbol] * (1 - self.trailing_stop_pct)
                if low_last < stop_level:
                    self._in_position[symbol] = False
                    self._bars_held[symbol] = 0
                    self._high_since_entry[symbol] = 0.0
                    signals.append(Signal(qty=Decimal("1"), side="sell", entry_atr=None))
                    exit_taken = True

            # Time-based exit: held too many bars (only if no exit taken yet)
            if not exit_taken and self._bars_held[symbol] >= self.max_holding_bars:
                self._in_position[symbol] = False
                self._bars_held[symbol] = 0
                self._high_since_entry[symbol] = 0.0
                signals.append(Signal(qty=Decimal("1"), side="sell", entry_atr=None))
                exit_taken = True

            # Channel low exit (stop-loss) — only if no exit taken yet
            if not exit_taken and low_last < channel_low:
                self._in_position[symbol] = False
                self._bars_held[symbol] = 0
                self._high_since_entry[symbol] = 0.0
                signals.append(Signal(qty=Decimal("1"), side="sell", entry_atr=None))

        # ── Not in position: check for breakout entry ───────────────────────
        else:
            # LONG breakout: price closes above channel_high (and wasn't above yesterday)
            if close_prev <= channel_high and close_last > channel_high:
                self._in_position[symbol] = True
                self._bars_held[symbol] = 0
                self._high_since_entry[symbol] = high_last
                signals.append(Signal(qty=Decimal("1"), side="buy", entry_atr=None))

        return signals
