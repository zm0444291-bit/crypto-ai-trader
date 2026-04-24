"""MarketRegimeDetector - classifies market as trend / range / volatile using ADX + BB bandwidth."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd


class MarketRegimeResult(TypedDict):
    regime: str  # "trend", "range", "volatile"
    adx: float
    bb_bandwidth: float


def detect_market_regime(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    adx_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
    adx_strong_threshold: float = 25.0,
    bb_narrow_threshold: float = 0.04,
) -> MarketRegimeResult:
    """Classify the latest bar's market regime.

    Uses ADX to measure trend strength and Bollinger Bandwidth to detect
    volatility contraction (range) vs expansion (trend/volatile).

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC prices.
    adx_period : int
        ADX smoothing period (default 14).
    bb_period : int
        Bollinger Bands period (default 20).
    bb_std : float
        Bollinger Bands standard deviations (default 2.0).
    adx_strong_threshold : float
        ADX above this → trend regime (default 25.0).
    bb_narrow_threshold : float
        BB Bandwidth below this → range regime (default 0.05).

    Returns
    -------
    MarketRegimeResult
        Keys: regime ("trend" | "range" | "volatile"), adx (float), bb_bandwidth (float).

    Notes
    -----
    BB Bandwidth = (upper - lower) / middle
    """
    if len(close) < max(adx_period * 2, bb_period):
        return MarketRegimeResult(regime="range", adx=0.0, bb_bandwidth=0.0)

    # ── ADX ────────────────────────────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)

    atr_s = tr.ewm(span=adx_period, adjust=False).mean()
    smooth_plus_dm = plus_dm.ewm(span=adx_period, adjust=False).mean()
    smooth_minus_dm = minus_dm.ewm(span=adx_period, adjust=False).mean()

    dmi_plus = 100 * smooth_plus_dm / atr_s
    dmi_minus = 100 * smooth_minus_dm / atr_s
    dx = 100 * (dmi_plus - dmi_minus).abs() / (dmi_plus + dmi_minus)
    adx_series = dx.ewm(span=adx_period, adjust=False).mean()

    adx_val = float(adx_series.iloc[-1])

    # ── Bollinger Bandwidth ───────────────────────────────────────────────
    middle = close.rolling(window=bb_period).mean()
    sigma = close.rolling(window=bb_period).std()
    upper = middle + bb_std * sigma
    lower = middle - bb_std * sigma
    bandwidth = (upper - lower) / middle
    bb_bw = float(bandwidth.iloc[-1])

    # Guard against NaN ADX (can happen when atr ≈ 0 or data is flat)
    if adx_val != adx_val:  # NaN check
        return MarketRegimeResult(regime="range", adx=0.0, bb_bandwidth=bb_bw)

    # ── Classification ───────────────────────────────────────────────────
    # Classification logic:
    #   "trend":    ADX >= adx_strong_threshold (strong directional movement)
    #   "range":    ADX < adx_strong_threshold AND BB bandwidth < bb_narrow_threshold
    #   "volatile": otherwise (low ADX but high volatility — not a clean range)
    if adx_val >= adx_strong_threshold:
        regime = "trend"
    elif bb_bw < bb_narrow_threshold:
        # Low ADX + narrow bands = clean range / compression
        regime = "range"
    else:
        # Low ADX + wide bands = volatile / choppy
        regime = "volatile"

    return MarketRegimeResult(regime=regime, adx=adx_val, bb_bandwidth=bb_bw)
