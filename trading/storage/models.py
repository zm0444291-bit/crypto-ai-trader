from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, UniqueConstraint
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
