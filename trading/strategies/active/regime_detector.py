"""
RegimeDetector — 4-state market regime detection.

Combines:
  - Trend direction: EMA fast vs slow crossover
  - Trend strength: ADX
  - Volatility state: ATR percentile rank over lookback window

States
------
  BULL_TREND    : price > EMA(fast) > EMA(slow) AND ADX > 25  (strong uptrend)
  BEAR_TREND    : price < EMA(fast) < EMA(slow) AND ADX > 25  (strong downtrend)
  RANGE_BOUND   : |EMA(fast) - EMA(slow)| narrow AND ADX < 25 (choppy, no trend)
  VOLATILE_CHOP : |EMA(fast) - EMA(slow)| narrow AND ADX >= 25 (whipsaw)

Each state maps to a preferred strategy:
  BULL_TREND    → momentum / trend-following (EMA cross, MACD)
  BEAR_TREND    → trend-following (short signals, or avoid since long-only)
  RANGE_BOUND   → mean-reversion (Bollinger Band)
  VOLATILE_CHOP → reduce activity, use wider stops
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

RegimeState = Literal["BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "VOLATILE_CHOP"]


@dataclass
class RegimeReport:
    """Full diagnostic output from regime detection."""

    state: RegimeState
    # raw indicators
    adx: float
    atr_pct_rank: float  # 0..1
    ema_fast: float
    ema_slow: float
    close: float
    # confidence 0..1
    confidence: float
    # recommended max position size (0..1)
    max_position_pct: float


def detect_regime(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    ema_fast_period: int = 10,
    ema_slow_period: int = 30,
    adx_period: int = 14,
    atr_period: int = 14,
    atr_lookback: int = 100,
    adx_trend_threshold: float = 25.0,
    atr_high_pct: float = 0.70,  # 70th percentile → "high vol"
) -> RegimeReport:
    """
    Classify the latest bar into one of four regime states.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC data (index aligned).
    ema_fast_period, ema_slow_period : int
        EMA periods for trend direction.
    adx_period : int
        ADX smoothing period.
    atr_period : int
        ATR smoothing period.
    atr_lookback : int
        Lookback window for ATR percentile rank.
    adx_trend_threshold : float
        ADX above this → directional/trending market.
    atr_high_pct : float
        ATR percentile above this → "high volatility" state.
    """
    n = len(close)
    warmup = max(ema_slow_period * 2, adx_period * 2, atr_lookback)

    if n < warmup:
        return RegimeReport(
            state="RANGE_BOUND",
            adx=0.0,
            atr_pct_rank=0.5,
            ema_fast=close.iloc[-1] if n > 0 else 0.0,
            ema_slow=close.iloc[-1] if n > 0 else 0.0,
            close=close.iloc[-1] if n > 0 else 0.0,
            confidence=0.0,
            max_position_pct=0.0,
        )

    # ── EMA for direction ────────────────────────────────────────────────────
    ema_f = close.ewm(span=ema_fast_period, adjust=False).mean()
    ema_s = close.ewm(span=ema_slow_period, adjust=False).mean()

    # ── ADX for trend strength ──────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)

    atr_s = tr.ewm(span=atr_period, adjust=False).mean()
    smooth_plus = plus_dm.ewm(span=adx_period, adjust=False).mean()
    smooth_minus = minus_dm.ewm(span=adx_period, adjust=False).mean()

    dmi_plus = 100 * smooth_plus / atr_s
    dmi_minus = 100 * smooth_minus / atr_s
    dx = 100 * (dmi_plus - dmi_minus).abs() / (dmi_plus + dmi_minus)
    adx_series = dx.ewm(span=adx_period, adjust=False).mean()
    adx_val = float(adx_series.iloc[-1])

    # ── ATR percentile rank ───────────────────────────────────────────────────
    atr_vals = atr_s.iloc[-atr_lookback:]
    current_atr = float(atr_s.iloc[-1])
    pct_rank = float((atr_vals < current_atr).sum() / len(atr_vals))

    # ── Latest values ─────────────────────────────────────────────────────────
    c = float(close.iloc[-1])
    ef = float(ema_f.iloc[-1])
    es = float(ema_s.iloc[-1])

    # ── Classify state ──────────────────────────────────────────────────────
    ema_spread = abs(ef - es) / es  # normalised spread
    is_trending = adx_val >= adx_trend_threshold

    if is_trending:
        if ef > es:
            state: RegimeState = "BULL_TREND"
        else:
            state = "BEAR_TREND"
    else:
        # Not trending — check if it's clean range or volatile chop
        if ema_spread < 0.005:  # emas very close → clean range
            state = "RANGE_BOUND"
        else:
            state = "VOLATILE_CHOP"

    # ── Confidence score (how sure are we?) ────────────────────────────────────
    if state in ("BULL_TREND", "BEAR_TREND"):
        adx_conf = min(adx_val / 40.0, 1.0)  # 40 = "very strong"
        spread_conf = min(ema_spread * 20, 1.0)  # larger spread → more confident
        confidence = float(np.clip(0.5 * adx_conf + 0.5 * spread_conf, 0, 1))
    elif state == "RANGE_BOUND":
        # High confidence when ADX is very low AND bands are narrow
        confidence = float(np.clip(1 - adx_val / 25.0, 0, 1))
    else:  # VOLATILE_CHOP
        confidence = 0.3  # never very confident in chop

    # ── Max position size ──────────────────────────────────────────────────────
    if state in ("BULL_TREND", "BEAR_TREND"):
        if pct_rank < atr_high_pct:
            max_pos = 1.0  # normal
        else:
            max_pos = 0.5  # reduce in high vol
    elif state == "RANGE_BOUND":
        max_pos = 0.75
    else:  # VOLATILE_CHOP
        max_pos = 0.3

    return RegimeReport(
        state=state,
        adx=adx_val,
        atr_pct_rank=pct_rank,
        ema_fast=ef,
        ema_slow=es,
        close=c,
        confidence=confidence,
        max_position_pct=max_pos,
    )


# ── Convenience lookup table ────────────────────────────────────────────────────
# Maps regime → which strategy types are preferred and their base weights.
from typing import NamedTuple


class StrategyWeights(NamedTuple):
    bb: float       # Bollinger Band mean-reversion
    ema: float      # EMA cross / trend-following
    macd: float     # MACD momentum
    rsi: float      # RSI
    donchian: float # Donchian breakout
    flat: float     # no position


REGIME_WEIGHTS: dict[RegimeState, StrategyWeights] = {
    "BULL_TREND": StrategyWeights(bb=0.10, ema=0.45, macd=0.30, rsi=0.10, donchian=0.05, flat=0.00),
    "BEAR_TREND": StrategyWeights(bb=0.05, ema=0.30, macd=0.30, rsi=0.15, donchian=0.05, flat=0.15),
    "RANGE_BOUND": StrategyWeights(bb=0.55, ema=0.05, macd=0.10, rsi=0.20, donchian=0.05, flat=0.05),
    "VOLATILE_CHOP": StrategyWeights(bb=0.20, ema=0.10, macd=0.10, rsi=0.10, donchian=0.05, flat=0.45),
}


def get_strategy_weights(regime: RegimeState) -> StrategyWeights:
    return REGIME_WEIGHTS[regime]
