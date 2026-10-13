#!/usr/bin/env bash
# Fantasy trading setup (owner, 2026-10-12: "first-cut manual trading, staging only"): creates the manual-trading tables
# (accounts.fantasy_orders, fantasy_fills, fantasy_positions) and the ledger's ref columns with `racinglines users setup`
# (idempotent; fantasy/ledger.py). Accounts without their 1,000 grant get it, as setup always does. No Alembic
# migration: a deploy never runs this.
#
#   TARGET=prod|staging   which app and database (default staging; prod only on the owner's go)
#
# Steps: a backup (its trailer checked), setup, then a data_changes note naming the backup. Rollback: restore that
# backup (vm.sh restore), or leave the empty tables (harmless with the pages switched off).
#
#   sudo -u racinglines TARGET=staging bash /opt/racinglines-staging/scripts/vm/fantasy_setup.sh
set -euo pipefail
TARGET=${TARGET:-staging}
case "$TARGET" in
  prod)    ENV_FILE=${ENV_FILE:-/etc/racinglines.env};         APP=${APP:-/opt/racinglines};         DB=racinglines ;;
  staging) ENV_FILE=${ENV_FILE:-/etc/racinglines-staging.env}; APP=${APP:-/opt/racinglines-staging}; DB=racinglines_staging ;;
  *) echo "TARGET must be prod or staging, not $TARGET"; exit 2 ;;
esac
DC() { (cd "${DC_DIR:-/opt/racinglines}" && docker compose "$@"); }   # the database container is production's
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1
cd "$APP"
R=${R:-.venv/bin/racinglines}
mkdir -p data/backups/db
B=data/backups/db/$DB-before-fantasy-setup-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
echo "fantasy setup ($TARGET): backing up to $B"
DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' || { echo "STOP: backup $B is incomplete; nothing written"; exit 1; }
echo "backup $B ($(du -h "$B" | cut -f1))"
$R users setup
$R db changes --add "Fantasy trading setup ($TARGET): accounts.fantasy_orders, fantasy_fills, fantasy_positions and fantasy_ledger ref columns created (owner 2026-10-12); backup $B" >/dev/null
echo "data_changes note added"
