from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trading.market_data.schemas import CandleData
from trading.storage.db import Base
from trading.storage.repositories import CandlesRepository


def make_candle(symbol: str = "BTCUSDT", minutes: int = 0, close: str = "101") -> CandleData:
    open_time = datetime(2026, 4, 19, 0, minutes, tzinfo=UTC)
    return CandleData(
        symbol=symbol,
        timeframe="15m",
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("12.5"),
        source="binance",
    )


def test_candles_repository_upserts_by_symbol_timeframe_open_time():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = CandlesRepository(session)
        assert repository.upsert_many([make_candle(close="101")]) == 1
        assert repository.upsert_many([make_candle(close="105")]) == 1

        candles = repository.list_recent("BTCUSDT", "15m", limit=10)

        assert len(candles) == 1
        assert candles[0].close == Decimal("105.0000000000")


def test_candles_repository_lists_recent_oldest_to_newest():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = CandlesRepository(session)
        repository.upsert_many([make_candle(minutes=0), make_candle(minutes=15)])

        candles = repository.list_recent("BTCUSDT", "15m", limit=2)

        assert [candle.open_time.minute for candle in candles] == [0, 15]
        assert repository.get_latest("BTCUSDT", "15m").open_time.minute == 15