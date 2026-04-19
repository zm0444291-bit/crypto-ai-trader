# Claude Code Next Task Prompts (Sequential)

Use the prompts below **in order**.  
Each prompt is self-contained and safe for paper-only development.

---

## Prompt 1: Build Paper Trading Cycle Orchestrator

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Implement a single "paper trading cycle orchestrator" that stitches existing modules into one deterministic cycle:
market data -> features -> strategy candidate -> AI score -> pre-trade risk -> position sizing -> paper execution -> persistence -> runtime events.

Read first:
- trading/market_data/binance_client.py
- trading/market_data/candle_service.py
- trading/features/builder.py
- trading/strategies/active/multi_timeframe_momentum.py
- trading/ai/scorer.py
- trading/risk/pre_trade.py
- trading/risk/position_sizing.py
- trading/execution/paper_executor.py
- trading/storage/repositories.py
- tests/integration/test_paper_trade_flow.py

Requirements:
1) Create module: trading/runtime/paper_cycle.py
2) Add models:
   - CycleInput (symbol, now, day_start_equity, account_equity, market_prices, risk snapshot fields)
   - CycleResult (status, candidate_present, ai_decision, risk_state, order_executed, reject_reasons, event_ids)
3) Implement function:
   - run_paper_cycle(input, deps...) -> CycleResult
4) Behavior:
   - If no candidate: return status "no_signal", no execution.
   - AI fail-closed should propagate to reject path.
   - If pre-trade rejects: no execution.
   - If position size rejects: no execution.
   - Execute paper buy only when all checks pass.
   - Persist order/fill via ExecutionRecordsRepository when executed.
   - Record structured events for each major stage via EventsRepository (cycle_started, signal_generated, risk_rejected, order_executed, cycle_finished).
5) Keep dependency injection friendly (accept repository/session/deps params); do not hardcode real external clients in core logic.

Safety:
- No live trading
- No Binance private API
- No API key handling
- No bypass of risk checks

Tests:
- Add unit tests in tests/unit/test_paper_cycle.py
- Cover at least:
  - no signal path
  - risk rejection path
  - successful execution path with persisted order/fill
  - AI fail-closed rejection path

Verification:
- .venv/bin/pytest tests/unit/test_paper_cycle.py -q
- .venv/bin/ruff check trading/runtime/paper_cycle.py tests/unit/test_paper_cycle.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/runtime/paper_cycle.py tests/unit/test_paper_cycle.py docs/claude-tasks/last-result.md
- git commit -m "feat: add paper trading cycle orchestrator"

