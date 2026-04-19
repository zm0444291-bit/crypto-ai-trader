from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trading.storage.db import Base


class Event(Base):
    """Structured runtime event for audit and dashboard display."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )


class Candle(Base):
    """OHLCV candle data for market analysis."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "open_time",
            name="uq_candle_symbol_timeframe_open_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)
    high: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)
    low: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)
    close: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)
    volume: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="binance")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class Order(Base):
    """Order record for paper and later live/shadow execution."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_notional_usdt: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class Fill(Base):
    """Fill record tied to an order."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(28, 28), nullable=False)
    fee_usdt: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class RuntimeControl(Base):
    """Key-value store for runtime control-plane state (mode, lock, etc.)."""

    __tablename__ = "runtime_control"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ShadowExecution(Base):
    """Hypothetical execution plan/result recorded in live_shadow mode.

    No real orders are placed. This table captures what *would* have been executed
    for audit, analysis, and dashboard visibility.
    """

    __tablename__ = "shadow_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    planned_notional_usdt: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    simulated_fill_price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    simulated_slippage_bps: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    source_cycle_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
