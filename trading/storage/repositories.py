from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trading.market_data.schemas import CandleData
from trading.storage.models import Candle, Event


class EventsRepository:
    """Persistence helper for runtime events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_type=event_type,
            severity=severity,
            component=component,
            message=message,
            context_json=context or {},
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def list_recent(self, limit: int = 50) -> list[Event]:
        statement = select(Event).order_by(desc(Event.id)).limit(limit)
        return list(self.session.scalars(statement))


class CandlesRepository:
    """Persistence helper for OHLCV candles."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, candles: list[CandleData]) -> int:
        affected = 0
        for candle_data in candles:
            existing = self.session.scalar(
                select(Candle).where(
                    Candle.symbol == candle_data.symbol,
                    Candle.timeframe == candle_data.timeframe,
                    Candle.open_time == candle_data.open_time,
                )
            )
            if existing is None:
                self.session.add(
                    Candle(
                        symbol=candle_data.symbol,
                        timeframe=candle_data.timeframe,
                        open_time=candle_data.open_time,
                        close_time=candle_data.close_time,
                        open=candle_data.open,
                        high=candle_data.high,
                        low=candle_data.low,
                        close=candle_data.close,
                        volume=candle_data.volume,
                        source=candle_data.source,
                    )
                )
            else:
                existing.close_time = candle_data.close_time
                existing.open = candle_data.open
                existing.high = candle_data.high
                existing.low = candle_data.low
                existing.close = candle_data.close
                existing.volume = candle_data.volume
                existing.source = candle_data.source
            affected += 1

        self.session.commit()
        return affected

    def list_recent(self, symbol: str, timeframe: str, limit: int = 100) -> list[Candle]:
        newest_first = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.open_time))
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(newest_first))))

    def get_latest(self, symbol: str, timeframe: str) -> Candle | None:
        statement = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.open_time))
            .limit(1)
        )
        return self.session.scalar(statement)