Completion report:
Write docs/claude-tasks/last-result.md with task, changed files, verification, commit, and safety checklist. Then stop.
```

---

## Prompt 2: Add Runtime Loop Service (Once + Polling)

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Add a runtime service that can execute the paper cycle once or on a fixed interval loop for local operation.

Read first:
- trading/runtime/paper_cycle.py
- trading/runtime/config.py
- trading/main.py
- trading/storage/db.py
- trading/storage/repositories.py

Requirements:
1) Create module: trading/runtime/runner.py
2) Implement:
   - run_once(...) -> CycleResult
   - run_loop(interval_seconds: int, max_cycles: int | None = None, stop_event optional)
3) Add a small CLI entrypoint module:
   - trading/runtime/cli.py
   - supports:
     - python -m trading.runtime.cli --once
     - python -m trading.runtime.cli --interval 60 --max-cycles 5
4) Loop behavior:
   - records start/finish events
   - catches per-cycle exceptions and records error event without crashing the whole loop
   - exits cleanly on KeyboardInterrupt
5) Use existing SQLite setup from AppSettings/create_database_engine/init_db.
6) Default mode remains paper-only. No live execution options.

Safety:
- No live trading mode switch
- No private Binance endpoints
- No API key handling

Tests:
- Add tests/unit/test_runtime_runner.py
- Validate:
  - once mode calls cycle once
  - interval loop runs expected count with max_cycles
  - exception in one cycle records error and continues

Verification:
- .venv/bin/pytest tests/unit/test_runtime_runner.py -q
- .venv/bin/ruff check trading/runtime tests/unit/test_runtime_runner.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/runtime/runner.py trading/runtime/cli.py tests/unit/test_runtime_runner.py docs/claude-tasks/last-result.md
- git commit -m "feat: add local runtime loop service"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 3: Add Runtime Status API For Dashboard

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Expose runtime loop visibility to dashboard with read-only APIs.

Read first:
- trading/dashboard_api/routes_events.py
- trading/main.py
- trading/storage/repositories.py
- trading/runtime/runner.py
- tests/integration/test_events_api.py

Requirements:
1) Create route file: trading/dashboard_api/routes_runtime.py
2) Add endpoint:
   - GET /runtime/status
3) Response should include:
   - last_cycle_status (from latest cycle event context)
   - last_cycle_time
   - last_error_message (if any)
   - cycles_last_hour (count from events)
   - orders_last_hour (count from orders table)
4) Data source:
   - derive from EventsRepository + ExecutionRecordsRepository (read-only)
5) Wire router in trading/main.py
6) Keep endpoint resilient: if data missing, return null/0 defaults (not 500).

Safety:
- Read-only endpoint only
- No trading actions in API

Tests:
- Add tests/integration/test_runtime_status_api.py
- Validate:
  - empty DB returns safe defaults
  - events/orders present produce expected counters and latest status

Verification:
- .venv/bin/pytest tests/integration/test_runtime_status_api.py -q
- .venv/bin/ruff check trading/dashboard_api/routes_runtime.py tests/integration/test_runtime_status_api.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/dashboard_api/routes_runtime.py trading/main.py tests/integration/test_runtime_status_api.py docs/claude-tasks/last-result.md
- git commit -m "feat: add runtime status dashboard API"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 4: Dashboard Polling + Runtime Panel

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Upgrade dashboard from one-time fetch to polling mode and add runtime status panel.

Read first:
- dashboard/src/App.tsx
- dashboard/src/api/client.ts
- dashboard/src/styles.css
- trading/dashboard_api/routes_runtime.py

Requirements:
1) Add API client function:
   - getRuntimeStatus()
2) In App.tsx:
   - fetch all panels on initial load
   - poll every 10 seconds
   - keep per-panel failure tracking (do not regress recent fixes)
   - show "last updated" timestamp
3) Add new Runtime section showing:
   - last cycle status
   - cycles last hour
   - orders last hour
   - last error message (if exists)
4) Keep current read-only safety banner.
5) Preserve partial-failure behavior: failed panels show placeholders, successful panels keep real data.

Safety:
- Frontend-only
- No trading controls or order actions

Verification:
- cd dashboard && npm run build
- cd ..
- .venv/bin/ruff check .
- .venv/bin/pytest -q
- git status --short

Commit:
- git add dashboard/src/App.tsx dashboard/src/api/client.ts dashboard/src/styles.css docs/claude-tasks/last-result.md
- git commit -m "feat: add dashboard polling and runtime panel"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 5: Telegram Notification Adapter (Safe Stub + Optional Real Sender)

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Add a notification abstraction for runtime alerts with safe defaults and optional Telegram sender wiring.

Read first:
- trading/runtime/config.py
- trading/storage/repositories.py
- trading/runtime/runner.py

Requirements:
1) Create package:
   - trading/notifications/__init__.py
   - trading/notifications/base.py
   - trading/notifications/telegram_notifier.py
   - trading/notifications/log_notifier.py
2) Define protocol/interface:
   - notify(level, title, message, context)
3) Provide default LogNotifier (writes events/logs only).
4) Telegram notifier:
   - use env vars TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
   - if missing config, it should no-op safely (no crash)
   - network failures should be caught and recorded as warning events
5) Integrate notifier calls in runtime runner for:
   - cycle error
   - risk global_pause/emergency_stop event
6) Keep behavior paper-only and read-only wrt trading.

Safety:
- No secrets committed
- No hardcoded tokens
- No live trading logic

Tests:
- Add tests/unit/test_notifications.py
- Cover:
  - log notifier path
  - telegram notifier with missing config no-op
  - telegram send failure handled without crash

Verification:
- .venv/bin/pytest tests/unit/test_notifications.py -q
- .venv/bin/ruff check trading/notifications tests/unit/test_notifications.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/notifications trading/runtime/runner.py tests/unit/test_notifications.py docs/claude-tasks/last-result.md
- git commit -m "feat: add notification adapters for runtime alerts"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 6: Local Ops Runbook + One-Command Dev Startup

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Make local operation easy: one command for backend + dashboard + runtime loop, with clear runbook docs.

Read first:
- README.md
- dashboard/README.md
- trading/runtime/cli.py

Requirements:
1) Add scripts to simplify local startup:
   - backend API
   - dashboard dev server
   - runtime loop
2) Preferred options:
   - Use a Makefile or simple shell scripts under scripts/
   - Keep commands explicit and cross-machine safe
3) Update docs:
   - README.md add "Local Paper Trading Quickstart"
   - include:
     - environment setup
     - DB init behavior
     - start order of services
     - health checks
     - known safe defaults (paper only)
4) Add troubleshooting section:
   - CORS issue
   - port conflicts
   - missing telegram config
5) Do not add cloud deployment or live trading instructions in this task.

Safety:
- Documentation and local scripts only
- keep live trading disabled

Verification:
- Run listed startup commands once to ensure they launch (can stop immediately)
- .venv/bin/ruff check .
- .venv/bin/pytest -q
- git status --short

Commit:
- git add README.md dashboard/README.md Makefile scripts docs/claude-tasks/last-result.md
- git commit -m "docs: add local paper trading runbook and startup scripts"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 7: Real AI Scoring Adapter (Still Fail-Closed)

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Replace the runtime NoOp AI scorer path with a real configurable AI scoring adapter while preserving strict fail-closed behavior.

Read first:
- trading/ai/scorer.py
- trading/ai/schemas.py
- trading/runtime/cli.py
- trading/runtime/runner.py
- tests/unit/test_ai_scorer.py

Requirements:
1) Create:
   - trading/ai/http_client.py
2) Implement a production-ready client:
   - class HttpAIScoringClient with method `score(payload) -> dict`
   - configurable via env:
     - AI_SCORING_URL (optional)
     - AI_SCORING_TIMEOUT_SECONDS (default reasonable)
   - when URL is missing, do not crash; return response that causes AIScorer fail-closed behavior
   - catch network/HTTP/JSON errors and surface as exceptions so AIScorer catches and fail-closes
3) Update runtime CLI wiring:
   - remove hardcoded always-allow behavior
   - use AIScorer(HttpAIScoringClient(...))
4) Keep fallback semantics:
   - runtime must continue operating in paper mode even if AI endpoint unavailable
   - candidate should be rejected by fail-closed score when AI request fails
5) Add/extend tests:
   - tests/unit/test_ai_scorer_http_client.py
   - cover missing URL, timeout/HTTP error, invalid payload, and valid response path
6) Update docs minimally:
   - README: add optional AI_SCORING_URL note under local runtime section

Safety:
- No live trading
- No private Binance API
- No secret hardcoding
- Fail-closed must remain default

Verification:
- .venv/bin/pytest tests/unit/test_ai_scorer.py tests/unit/test_ai_scorer_http_client.py -q
- .venv/bin/ruff check trading/ai trading/runtime tests/unit/test_ai_scorer_http_client.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/ai/http_client.py trading/runtime/cli.py README.md tests/unit/test_ai_scorer_http_client.py docs/claude-tasks/last-result.md
- git commit -m "feat: add fail-closed HTTP AI scoring adapter"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```

