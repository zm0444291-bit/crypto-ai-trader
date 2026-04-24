"""Volume indicators: OBV, VWAP."""

import pandas as pd


def obv(closes: pd.Series, volumes: pd.Series) -> pd.Series:
    """On-Balance Volume.

    Parameters
    ----------
    closes : pd.Series
        Closing prices.
    volumes : pd.Series
        Volume (same length as closes).

    Returns
    -------
    pd.Series of the same length as input.
    First value is the raw volume; subsequent values accumulate.

    Notes
    -----
    OBV_t = OBV_{t-1} + volume_t  if close_t > close_{t-1}
    OBV_t = OBV_{t-1} - volume_t  if close_t < close_{t-1}
    OBV_t = OBV_{t-1}             if close_t == close_{t-1}
    """
    if len(closes) != len(volumes):
        raise ValueError(
            f"closes and volumes must have the same length: "
            f"got {len(closes)} and {len(volumes)}"
        )

    direction = closes.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv_vals = (direction * volumes).cumsum()
    obv_vals = obv_vals.fillna(volumes.iloc[0])
    return obv_vals


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volumes: pd.Series,
) -> pd.Series:
    """Volume Weighted Average Price.

    Parameters
    ----------
    high, low, close, volumes : pd.Series
        OHLCV data (same length).

    Returns
    -------
    pd.Series of the same length as input.
    """
    if not (len(high) == len(low) == len(close) == len(volumes)):
        raise ValueError(
            f"high, low, close, and volumes must have the same length: "
            f"got {len(high)}, {len(low)}, {len(close)}, {len(volumes)}"
        )

    typical_price = (high + low + close) / 3.0
    cumulative_tp_vol = (typical_price * volumes).cumsum()
    cumulative_vol = volumes.cumsum()
    vwap_vals = cumulative_tp_vol / cumulative_vol
    return vwap_vals.fillna(typical_price)
