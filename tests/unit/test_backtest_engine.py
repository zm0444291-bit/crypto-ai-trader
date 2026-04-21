"""Unit tests for the backtest engine and ParquetCandleStore."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


class DummySignal:
    def __init__(self, qty: Decimal, side: str) -> None:
        self.qty = qty
        self.side = side


class DummyStrategy:
    """Buy once on the 5th bar, sell on the 10th."""

    def __init__(self) -> None:
        self.call_count = 0

    def generate_signals(self, symbol: str, df: pd.DataFrame):
        self.call_count += 1
        if len(df) == 5:
            return [DummySignal(qty=Decimal("0.01"), side="buy")]
        if len(df) == 10:
            return [DummySignal(qty=Decimal("0.01"), side="sell")]
        return []


class TestParquetCandleStore:
    def test_save_and_load(self, tmp_path: Path):
        store = ParquetCandleStore(base_dir=tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2023-01-01", periods=5, freq="h", tz=UTC),
                "open": [100.0] * 5,
                "high": [105.0] * 5,
                "low": [95.0] * 5,
                "close": [102.0] * 5,
                "volume": [1000.0] * 5,
            }
        )
        store.save("BTCUSDT", "1h", df)
        loaded = store.load("BTCUSDT", "1h")
        assert loaded is not None
        assert len(loaded) == 5
        assert loaded["close"].iloc[0] == Decimal("102")

    def test_load_missing_returns_none(self, tmp_path: Path):
        store = ParquetCandleStore(base_dir=tmp_path)
        assert store.load("MISSING", "1h") is None

    def test_exists(self, tmp_path: Path):
        store = ParquetCandleStore(base_dir=tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2023-01-01", periods=3, freq="h", tz=UTC),
                "open": [100.0] * 3,
                "high": [105.0] * 3,
                "low": [95.0] * 3,
                "close": [102.0] * 3,
                "volume": [1000.0] * 3,
            }
        )
        assert not store.exists("BTCUSDT", "1h")
        store.save("BTCUSDT", "1h", df)
        assert store.exists("BTCUSDT", "1h")

    def test_delete(self, tmp_path: Path):
        store = ParquetCandleStore(base_dir=tmp_path)
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2023-01-01", periods=3, freq="h", tz=UTC),
                "open": [100.0] * 3,
                "high": [105.0] * 3,
                "low": [95.0] * 3,
                "close": [102.0] * 3,
                "volume": [1000.0] * 3,
            }
        )
        store.save("BTCUSDT", "1h", df)
        store.delete("BTCUSDT", "1h")
        assert not store.exists("BTCUSDT", "1h")


class TestBacktestEngine:
    @pytest.fixture
    def store(self, tmp_path: Path) -> ParquetCandleStore:
        s = ParquetCandleStore(base_dir=tmp_path)
        now = datetime(2023, 1, 1, tzinfo=UTC)
        timestamps = [now + timedelta(hours=i) for i in range(20)]
        df = pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0] * 20,
                "high": [105.0] * 20,
                "low": [95.0] * 20,
                "close": [100.0 + i for i in range(20)],
                "volume": [1000.0] * 20,
            }
        )
        s.save("BTCUSDT", "15m", df)
        return s

    def test_engine_runs_without_error(self, store: ParquetCandleStore):
        config = BacktestConfig(initial_equity=Decimal("100_000"), interval="15m")
        engine = BacktestEngine(config, store)
        strategy = DummyStrategy()
        result = engine.run(
            strategy=strategy,
            symbols=["BTCUSDT"],
            start_time=datetime(2023, 1, 1, tzinfo=UTC),
            end_time=datetime(2023, 1, 1, 23, tzinfo=UTC),
        )
        assert result.initial_equity == Decimal("100_000")
        assert result.final_equity >= Decimal("0")

    def test_equity_curve_starts_at_initial(self, store: ParquetCandleStore):
        config = BacktestConfig(initial_equity=Decimal("50_000"), interval="15m")
        engine = BacktestEngine(config, store)
        strategy = DummyStrategy()
        result = engine.run(
            strategy=strategy,
            symbols=["BTCUSDT"],
            start_time=datetime(2023, 1, 1, tzinfo=UTC),
            end_time=datetime(2023, 1, 1, 23, tzinfo=UTC),
        )
        assert result.equity_curve[0][1] == Decimal("50_000")

    def test_no_data_raises(self, tmp_path: Path):
        store = ParquetCandleStore(base_dir=tmp_path)
        config = BacktestConfig()
        engine = BacktestEngine(config, store)
        with pytest.raises(ValueError, match="No data"):
            engine.run(
                strategy=DummyStrategy(),
                symbols=["BTCUSDT"],
                start_time=datetime(2023, 1, 1, tzinfo=UTC),
                end_time=datetime(2023, 1, 2, tzinfo=UTC),
            )

    def test_backtest_result_has_required_fields(self, store: ParquetCandleStore):
        config = BacktestConfig(interval="15m")
        engine = BacktestEngine(config, store)
        result = engine.run(
            strategy=DummyStrategy(),
            symbols=["BTCUSDT"],
            start_time=datetime(2023, 1, 1, tzinfo=UTC),
            end_time=datetime(2023, 1, 1, 23, tzinfo=UTC),
        )
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown_pct")
        assert hasattr(result, "win_rate")
        assert hasattr(result, "total_trades")
        assert isinstance(result.equity_curve, list)
