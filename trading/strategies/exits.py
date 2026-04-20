"""Exit engine for paper trading — evaluates exit signals on open positions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ExitReason(StrEnum):
    HARD_STOP = "hard_stop"
    TAKE_PROFIT = "take_profit"
    TIME_EXIT = "time_exit"


@dataclass
class ExitSignal:
    """An exit signal generated for a specific position."""

    symbol: str
    reason: ExitReason
    exit_price: Decimal
    qty_to_exit: Decimal  # Decimal; may be less than full position for partial exits
    created_at: datetime
    confidence: Decimal = field(default=Decimal("1.0"))  # 0..1
    message: str = ""


class ExitRule(ABC):
    """Base class for a single exit rule."""

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime,
    ) -> ExitSignal | None:
        """Return an ExitSignal if this rule triggers, else None."""
        ...


class HardStopRule(ExitRule):
    """Exit when price falls below stop_reference (ATR-based stop)."""

    def __init__(
        self,
        stop_reference: Decimal | None = None,
        atr_multiplier: Decimal = Decimal("2"),
    ) -> None:
        self.stop_reference = stop_reference  # if None, uses position's stored stop
        self.atr_multiplier = atr_multiplier

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime,
    ) -> ExitSignal | None:
        if self.stop_reference is None:
            return None  # caller must provide via ExitEngine config
        if market_price <= self.stop_reference:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.HARD_STOP,
                exit_price=self.stop_reference,
                qty_to_exit=position_qty,
                confidence=Decimal("1.0"),
                created_at=current_time,
                message=f"Hard stop triggered: market={market_price} <= stop={self.stop_reference}",
            )
        return None


class TakeProfitRule(ExitRule):
    """Exit when price rises above a target."""

    def __init__(self, target_price: Decimal | None = None) -> None:
        self.target_price = target_price

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime,
    ) -> ExitSignal | None:
        if self.target_price is None:
            return None
        if market_price >= self.target_price:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.TAKE_PROFIT,
                exit_price=self.target_price,
                qty_to_exit=position_qty,
                confidence=Decimal("1.0"),
                created_at=current_time,
                message=(
                    f"Take profit triggered: market={market_price} >= target={self.target_price}"
                ),
            )
        return None


class TimeExitRule(ExitRule):
    """Exit after a maximum holding period."""

    def __init__(self, max_hours: int = 24) -> None:
        self.max_hours = max_hours

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime,
    ) -> ExitSignal | None:
        if position_opened_at is None:
            return None
        elapsed = current_time - position_opened_at
        if elapsed.total_seconds() >= self.max_hours * 3600:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.TIME_EXIT,
                exit_price=market_price,
                qty_to_exit=position_qty,
                confidence=Decimal("0.8"),
                created_at=current_time,
                message=(
                    f"Time exit triggered: held {elapsed.total_seconds() / 3600:.1f}h"
                    f" > {self.max_hours}h"
                ),
            )
        return None


class ExitEngine:
    """Evaluates all exit rules against a position and returns the best signal."""

    def __init__(
        self,
        hard_stop_reference: Decimal | None = None,
        take_profit_pct: Decimal = Decimal("5"),  # % above entry
        max_hours: int = 24,
    ) -> None:
        self.hard_stop_reference = hard_stop_reference
        self.take_profit_pct = take_profit_pct
        self.max_hours = max_hours

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_stop: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime,
    ) -> ExitSignal | None:
        """Evaluate all rules; return the first triggered exit signal, or None."""
        rules: list[ExitRule] = []

        # Hard stop: use position's own stop if provided, else engine default
        stop_ref = position_stop if position_stop is not None else self.hard_stop_reference
        if stop_ref is not None:
            rules.append(HardStopRule(stop_reference=stop_ref))

        # Take profit
        if self.take_profit_pct != 0 and position_avg_entry != 0:
            tp_target = position_avg_entry * (Decimal("1") + self.take_profit_pct / Decimal("100"))
            rules.append(TakeProfitRule(target_price=tp_target))

        # Time exit
        if self.max_hours > 0:
            rules.append(TimeExitRule(max_hours=self.max_hours))

        for rule in rules:
            signal = rule.evaluate(
                symbol=symbol,
                position_qty=position_qty,
                position_avg_entry=position_avg_entry,
                market_price=market_price,
                current_time=current_time,
                position_opened_at=position_opened_at,
            )
            if signal is not None:
                return signal

        return None
