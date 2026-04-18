# Milestone 1 Market Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Binance public candle ingestion, candle persistence, data quality checks, and a dashboard API for market-data status.

**Architecture:** This milestone is still read-only market infrastructure. It stores public OHLCV candles in SQLite, validates freshness/gaps/duplicates, and exposes status through FastAPI. It does not implement strategies, AI scoring, risk decisions, order execution, private Binance API calls, or live trading.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic, httpx, pytest, SQLite.

---

## Scope

Implement only Milestone 1:

- Candle SQLAlchemy model
- Candle repository
- Binance public REST kline client
- Market-data service
- Data quality checks
- Dashboard API for market data status
- Unit and integration tests

Do not implement:

- Binance private endpoints
- API key usage
- Strategies
- AI scoring
- RiskEngine
- PaperExecutor
- Any live trading behavior

## Parallel Agent Boundaries

Claude Code may use multiple agents in parallel, but file ownership must stay disjoint.

Agent A: Storage

- Owns `trading/storage/models.py`
- Owns `trading/storage/repositories.py`
- Owns `tests/unit/test_candles_repository.py`

Agent B: Binance Client

- Owns `trading/market_data/__init__.py`
- Owns `trading/market_data/schemas.py`
- Owns `trading/market_data/binance_client.py`
- Owns `tests/unit/test_binance_client.py`

Agent C: Data Quality

- Owns `trading/market_data/data_quality.py`
- Owns `tests/unit/test_data_quality.py`

Agent D: Service And API

- Owns `trading/market_data/candle_service.py`
- Owns `trading/dashboard_api/routes_market_data.py`
- Modifies `trading/main.py`
- Owns `tests/integration/test_market_data_api.py`

Shared files:

- `trading/storage/models.py` and `trading/storage/repositories.py` must be integrated by one final pass after agents finish.
- `trading/main.py` must only include the market data router. It must not start a scheduler or background trading loop.

## Data Contract

Use this Pydantic model in `trading/market_data/schemas.py`:

```python
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CandleData(BaseModel):
    """Normalized OHLCV candle from an exchange."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    source: str = "binance"
```

## Database Contract

Add a `Candle` model to `trading/storage/models.py` without removing `Event`.

Required columns:

```text
id integer primary key
symbol string indexed
timeframe string indexed
open_time datetime indexed
close_time datetime indexed
open numeric
high numeric
low numeric
close numeric
volume numeric
source string
received_at datetime
```

Required uniqueness:

```text
unique(symbol, timeframe, open_time)
```

Use `Decimal`-friendly SQLAlchemy `Numeric(28, 10)` columns.

## Task 1.1: Candle Storage

**Files:**

- Modify: `trading/storage/models.py`
- Modify: `trading/storage/repositories.py`
- Create: `tests/unit/test_candles_repository.py`

Steps:

- [ ] Add failing tests for candle upsert and recent listing.
- [ ] Implement `Candle` model.
- [ ] Implement `CandlesRepository`.
- [ ] Run `pytest tests/unit/test_candles_repository.py -v`.
- [ ] Run `pytest tests/unit/test_events_repository.py -v`.
- [ ] Commit with `feat: add candle storage`.

Required repository API:

```python
class CandlesRepository:
    def __init__(self, session: Session) -> None: ...

    def upsert_many(self, candles: list[CandleData]) -> int:
        """Insert or update candles by symbol/timeframe/open_time. Return affected count."""

    def list_recent(self, symbol: str, timeframe: str, limit: int = 100) -> list[Candle]:
        """Return recent candles ordered oldest to newest."""

    def get_latest(self, symbol: str, timeframe: str) -> Candle | None:
        """Return the newest candle for a symbol/timeframe."""
```

Required tests:

```python
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
```

## Task 1.2: Binance Public Candle Client

**Files:**

- Create: `trading/market_data/__init__.py`
- Create: `trading/market_data/schemas.py`
- Create: `trading/market_data/binance_client.py`
- Create: `tests/unit/test_binance_client.py`

Steps:

- [ ] Add failing tests using `httpx.MockTransport`.
- [ ] Implement `CandleData`.
- [ ] Implement `BinanceKlineClient`.
- [ ] Run `pytest tests/unit/test_binance_client.py -v`.
- [ ] Commit with `feat: add Binance kline client`.

Required client API:

```python
class BinanceKlineClient:
    def __init__(self, base_url: str = "https://api.binance.com", client: httpx.Client | None = None) -> None: ...

    def fetch_klines(self, symbol: str, interval: str, limit: int = 100) -> list[CandleData]:
        """Fetch public spot klines from Binance and return normalized candles."""
```

Required behavior:

- Call `/api/v3/klines`.
- Use params `symbol`, `interval`, `limit`.
- Do not use API keys.
- Convert millisecond timestamps to timezone-aware UTC datetimes.
- Convert OHLCV strings to `Decimal`.
- Raise `httpx.HTTPStatusError` for non-2xx responses.

