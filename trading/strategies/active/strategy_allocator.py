"""
StrategyAllocator — aggregates signals from multiple strategies,
applies regime-based weights, and produces a final consensus signal.

The allocator:
  1. Runs each strategy and collects its SignalDict output.
  2. Filters out None signals.
  3. Computes weighted confidence scores:
     - Base weight: how much this strategy matters in current regime
     - Regime fit: does the signal match the regime? (penalize mismatches)
     - Confidence: the strategy's own confidence score
  4. Combines same-direction signals by summing weighted scores.
  5. If BUY and SELL are both strong → FLAT (no consensus).
  6. Otherwise: emit the higher-confidence direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from trading.strategies.active.regime_detector import (
    RegimeReport,
    RegimeState,
    get_strategy_weights,
)
from trading.strategies.active.strategy_signals import (
    STRATEGY_REGISTRY,
    SignalDict,
    SignalSide,
)


@dataclass
class AllocationResult:
    """Final output of the allocator."""
    final_side: SignalSide
    final_confidence: float
    total_buy_weight: float
    total_sell_weight: float
    strategy_signals: list[tuple[str, SignalDict]]
    regime: RegimeState
    regime_confidence: float
    max_position_pct: float
    reason: str


# Maps strategy types to their ideal market character
@dataclass
class StrategyAllocator:
    """Aggregates multiple strategies with regime-based dynamic weighting."""

    # Minimum total weighted score to act
    min_activation: float = 0.08

    # Conflict: if min(buy,sell) / max(buy,sell) > this → conflict → FLAT
    conflict_ratio: float = 0.25

    _history: dict[str, list[tuple[SignalSide, bool]]] = field(default_factory=dict)

    def allocate(
        self,
        df: pd.DataFrame,
        regime: RegimeReport,
    ) -> AllocationResult:
        """
        Generate a consensus signal from all strategies.
        """
        signals: list[tuple[str, SignalDict]] = []
        weights = get_strategy_weights(regime.state)

        # Map regime-based weights to strategy instances
        strategy_base_weights = {
            "ema_cross": weights.ema,
            "macd": weights.macd,
            "rsi": weights.rsi,
            "donchian": weights.donchian,
            "bb": weights.bb,
        }

        total_buy = 0.0
        total_sell = 0.0

        for name, strat in STRATEGY_REGISTRY.items():
            sig = strat.generate(df)
            if sig is None:
                continue

            self._last_signals[name] = sig
            base_weight = strategy_base_weights.get(name, 0.0)
            effective_weight = base_weight * sig["confidence"]

            signals.append((name, sig))

            if sig["side"] == SignalSide.BUY:
                total_buy += effective_weight
            elif sig["side"] == SignalSide.SELL:
                total_sell += effective_weight

        total = total_buy + total_sell

        # Activation gate
        if total < self.min_activation:
            return AllocationResult(
                final_side=SignalSide.FLAT,
                final_confidence=0.0,
                total_buy_weight=total_buy,
                total_sell_weight=total_sell,
                strategy_signals=signals,
                regime=regime.state,
                regime_confidence=regime.confidence,
                max_position_pct=regime.max_position_pct,
                reason=f"Weak aggregate signal (total={total:.3f} < {self.min_activation})",
            )

        # Conflict detection: if both sides are meaningful, no consensus
        if total_buy > 0 and total_sell > 0:
            ratio = min(total_buy, total_sell) / max(total_buy, total_sell)
            if ratio > self.conflict_ratio:
                return AllocationResult(
                    final_side=SignalSide.FLAT,
                    final_confidence=0.0,
                    total_buy_weight=total_buy,
                    total_sell_weight=total_sell,
                    strategy_signals=signals,
                    regime=regime.state,
                    regime_confidence=regime.confidence,
                    max_position_pct=regime.max_position_pct,
                    reason="Conflicting signals — both BUY and SELL have meaningful weight",
                )

        # Final decision
        if total_buy >= total_sell:
            final_side = SignalSide.BUY
            final_confidence = min(total_buy / (total + 1e-9), 1.0)
            reason = self._build_reason(signals, SignalSide.BUY)
        else:
            final_side = SignalSide.SELL
            final_confidence = min(total_sell / (total + 1e-9), 1.0)
            reason = self._build_reason(signals, SignalSide.SELL)

        return AllocationResult(
            final_side=final_side,
            final_confidence=final_confidence,
            total_buy_weight=total_buy,
            total_sell_weight=total_sell,
            strategy_signals=signals,
            regime=regime.state,
            regime_confidence=regime.confidence,
            max_position_pct=regime.max_position_pct,
            reason=reason,
        )

    def record_outcome(
        self, strategy_name: str, side: SignalSide, won: bool
    ) -> None:
        """Record whether a signal was correct (called after trade closes)."""
        if strategy_name not in self._history:
            self._history[strategy_name] = []
        self._history[strategy_name].append((side, won))
        if len(self._history[strategy_name]) > self._accuracy_lookback:
            self._history[strategy_name].pop(0)

    @property
    def _accuracy_lookback(self) -> int:
        return 60

    def _rolling_accuracy(self, strategy_name: str) -> float:
        hist = self._history.get(strategy_name, [])
        if len(hist) < 5:
            return 0.5
        return sum(1 for _, won in hist if won) / len(hist)

    def _build_reason(
        self, signals: list[tuple[str, SignalDict]], side: SignalSide
    ) -> str:
        parts = []
        for name, sig in signals:
            if sig["side"] == side:
                parts.append(f'{name}(conf={sig["confidence"]:.2f})')
        return f"Confirmed by: {', '.join(parts)}" if parts else "No confirming signals"

    def reset(self) -> None:
        self._history.clear()
        self._last_signals.clear()

    _last_signals: dict[str, SignalDict | None] = field(default_factory=dict)
