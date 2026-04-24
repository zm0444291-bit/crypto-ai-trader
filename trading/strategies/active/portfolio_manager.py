"""PortfolioStrategyManager - routes market data to multiple strategies and aggregates candidates.

Given a list of strategy instances (or strategy names to instantiate via
StrategyRegistry), the manager:
  1. Feeds each strategy the same market data.
  2. Collects all TradeCandidate objects returned.
  3. Returns them ranked/ranked for downstream AI scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from trading.strategies.factory import StrategyRegistry


class HasGenerateSignals(Protocol):
    """Protocol for strategy objects that generate signals."""

    STRATEGY_NAME: str

    def generate_signals(self, symbol: str, df: Any) -> Any:
        ...


@dataclass
class CandidateRanking:
    """A candidate enriched with its strategy name and regime."""

    strategy_name: str
    symbol: str
    side: str
    qty: Decimal
    entry_atr: float | None
    regime: str
    created_at: datetime


class PortfolioStrategyManager:
    """Routes data to multiple strategies and aggregates signals.

    Parameters
    ----------
    strategy_names : list[str]
        Names of strategies to instantiate via StrategyRegistry.
    strategy_kwargs : dict[str, dict[str, object]]
        Per-strategy keyword arguments for construction.
        Example: {"mean_reversion": {"bb_period": 30}}
    """

    def __init__(
        self,
        strategy_names: list[str],
        strategy_kwargs: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.strategy_names = strategy_names
        self.strategy_kwargs = strategy_kwargs or {}
        self._strategies: list[HasGenerateSignals] = []
        self._instances: dict[str, HasGenerateSignals] = {}
        self._build_strategies()

    def _build_strategies(self) -> None:
        """Instantiate all registered strategies."""
        for name in self.strategy_names:
            kwargs = self.strategy_kwargs.get(name, {})
            instance = StrategyRegistry.create(name, **kwargs)
            self._strategies.append(instance)  # type: ignore[arg-type]
            self._instances[name] = instance  # type: ignore[assignment]

    def generate_signals(
        self, symbol: str, df: Any
    ) -> list[CandidateRanking]:
        """Feed market data to all strategies and aggregate signals.

        Parameters
        ----------
        symbol : str
            Trading symbol.
        df : pd.DataFrame
            OHLCV DataFrame with columns: high, low, close, volume, timestamp.

        Returns
        -------
        list[CandidateRanking]
            All signals returned by all strategies, tagged with strategy name.
        """
        results: list[CandidateRanking] = []
        for strat in self._strategies:
            try:
                signals = strat.generate_signals(symbol, df)
            except Exception:
                signals = []
            for sig in signals:
                results.append(
                    CandidateRanking(
                        strategy_name=strat.STRATEGY_NAME,
                        symbol=symbol,
                        side=sig.side,
                        qty=sig.qty,
                        entry_atr=sig.entry_atr,
                        regime="unknown",
                        created_at=datetime.now(),
                    )
                )
        return results

    def strategy_instance(self, name: str) -> HasGenerateSignals | None:
        """Return the instantiated strategy instance by name, or None."""
        return self._instances.get(name)

    def active_strategy_names(self) -> list[str]:
        """Return the list of strategy names this manager routes to."""
        return list(self._instances.keys())
