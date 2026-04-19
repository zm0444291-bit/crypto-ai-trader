.PHONY: help install backend dashboard db-init runtime-once runtime-loop check lint test

PYTHON=.venv/bin/python
PYTEST=.venv/bin/pytest
RUFF=.venv/bin/ruff
BACKEND_PORT?=8000
DASHBOARD_PORT?=5173
RUNTIME_INTERVAL?=300
RUNTIME_SYMBOLS?=BTCUSDT,ETHUSDT,SOLUSDT

help:
	@echo "Crypto AI Trader — Local Paper Trading"
	@echo ""
	@echo "  make install          Install dependencies (.venv + pip install -e .[dev])"
	@echo "  make db-init          Initialize SQLite database"
	@echo "  make backend          Start backend API (uvicorn, port $(BACKEND_PORT))"
	@echo "  make dashboard        Start dashboard dev server (Vite, port $(DASHBOARD_PORT))"
	@echo "  make runtime-once     Run one paper trading cycle and exit"
	@echo "  make runtime-loop     Run paper trading loop continuously"
	@echo "  make check            Run lint and tests"
	@echo "  make lint             Run ruff linter"
	@echo "  make test             Run test suite"
	@echo ""
	@echo "Ports: BACKEND_PORT=$(BACKEND_PORT) DASHBOARD_PORT=$(DASHBOARD_PORT)"
	@echo "Symbols: RUNTIME_SYMBOLS=$(RUNTIME_SYMBOLS)"

install:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -e ".[dev]"

db-init:
	$(PYTHON) -c "from trading.storage.db import create_database_engine, init_db; from trading.runtime.config import AppSettings; engine = create_database_engine(AppSettings().database_url); init_db(engine); print('Database initialized.')"

backend:
	$(PYTHON) -m uvicorn trading.main:app --host 127.0.0.1 --port $(BACKEND_PORT) --reload

dashboard:
	cd dashboard && npm run dev

runtime-once:
	$(PYTHON) -m trading.runtime.cli --once $(if $(RUNTIME_SYMBOLS),--symbols $(RUNTIME_SYMBOLS),)

runtime-loop:
	$(PYTHON) -m trading.runtime.cli --interval $(RUNTIME_INTERVAL) $(if $(RUNTIME_SYMBOLS),--symbols $(RUNTIME_SYMBOLS),)

check:
	$(RUFF) check .
	$(PYTEST) -q

lint:
	$(RUFF) check .

test:
	$(PYTEST) -q
