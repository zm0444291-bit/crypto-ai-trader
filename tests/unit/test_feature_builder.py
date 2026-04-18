from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading.features.builder import build_features
from trading.market_data.schemas import CandleData


def make_candles(count: int, start_close: Decimal = Decimal("100")) -> list[CandleData]:
    candles: list[CandleData] = []
    for index in range(count):
        open_time = datetime(2026, 4, 19, 0, 0, tzinfo=UTC) + timedelta(minutes=15 * index)
        close = start_close + Decimal(index)
        candles.append(
            CandleData(
                symbol="BTCUSDT",
                timeframe="15m",
                open_time=open_time,
                close_time=open_time + timedelta(minutes=15),
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100") + Decimal(index),
            )
        )
    return candles


def test_build_features_preserves_order_and_length():
    candles = list(reversed(make_candles(30)))

    features = build_features(candles)

    assert len(features) == 30
    assert features[0].candle_time < features[-1].candle_time
    assert features[0].symbol == "BTCUSDT"
    assert features[0].timeframe == "15m"


def test_build_features_sets_unknown_until_emas_exist():
    features = build_features(make_candles(10))

    assert all(feature.trend_state == "unknown" for feature in features)


def test_build_features_marks_uptrend_when_fast_above_slow_and_close_above_slow():
    features = build_features(make_candles(60))

    latest = features[-1]

    assert latest.ema_fast is not None
    assert latest.ema_slow is not None
    assert latest.close > latest.ema_slow
    assert latest.ema_fast > latest.ema_slow
    assert latest.trend_state == "up"


def test_build_features_marks_downtrend_for_falling_market():
    candles = make_candles(60, start_close=Decimal("200"))
    falling = []
    for index, candle in enumerate(candles):
        close = Decimal("200") - Decimal(index)
        falling.append(
            candle.model_copy(
                update={
                    "close": close,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                }
            )
        )

    features = build_features(falling)

    assert features[-1].trend_state == "down"


def test_build_features_calculates_volume_ratio_after_prior_20_candles():
    candles = make_candles(25)

    features = build_features(candles)

    assert features[19].volume_ratio is None
    assert features[20].volume_ratio is not None
    expected_average = sum(
        (Decimal("100") + Decimal(i) for i in range(20)),
        Decimal("0"),
    ) / Decimal("20")
    assert features[20].volume_ratio == Decimal("120") / expected_average
