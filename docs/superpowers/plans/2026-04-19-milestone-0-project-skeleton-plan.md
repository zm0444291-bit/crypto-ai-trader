# Milestone 0 Project Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the initial local project skeleton for crypto-ai-trader with configuration files, Python package layout, SQLite bootstrapping, event logging, and smoke tests.

**Architecture:** This milestone creates a minimal Python backend shell only. It does not implement market data, AI scoring, strategy logic, risk decisions, or real exchange execution. The skeleton uses focused modules for config loading, database setup, event persistence, and runtime startup so later milestones can plug into stable boundaries.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic Settings, PyYAML, pytest, SQLite.

---

## Scope

Implement only Milestone 0 from the approved design:

- Project directories
- `.gitignore`
- `.env.example`
- Python package metadata
- YAML config files
- SQLite initialization
- Event model and repository
- Basic runtime startup
- Health endpoint
- Smoke tests

Do not implement:

- Binance API calls
- Strategy logic
- AI calls
- RiskEngine
- PaperExecutor
- Live trading
- Dashboard frontend

## File Structure

Create or modify these files:

```text
.gitignore
.env.example
README.md
pyproject.toml
config/app.yaml
config/risk_profiles.yaml
config/strategies.yaml
config/exchanges.yaml
research/.gitkeep
trading/__init__.py
trading/main.py
trading/runtime/__init__.py
trading/runtime/config.py
trading/runtime/health.py
trading/storage/__init__.py
trading/storage/db.py
trading/storage/models.py
trading/storage/repositories.py
trading/dashboard_api/__init__.py
trading/dashboard_api/routes_health.py
tests/__init__.py
tests/unit/__init__.py
tests/unit/test_config.py
tests/unit/test_events_repository.py
tests/integration/__init__.py
tests/integration/test_app_smoke.py
```

## Task 0.1: Repository Hygiene And Metadata

**Files:**

- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `research/.gitkeep`

- [ ] **Step 1: Create `.gitignore`**

Create `.gitignore` with exactly this content:

```gitignore
# macOS
.DS_Store

# Python
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/
venv/

# Environment and secrets
.env
.env.*
!.env.example

# Runtime artifacts
data/
logs/
*.sqlite
*.sqlite3
*.db

# Frontend
node_modules/
dist/
build/

# Superpowers visual companion
.superpowers/
```

- [ ] **Step 2: Create `.env.example`**

Create `.env.example` with exactly this content:

```dotenv
APP_ENV=local
APP_NAME=crypto-ai-trader
DATABASE_URL=sqlite:///./data/crypto_ai_trader.sqlite3
CONFIG_DIR=./config
LOG_LEVEL=INFO

# Do not put real keys in this file.
BINANCE_API_KEY=
BINANCE_API_SECRET=
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 3: Create `README.md`**

Create `README.md` with exactly this content:

```markdown
# Crypto AI Trader

Local-first AI-assisted cryptocurrency quantitative trading system.

The first implementation target is automatic paper trading for Binance spot with:

- Medium-frequency 15m/1h signals
- 4h trend context
- AI scoring for rule-generated candidates
- Dynamic risk profiles
- SQLite storage
- Local dashboard API
- Telegram notifications in a later milestone

## Safety

The default mode is paper trading.

Live trading must remain locked until the approved live unlock milestones are implemented and reviewed.

## First Local Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn trading.main:app --reload
```
```

- [ ] **Step 4: Create `pyproject.toml`**

Create `pyproject.toml` with exactly this content:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "crypto-ai-trader"
version = "0.1.0"
description = "Local-first AI-assisted crypto trading system"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "pydantic>=2.8.0",
  "pydantic-settings>=2.4.0",
  "PyYAML>=6.0.2",
  "SQLAlchemy>=2.0.32",
  "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "pytest-cov>=5.0.0",
  "ruff>=0.6.0",
]

