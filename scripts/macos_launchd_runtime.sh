#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER_SCRIPT="$PROJECT_ROOT/scripts/run_paper_supervisor.sh"
LOG_DIR="$PROJECT_ROOT/logs"

LABEL="${LABEL:-com.crypto_ai_trader.paper_runtime}"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"
SERVICE="$DOMAIN/$LABEL"

INGEST_INTERVAL="${INGEST_INTERVAL:-120}"
TRADE_INTERVAL="${TRADE_INTERVAL:-60}"
RUNTIME_SYMBOLS="${RUNTIME_SYMBOLS:-BTCUSDT,ETHUSDT,SOLUSDT}"

usage() {
    cat <<EOF
Usage:
  scripts/macos_launchd_runtime.sh install
  scripts/macos_launchd_runtime.sh start
  scripts/macos_launchd_runtime.sh stop
  scripts/macos_launchd_runtime.sh restart
  scripts/macos_launchd_runtime.sh status
  scripts/macos_launchd_runtime.sh logs
  scripts/macos_launchd_runtime.sh uninstall
  scripts/macos_launchd_runtime.sh render

Optional env:
  INGEST_INTERVAL (default: 120)
  TRADE_INTERVAL  (default: 60)
  RUNTIME_SYMBOLS (default: BTCUSDT,ETHUSDT,SOLUSDT)
  LABEL           (default: com.crypto_ai_trader.paper_runtime)
EOF
}

ensure_paths() {
    mkdir -p "$HOME/Library/LaunchAgents"
    mkdir -p "$LOG_DIR"
    if [[ ! -x "$RUNNER_SCRIPT" ]]; then
        echo "Missing executable runner: $RUNNER_SCRIPT"
        exit 1
    fi
}

render_plist() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER_SCRIPT</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>INGEST_INTERVAL</key>
    <string>$INGEST_INTERVAL</string>
    <key>TRADE_INTERVAL</key>
    <string>$TRADE_INTERVAL</string>
    <key>RUNTIME_SYMBOLS</key>
    <string>$RUNTIME_SYMBOLS</string>
  </dict>

  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/runtime-supervisor.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/runtime-supervisor.stderr.log</string>
</dict>
</plist>
EOF
}

install_agent() {
    ensure_paths
    render_plist > "$PLIST_PATH"
    launchctl bootout "$SERVICE" >/dev/null 2>&1 || true
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
    launchctl enable "$SERVICE"
    launchctl kickstart -k "$SERVICE"
    echo "Installed and started: $SERVICE"
    echo "Plist: $PLIST_PATH"
}

start_agent() {
    launchctl enable "$SERVICE"
    launchctl kickstart -k "$SERVICE"
    echo "Started: $SERVICE"
}

stop_agent() {
    launchctl bootout "$SERVICE" >/dev/null 2>&1 || true
    echo "Stopped: $SERVICE"
}

status_agent() {
    echo "== launchctl print =="
    launchctl print "$SERVICE" 2>/dev/null || echo "Service not loaded: $SERVICE"
    echo ""
    echo "== process check =="
    pgrep -fl "trading.runtime.cli --supervisor" || echo "No supervisor process found"
}

logs_agent() {
    mkdir -p "$LOG_DIR"
    echo "stdout: $LOG_DIR/runtime-supervisor.stdout.log"
    echo "stderr: $LOG_DIR/runtime-supervisor.stderr.log"
    tail -n 80 "$LOG_DIR/runtime-supervisor.stdout.log" "$LOG_DIR/runtime-supervisor.stderr.log" 2>/dev/null || true
}

uninstall_agent() {
    launchctl bootout "$SERVICE" >/dev/null 2>&1 || true
    rm -f "$PLIST_PATH"
    echo "Uninstalled: $SERVICE"
}

case "${1:-}" in
    install) install_agent ;;
    start) start_agent ;;
    stop) stop_agent ;;
    restart) stop_agent; install_agent ;;
    status) status_agent ;;
    logs) logs_agent ;;
    uninstall) uninstall_agent ;;
    render) render_plist ;;
    ""|-h|--help|help) usage ;;
    *)
        echo "Unknown command: $1"
        usage
        exit 1
        ;;
esac
