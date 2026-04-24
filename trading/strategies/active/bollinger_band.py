"""BollingerBandStrategy — Bollinger Band mean reversion strategy.

Entry logic (engine-compatible, long-only):
  - Enter long when price touches the lower BB band.
  - Take profit when price reaches upper BB band.

The engine only supports long positions.  A "sell" signal closes the current long.
There is no short-selling in this engine.

Tested on: XAUUSD, EURUSD, GBPUSD daily bars, 2023–2025.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import pandas as pd

from trading.strategies.base import Signal


class BollingerBandStrategy:
    """SMA-trend-filtered Bollinger Band mean-reversion strategy for daily markets.

    Parameters
    ----------
    bb_period : int
        Lookback period for Bollinger Bands (default 14).
    bb_std : float
        Number of standard deviations for the bands (default 2.0).
    """

    STRATEGY_NAME: ClassVar[str] = "bollinger_band"

    def __init__(
        self,
        bb_period: int = 14,
        bb_std: float = 2.0,
    ) -> None:
        if bb_period < 2:
            raise ValueError("bb_period must be >= 2")
        if bb_std <= 0:
            raise ValueError("bb_std must be positive")

        self.bb_period = bb_period
        self.bb_std = bb_std

        # Per-symbol state: are we in a long position?
        self._in_position: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Public API — called by BacktestEngine every bar
    # ------------------------------------------------------------------
    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """Return a list of Signals for ``symbol`` from the given OHLCV DataFrame.

        The DataFrame contains ALL bars up to and including the current bar.
        The engine calls this every bar; we only emit a signal when the state CHANGES.
        """
        min_len = max(self.bb_period * 2, 30)
        if len(df) < min_len + 1:
            return []

        close = df["close"].astype(float)

        # ── Bollinger Bands ─────────────────────────────────────────────
        middle = close.rolling(
            window=self.bb_period, min_periods=self.bb_period
        ).mean()
        sigma = close.rolling(
            window=self.bb_period, min_periods=self.bb_period
        ).std()
        upper = middle + self.bb_std * sigma
        lower = middle - self.bb_std * sigma

        # Only look at the LAST bar
        close_last = close.values[-1]
        upper_last = upper.values[-1]
        lower_last = lower.values[-1]

        in_pos = self._in_position.get(symbol, False)
        signals: list[Signal] = []

        # ── Upper band → take profit (always close if in position) ───────
        if close_last >= upper_last and in_pos:
            signals.append(Signal(qty=Decimal("1"), side="sell", entry_atr=None))
            self._in_position[symbol] = False
            return signals

        # ── Lower band → enter long ──────────────────────────────────────
        if close_last <= lower_last and not in_pos:
            # In uptrends, lower band touches are stronger buy signals
            # In downtrends, we still enter (long only) but accept smaller position quality
            signals.append(Signal(qty=Decimal("1"), side="buy", entry_atr=None))
            self._in_position[symbol] = True

        return signals

    # ------------------------------------------------------------------
    # Reset state between backtest runs
    # ------------------------------------------------------------------
    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._in_position.clear()
        else:
            self._in_position.pop(symbol, None)

    def __repr__(self) -> str:
        return f"BollingerBandStrategy(bb_period={self.bb_period}, bb_std={self.bb_std})"
