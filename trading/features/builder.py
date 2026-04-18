from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from trading.features.indicators import atr, ema, rsi
from trading.market_data.schemas import CandleData

TrendState = Literal["up", "down", "neutral", "unknown"]


class CandleFeatures(BaseModel):
    symbol: str
    timeframe: str
    candle_time: datetime
    close: Decimal
    ema_fast: Decimal | None
    ema_slow: Decimal | None
    ema_200: Decimal | None
    rsi_14: Decimal | None
    atr_14: Decimal | None
    volume_ratio: Decimal | None
    trend_state: TrendState


def build_features(candles: list[CandleData]) -> list[CandleFeatures]:
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    closes = [candle.close for candle in ordered]
    highs = [candle.high for candle in ordered]
    lows = [candle.low for candle in ordered]

    ema_fast_values = ema(closes, period=12)
    ema_slow_values = ema(closes, period=26)
    ema_200_values = ema(closes, period=200)
    rsi_values = rsi(closes, period=14)
    atr_values = atr(highs, lows, closes, period=14)

    return [
        CandleFeatures(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            candle_time=candle.open_time,
            close=candle.close,
            ema_fast=ema_fast_values[index],
            ema_slow=ema_slow_values[index],
            ema_200=ema_200_values[index],
            rsi_14=rsi_values[index],
            atr_14=atr_values[index],
            volume_ratio=_volume_ratio(ordered, index),
            trend_state=_trend_state(
                close=candle.close,
                ema_fast=ema_fast_values[index],
                ema_slow=ema_slow_values[index],
            ),
        )
        for index, candle in enumerate(ordered)
    ]


def _volume_ratio(candles: list[CandleData], index: int) -> Decimal | None:
    if index < 20:
        return None

    previous_volumes = [candle.volume for candle in candles[index - 20 : index]]
    average_volume = sum(previous_volumes, Decimal("0")) / Decimal("20")
    if average_volume == 0:
        return None

    return candles[index].volume / average_volume


def _trend_state(
    close: Decimal,
    ema_fast: Decimal | None,
    ema_slow: Decimal | None,
) -> TrendState:
    if ema_fast is None or ema_slow is None:
        return "unknown"
    if close > ema_slow and ema_fast > ema_slow:
        return "up"
    if close < ema_slow and ema_fast < ema_slow:
        return "down"
    return "neutral"
