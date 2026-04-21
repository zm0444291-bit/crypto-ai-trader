"""Momentum indicators: MACD, ROC, CCI, Stochastic."""

from typing import TypedDict

import pandas as pd


class MACDResult(TypedDict):
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """MACD (Moving Average Convergence Divergence).

    Parameters
    ----------
    closes : pd.Series
        Closing prices.
    fast : int
        Fast EMA period (default 12).
    slow : int
        Slow EMA period (default 26).
    signal : int
        Signal line EMA period (default 9).

    Returns
    -------
    MACDResult with keys: macd, signal, histogram.
    All Series have the same length as ``closes``.
    Warmup: first ``slow`` values are NaN.

    Notes
    -----
    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA(macd, period=signal)
    Histogram = MACD line - Signal line
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")
    if signal < 1:
        raise ValueError(f"signal period must be >= 1, got {signal}")

    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)


def roc(closes: pd.Series, period: int = 12) -> pd.Series:
    """Rate of Change.

    Parameters
    ----------
    closes : pd.Series
        Closing prices.
    period : int
        Lookback period (default 12).

    Returns
    -------
    pd.Series of the same length as ``closes``.
    First ``period`` values are NaN.

    Notes
    -----
    ROC = (close_t - close_{t-period}) / close_{t-period} * 100
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    roc_series = closes.pct_change(periods=period) * 100.0
    return roc_series


def cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
) -> pd.Series:
    """Commodity Channel Index.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC prices.
    period : int
        CCI period (default 20).

    Returns
    -------
    pd.Series of the same length as input.
    First ``period`` values are NaN.

    Notes
    -----
    CCI = (Typical Price - SMA_typical) / (0.015 * Mean Deviation)
    Typical Price = (high + low + close) / 3
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(window=period).mean()
    mean_dev = tp.rolling(window=period).apply(
        lambda x: abs(x - x.mean()).mean(), raw=True
    )
    cci_vals = (tp - sma_tp) / (mean_dev.replace(0, float("nan")) * 0.015)
    return cci_vals


class StochasticResult(TypedDict):
    k: pd.Series
    d: pd.Series


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k: int = 14,
    d: int = 3,
) -> StochasticResult:
    """Stochastic Oscillator (%K, %D).

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC prices (same length).
    k : int
        %K smoothing period (default 14).
    d : int
        %D smoothing period (default 3).

    Returns
    -------
    StochasticResult with keys: k, d.
    First ``k`` values are NaN.

    Notes
    -----
    %K = (close - lowest_low) / (highest_high - lowest_low) * 100
    %D = SMA(%K, period=d)
    """
    if k < 1:
        raise ValueError(f"%K period must be >= 1, got {k}")
    if d < 1:
        raise ValueError(f"%D period must be >= 1, got {d}")

    lowest = low.rolling(window=k).min()
    highest = high.rolling(window=k).max()
    k_vals = ((close - lowest) / (highest - lowest) * 100).fillna(0)
    d_vals = k_vals.rolling(window=d).mean()
    return StochasticResult(k=k_vals, d=d_vals)