[tool.setuptools.packages.find]
include = ["trading*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 5: Create `research/.gitkeep`**

Create an empty file at `research/.gitkeep`.

- [ ] **Step 6: Verify repository hygiene files**

Run:

```bash
git status --short
```

Expected:

```text
?? .env.example
?? .gitignore
?? README.md
?? pyproject.toml
?? research/
```

Other untracked documentation files from this plan are acceptable if this task is run after the plan is committed.

- [ ] **Step 7: Commit Task 0.1**

Run:

```bash
git add .gitignore .env.example README.md pyproject.toml research/.gitkeep
git commit -m "chore: add project metadata"
```

Expected: commit succeeds.

## Task 0.2: Configuration Files And Loader

**Files:**

- Create: `config/app.yaml`
- Create: `config/risk_profiles.yaml`
- Create: `config/strategies.yaml`
- Create: `config/exchanges.yaml`
- Create: `trading/__init__.py`
- Create: `trading/runtime/__init__.py`
- Create: `trading/runtime/config.py`
- Test: `tests/__init__.py`
- Test: `tests/unit/__init__.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/__init__.py` as an empty file.

Create `tests/unit/__init__.py` as an empty file.

Create `tests/unit/test_config.py` with exactly this content:

```python
from pathlib import Path

from trading.runtime.config import AppSettings, load_yaml_config


def test_app_settings_defaults_to_local_config_dir():
    settings = AppSettings()

    assert settings.app_name == "crypto-ai-trader"
    assert settings.app_env == "local"
    assert settings.config_dir == Path("config")


def test_load_yaml_config_reads_mapping(tmp_path):
    config_file = tmp_path / "sample.yaml"
    config_file.write_text("trade_mode: paper_auto\nsymbols:\n  - BTCUSDT\n", encoding="utf-8")

    loaded = load_yaml_config(config_file)

    assert loaded == {"trade_mode": "paper_auto", "symbols": ["BTCUSDT"]}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_config.py -v
```

Expected: FAIL because `trading.runtime.config` does not exist.

- [ ] **Step 3: Create YAML config files**

Create `config/app.yaml`:

```yaml
app:
  name: crypto-ai-trader
  default_trade_mode: paper_auto
  live_trading_enabled: false
  live_capital_cap_usdt: 500
  require_manual_unlock: true

runtime:
  loop_interval_seconds: 60
  timezone: Australia/Sydney

storage:
  database_url: sqlite:///./data/crypto_ai_trader.sqlite3

symbols:
  enabled:
    - BTCUSDT
    - ETHUSDT
    - SOLUSDT

timeframes:
  signal:
    - 15m
    - 1h
  context:
    - 4h
```

Create `config/risk_profiles.yaml`:

```yaml
risk_profiles:
  small_balanced:
    equity_min_usdt: 0
    equity_max_usdt: 1000
    daily_loss_caution_pct: 5
    daily_loss_no_new_positions_pct: 7
    daily_loss_global_pause_pct: 10
    max_trade_risk_pct: 1.5
    max_trade_risk_hard_cap_pct: 2.0
    max_symbol_position_pct: 30
    max_total_position_pct: 70
  medium_conservative:
    equity_min_usdt: 1000
    equity_max_usdt: 10000
    daily_loss_caution_pct: 3
    daily_loss_no_new_positions_pct: 5
    daily_loss_global_pause_pct: 7
    max_trade_risk_pct: 1.0
    max_trade_risk_hard_cap_pct: 1.5
    max_symbol_position_pct: 25
    max_total_position_pct: 60
  large_conservative:
    equity_min_usdt: 10000
    equity_max_usdt: null
    daily_loss_caution_pct: 2
    daily_loss_no_new_positions_pct: 4
    daily_loss_global_pause_pct: 5
    max_trade_risk_pct: 0.5
    max_trade_risk_hard_cap_pct: 1.0
    max_symbol_position_pct: 20
    max_total_position_pct: 50

policy:
  auto_tighten_risk: true
  auto_loosen_risk: false
```

Create `config/strategies.yaml`:

```yaml
strategies:
  active:
    multi_timeframe_momentum:
      enabled: true
      mode: paper_auto
      symbols:
        - BTCUSDT
        - ETHUSDT
        - SOLUSDT
  templates:
    futures_momentum:
      enabled: false
      reason: Requires derivatives risk model and funding data.
    orderbook_imbalance:
      enabled: false
      reason: Requires websocket order book and latency controls.
    cross_exchange_arbitrage:
      enabled: false
      reason: Requires multiple exchange accounts and transfer risk checks.
    news_sentiment:
      enabled: false
      reason: Requires reliable news and social data source validation.
    onchain_flow:
      enabled: false
      reason: Requires an on-chain data provider.
    ml_signal:
      enabled: false
      reason: Requires validated training pipeline and model monitoring.
```

Create `config/exchanges.yaml`:

```yaml
exchanges:
  binance:
    enabled: true
    default_market_type: spot
    live_trading_enabled: false
    allowed_symbols:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT
    disabled_products:
      - futures
      - margin
```

- [ ] **Step 4: Create config loader**

Create `trading/__init__.py`:

```python
"""Crypto AI Trader package."""
```

Create `trading/runtime/__init__.py`:

```python
"""Runtime utilities for Crypto AI Trader."""
```

Create `trading/runtime/config.py`:

```python
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Environment-backed runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="crypto-ai-trader", alias="APP_NAME")
    database_url: str = Field(
        default="sqlite:///./data/crypto_ai_trader.sqlite3",
        alias="DATABASE_URL",
    )
    config_dir: Path = Field(default=Path("config"), alias="CONFIG_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML config file and return a mapping."""

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in YAML config: {path}")

    return loaded
```

- [ ] **Step 5: Run config tests**

Run:

```bash
pytest tests/unit/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 0.2**

Run:

```bash
git add config trading tests/unit/test_config.py tests/__init__.py tests/unit/__init__.py
git commit -m "feat: add runtime config loader"
```

Expected: commit succeeds.

## Task 0.3: SQLite Database And Event Repository

**Files:**

- Create: `trading/storage/__init__.py`
- Create: `trading/storage/db.py`
- Create: `trading/storage/models.py`
- Create: `trading/storage/repositories.py`
- Test: `tests/unit/test_events_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/unit/test_events_repository.py` with exactly this content:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trading.storage.db import Base
from trading.storage.repositories import EventsRepository


def test_events_repository_records_event():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = EventsRepository(session)
        event = repository.record_event(
            event_type="system_started",
            severity="info",
            component="runtime",
            message="Runtime started",
            context={"trade_mode": "paper_auto"},
        )

        assert event.id is not None
        assert event.event_type == "system_started"
        assert event.severity == "info"
        assert event.context_json == {"trade_mode": "paper_auto"}


def test_events_repository_lists_recent_events_newest_first():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        repository = EventsRepository(session)
        repository.record_event("first", "info", "test", "First event", {})
        repository.record_event("second", "warning", "test", "Second event", {})

        events = repository.list_recent(limit=2)

        assert [event.event_type for event in events] == ["second", "first"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_events_repository.py -v
```

Expected: FAIL because storage modules do not exist.

- [ ] **Step 3: Create database module**

Create `trading/storage/__init__.py`:

```python
"""Storage layer for Crypto AI Trader."""
```

Create `trading/storage/db.py`:

```python
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def sqlite_path_from_url(database_url: str) -> Path | None:
    """Return a local SQLite path for file-backed SQLite URLs."""

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None

    raw_path = database_url.removeprefix(prefix)
    if raw_path == ":memory:":
        return None

    return Path(raw_path)


def create_database_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine and ensure SQLite parent directories exist."""

    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(engine: Engine) -> None:
    """Create database tables."""

    Base.metadata.create_all(engine)


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional session scope."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Create event model**

Create `trading/storage/models.py`:

```python
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from trading.storage.db import Base


class Event(Base):
    """Structured runtime event for audit and dashboard display."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
```

- [ ] **Step 5: Create event repository**

Create `trading/storage/repositories.py`:

```python
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from trading.storage.models import Event


class EventsRepository:
    """Persistence helper for runtime events."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_type=event_type,
            severity=severity,
            component=component,
            message=message,
            context_json=context or {},
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def list_recent(self, limit: int = 50) -> list[Event]:
        statement = select(Event).order_by(desc(Event.id)).limit(limit)
        return list(self.session.scalars(statement))
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
pytest tests/unit/test_events_repository.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 0.3**

Run:

```bash
git add trading/storage tests/unit/test_events_repository.py
git commit -m "feat: add event storage"
```

Expected: commit succeeds.

## Task 0.4: FastAPI App And Health Endpoint

**Files:**

- Create: `trading/dashboard_api/__init__.py`
- Create: `trading/runtime/health.py`
- Create: `trading/dashboard_api/routes_health.py`
- Create: `trading/main.py`
- Test: `tests/integration/__init__.py`
- Test: `tests/integration/test_app_smoke.py`

- [ ] **Step 1: Write failing app smoke test**

Create `tests/integration/__init__.py` as an empty file.

Create `tests/integration/test_app_smoke.py` with exactly this content:

```python
from fastapi.testclient import TestClient

from trading.main import app


def test_health_endpoint_returns_runtime_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["trade_mode"] == "paper_auto"
    assert response.json()["live_trading_enabled"] is False
```

- [ ] **Step 2: Run smoke test to verify failure**

Run:

```bash
pytest tests/integration/test_app_smoke.py -v
```

Expected: FAIL because `trading.main` does not exist.

- [ ] **Step 3: Create health service**

Create `trading/runtime/health.py`:

```python
from pydantic import BaseModel


class HealthStatus(BaseModel):
    """API response for runtime health."""

    status: str
    app_name: str
    trade_mode: str
    live_trading_enabled: bool


def get_health_status() -> HealthStatus:
    """Return static Milestone 0 health state."""

    return HealthStatus(
        status="ok",
        app_name="crypto-ai-trader",
        trade_mode="paper_auto",
        live_trading_enabled=False,
    )
```

- [ ] **Step 4: Create health route**

Create `trading/dashboard_api/__init__.py`:

```python
"""Dashboard API routes."""
```

Create `trading/dashboard_api/routes_health.py`:

```python
from fastapi import APIRouter

from trading.runtime.health import HealthStatus, get_health_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
def read_health() -> HealthStatus:
    """Return runtime health for smoke checks and dashboard boot."""

    return get_health_status()
```

- [ ] **Step 5: Create FastAPI app**

Create `trading/main.py`:

```python
from fastapi import FastAPI

from trading.dashboard_api.routes_health import router as health_router

app = FastAPI(title="Crypto AI Trader")
app.include_router(health_router)
```

- [ ] **Step 6: Run app smoke test**

Run:

```bash
pytest tests/integration/test_app_smoke.py -v
```

Expected: PASS.

- [ ] **Step 7: Run all tests**

Run:

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit Task 0.4**

Run:

```bash
git add trading/runtime/health.py trading/dashboard_api trading/main.py tests/integration
git commit -m "feat: add health API"
```

Expected: commit succeeds.

## Task 0.5: Runtime Startup Event

**Files:**

- Modify: `trading/main.py`
- Test: `tests/integration/test_app_smoke.py`

- [ ] **Step 1: Extend smoke test for startup event helper**

Replace `tests/integration/test_app_smoke.py` with exactly this content:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from trading.main import app, record_startup_event
from trading.storage.db import Base
from trading.storage.models import Event


def test_health_endpoint_returns_runtime_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["trade_mode"] == "paper_auto"
    assert response.json()["live_trading_enabled"] is False


def test_record_startup_event_writes_system_started():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    record_startup_event(session_factory)

    with session_factory() as session:
        event = session.scalars(select(Event)).one()

    assert event.event_type == "system_started"
    assert event.severity == "info"
    assert event.component == "runtime"
    assert event.context_json == {"trade_mode": "paper_auto"}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/integration/test_app_smoke.py::test_record_startup_event_writes_system_started -v
```

Expected: FAIL because `record_startup_event` does not exist.

- [ ] **Step 3: Add startup event helper**

Replace `trading/main.py` with exactly this content:

```python
from collections.abc import Callable

from fastapi import FastAPI
from sqlalchemy.orm import Session

from trading.dashboard_api.routes_health import router as health_router
from trading.storage.repositories import EventsRepository

app = FastAPI(title="Crypto AI Trader")
app.include_router(health_router)


def record_startup_event(session_factory: Callable[[], Session]) -> None:
    """Record a startup event using the provided session factory."""

    with session_factory() as session:
        EventsRepository(session).record_event(
            event_type="system_started",
            severity="info",
            component="runtime",
            message="Crypto AI Trader runtime started",
            context={"trade_mode": "paper_auto"},
        )
```

- [ ] **Step 4: Run full test suite**

Run:

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 0.5**

Run:

```bash
git add trading/main.py tests/integration/test_app_smoke.py
git commit -m "feat: record startup event"
```

Expected: commit succeeds.

## Task 0.6: Final Milestone 0 Verification

**Files:**

- No new files expected.

- [ ] **Step 1: Run formatter/linter check**

Run:

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 2: Run test suite**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 3: Run git status**

Run:

```bash
git status --short
```

Expected:

```text
```

If only ignored `.DS_Store`, `.pytest_cache`, `.venv`, `data`, or `logs` artifacts exist, they must not appear in `git status --short`.

- [ ] **Step 4: Worker completion report**

Report:

```text
Milestone 0 complete.

Files created/changed:
- [list files]

Verification:
- ruff check .: PASS
- pytest -v: PASS

Commits:
- [list commit hashes and messages]

Notes:
- No live trading code implemented.
- No real secrets created or committed.
```

## Self-Review Checklist

- The plan implements only Milestone 0.
- No live trading behavior is included.
- No API keys or secrets are included.
- Every task has explicit file paths.
- Every code step includes complete file content.
- Every task has verification commands and expected outcomes.
- Each task ends with a commit.

