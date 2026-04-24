"""MeanReversionStrategy — Bollinger Band mean reversion strategy.

Entry logic:
  - Price touches or crosses below the lower BB band → BUY (oversold bounce).
  - Price touches or crosses above the upper BB band → SELL (overbought exit only).

The strategy only enters long positions; sells are closing existing long positions.
Designed to run in RANGE regimes; in TREND regimes it skips signal generation.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading.strategies.active.market_regime import detect_market_regime
from trading.strategies.base import Signal


class MeanReversionStrategy:
    """Bollinger Band mean-reversion strategy.

    Parameters
    ----------
    bb_period : int
        Bollinger Bands lookback period (default 20).
    bb_std : float
        Number of standard deviations for bands (default 2.0).
    regime_adx_threshold : float
        ADX above this = trend regime; strategy refuses to enter in trend (default 25.0).
    min_confidence : float
        Minimum rule confidence to emit a candidate (0–1, default 0.6).
    """

    STRATEGY_NAME = "mean_reversion"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        regime_adx_threshold: float = 25.0,
        min_confidence: float = 0.6,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.regime_adx_threshold = regime_adx_threshold
        self.min_confidence = min_confidence
        self._in_position: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Public API — BacktestEngine calls this
    # ------------------------------------------------------------------
    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """Return list of Signals for ``symbol`` from the given OHLCV DataFrame.

        The DataFrame must contain at least: high, low, close, volume, timestamp.
        This method is duck-typed to BacktestEngine's expected interface.
        """
        if len(df) < max(self.bb_period * 2, 30):
            return []

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # ── Detect market regime ──────────────────────────────────────────
        regime_info = detect_market_regime(
            high=high,
            low=low,
            close=close,
            adx_period=14,
            bb_period=self.bb_period,
            bb_std=self.bb_std,
        )
        if regime_info["regime"] == "trend":
            # No entries during strong trends; close any open position on trend onset
            if self._in_position.get(symbol, False):
                self._in_position[symbol] = False
                return [Signal(qty=Decimal("1"), side="sell", entry_atr=None)]
            return []

        # ── Bollinger Bands ─────────────────────────────────────────────────
        middle = close.rolling(window=self.bb_period).mean()
        sigma = close.rolling(window=self.bb_period).std()
        upper = middle + self.bb_std * sigma
        lower = middle - self.bb_std * sigma

        close_vals = close.values
        upper_vals = upper.values
        lower_vals = lower.values
        in_pos = self._in_position.get(symbol, False)

        # Last two bars
        upper_last = upper_vals[-1]
        lower_last = lower_vals[-1]
        close_last = close_vals[-1]

        signals: list[Signal] = []

        # BUY: price crosses below lower band (or touches it)
        if not in_pos and close_last <= lower_last:
            self._in_position[symbol] = True
            signals.append(Signal(qty=Decimal("1"), side="buy", entry_atr=None))

        # SELL: overbought — price crosses above upper band while in position
        elif in_pos and close_last >= upper_last:
            self._in_position[symbol] = False
            signals.append(Signal(qty=Decimal("1"), side="sell", entry_atr=None))

        return signals
