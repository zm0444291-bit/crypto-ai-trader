from datetime import datetime
from decimal import Decimal

from trading.features.builder import CandleFeatures
from trading.strategies.base import TradeCandidate

STRATEGY_NAME = "multi_timeframe_momentum"


def generate_momentum_candidate(
    symbol: str,
    features_15m: list[CandleFeatures],
    features_1h: list[CandleFeatures],
    features_4h: list[CandleFeatures],
    now: datetime,
) -> TradeCandidate | None:
    if not features_15m or not features_1h or not features_4h:
        return None

    latest_15m = features_15m[-1]
    latest_1h = features_1h[-1]
    latest_4h = features_4h[-1]

    if latest_4h.trend_state == "down":
        return None
    if latest_1h.trend_state != "up":
        return None
    if latest_15m.trend_state != "up":
        return None
    if latest_15m.ema_fast is None or latest_15m.close <= latest_15m.ema_fast:
        return None
    if latest_15m.atr_14 is None:
        return None

    entry_reference = latest_15m.close
    stop_reference = entry_reference - (latest_15m.atr_14 * Decimal("2"))
    if stop_reference <= 0:
        return None

    return TradeCandidate(
        strategy_name=STRATEGY_NAME,
        symbol=symbol,
        side="BUY",
        entry_reference=entry_reference,
        stop_reference=stop_reference,
        rule_confidence=Decimal("0.70"),
        reason="15m/1h momentum aligned with non-bearish 4h context.",
        created_at=now,
    )
