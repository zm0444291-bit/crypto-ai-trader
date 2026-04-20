#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs

# Load local runtime environment when available.
# shellcheck disable=SC1091
if [[ -f ".env" ]]; then
    set -a
    source ".env"
    set +a
fi

INGEST_INTERVAL="${INGEST_INTERVAL:-120}"
TRADE_INTERVAL="${TRADE_INTERVAL:-60}"
RUNTIME_SYMBOLS="${RUNTIME_SYMBOLS:-BTCUSDT,ETHUSDT,SOLUSDT}"
AI_SCORING_BACKEND="${AI_SCORING_BACKEND:-http}"

if [[ ! -x ".venv/bin/python" ]]; then
    echo "Missing .venv/bin/python. Run: make install"
    exit 1
fi

# Ensure DB schema exists before long-running supervisor starts.
.venv/bin/python -c "from trading.storage.db import create_database_engine, init_db; from trading.runtime.config import AppSettings; engine = create_database_engine(AppSettings().database_url); init_db(engine)"

echo "[runtime] backend=${AI_SCORING_BACKEND} symbols=${RUNTIME_SYMBOLS} ingest_interval=${INGEST_INTERVAL}s trade_interval=${TRADE_INTERVAL}s"
if [[ "${AI_SCORING_BACKEND}" == "minimax" ]]; then
    if [[ -z "${MINIMAX_API_KEY:-}" ]]; then
        echo "[runtime] warning: AI_SCORING_BACKEND=minimax but MINIMAX_API_KEY is empty"
    else
        echo "[runtime] minimax_model=${MINIMAX_MODEL:-MiniMax-M2.1} minimax_base_url=${MINIMAX_BASE_URL:-https://api.minimax.io/v1}"
    fi
fi

exec .venv/bin/python -m trading.runtime.cli --supervisor \
    --ingest-interval "$INGEST_INTERVAL" \
    --trade-interval "$TRADE_INTERVAL" \
    --symbols "$RUNTIME_SYMBOLS"
