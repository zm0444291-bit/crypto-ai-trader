.PHONY: help install backend dashboard db-init runtime-once runtime-loop runtime-supervisor runtime-health runtime-tail-events runtime-minimax-smoke runtime-agent-install runtime-agent-start runtime-agent-stop runtime-agent-restart runtime-agent-status runtime-agent-logs runtime-agent-uninstall check lint test

PYTHON=.venv/bin/python
PYTEST=.venv/bin/pytest
RUFF=.venv/bin/ruff
BACKEND_PORT?=8000
DASHBOARD_PORT?=5173
RUNTIME_INTERVAL?=300
RUNTIME_SYMBOLS?=BTCUSDT,ETHUSDT,SOLUSDT
INGEST_INTERVAL?=300
TRADE_INTERVAL?=300
API_BASE=http://127.0.0.1:$(BACKEND_PORT)

help:
	@echo "Crypto AI Trader — Local Paper Trading"
	@echo ""
	@echo "  make install              Install dependencies (.venv + pip install -e .[dev])"
	@echo "  make db-init              Initialize SQLite database"
	@echo "  make backend              Start backend API (uvicorn, port $(BACKEND_PORT))"
	@echo "  make dashboard            Start dashboard dev server (Vite, port $(DASHBOARD_PORT))"
	@echo "  make runtime-once         Run one paper trading cycle and exit"
	@echo "  make runtime-loop         Run paper trading loop continuously"
	@echo "  make runtime-supervisor   Run ingestion + trading loops concurrently (single terminal)"
	@echo "  make check                Run lint and tests"
	@echo "  make lint                 Run ruff linter"
	@echo "  make test                 Run test suite"
	@echo ""
	@echo "Ports: BACKEND_PORT=$(BACKEND_PORT) DASHBOARD_PORT=$(DASHBOARD_PORT)"
	@echo "Symbols: RUNTIME_SYMBOLS=$(RUNTIME_SYMBOLS)"
	@echo "Supervisor: INGEST_INTERVAL=$(INGEST_INTERVAL)s, TRADE_INTERVAL=$(TRADE_INTERVAL)s"

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

runtime-supervisor:
	$(PYTHON) -m trading.runtime.cli --supervisor \
		--ingest-interval $(INGEST_INTERVAL) \
		--trade-interval $(TRADE_INTERVAL) \
		$(if $(RUNTIME_SYMBOLS),--symbols $(RUNTIME_SYMBOLS),) \
		$(if $(MAX_CYCLES),--max-cycles $(MAX_CYCLES),)

runtime-health:
	@echo "=== Health ===" && curl -s $(API_BASE)/health | $(PYTHON) -m json.tool && \
	echo "=== Runtime Status ===" && curl -s $(API_BASE)/runtime/status | $(PYTHON) -m json.tool && \
	echo "=== Risk Status ===" && curl -s "$(API_BASE)/risk/status?day_start_equity=500&current_equity=500" | $(PYTHON) -m json.tool

runtime-tail-events:
	$(PYTHON) -m trading.runtime.event_tail

runtime-minimax-smoke:
	@_AI_SCORING_BACKEND="$$AI_SCORING_BACKEND"; \
	_MINIMAX_API_KEY="$$MINIMAX_API_KEY"; \
	_MINIMAX_BASE_URL="$$MINIMAX_BASE_URL"; \
	_MINIMAX_MODEL="$$MINIMAX_MODEL"; \
	_MINIMAX_TIMEOUT="$$MINIMAX_TIMEOUT"; \
	if [ -f .env ]; then \
		set -a; . ./.env; set +a; \
	fi; \
	if [ -n "$$_AI_SCORING_BACKEND" ]; then export AI_SCORING_BACKEND="$$_AI_SCORING_BACKEND"; fi; \
	if [ -n "$$_MINIMAX_API_KEY" ]; then export MINIMAX_API_KEY="$$_MINIMAX_API_KEY"; fi; \
	if [ -n "$$_MINIMAX_BASE_URL" ]; then export MINIMAX_BASE_URL="$$_MINIMAX_BASE_URL"; fi; \
	if [ -n "$$_MINIMAX_MODEL" ]; then export MINIMAX_MODEL="$$_MINIMAX_MODEL"; fi; \
	if [ -n "$$_MINIMAX_TIMEOUT" ]; then export MINIMAX_TIMEOUT="$$_MINIMAX_TIMEOUT"; fi; \
	$(PYTHON) scripts/minimax_smoke_test.py

runtime-agent-install:
	./scripts/macos_launchd_runtime.sh install

runtime-agent-start:
	./scripts/macos_launchd_runtime.sh start

runtime-agent-stop:
	./scripts/macos_launchd_runtime.sh stop

runtime-agent-restart:
	./scripts/macos_launchd_runtime.sh restart

runtime-agent-status:
	./scripts/macos_launchd_runtime.sh status

runtime-agent-logs:
	./scripts/macos_launchd_runtime.sh logs

runtime-agent-uninstall:
	./scripts/macos_launchd_runtime.sh uninstall

check:
	$(RUFF) check .
	$(PYTEST) -q

lint:
	$(RUFF) check .

test:
	$(PYTEST) -q
