"""StrategySelector — routes market data to the appropriate strategy based on detected regime.

Architecture:
    1. Detect market regime (trend / range / volatile) via MarketRegimeDetector
    2. Run all applicable strategies for that regime
    3. Collect and rank signals
    4. Return the best TradeCandidate (or None)

Regime → Strategy mapping:
    trend    → BreakoutStrategy (momentum breakouts work in trending markets)
    range    → MeanReversionStrategy (mean reversion works in ranging markets)
    volatile → BreakoutStrategy (breakouts can capture volatile moves)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd

from trading.features.builder import CandleFeatures
from trading.strategies.active.breakout import BreakoutStrategy
from trading.strategies.active.market_regime import detect_market_regime
from trading.strategies.active.mean_reversion import MeanReversionStrategy
from trading.strategies.base import Signal, TradeCandidate


class StrategySelector:
    """Selects the best trading strategy based on detected market regime.

    Parameters
    ----------
    symbols : list[str]
        Symbols to generate candidates for.
    regime_adx_threshold : float
        ADX threshold for trend detection (default 25.0).
    bb_narrow_threshold : float
        BB bandwidth threshold for range detection (default 0.04).
    min_confidence : float
        Minimum confidence to emit a candidate (default 0.6).
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        regime_adx_threshold: float = 25.0,
        bb_narrow_threshold: float = 0.04,
        min_confidence: float = 0.6,
    ) -> None:
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.regime_adx_threshold = regime_adx_threshold
        self.bb_narrow_threshold = bb_narrow_threshold
        self.min_confidence = min_confidence

        # Instantiate strategy instances
        self._breakout = BreakoutStrategy(
            lookback=20,
            regime_adx_threshold=regime_adx_threshold,
            min_confidence=min_confidence,
        )
        self._mean_reversion = MeanReversionStrategy(
            bb_period=20,
            bb_std=2.0,
            regime_adx_threshold=regime_adx_threshold,
            min_confidence=min_confidence,
        )

        # Per-symbol regime cache (updated on each call)
        self._regime_cache: dict[str, str] = {}

    def detect_regime(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
    ) -> str:
        """Detect market regime using ADX + Bollinger Bandwidth.

        Returns
        -------
        str
            "trend", "range", or "volatile".
        """
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

    def _build_dataframe(self, features: list[CandleFeatures]) -> pd.DataFrame:
        """Convert CandleFeatures list to DataFrame for strategy input."""
        if not features:
            return pd.DataFrame()

        rows = []
        for f in features:
            rows.append(
                {
                    "timestamp": f.candle_time,
                    "open": float(f.close),  # approximated
                    "high": float(f.close) * 1.001,  # approximated
                    "low": float(f.close) * 0.999,  # approximated
                    "close": float(f.close),
                    "volume": 1.0,  # placeholder
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
        if latest.atr_14 is None:
            atr_val: Decimal = Decimal("100")
        else:
            atr_val = latest.atr_14

        entry_reference = latest.close
        stop_reference = entry_reference - (atr_val * Decimal("2"))

        if stop_reference <= 0:
            return None

        return TradeCandidate(
            strategy_name=f"{signal.side}_{regime}",  # e.g. "buy_trend"
            symbol=symbol,
            side="BUY",
            entry_reference=entry_reference,
            stop_reference=stop_reference,
            rule_confidence=Decimal(str(self.min_confidence)),
            reason=f"{signal.side} signal via {regime} regime strategy",
            created_at=now,
        )

    def select_candidate(
        self,
        symbol: str,
        features_15m: list[CandleFeatures],
        features_1h: list[CandleFeatures],
        features_4h: list[CandleFeatures],
        now: datetime,
    ) -> TradeCandidate | None:
        """Detect regime and return the best candidate from the appropriate strategy.

        Pipeline:
            1. Detect regime from 15m candles
            2. Run regime-appropriate strategies
            3. Rank and return best candidate (or None)
        """
        if not features_15m:
            return None

        # Build DataFrame from 15m candles for strategy input
        high_15m = pd.Series([float(f.close) * 1.001 for f in features_15m])
        low_15m = pd.Series([float(f.close) * 0.999 for f in features_15m])
        close_15m = pd.Series([float(f.close) for f in features_15m])

        regime = self.detect_regime(high=high_15m, low=low_15m, close=close_15m)
        self._regime_cache[symbol] = regime

        candidates: list[TradeCandidate] = []

        # ── Range regime: MeanReversion ─────────────────────────────────────
        if regime == "range":
            df = self._build_dataframe(features_15m)
            if not df.empty:
                signals = self._mean_reversion.generate_signals(symbol, df)
                for sig in signals:
                    if sig.side.lower() == "buy":
                        cand = self._signal_to_candidate(
                            sig, symbol, regime, features_15m, now
                        )
                        if cand:
                            candidates.append(cand)

        # ── Trend / Volatile regime: Breakout ────────────────────────────────
        elif regime in ("trend", "volatile"):
            df = self._build_dataframe(features_15m)
            if not df.empty:
                signals = self._breakout.generate_signals(symbol, df)
                for sig in signals:
                    if sig.side.lower() == "buy":
                        cand = self._signal_to_candidate(
                            sig, symbol, regime, features_15m, now
                        )
                        if cand:
                            candidates.append(cand)

        # No candidate found
        if not candidates:
            return None

        # Return highest confidence candidate
        best = max(candidates, key=lambda c: c.rule_confidence)
        return best

    def get_regime(self, symbol: str) -> str:
        """Return the last detected regime for a symbol, or 'unknown'."""
        return self._regime_cache.get(symbol, "unknown")
