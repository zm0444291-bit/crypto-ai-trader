"""Tests for Stage 2b storage models (ORM mapping for new tables)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading.storage.db import Base, create_database_engine, create_session_factory


class TestNewModelDefinitions:
    """Verify that all new ORM models are importable and have correct tablename."""

    def test_exit_signal_import(self):
        from trading.storage.models import ExitSignal

        assert ExitSignal.__tablename__ == "exit_signals"
        assert hasattr(ExitSignal, "cycle_id")
        assert hasattr(ExitSignal, "symbol")
        assert hasattr(ExitSignal, "qty_to_exit")
        assert hasattr(ExitSignal, "confidence")

    def test_ai_score_import(self):
        from trading.storage.models import AIScore

        assert AIScore.__tablename__ == "ai_scores"
        assert hasattr(AIScore, "cycle_id")
        assert hasattr(AIScore, "symbol")
        assert hasattr(AIScore, "decision_hint")
        assert hasattr(AIScore, "ai_score")

    def test_backtest_run_import(self):
        from trading.storage.models import BacktestRun

        assert BacktestRun.__tablename__ == "backtest_runs"
        assert hasattr(BacktestRun, "run_id")
        assert hasattr(BacktestRun, "strategy_name")
        assert hasattr(BacktestRun, "total_return_pct")
        assert hasattr(BacktestRun, "sharpe_ratio")

    def test_strategy_params_history_import(self):
        from trading.storage.models import StrategyParamsHistory

        assert StrategyParamsHistory.__tablename__ == "strategy_params_history"
        assert hasattr(StrategyParamsHistory, "strategy_name")
        assert hasattr(StrategyParamsHistory, "param_key")
        assert hasattr(StrategyParamsHistory, "param_value")

    def test_risk_state_model_import(self):
        from trading.storage.models import RiskState

        assert RiskState.__tablename__ == "risk_states"
        assert hasattr(RiskState, "symbol")
        assert hasattr(RiskState, "risk_state")
        assert hasattr(RiskState, "consecutive_losses_json")


class TestOrmCrud:
    """End-to-end ORM create/read on the new models using a temp DB."""

    @pytest.fixture
    def session(self, tmp_path):
        db_path = tmp_path / "orm_test.db"
        database_url = f"sqlite:///{db_path}"
        engine = create_database_engine(database_url)
        # Create all tables via Base.metadata
        Base.metadata.create_all(engine)
        session_factory = create_session_factory(engine)
        session = session_factory()
        yield session
        session.close()

    def test_exit_signal_crud(self, session):
        from trading.storage.models import ExitSignal

        sig = ExitSignal(
            cycle_id="cycle-001",
            symbol="BTCUSDT",
            side="sell",
            signal_reason="RSI overbought",
            qty_to_exit=0.5,
            confidence=0.85,
            executed=False,
        )
        session.add(sig)
        session.commit()

        result = session.query(ExitSignal).filter_by(cycle_id="cycle-001").first()
        assert result is not None
        assert result.symbol == "BTCUSDT"
        assert result.side == "sell"
        assert result.qty_to_exit == 0.5
        assert float(result.confidence) == pytest.approx(0.85)
        assert int(result.executed) == 0  # stored as INTEGER 0

    def test_ai_score_crud(self, session):
        from trading.storage.models import AIScore

        score = AIScore(
            cycle_id="cycle-002",
            symbol="ETHUSDT",
            decision_hint="accept",
            ai_score=0.73,
            model_used="MiniMax-M2.7",
            reasoning="Strong momentum confirmed by volume",
            latency_ms=120,
        )
        session.add(score)
        session.commit()

        result = session.query(AIScore).filter_by(cycle_id="cycle-002").first()
        assert result is not None
        assert result.symbol == "ETHUSDT"
        assert result.decision_hint == "accept"
        assert float(result.ai_score) == pytest.approx(0.73)
        assert result.model_used == "MiniMax-M2.7"
        assert result.latency_ms == 120

    def test_backtest_run_crud(self, session):
        from trading.storage.models import BacktestRun

        run = BacktestRun(
            run_id="run-2024-001",
            strategy_name="momentum_v1",
            symbols="BTCUSDT,ETHUSDT",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 31, tzinfo=UTC),
            initial_equity_usdt=50_000.0,
            final_equity_usdt=55_000.0,
            total_return_pct=10.0,
            sharpe_ratio=1.5,
            max_drawdown_pct=5.0,
            win_rate=0.6,
            total_trades=20,
            avg_win_loss_ratio=2.0,
            monthly_returns_json={"2024-01": 10.0},
            equity_curve_json=[],
            trades_json=[],
            config_json={"fee_bps": 10},
        )
        session.add(run)
        session.commit()

        result = session.query(BacktestRun).filter_by(run_id="run-2024-001").first()
        assert result is not None
        assert result.strategy_name == "momentum_v1"
        assert result.final_equity_usdt == 55_000.0
        assert result.sharpe_ratio == 1.5
        assert result.monthly_returns_json == {"2024-01": 10.0}

    def test_strategy_params_history_crud(self, session):
        from trading.storage.models import StrategyParamsHistory

        hist = StrategyParamsHistory(
            strategy_name="momentum_v1",
            param_key="rsi_threshold",
            param_value="35",
            changed_by="alice",
            changed_at=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
            reason="Lowered threshold for faster entries",
        )
        session.add(hist)
        session.commit()

        result = session.query(StrategyParamsHistory).filter_by(
            strategy_name="momentum_v1", param_key="rsi_threshold"
        ).first()
        assert result is not None
        assert result.param_value == "35"
        assert result.changed_by == "alice"

    def test_risk_state_crud(self, session):
        from trading.storage.models import RiskState

        state = RiskState(
            symbol="BTCUSDT",
            risk_state="normal",
            day_start_equity_usdt=50_000.0,
            current_equity_usdt=48_000.0,
            daily_pnl_usdt=-2_000.0,
            daily_pnl_pct=-4.0,
            consecutive_losses_json={"BTCUSDT": 2, "ETHUSDT": 0},
        )
        session.add(state)
        session.commit()

        result = session.query(RiskState).filter_by(symbol="BTCUSDT").first()
        assert result is not None
        assert result.risk_state == "normal"
        assert result.consecutive_losses_json == {"BTCUSDT": 2, "ETHUSDT": 0}

    def test_risk_state_default_consecutive_losses_json(self, session):
        from trading.storage.models import RiskState

        state = RiskState(
            symbol="ETHUSDT",
            risk_state="normal",
            day_start_equity_usdt=50_000.0,
            current_equity_usdt=49_500.0,
        )
        session.add(state)
        session.commit()

        result = session.query(RiskState).filter_by(symbol="ETHUSDT").first()
        assert result is not None
        assert result.consecutive_losses_json == {}