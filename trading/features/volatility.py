"""Volatility indicators: Bollinger Bands, Keltner Channel."""

from typing import TypedDict

import pandas as pd


class BollingerBandsResult(TypedDict):
    middle: pd.Series
    upper: pd.Series
    lower: pd.Series


class KeltnerChannelResult(TypedDict):
    middle: pd.Series
    upper: pd.Series
    lower: pd.Series


def bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    std: float = 2.0,
) -> BollingerBandsResult:
    """Bollinger Bands.
    ...
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    if std <= 0:
        raise ValueError(f"std multiplier must be > 0, got {std}")

    middle = closes.rolling(window=period).mean()
    sigma = closes.rolling(window=period).std()
    upper = middle + std * sigma
    lower = middle - std * sigma

    return BollingerBandsResult(middle=middle, upper=upper, lower=lower)


def keltner_channel(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    ema_period: int = 20,
    atr_period: int = 10,
    mult: float = 2.0,
) -> KeltnerChannelResult:
    """Keltner Channel.
    ...
    """
    if ema_period < 1:
        raise ValueError(f"ema_period must be >= 1, got {ema_period}")
    if atr_period < 1:
        raise ValueError(f"atr_period must be >= 1, got {atr_period}")
    if mult <= 0:
        raise ValueError(f"mult must be > 0, got {mult}")

    middle = close.ewm(span=ema_period, adjust=False).mean()

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=atr_period, adjust=False).mean()

    upper = middle + mult * atr
    lower = middle - mult * atr

    return KeltnerChannelResult(middle=middle, upper=upper, lower=lower)
