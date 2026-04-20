#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_URL="http://127.0.0.1:8000"
DASHBOARD_URL_LOCALHOST="http://localhost:5173"
DASHBOARD_URL_127="http://127.0.0.1:5173"

open_terminal_command() {
  local cmd="$1"
  osascript - "$cmd" <<'APPLESCRIPT'
on run argv
  set shellCmd to item 1 of argv
  tell application "Terminal"
    activate
    do script shellCmd
  end tell
end run
APPLESCRIPT
}

echo "[dashboard] project: $PROJECT_ROOT"

# Start backend if not already healthy.
if ! curl -fsS --max-time 2 "$BACKEND_URL/health" >/dev/null 2>&1; then
  echo "[dashboard] starting backend on :8000"
  open_terminal_command "cd \"$PROJECT_ROOT\" && make backend"
else
  echo "[dashboard] backend already running"
fi

# Start dashboard dev server if not already running.
if ! curl -fsS --max-time 2 "$DASHBOARD_URL_LOCALHOST" >/dev/null 2>&1 && \
   ! curl -fsS --max-time 2 "$DASHBOARD_URL_127" >/dev/null 2>&1; then
  echo "[dashboard] starting dashboard on :5173"
  open_terminal_command "cd \"$PROJECT_ROOT/dashboard\" && npm run dev"
else
  echo "[dashboard] dashboard already running"
fi

# Wait briefly for dashboard server then open browser.
for _ in {1..30}; do
  if curl -fsS --max-time 2 "$DASHBOARD_URL_LOCALHOST" >/dev/null 2>&1 || \
     curl -fsS --max-time 2 "$DASHBOARD_URL_127" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if curl -fsS --max-time 2 "$DASHBOARD_URL_LOCALHOST" >/dev/null 2>&1; then
  open "$DASHBOARD_URL_LOCALHOST"
  echo "[dashboard] opened $DASHBOARD_URL_LOCALHOST"
else
  open "$DASHBOARD_URL_127"
  echo "[dashboard] opened $DASHBOARD_URL_127"
fi
