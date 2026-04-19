"""Unit tests for the ShadowExecutionRepository."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from trading.storage.db import Base
from trading.storage.models import ShadowExecution
from trading.storage.repositories import ShadowExecutionRepository


def test_record_shadow_execution_creates_record():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = ShadowExecutionRepository(session)

        record = repository.record_shadow_execution(
            symbol="BTCUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("100"),
            reference_price=Decimal("95000"),
            simulated_fill_price=Decimal("95010"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="live_shadow_approved",
            source_cycle_status="shadow_recorded",
        )

        assert record.id is not None
        assert record.symbol == "BTCUSDT"
        assert record.side == "BUY"
        assert record.planned_notional_usdt == Decimal("100")
        assert record.reference_price == Decimal("95000")
        assert record.simulated_fill_price == Decimal("95010")
        assert record.simulated_slippage_bps == Decimal("10")
        assert record.decision_reason == "live_shadow_approved"
        assert record.source_cycle_status == "shadow_recorded"


def test_list_recent_shadow_returns_newest_first():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = ShadowExecutionRepository(session)

        # First record
        repository.record_shadow_execution(
            symbol="BTCUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("100"),
            reference_price=Decimal("95000"),
            simulated_fill_price=Decimal("95010"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="first",
        )

        # Second record (newer)
        repository.record_shadow_execution(
            symbol="ETHUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("50"),
            reference_price=Decimal("3500"),
            simulated_fill_price=Decimal("3503"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="second",
        )

        recent = repository.list_recent_shadow(limit=10)

        assert len(recent) == 2
        # Newest first
        assert recent[0].symbol == "ETHUSDT"
        assert recent[1].symbol == "BTCUSDT"


def test_list_recent_shadow_respects_limit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = ShadowExecutionRepository(session)

        for i in range(5):
            repository.record_shadow_execution(
                symbol=f"SYMBOL{i}USDT",
                side="BUY",
                planned_notional_usdt=Decimal("100"),
                reference_price=Decimal("95000"),
                simulated_fill_price=Decimal("95010"),
                simulated_slippage_bps=Decimal("10"),
                decision_reason=f"record_{i}",
            )

        recent = repository.list_recent_shadow(limit=3)

        assert len(recent) == 3


def test_count_last_hour_counts_only_recent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    now = datetime.now(UTC)

    with session_factory() as session:
        repository = ShadowExecutionRepository(session)

        # Record from 30 minutes ago (should count)
        old_record = repository.record_shadow_execution(
            symbol="OLDUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("100"),
            reference_price=Decimal("95000"),
            simulated_fill_price=Decimal("95010"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="old",
        )
        # Manually backdate the created_at
        session.query(ShadowExecution).filter_by(id=old_record.id).update(
            {"created_at": now - timedelta(minutes=30)}
        )
        session.commit()

        # Record from now (should count)
        repository.record_shadow_execution(
            symbol="NEWUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("100"),
            reference_price=Decimal("95000"),
            simulated_fill_price=Decimal("95010"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="new",
        )

        one_hour_ago = now - timedelta(hours=1)
        count = repository.count_last_hour(one_hour_ago)

        assert count == 2


def test_count_last_hour_excludes_old_records():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    now = datetime.now(UTC)

    with session_factory() as session:
        repository = ShadowExecutionRepository(session)

        # Record from 2 hours ago (should NOT count)
        old_record = repository.record_shadow_execution(
            symbol="ANCIENTUSDT",
            side="BUY",
            planned_notional_usdt=Decimal("100"),
            reference_price=Decimal("95000"),
            simulated_fill_price=Decimal("95010"),
            simulated_slippage_bps=Decimal("10"),
            decision_reason="ancient",
        )
        # Manually backdate the created_at
        stmt = update(ShadowExecution).where(ShadowExecution.id == old_record.id).values(
            created_at=now - timedelta(hours=2)
        )
        session.execute(stmt)
        session.commit()

        one_hour_ago = now - timedelta(hours=1)
        count = repository.count_last_hour(one_hour_ago)

        assert count == 0
