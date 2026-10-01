#!/usr/bin/env bash
# One-time setup of staging on the VM, as root: a second copy of the app beside production, for
# staging.racinglines.bet. Safe to re-run (every step is idempotent). Piped over ssh by
# `scripts/deploy/vm.sh staging setup [ref]`, so the VM doesn't need to have this file yet.
#
#   sudo REF=<branch> bash -s < deploy/vm/staging/setup.sh
#   sudo RESET_DB=1 bash -s < deploy/vm/staging/setup.sh    # drop and re-copy the staging database
#
# What it makes, and what it never touches:
#   /opt/racinglines-staging            its own checkout (REF, default `staging`, else main) and venv, owned by racinglines
#   racinglines_staging                 a database in production's Postgres container, copied from `racinglines` with
#                                       pg_dump | psql (a read of production; production's rows are never written)
#   /etc/racinglines-staging.env        production's settings with its own DATABASE_URL, data folder, URL, secret,
#                                       RACINGLINES_ENV=staging, WEB_PORT=8010, and NO trading flags, alerts or ntfy topic
#   racinglines-staging-web.service     the web app on 127.0.0.1:8010 (installed and started; nothing else: no
#                                       recorder, signals, live-event or MCP units for staging)
# Production's checkout, database, /etc/racinglines.env, units and timers are not read for writing and not restarted.
set -euo pipefail
REPO="${REPO:-https://github.com/lalligagger/racinglines-public.git}"
REF="${REF:-staging}"
APP=/opt/racinglines
STG=/opt/racinglines-staging
ENVF=/etc/racinglines-staging.env
DB=racinglines_staging
log() { echo "[staging-setup $(date -u +%H:%M:%S)] $*"; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -d "$APP/.git" ] || { echo "production checkout $APP missing: run vm.sh setup first"; exit 1; }
as() { sudo -u racinglines -H "$@"; }
# production's compose project (its Postgres container), read-only use below
pg() { as bash -c "cd $APP && docker compose exec -T db $*"; }

log "checkout $STG ($REF)"
if [ ! -d "$STG/.git" ]; then
  mkdir -p "$STG" && chown racinglines: "$STG"
  as git clone --quiet "$REPO" "$STG"
fi
as bash -c "cd $STG && git fetch --quiet --prune origin && \
  { git rev-parse --verify -q origin/$REF^{commit} >/dev/null && git checkout --quiet --detach origin/$REF || git checkout --quiet --detach origin/main; } && \
  git log -1 --format='staging checkout at %h %s'"

log "venv (the same Python as production)"
if [ ! -x "$STG/.venv/bin/python" ]; then
  as sh -c "cd $STG && UV_PYTHON_INSTALL_DIR=\$HOME/.uv-python /opt/uv/bin/uv venv --quiet --seed --python 3.14 .venv"
fi
as sh -c "cd $STG && .venv/bin/pip install --quiet -r requirements.txt -e ."
as mkdir -p "$STG/data/runs/logs" "$STG/data/backups/db"

log "database $DB (in production's Postgres container)"
pg pg_isready -U racinglines >/dev/null || { echo "production's database container is not up"; exit 1; }
if [ "${RESET_DB:-0}" = 1 ]; then
  log "RESET_DB=1: dropping $DB"
  pg psql -U racinglines -d postgres -v ON_ERROR_STOP=1 -c "\"DROP DATABASE IF EXISTS $DB WITH (FORCE)\""
fi
exists=$(pg psql -U racinglines -d postgres -tAc "\"SELECT 1 FROM pg_database WHERE datname='$DB'\"" | tail -n 1)
if [ "$exists" != 1 ]; then
  pg psql -U racinglines -d postgres -v ON_ERROR_STOP=1 -c "\"CREATE DATABASE $DB\""
  log "copying production's rows into $DB (pg_dump | psql; production is only read)"
  as bash -c "cd $APP && set -o pipefail && docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines \
    | docker compose exec -T db psql -q -U racinglines -d $DB -v ON_ERROR_STOP=0 >/dev/null"
  n=$(pg psql -U racinglines -d "$DB" -tAc "\"SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')\"" | tail -n 1)
  log "$DB has $n tables"
else
  log "$DB exists; keeping it (RESET_DB=1 re-copies it)"
fi

log "$ENVF"
if [ ! -f "$ENVF" ]; then
  # production's settings minus everything staging must own or must not have
  grep -vE '^(DATABASE_URL|RACINGLINES_DATA|RACINGLINES_URL|APP_SECRET|RACINGLINES_NTFY_TOPIC|ALERT_WEBHOOK_URL|RACINGLINES_ENV|WEB_PORT|WEB_HOST)=' /etc/racinglines.env \
    | grep -viE 'TRADING' > "$ENVF.tmp"
  cat >> "$ENVF.tmp" <<EOT
# --- staging (deploy/vm/staging/setup.sh); never trading flags, never alerts ---
RACINGLINES_ENV=staging
WEB_PORT=8010
DATABASE_URL=postgresql+psycopg://racinglines:racinglines@127.0.0.1:5433/$DB
RACINGLINES_DATA=$STG/data
RACINGLINES_URL=https://staging.racinglines.bet
APP_SECRET=$(openssl rand -hex 32)
RACINGLINES_NTFY_TOPIC=
ALERT_WEBHOOK_URL=
EOT
  install -o root -g racinglines -m 640 "$ENVF.tmp" "$ENVF" && rm -f "$ENVF.tmp"
else
  log "$ENVF exists; keeping it"
fi
grep -qiE 'TRADING_ENABLED=1' "$ENVF" && { echo "$ENVF has a trading flag on: staging never trades. Fix it by hand."; exit 1; }

log "migrations and seed against $DB only"
as bash -c "cd $STG && set -a && . $ENVF && set +a && case \"\$DATABASE_URL\" in */$DB) ;; *) echo \"refusing: DATABASE_URL is not $DB\"; exit 1;; esac && .venv/bin/alembic upgrade head && .venv/bin/racinglines db seed"

log "unit racinglines-staging-web (port 8010)"
unit="$STG/deploy/vm/systemd/racinglines-staging-web.service"
[ -f "$unit" ] || { echo "$unit missing: REF=$REF doesn't carry the staging unit yet"; exit 1; }
install -m 644 "$unit" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now racinglines-staging-web
sleep 3
systemctl --no-pager status racinglines-staging-web | grep -E 'Active'
curl -s -o /dev/null -w 'GET http://127.0.0.1:8010/login: %{http_code}  env: %header{x-racinglines-env}\n' http://127.0.0.1:8010/login || true
log "done. Point staging.racinglines.bet at http://localhost:8010 in Cloudflare, then: bash scripts/deploy/smoke.sh https://staging.racinglines.bet"
