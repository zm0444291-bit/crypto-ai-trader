"""Unit tests for StrategyRegistry and PortfolioStrategyManager."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from trading.strategies.active.portfolio_manager import (
    CandidateRanking,
    PortfolioStrategyManager,
)
from trading.strategies.factory import StrategyRegistry


def _ohlcv_df(
    closes: list[float],
    start: datetime | None = None,
) -> pd.DataFrame:
    if start is None:
        start = datetime(2023, 1, 1, tzinfo=UTC)
    n = len(closes)
    timestamps = [start + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


class TestStrategyRegistry:
    def test_register_and_create(self):
        # Already auto-registered in factory.py
        names = StrategyRegistry.list_strategies()
        assert "mean_reversion" in names
        assert "breakout" in names

    def test_create_mean_reversion(self):
        strat = StrategyRegistry.create("mean_reversion")
        assert strat.STRATEGY_NAME == "mean_reversion"

    def test_create_breakout(self):
        strat = StrategyRegistry.create("breakout", lookback=10)
        assert strat.STRATEGY_NAME == "breakout"

    def test_create_with_kwargs(self):
        strat = StrategyRegistry.create("mean_reversion", bb_period=30, bb_std=2.5)
        assert strat.bb_period == 30
        assert strat.bb_std == 2.5

    def test_create_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            StrategyRegistry.create("nonexistent_strategy")

    def test_is_registered(self):
        assert StrategyRegistry.is_registered("mean_reversion")
        assert StrategyRegistry.is_registered("breakout")
        assert not StrategyRegistry.is_registered("nonexistent")


class TestPortfolioStrategyManager:
    def test_manager_builds_strategies(self):
        manager = PortfolioStrategyManager(
            strategy_names=["mean_reversion", "breakout"],
            strategy_kwargs={
                "breakout": {"lookback": 10},
            },
        )
        assert "mean_reversion" in manager.active_strategy_names()
        assert "breakout" in manager.active_strategy_names()
        breakout = manager.strategy_instance("breakout")
        assert breakout is not None
        assert breakout.lookback == 10

    def test_generate_signals_aggregates(self):
        manager = PortfolioStrategyManager(strategy_names=["mean_reversion", "breakout"])
        # Flat range market — neither strategy should generate buy signals
        closes = [100.0] * 50
        df = _ohlcv_df(closes)
        signals = manager.generate_signals("BTCUSDT", df)
        # All returned as CandidateRanking
        for sig in signals:
            assert isinstance(sig, CandidateRanking)
            assert sig.symbol == "BTCUSDT"

    def test_manager_empty_strategies(self):
        manager = PortfolioStrategyManager(strategy_names=[])
        signals = manager.generate_signals("BTCUSDT", pd.DataFrame())
        assert signals == []

    def test_active_strategy_names(self):
        manager = PortfolioStrategyManager(
            strategy_names=["mean_reversion"],
            strategy_kwargs={"mean_reversion": {"bb_period": 30}},
        )
        names = manager.active_strategy_names()
        assert names == ["mean_reversion"]
