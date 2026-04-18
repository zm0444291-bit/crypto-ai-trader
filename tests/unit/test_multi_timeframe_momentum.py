from datetime import UTC, datetime
from decimal import Decimal

from trading.features.builder import CandleFeatures
from trading.strategies.active.multi_timeframe_momentum import generate_momentum_candidate


def make_feature(
    trend_state: str = "up",
    close: Decimal = Decimal("100"),
    ema_fast: Decimal | None = Decimal("99"),
    ema_slow: Decimal | None = Decimal("98"),
    atr_14: Decimal | None = Decimal("2"),
) -> CandleFeatures:
    return CandleFeatures(
        symbol="BTCUSDT",
        timeframe="15m",
        candle_time=datetime(2026, 4, 19, 0, 0, tzinfo=UTC),
        close=close,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        ema_200=None,
        rsi_14=Decimal("55"),
        atr_14=atr_14,
        volume_ratio=Decimal("1.2"),
        trend_state=trend_state,
    )


def test_generate_momentum_candidate_when_all_rules_pass():
    now = datetime(2026, 4, 19, 1, 0, tzinfo=UTC)

    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[make_feature(close=Decimal("100"), ema_fast=Decimal("99"))],
        features_1h=[make_feature(trend_state="up")],
        features_4h=[make_feature(trend_state="neutral")],
        now=now,
    )

    assert candidate is not None
    assert candidate.strategy_name == "multi_timeframe_momentum"
    assert candidate.symbol == "BTCUSDT"
    assert candidate.side == "BUY"
    assert candidate.entry_reference == Decimal("100")
    assert candidate.stop_reference == Decimal("96")
    assert candidate.rule_confidence == Decimal("0.70")
    assert candidate.created_at == now
    assert "15m/1h momentum" in candidate.reason


def test_generate_momentum_candidate_rejects_4h_downtrend():
    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[make_feature()],
        features_1h=[make_feature()],
        features_4h=[make_feature(trend_state="down")],
        now=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )

    assert candidate is None


def test_generate_momentum_candidate_rejects_when_1h_not_up():
    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[make_feature()],
        features_1h=[make_feature(trend_state="neutral")],
        features_4h=[make_feature(trend_state="up")],
        now=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )

    assert candidate is None


def test_generate_momentum_candidate_rejects_when_15m_close_below_fast_ema():
    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[make_feature(close=Decimal("98"), ema_fast=Decimal("99"))],
        features_1h=[make_feature(trend_state="up")],
        features_4h=[make_feature(trend_state="up")],
        now=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )

    assert candidate is None


def test_generate_momentum_candidate_rejects_missing_atr():
    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[make_feature(atr_14=None)],
        features_1h=[make_feature(trend_state="up")],
        features_4h=[make_feature(trend_state="up")],
        now=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )

    assert candidate is None


def test_generate_momentum_candidate_rejects_empty_features():
    candidate = generate_momentum_candidate(
        symbol="BTCUSDT",
        features_15m=[],
        features_1h=[make_feature()],
        features_4h=[make_feature()],
        now=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )

    assert candidate is None
