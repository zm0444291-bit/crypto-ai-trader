from typing import Any

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.market_data.schemas import CandleData
from trading.storage.models import Candle, Event, Fill, Order


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
        oldest_first = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(asc(Candle.open_time))
            .limit(limit)
        )
        return list(self.session.scalars(oldest_first))

    def get_latest(self, symbol: str, timeframe: str) -> Candle | None:
        statement = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.open_time))
            .limit(1)
        )
        return self.session.scalar(statement)


class ExecutionRecordsRepository:
    """Persistence helper for paper execution records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_paper_execution(self, order: PaperOrder, fill: PaperFill) -> tuple[Order, Fill]:
        order_record = Order(
            mode="paper",
            exchange="paper",
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            requested_notional_usdt=order.requested_notional_usdt,
            status=order.status,
            created_at=order.created_at,
        )
        self.session.add(order_record)
        self.session.flush()

        fill_record = Fill(
            order_id=order_record.id,
            symbol=fill.symbol,
            side=fill.side,
            price=fill.price,
            qty=fill.qty,
            fee_usdt=fill.fee_usdt,
            slippage_bps=fill.slippage_bps,
            filled_at=fill.filled_at,
        )
        self.session.add(fill_record)
        self.session.commit()
        self.session.refresh(order_record)
        self.session.refresh(fill_record)
        return order_record, fill_record

    def list_recent_orders(self, limit: int = 50) -> list[Order]:
        statement = select(Order).order_by(desc(Order.created_at), desc(Order.id)).limit(limit)
        return list(self.session.scalars(statement))

    def list_fills_chronological(self) -> list[Fill]:
        statement = select(Fill).order_by(Fill.filled_at, Fill.id)
        return list(self.session.scalars(statement))
