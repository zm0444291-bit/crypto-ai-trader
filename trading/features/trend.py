"""Trend indicators: ADX, Supertrend, Aroon."""

from typing import TypedDict

import pandas as pd


class ADXResult(TypedDict):
    adx: pd.Series
    dmi_plus: pd.Series
    dmi_minus: pd.Series


class SupertrendResult(TypedDict):
    direction: pd.Series  # 1 = bullish, -1 = bearish
    supertrend: pd.Series


class AroonResult(TypedDict):
    aroon_up: pd.Series
    aroon_down: pd.Series
    aroon_oscillator: pd.Series


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> ADXResult:
    """Average Directional Index (ADX).

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC prices (same length).
    period : int
        ADX smoothing period (default 14).

    Returns
    -------
    ADXResult with keys: adx, dmi_plus, dmi_minus.
    First ``2 * period`` values may be NaN.

    Notes
    -----
    +DI = 100 * EMA(plus_dm, period) / ATR(period)
    -DI = 100 * EMA(minus_dm, period) / ATR(period)
    DX = 100 * |+DI - (-DI)| / |+DI + (-DI)|
    ADX = EMA(DX, period)
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)

    atr = tr.ewm(span=period, adjust=False).mean()
    smooth_plus_dm = plus_dm.ewm(span=period, adjust=False).mean()
    smooth_minus_dm = minus_dm.ewm(span=period, adjust=False).mean()

    dmi_plus = 100 * smooth_plus_dm / atr
    dmi_minus = 100 * smooth_minus_dm / atr

    dx = 100 * (dmi_plus - dmi_minus).abs() / (dmi_plus + dmi_minus)
    adx_result = dx.ewm(span=period, adjust=False).mean()

    return ADXResult(adx=adx_result, dmi_plus=dmi_plus, dmi_minus=dmi_minus)


def supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 10,
    mult: float = 3.0,
) -> SupertrendResult:
    """Supertrend indicator.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC prices (same length).
    period : int
        ATR period (default 10).
    mult : float
        ATR multiplier for the bands (default 3.0).

    Returns
    -------
    SupertrendResult with keys: direction, supertrend.
    First ``period`` values are NaN.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if mult <= 0:
        raise ValueError(f"mult must be > 0, got {mult}")

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    hl2 = (high + low) / 2.0
    upper_band = hl2 + mult * atr
    lower_band = hl2 - mult * atr

    direction = pd.Series(1, index=close.index, dtype=float)
    supertrend_vals = pd.Series(0.0, index=close.index, dtype=float)

    for i in range(period, len(close)):
        prev_st = supertrend_vals.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]

        if close.iloc[i] > upper_band.iloc[i]:
            direction.iloc[i] = 1.0
            supertrend_vals.iloc[i] = lower_band.iloc[i]
        elif close.iloc[i] < lower_band.iloc[i]:
            direction.iloc[i] = -1.0
            supertrend_vals.iloc[i] = upper_band.iloc[i]
        else:
            direction.iloc[i] = prev_dir
            if prev_dir == 1.0:
                supertrend_vals.iloc[i] = (
                    lower_band.iloc[i]
                    if lower_band.iloc[i] < prev_st
                    else prev_st
                )
            else:
                supertrend_vals.iloc[i] = (
                    upper_band.iloc[i]
                    if upper_band.iloc[i] > prev_st
                    else prev_st
                )

    return SupertrendResult(direction=direction, supertrend=supertrend_vals)


def aroon(
    high: pd.Series,
    low: pd.Series,
    period: int = 25,
) -> AroonResult:
    """Aroon indicator.

    Parameters
    ----------
    high, low : pd.Series
        High and low prices (same length).
    period : int
        Aroon lookback period (default 25).

    Returns
    -------
    AroonResult with keys: aroon_up, aroon_down, aroon_oscillator.
    First ``period`` values are NaN.

    Notes
    -----
    Aroon Up   = (period - periods_since_highest_high) / period * 100
    Aroon Down = (period - periods_since_lowest_low) / period * 100
    Aroon Oscillator = Aroon Up - Aroon Down
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    aroon_up = high.rolling(window=period + 1).apply(
        lambda x: float(period - int(pd.Series(x).idxmax()))
        if len(x) == period + 1
        else float("nan"),
        raw=True,
    )
    aroon_down = low.rolling(window=period + 1).apply(
        lambda x: float(period - int(pd.Series(x).idxmin()))
        if len(x) == period + 1
        else float("nan"),
        raw=True,
    )
    aroon_oscillator = aroon_up - aroon_down

    return AroonResult(
        aroon_up=aroon_up,
        aroon_down=aroon_down,
        aroon_oscillator=aroon_oscillator,
    )
