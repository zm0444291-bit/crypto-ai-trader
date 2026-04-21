"""Exit engine for paper trading — evaluates exit signals on open positions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any


class ExitReason(StrEnum):
    HARD_STOP = "hard_stop"
    TAKE_PROFIT = "take_profit"
    TIME_EXIT = "time_exit"
    MANUAL = "manual"


# Default ATR used when position has no entry_atr
DEFAULT_ATR = Decimal("100")


@dataclass
class ExitConfig:
    """Configuration for all exit rules.

    All ATR multipliers are expressed as raw multipliers (e.g. 2.0 = 2x ATR).
    All percentage fields are expressed as decimals (e.g. 0.5 = 50%).
    """

    hard_stop_atr_mult: Decimal = field(default=Decimal("2"))
    take_profit_atr_mult: Decimal = field(default=Decimal("3"))
    max_hold_hours: int = field(default=24)
    time_exit_pct: Decimal = field(default=Decimal("0.5"))  # fraction of position to exit


@dataclass
class ExitSignal:
    """An exit signal generated for a specific position."""

    symbol: str
    reason: ExitReason
    exit_price: Decimal  # market price at signal generation (for immediate execution)
    qty_to_exit: Decimal  # Decimal; may be less than full position for partial exits
    created_at: datetime
    confidence: Decimal = field(default=Decimal("1.0"))  # 0..1
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reason": self.reason.value,
            "exit_price": str(self.exit_price),
            "qty_to_exit": str(self.qty_to_exit),
            "created_at": self.created_at.isoformat(),
            "confidence": str(self.confidence),
            "message": self.message,
        }


class ExitRule(ABC):
    """Base class for a single exit rule."""

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_entry_atr: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime | None,
        config: ExitConfig,
    ) -> ExitSignal | None:
        """Return an ExitSignal if this rule triggers, else None."""
        ...


class HardStopRule(ExitRule):
    """Exit when price falls below the ATR-based stop level.

    stop_price = entry_price * (1 - atr_mult * atr / entry_price)
    Triggers when market_price <= stop_price.
    """

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_entry_atr: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime | None,
        config: ExitConfig,
    ) -> ExitSignal | None:
        if position_avg_entry <= 0:
            return None
        atr = position_entry_atr if position_entry_atr is not None else DEFAULT_ATR
        stop_price = position_avg_entry * (
            Decimal("1") - config.hard_stop_atr_mult * atr / position_avg_entry
        )
        if market_price <= stop_price:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.HARD_STOP,
                exit_price=market_price,
                qty_to_exit=position_qty,
                confidence=Decimal("1.0"),
                created_at=current_time,
                message=f"Hard stop: {market_price} <= {stop_price:.4f}",
            )
        return None


class TakeProfitRule(ExitRule):
    """Exit when price rises above the ATR-based profit target.

    tp_price = entry_price * (1 + atr_mult * atr / entry_price)
    Triggers when market_price >= tp_price.
    """

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_entry_atr: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime | None,
        config: ExitConfig,
    ) -> ExitSignal | None:
        if position_avg_entry <= 0:
            return None
        atr = position_entry_atr if position_entry_atr is not None else DEFAULT_ATR
        tp_price = position_avg_entry * (
            Decimal("1") + config.take_profit_atr_mult * atr / position_avg_entry
        )
        if market_price >= tp_price:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.TAKE_PROFIT,
                exit_price=market_price,
                qty_to_exit=position_qty,
                confidence=Decimal("1.0"),
                created_at=current_time,
                message=f"Take profit: {market_price} >= {tp_price:.4f}",
            )
        return None


class TimeExitRule(ExitRule):
    """Exit after a maximum holding period — always partial (config.time_exit_pct)."""

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_entry_atr: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime | None,
        config: ExitConfig,
    ) -> ExitSignal | None:
        if position_opened_at is None or config.max_hold_hours <= 0:
            return None
        elapsed = current_time - position_opened_at
        if elapsed.total_seconds() >= config.max_hold_hours * 3600:
            return ExitSignal(
                symbol=symbol,
                reason=ExitReason.TIME_EXIT,
                exit_price=market_price,
                qty_to_exit=position_qty * config.time_exit_pct,
                confidence=Decimal("0.8"),
                created_at=current_time,
                message=(
                    f"Time exit: held {elapsed.total_seconds() / 3600:.1f}h"
                    f" > {config.max_hold_hours}h,"
                    f" exiting {float(config.time_exit_pct) * 100:.0f}%"
                ),
            )
        return None


# Priority map: lower number = higher priority
_EXIT_PRIORITY = {
    ExitReason.HARD_STOP: 0,
    ExitReason.TAKE_PROFIT: 1,
    ExitReason.TIME_EXIT: 2,
    ExitReason.MANUAL: -1,  # manual always wins if present
}


class ExitEngine:
    """Evaluates all exit rules and returns the highest-priority triggered signal."""

    def __init__(self, config: ExitConfig) -> None:
        self.config = config
        self._rules: list[ExitRule] = [
            HardStopRule(),
            TakeProfitRule(),
            TimeExitRule(),
        ]

    def evaluate(
        self,
        symbol: str,
        position_qty: Decimal,
        position_avg_entry: Decimal,
        position_stop: Decimal | None,
        position_entry_atr: Decimal | None,
        market_price: Decimal,
        current_time: datetime,
        position_opened_at: datetime | None,
    ) -> ExitSignal | None:
        """Evaluate all rules; return the highest-priority triggered signal, or None.

        When multiple rules trigger simultaneously, priority is:
            HARD_STOP(0) < TAKE_PROFIT(1) < TIME_EXIT(2) < MANUAL(-1)
        """
        if position_qty <= 0:
            return None

        signals: list[ExitSignal] = []
        for rule in self._rules:
            sig = rule.evaluate(
                symbol=symbol,
                position_qty=position_qty,
                position_avg_entry=position_avg_entry,
                position_entry_atr=position_entry_atr,
                market_price=market_price,
                current_time=current_time,
                position_opened_at=position_opened_at,
                config=self.config,
            )
            if sig is not None:
                signals.append(sig)

        if not signals:
            return None

        # Highest priority = lowest _EXIT_PRIORITY number; MANUAL always wins
        return min(signals, key=lambda s: _EXIT_PRIORITY.get(s.reason, 99))


def load_exit_rules_from_yaml(path: str | Path) -> ExitConfig:
    """Load ExitConfig from a YAML file.

    Args:
        path: Path to config/exit_rules.yaml

    Returns:
        ExitConfig with values from YAML; missing fields use defaults.

    Raises:
        FileNotFoundError: if path does not exist.
        ValueError: if YAML is malformed.
    """
    import yaml

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Exit rules config not found: {path}")

    data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    rules = data.get("exit_rules", {})

    def _decimal(value: object, default: str) -> Decimal:
        if value is None:
            return Decimal(default)
        return Decimal(str(value))

    def _int(value: object, default: int) -> int:
        if value is None:
            return default
        if isinstance(value, int):
            return value
        return int(str(value))

    return ExitConfig(
        hard_stop_atr_mult=_decimal(
            rules.get("hard_stop", {}).get("atr_multiplier"), "2.0"
        ),
        take_profit_atr_mult=_decimal(
            rules.get("take_profit", {}).get("atr_multiplier"), "3.0"
        ),
        max_hold_hours=_int(rules.get("time_exit", {}).get("max_hold_hours"), 24),
        time_exit_pct=_decimal(
            rules.get("time_exit", {}).get("partial_exit_pct"), "0.5"
        ),
    )