Required tests:

```python
from decimal import Decimal

import httpx

from trading.market_data.binance_client import BinanceKlineClient


def test_fetch_klines_normalizes_binance_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["interval"] == "15m"
        assert request.url.params["limit"] == "2"
        return httpx.Response(
            200,
            json=[
                [
                    1776532800000,
                    "100.0",
                    "110.0",
                    "90.0",
                    "105.0",
                    "12.5",
                    1776533699999,
                    "0",
                    1,
                    "0",
                    "0",
                    "0",
                ]
            ],
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
    client = BinanceKlineClient(client=http_client)

    candles = client.fetch_klines("BTCUSDT", "15m", limit=2)

    assert len(candles) == 1
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].timeframe == "15m"
    assert candles[0].open == Decimal("100.0")
    assert candles[0].close == Decimal("105.0")
    assert candles[0].open_time.tzinfo is not None


def test_fetch_klines_raises_for_http_error():
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"msg": "bad"})),
        base_url="https://api.binance.com",
    )
    client = BinanceKlineClient(client=http_client)

    try:
        client.fetch_klines("BTCUSDT", "15m")
    except httpx.HTTPStatusError:
        assert True
    else:
        raise AssertionError("Expected HTTPStatusError")
```

## Task 1.3: Data Quality Checks

**Files:**

- Create: `trading/market_data/data_quality.py`
- Create: `tests/unit/test_data_quality.py`

Steps:

- [ ] Add failing data quality tests.
- [ ] Implement quality result and checker.
- [ ] Run `pytest tests/unit/test_data_quality.py -v`.
- [ ] Commit with `feat: add market data quality checks`.

Required API:

```python
from datetime import datetime
from pydantic import BaseModel


class DataQualityIssue(BaseModel):
    severity: str
    code: str
    message: str


class DataQualityReport(BaseModel):
    symbol: str
    timeframe: str
    ok: bool
    issues: list[DataQualityIssue]


def expected_interval_seconds(timeframe: str) -> int: ...


def check_candle_quality(candles: list[CandleData], now: datetime) -> DataQualityReport: ...
```

Required checks:

- Empty candle list: `ok=False`, issue code `empty`.
- Duplicate open_time: issue code `duplicate`.
- Gap larger than expected interval: issue code `gap`.
- Latest closed candle too old: issue code `stale`.
- Zero or negative price: Pydantic should reject through `CandleData`.

Required tests:

- Good 15m candles return `ok=True`.
- Missing interval returns `gap`.
- Duplicate open_time returns `duplicate`.
- Latest candle older than 2 intervals returns `stale`.
- Empty list returns `empty`.

## Task 1.4: Market Data Service And API

**Files:**

- Create: `trading/market_data/candle_service.py`
- Create: `trading/dashboard_api/routes_market_data.py`
- Modify: `trading/main.py`
- Create: `tests/integration/test_market_data_api.py`

Steps:

- [ ] Add failing API integration tests.
- [ ] Implement service DTOs.
- [ ] Implement `/market-data/status`.
- [ ] Include router in `trading/main.py`.
- [ ] Run `pytest tests/integration/test_market_data_api.py -v`.
- [ ] Run `pytest -v`.
- [ ] Commit with `feat: add market data status API`.

Required endpoint:

```text
GET /market-data/status
```

Required response:

```json
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
  "timeframes": ["15m", "1h", "4h"],
  "status": "configured",
  "live_trading_enabled": false
}
```

This endpoint should read static configuration for now. It must not call Binance during the request.

Required tests:

```python
from fastapi.testclient import TestClient

from trading.main import app


def test_market_data_status_returns_configured_symbols_and_timeframes():
    client = TestClient(app)

    response = client.get("/market-data/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "configured"
    assert body["live_trading_enabled"] is False
    assert body["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert body["timeframes"] == ["15m", "1h", "4h"]
```

## Final Verification

Run:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -v
git status --short
```

Expected:

- Ruff passes.
- Pytest passes.
- Worktree is clean after commits.

## Worker Completion Report

Report:

```text
Milestone 1 complete.

Agents used:
- [agent names and responsibilities]

Files created/changed:
- [list files]

Verification:
- .venv/bin/ruff check .: PASS
- .venv/bin/pytest -v: PASS

Commits:
- [list commit hashes and messages]

Safety:
- No private Binance API endpoints implemented.
- No API keys used.
- No strategy, risk, execution, or live trading behavior implemented.
```

## Self-Review Checklist

- The plan implements only Milestone 1.
- No live trading behavior is included.
- No private API key usage is included.
- Agent file ownership is explicit.
- Tests cover storage, client parsing, quality checks, and API status.
- Final verification includes lint and all tests.

