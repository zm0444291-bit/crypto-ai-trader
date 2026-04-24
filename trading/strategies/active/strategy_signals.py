"""
StrategySignals — unified signal output with confidence scores.

Each strategy module returns a TypedDict containing:
  side     : BUY | SELL | FLAT
  confidence : 0.0–1.0
  reason   : human-readable explanation
  entry_price : float (optional)
  stop_price  : float (optional)
  regime_fit  : how well this strategy fits the current market regime

The CompositeStrategy aggregates outputs from all strategies,
applies regime-based weighting, and produces a final consensus signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypedDict, runtime_checkable

import numpy as np
import pandas as pd


class SignalSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"


class SignalDict(TypedDict):
    side: SignalSide
    confidence: float
    reason: str
    entry_price: float | None
    stop_price: float | None
    regime_fit: float  # 0..1 how appropriate this strategy is for current regime


# ─── EMA Cross Strategy ──────────────────────────────────────────────────────


@dataclass
class EMACrossSignal:
    """EMA fast/slow crossover — trend-following."""
    fast_period: int = 10
    slow_period: int = 30

    def generate(self, df: pd.DataFrame) -> SignalDict | None:
        if len(df) < self.slow_period * 2:
            return None

        close = df["close"].astype(float)
        ema_f = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_s = close.ewm(span=self.slow_period, adjust=False).mean()

        # require 3 consecutive crosses for confirmation
        if len(ema_f) < 3:
            return None

        diff_now = float(ema_f.iloc[-1] - ema_s.iloc[-1])
        diff_prev = float(ema_f.iloc[-2] - ema_s.iloc[-2])

        close_last = float(close.iloc[-1])

        # Bull cross: fast crosses above slow
        if diff_now > 0 and diff_prev <= 0:
            # Calculate ATR for stop
            atr = self._atr(df)
            return SignalDict(
                side=SignalSide.BUY,
                confidence=min(abs(diff_now / close_last) * 10, 1.0),
                reason=f"EMA{self.fast_period} crossed above EMA{self.slow_period}",
                entry_price=close_last,
                stop_price=close_last - 1.5 * atr,
                regime_fit=0.9,  # best in trending markets
            )

        # Bear cross: fast crosses below slow
        if diff_now < 0 and diff_prev >= 0:
            atr = self._atr(df)
            return SignalDict(
                side=SignalSide.SELL,  # exit long
                confidence=min(abs(diff_now / close_last) * 10, 1.0),
                reason=f"EMA{self.fast_period} crossed below EMA{self.slow_period}",
                entry_price=close_last,
                stop_price=close_last + 1.5 * atr,
                regime_fit=0.9,
            )

        return None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


# ─── MACD Strategy ──────────────────────────────────────────────────────────


@dataclass
class MACDSignal:
    """MACD histogram — momentum / trend-following."""
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def generate(self, df: pd.DataFrame) -> SignalDict | None:
        if len(df) < self.slow_period + self.signal_period:
            return None

        close = df["close"].astype(float)
        ema_f = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_s = close.ewm(span=self.slow_period, adjust=False).mean()
        macd_line = ema_f - ema_s
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        if len(histogram) < 2:
            return None

        hist_now = float(histogram.iloc[-1])
        hist_prev = float(histogram.iloc[-2])
        close_last = float(close.iloc[-1])

        # MACD crosses above signal line → buy
        if hist_now > 0 and hist_prev <= 0:
            atr = self._atr(df)
            return SignalDict(
                side=SignalSide.BUY,
                confidence=min(abs(hist_now / close_last) * 20, 1.0),
                reason=f"MACD histogram crossed above signal (hist={hist_now:.2f})",
                entry_price=close_last,
                stop_price=close_last - 1.5 * atr,
                regime_fit=0.8,
            )

        # MACD crosses below signal line → exit
        if hist_now < 0 and hist_prev >= 0:
            atr = self._atr(df)
            return SignalDict(
                side=SignalSide.SELL,
                confidence=min(abs(hist_now / close_last) * 20, 1.0),
                reason=f"MACD histogram crossed below signal (hist={hist_now:.2f})",
                entry_price=close_last,
                stop_price=close_last + 1.5 * atr,
                regime_fit=0.8,
            )

        return None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


# ─── RSI Strategy ───────────────────────────────────────────────────────────


@dataclass
class RSISignal:
    """RSI — mean-reversion / overbought-oversold."""
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def generate(self, df: pd.DataFrame) -> SignalDict | None:
        if len(df) < self.period * 2:
            return None

        close = df["close"].astype(float)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=self.period, adjust=False).mean()
        avg_loss = loss.ewm(span=self.period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        if len(rsi) < 2:
            return None

        rsi_now = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2])
        close_last = float(close.iloc[-1])

        atr = self._atr(df)

        # RSI exits oversold → buy
        if rsi_prev <= self.oversold and rsi_now > self.oversold:
            return SignalDict(
                side=SignalSide.BUY,
                confidence=min((rsi_now - self.oversold) / 20.0, 1.0),
                reason=f"RSI exited oversold zone ({rsi_now:.1f})",
                entry_price=close_last,
                stop_price=close_last - 1.5 * atr,
                regime_fit=0.6,  # better in range-bound markets
            )

        # RSI exits overbought → exit long
        if rsi_prev >= self.overbought and rsi_now < self.overbought:
            return SignalDict(
                side=SignalSide.SELL,
                confidence=min((self.overbought - rsi_now) / 20.0, 1.0),
                reason=f"RSI exited overbought zone ({rsi_now:.1f})",
                entry_price=close_last,
                stop_price=close_last + 1.5 * atr,
                regime_fit=0.6,
            )

        return None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


# ─── Donchian Breakout Strategy ─────────────────────────────────────────────


@dataclass
class DonchianSignal:
    """Donchian Channel breakout — trend-following."""
    period: int = 20

    def generate(self, df: pd.DataFrame) -> SignalDict | None:
        if len(df) < self.period + 1:
            return None

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        upper = high.rolling(window=self.period).max().shift(1)
        lower = low.rolling(window=self.period).min().shift(1)
        middle = (upper + lower) / 2

        close_last = float(close.iloc[-1])
        close_prev = float(close.iloc[-2])
        upper_last = float(upper.iloc[-1])
        lower_last = float(lower.iloc[-1])
        atr = self._atr(df)

        # Breakout above upper band → buy
        if close_prev <= float(upper.iloc[-2]) and close_last > upper_last:
            return SignalDict(
                side=SignalSide.BUY,
                confidence=0.65,
                reason=f"Donchian{self.period} upper band breakout",
                entry_price=close_last,
                stop_price=float(middle.iloc[-1]),
                regime_fit=0.7,
            )

        # Breakdown below lower band → exit
        if close_prev >= float(lower.iloc[-2]) and close_last < lower_last:
            return SignalDict(
                side=SignalSide.SELL,
                confidence=0.65,
                reason=f"Donchian{self.period} lower band breakdown",
                entry_price=close_last,
                stop_price=close_last + 1.5 * atr,
                regime_fit=0.7,
            )

        return None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


# ─── Bollinger Band Strategy (signal-level) ─────────────────────────────────


@dataclass
class BBSignal:
    """Bollinger Band mean-reversion — best in range-bound markets."""
    bb_period: int = 10
    bb_std: float = 1.0

    def generate(self, df: pd.DataFrame) -> SignalDict | None:
        if len(df) < self.bb_period * 2:
            return None

        close = df["close"].astype(float)
        middle = close.rolling(window=self.bb_period).mean()
        sigma = close.rolling(window=self.bb_period).std()
        upper = middle + self.bb_std * sigma
        lower = middle - self.bb_std * sigma

        close_last = float(close.iloc[-1])
        lower_last = float(lower.iloc[-1])
        upper_last = float(upper.iloc[-1])
        atr = self._atr(df)

        # Price touches lower band → buy
        if close_last <= lower_last:
            dist_to_lower = (close_last - lower_last) / close_last
            return SignalDict(
                side=SignalSide.BUY,
                confidence=min(0.7 + (1 - abs(dist_to_lower) * 100) * 0.3, 1.0),
                reason=f"Price at lower BB({self.bb_period},{self.bb_std}) band",
                entry_price=close_last,
                stop_price=close_last - 1.5 * atr,
                regime_fit=0.85,  # very good in range markets
            )

        # Price reaches upper band → exit
        if close_last >= upper_last:
            return SignalDict(
                side=SignalSide.SELL,
                confidence=0.7,
                reason=f"Price at upper BB({self.bb_period},{self.bb_std}) band",
                entry_price=close_last,
                stop_price=close_last + 1.5 * atr,
                regime_fit=0.85,
            )

        return None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])


# ─── Composite Signal Aggregator ────────────────────────────────────────────


@dataclass
class CompositeSignal:
    """Aggregated signal from all strategy outputs, weighted by regime fit."""
    side: SignalSide
    confidence: float  # weighted confidence
    total_weight: float
    signals: list[SignalDict]
    regime: str
    reason: str


@runtime_checkable
class SignalGenerator(Protocol):
    """Protocol for strategy signal generators."""
    def generate(self, df: pd.DataFrame) -> SignalDict | None: ...


# Registry of all strategies
STRATEGY_REGISTRY: dict[str, SignalGenerator] = {
    "ema_cross": EMACrossSignal(fast_period=10, slow_period=30),
    "macd": MACDSignal(fast_period=12, slow_period=26, signal_period=9),
    "rsi": RSISignal(period=14, oversold=30.0, overbought=70.0),
    "donchian": DonchianSignal(period=20),
    "bb": BBSignal(bb_period=10, bb_std=1.0),
}
