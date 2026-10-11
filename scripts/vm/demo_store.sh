#!/usr/bin/env bash
# The hosted demo store (docs/demo.md, "The hosted demo store"): a data pack (default kart, synthetic) built into its own
# database next to production's, and a second MCP server over it, so `racinglines ... --demo --remote` runs the
# quickstart's hosted commands (book map|price|settle, model backtest|forecast) with no local database.
# Written for the owner; nothing has run it yet. Two steps, each its own command:
#
#   1. build (as the app user, a transient unit; a few minutes):
#        sudo systemd-run --unit=rl-demo-store --uid=racinglines /opt/racinglines/scripts/vm/demo_store.sh build
#      Backup of production first (checked), then `racinglines db stats --demo PACK`, which builds the store as on any
#      machine: creates racinglines_demo_<pack> on the same Postgres (the name must contain "demo"; production's
#      database is never written), Alembic upgrade head and the seed on it, the pack's synthetic files under
#      data/demo/<pack>/, the real ingest, forecast and link imports, a data_changes row in the demo database.
#   2. serve (root; starts or restarts the demo MCP server as a transient unit on 127.0.0.1:8766):
#        sudo /opt/racinglines/scripts/vm/demo_store.sh serve
#      Then, once, in Cloudflare: tunnel racinglines-vm > Public hostnames > Add: subdomain mcp-demo, domain
#      racinglines.bet, type HTTP, URL localhost:8766 (the pack's [remote] mcp_url). Check from anywhere:
#        curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp-demo.racinglines.bet/mcp     # 401: up
#
# What the demo server reads: the demo database and data/demo/<pack> only (--demo). Accounts, rl_ tokens and OAuth
# sign-ins come from production's database (RACINGLINES_MCP_ACCOUNTS_URL = production's DATABASE_URL), so the same Pro
# and admin accounts sign in; jobs are filed with no owner on this shared store. The sql tool's read-only production
# role (RACINGLINES_MCP_SQL_URL) is unset for this server, so sql reads the demo database. No real exchange data, no
# `data pull`, no trading flag, no migration of production's database, no timer.
#
# Known risk (Core review, 2026-10-11): this server holds production's full app DATABASE_URL on a public hostname,
# only to read accounts and write tokens and OAuth sign-ins. Before serving real users, give it a login limited to
# users and the token/OAuth tables (like scripts/vm/mcp_sql_role.sh does for sql) as RACINGLINES_MCP_ACCOUNTS_URL.
#
# Not on deploys: `vm.sh deploy` restarts the listed services only; rerun `demo_store.sh serve` after a deploy to pick
# up new code, and `build` when the pack changed (a build on an up-to-date store does nothing). A transient unit does
# not survive a reboot: rerun `serve`. Stop: `sudo systemctl stop racinglines-mcp-demo`. Remove the store:
# `sudo systemctl stop racinglines-mcp-demo`, then DROP DATABASE racinglines_demo_<pack> and rm -r data/demo/<pack>.
#
# Log: data/runs/logs/demo-store-<UTC>.log; markers demo-store.done / .failed. A progress line every HEARTBEAT_MIN=5.
set -eEuo pipefail
STEP=${1:-build}
PACK=${PACK:-kart}
PORT=${PORT:-8766}
PUBLIC_URL=${PUBLIC_URL:-https://mcp-demo.racinglines.bet/mcp}
APP=/opt/racinglines
ENV_FILE=/etc/racinglines.env
HEARTBEAT_MIN=${HEARTBEAT_MIN:-5}
case "$PACK" in ""|*[!a-z0-9_-]*) echo "PACK: lowercase letters, digits, _ and - only"; exit 2 ;; esac
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1
cd "$APP"
R=$APP/.venv/bin/racinglines

case "$STEP" in
  build)
    [ "$(id -un)" = racinglines ] || { echo "build runs as the app user (systemd-run --uid=racinglines)"; exit 2; }
    LOGS=data/runs/logs
    mkdir -p "$LOGS" data/backups/db
    UTC=$(date -u +%Y%m%dT%H%M%SZ)
    LOG=$LOGS/demo-store-$UTC.log
    DONE=$LOGS/demo-store.done
    FAILED=$LOGS/demo-store.failed
    rm -f "$DONE" "$FAILED"
    exec > >(tee -a "$LOG") 2>&1
    trap 'echo "DEMO-STORE FAILED at line $LINENO (log $LOG)"; date -u > "$FAILED"' ERR
    if systemctl list-units --no-legend --plain --state=active,activating 'racinglines-live-*' | grep -q .; then
      echo "not starting: a live-event unit is active"; date -u > "$FAILED"; exit 1
    fi
    START=$(date +%s)
    ( while sleep $((HEARTBEAT_MIN * 60)); do
        echo "progress demo-store: $(( ($(date +%s) - START) / 60 )) min elapsed · building the $PACK store"; done ) &
    BEAT=$!
    trap 'kill $BEAT 2>/dev/null || true' EXIT
    B=data/backups/db/racinglines-before-demo-store-$UTC.sql.gz
    docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B"
    gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'
    echo "backup $B ($(du -h "$B" | cut -f1)): production's database, before the demo store (which never writes it)"
    echo "== build the $PACK store (racinglines_demo_$PACK, data/demo/$PACK)"
    nice "$R" db stats --demo "$PACK"
    echo "DEMO-STORE DONE (log $LOG, backup $B); next: sudo $APP/scripts/vm/demo_store.sh serve"
    date -u > "$DONE"
    ;;
  serve)
    [ "$(id -u)" = 0 ] || { echo "serve starts a systemd unit: run it with sudo"; exit 2; }
    [ -f "$APP/data/demo/$PACK/demo-store.json" ] || { echo "no $PACK store yet: run the build step first"; exit 1; }
    systemctl stop racinglines-mcp-demo 2>/dev/null || true
    systemctl reset-failed racinglines-mcp-demo 2>/dev/null || true
    # The env file is read inside the unit and the overrides set after it (a unit's EnvironmentFile= would beat
    # --setenv): production's URL becomes the accounts database, the public URL is the demo's, no sql role.
    systemd-run --unit=racinglines-mcp-demo --uid=racinglines --working-directory="$APP" \
      -p Restart=always -p RestartSec=5 -p TimeoutStopSec=20 \
      /bin/bash -c "set -a; . $ENV_FILE; set +a; export RACINGLINES_MCP_ACCOUNTS_URL=\"\$DATABASE_URL\" \
        RACINGLINES_MCP_URL=$PUBLIC_URL PYTHONUNBUFFERED=1; unset RACINGLINES_MCP_SQL_URL RACINGLINES_MCP_ISSUER; \
        exec $R mcp --http --port $PORT --demo $PACK"
    sleep 5
    systemctl --no-pager --lines=5 status racinglines-mcp-demo
    code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/mcp" || true)
    echo "local check: POST http://127.0.0.1:$PORT/mcp -> $code (401 = up and asking for a sign-in)"
    ;;
  *) echo "usage: demo_store.sh build|serve   (PACK=kart PORT=8766 PUBLIC_URL=$PUBLIC_URL)"; exit 2 ;;
esac
