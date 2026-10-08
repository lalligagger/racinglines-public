#!/bin/bash
set -euo pipefail

# HAProxy reverse proxy setup for staging failover
# Run on the VM: bash scripts/deploy/vm/setup-haproxy.sh
# This adds HAProxy with health checks and failover: if staging is down, staging.racinglines.bet routes to prod.

log() { echo "[haproxy setup] $*" >&2; }

if ! command -v haproxy &>/dev/null; then
  log "Installing HAProxy..."
  sudo apt-get update -q && sudo apt-get install -y -qq haproxy
else
  log "HAProxy already installed: $(haproxy -v | head -1)"
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
HAPROXY_CFG_SRC="$REPO_ROOT/deploy/vm/haproxy/racinglines-proxy.cfg"
HAPROXY_CFG_DEST="/etc/racinglines/haproxy.cfg"
SYSTEMD_SRC="$REPO_ROOT/deploy/vm/systemd/racinglines-proxy.service"
SYSTEMD_DEST="/etc/systemd/system/racinglines-proxy.service"

if [ ! -f "$HAPROXY_CFG_SRC" ]; then
  log "ERROR: $HAPROXY_CFG_SRC not found. Run this from the repo root."
  exit 1
fi

log "Copying HAProxy config to $HAPROXY_CFG_DEST..."
sudo install -m 644 "$HAPROXY_CFG_SRC" "$HAPROXY_CFG_DEST"

log "Copying systemd service to $SYSTEMD_DEST..."
sudo install -m 644 "$SYSTEMD_SRC" "$SYSTEMD_DEST"

log "Reloading systemd..."
sudo systemctl daemon-reload

log "Enabling and starting racinglines-proxy..."
sudo systemctl enable racinglines-proxy
sudo systemctl restart racinglines-proxy

sleep 2
if sudo systemctl is-active --quiet racinglines-proxy; then
  log "✓ racinglines-proxy is running"
  log "Backends: prod (8000), staging (8010)"
  log "HAProxy stats: http://127.0.0.1:8404/stats"
  log ""
  log "Next step: Update GCP Load Balancer or Cloudflare to route racinglines.bet and"
  log "staging.racinglines.bet to 127.0.0.1:8080 (HAProxy) instead of direct app ports."
  log "Then HAProxy handles failover automatically."
else
  log "ERROR: racinglines-proxy failed to start"
  sudo systemctl status racinglines-proxy || true
  exit 1
fi
