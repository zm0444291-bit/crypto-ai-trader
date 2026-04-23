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
    # Lifecycle correlation fields
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


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
    open: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)  # type: ignore[type-arg]
    high: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)  # type: ignore[type-arg]
    low: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)  # type: ignore[type-arg]
    close: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)  # type: ignore[type-arg]
    volume: Mapped[Numeric] = mapped_column(Numeric(28, 10), nullable=False)  # type: ignore[type-arg]
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


class ExitSignal(Base):
    """Exit signal generated by exit strategies for a trading cycle."""

    __tablename__ = "exit_signals"
    __table_args__ = (
        UniqueConstraint("cycle_id", "symbol", "side", name="uq_exit_signal_cycle_symbol_side"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_reason: Mapped[str] = mapped_column(String(200), nullable=False)
    qty_to_exit: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(28, 10), nullable=True)
    executed: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class AIScore(Base):
    """AI scoring result for a candidate signal in a trading cycle."""

    __tablename__ = "ai_scores"
    __table_args__ = (
        UniqueConstraint("cycle_id", "symbol", name="uq_ai_score_cycle_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    decision_hint: Mapped[str] = mapped_column(String(20), nullable=False)
    ai_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    model_used: Mapped[str] = mapped_column(String(80), nullable=False)
    reasoning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class BacktestRun(Base):
    """Persisted backtest run result."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    symbols: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_equity_usdt: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    final_equity_usdt: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    total_return_pct: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    win_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_win_loss_ratio: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    monthly_returns_json: Mapped[dict[str, float]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    equity_curve_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    trades_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class StrategyParamsHistory(Base):
    """Audit trail for strategy parameter changes."""

    __tablename__ = "strategy_params_history"
    __table_args__ = (
        UniqueConstraint("strategy_name", "param_key", "changed_at", name="uq_param_change"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    param_key: Mapped[str] = mapped_column(String(80), nullable=False)
    param_value: Mapped[str] = mapped_column(String(500), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(80), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class RiskState(Base):
    """Persisted risk state per symbol with consecutive loss tracking."""

    __tablename__ = "risk_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    risk_state: Mapped[str] = mapped_column(String(30), nullable=False, default="normal")
    day_start_equity_usdt: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    current_equity_usdt: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    daily_pnl_usdt: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False, default=0)
    daily_pnl_pct: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    consecutive_losses_json: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
