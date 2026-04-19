from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from trading.execution.gate import TRADE_MODES, LiveTradingLock
from trading.execution.paper_executor import PaperFill, PaperOrder
from trading.market_data.schemas import CandleData
from trading.storage.models import Candle, Event, Fill, Order, RuntimeControl, ShadowExecution


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

    def list_recent(
        self,
        limit: int = 50,
        severity: str | None = None,
        component: str | None = None,
        event_type: str | None = None,
    ) -> list[Event]:
        statement = select(Event)
        if severity is not None:
            statement = statement.where(Event.severity == severity)
        if component is not None:
            statement = statement.where(Event.component == component)
        if event_type is not None:
            statement = statement.where(Event.event_type == event_type)
        statement = statement.order_by(desc(Event.id)).limit(limit)
        return list(self.session.scalars(statement))

    def get_latest_event_by_type(self, event_type: str) -> Event | None:
        """Return the most recent event of the given type, or None."""
        statement = (
            select(Event)
            .where(Event.event_type == event_type)
            .order_by(desc(Event.id))
            .limit(1)
        )
        return self.session.scalar(statement)


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


class RuntimeControlRepository:
    """Persistence helper for runtime control-plane state (trade mode, lock, etc.)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── trade mode ─────────────────────────────────────────────────────────────

    def get_trade_mode(self, default: TRADE_MODES = "paper_auto") -> TRADE_MODES:
        """Return the persisted trade mode, or the default if absent."""
        row = self.session.get(RuntimeControl, "trade_mode")
        if row is None:
            return default
        return row.value_json.get("mode", default)

    def set_trade_mode(self, mode: TRADE_MODES) -> None:
        """Persist a trade mode."""
        row = self.session.get(RuntimeControl, "trade_mode")
        if row is None:
            row = RuntimeControl(key="trade_mode", value_json={"mode": mode})
            self.session.add(row)
        else:
            row.value_json = {"mode": mode}
        self.session.commit()

    # ── live trading lock ───────────────────────────────────────────────────────

    def get_live_trading_lock(self) -> LiveTradingLock:
        """Return the persisted live trading lock state."""
        row = self.session.get(RuntimeControl, "live_trading_lock")
        if row is None:
            return LiveTradingLock(enabled=False)
        return LiveTradingLock(
            enabled=row.value_json.get("enabled", False),
            reason=row.value_json.get("reason"),
        )

    def set_live_trading_lock(self, enabled: bool, reason: str | None = None) -> None:
        """Persist the live trading lock state."""
        row = self.session.get(RuntimeControl, "live_trading_lock")
        if row is None:
            row = RuntimeControl(
                key="live_trading_lock",
                value_json={"enabled": enabled, "reason": reason},
            )
            self.session.add(row)
        else:
            row.value_json = {"enabled": enabled, "reason": reason}
        self.session.commit()

    # ── snapshot ────────────────────────────────────────────────────────────────

    def get_control_plane_snapshot(self) -> dict[str, Any]:
        """Return a full snapshot of the control plane for read-only queries."""
        mode = self.get_trade_mode()
        lock = self.get_live_trading_lock()
        return {
            "trade_mode": mode,
            "lock_enabled": lock.enabled,
            "lock_reason": lock.reason,
        }


class ShadowExecutionRepository:
    """Persistence helper for shadow execution records (live_shadow mode)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_shadow_execution(
        self,
        symbol: str,
        side: str,
        planned_notional_usdt: Decimal,
        reference_price: Decimal,
        simulated_fill_price: Decimal,
        simulated_slippage_bps: Decimal,
        decision_reason: str,
        source_cycle_status: str | None = None,
    ) -> ShadowExecution:
        """Persist a shadow execution record."""
        record = ShadowExecution(
            symbol=symbol,
            side=side,
            planned_notional_usdt=planned_notional_usdt,
            reference_price=reference_price,
            simulated_fill_price=simulated_fill_price,
            simulated_slippage_bps=simulated_slippage_bps,
            decision_reason=decision_reason,
            source_cycle_status=source_cycle_status,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_recent_shadow(self, limit: int = 50) -> list[ShadowExecution]:
        """Return the most recent shadow execution records."""
        statement = (
            select(ShadowExecution)
            .order_by(desc(ShadowExecution.created_at))
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_last_hour(self, cutoff: datetime) -> int:
        """Return count of shadow executions created after cutoff."""
        statement = select(ShadowExecution).where(
            ShadowExecution.created_at >= cutoff
        )
        return len(list(self.session.scalars(statement)))