---

## Prompt 8: Market Data Ingestion Scheduler + Freshness Visibility

```text
You are the implementation worker for /Users/zihanma/Desktop/crypto-ai-trader.

Goal:
Add a local market data ingestion scheduler so runtime has fresh candles without manual preloading, plus visibility on freshness.

Read first:
- trading/market_data/binance_client.py
- trading/storage/repositories.py
- trading/runtime/runner.py
- trading/dashboard_api/routes_market_data.py
- tests/integration/test_market_data_api.py

Requirements:
1) Create:
   - trading/market_data/ingestion_runner.py
2) Implement:
   - `ingest_once(symbols, timeframes, limit)`:
     - fetch klines via BinanceKlineClient (public endpoint only)
     - upsert into CandlesRepository
     - record event with counts and symbols/timeframes
   - `ingest_loop(interval_seconds, max_cycles=None, stop_event=None)`:
     - runs ingest_once on interval
     - records start/stop/error events
3) Integrate with existing runtime ops:
   - add CLI entrypoint options in `trading/runtime/cli.py` OR dedicated simple CLI module for ingestion
   - commands should support one-shot and loop modes
4) Add market-data freshness endpoint improvements:
   - extend `GET /market-data/status` to include latest candle timestamp per symbol/timeframe and `is_fresh` flag
   - resilience: if no candles exist, return safe null/default fields, not 500
5) Add tests:
   - unit test for ingestion runner with mocked client
   - integration test for `/market-data/status` freshness fields

Safety:
- Public Binance API only (`/api/v3/klines`)
- No private endpoints, no API keys
- No trading execution changes

Verification:
- .venv/bin/pytest tests/unit/test_market_data_ingestion_runner.py tests/integration/test_market_data_api.py -q
- .venv/bin/ruff check trading/market_data trading/dashboard_api tests/unit/test_market_data_ingestion_runner.py
- .venv/bin/pytest -q
- .venv/bin/ruff check .
- git status --short

Commit:
- git add trading/market_data/ingestion_runner.py trading/dashboard_api/routes_market_data.py trading/runtime/cli.py tests/unit/test_market_data_ingestion_runner.py tests/integration/test_market_data_api.py docs/claude-tasks/last-result.md
- git commit -m "feat: add market data ingestion scheduler and freshness status"

Completion report:
Write docs/claude-tasks/last-result.md and stop.
```
