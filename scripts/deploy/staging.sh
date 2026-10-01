#!/usr/bin/env bash
# Start or stop a temporary Cloudflare tunnel for a local staging app.
#
#   bash scripts/deploy/staging.sh start [port]
#   bash scripts/deploy/staging.sh smoke [port]
#   bash scripts/deploy/staging.sh stop [port]
#
# This is intentionally a short-lived tunnel: no LaunchAgent, no ~/.cloudflared config, and no
# long-running tunnel left behind on the owner's Mac. The tunnel lives only for the command that
# launches it, and exits when the script does.
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"
SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then SCRIPT_DIR="."; fi
cd "$SCRIPT_DIR/../.."
PORT="${2:-8010}"
APP_URL="http://127.0.0.1:${PORT}"
LOG_FILE="${TMPDIR:-/tmp}/racinglines-staging-cloudflared.log"
PID_FILE="${TMPDIR:-/tmp}/racinglines-staging-cloudflared.pid"

stop_tunnel() {
  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
  pkill -f "cloudflared.*--url.*${APP_URL}" 2>/dev/null || true
  rm -f "$LOG_FILE"
}

start_tunnel() {
  command -v cloudflared >/dev/null 2>&1 || {
    echo "cloudflared is not installed; install it or use the VM staging host instead" >&2
    exit 1
  }
  stop_tunnel
  rm -f "$LOG_FILE"
  nohup cloudflared tunnel --no-autoupdate --url "$APP_URL" >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  timeout=60
  url=""
  for i in $(seq 1 "$timeout"); do
    if grep -Eo 'https://[^[:space:]]+trycloudflare.com' "$LOG_FILE" >/dev/null 2>&1; then
      url="$(grep -Eo 'https://[^[:space:]]+trycloudflare.com' "$LOG_FILE" | tail -1 || true)"
      if [ -n "$url" ] && curl -fsS --max-time 10 "$url" >/dev/null 2>&1; then
        echo "$url"
        return 0
      fi
    fi
    sleep 1
  done

  echo "temp tunnel failed to start for $APP_URL" >&2
  echo "--- log ---" >&2
  tail -n 50 "$LOG_FILE" >&2 || true
  exit 1
}

case "${1:-start}" in
  start)
    start_tunnel
    ;;
  stop)
    stop_tunnel
    echo "staging temp tunnel stopped"
    ;;
  smoke)
    tunnel_url="$(start_tunnel)"
    trap 'stop_tunnel' EXIT
    echo "staging temp tunnel: $tunnel_url"
    bash scripts/deploy/smoke.sh "$tunnel_url"
    ;;
  *)
    echo "usage: bash scripts/deploy/staging.sh [start|smoke|stop] [port]" >&2
    exit 1
    ;;
 esac
