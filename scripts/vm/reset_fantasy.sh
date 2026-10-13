#!/usr/bin/env bash
# Fantasy reset (owner, 2026-10-11: "seed all users with 1k fantasy bucks, and zero trading history"): every active
# account but the demo maker and taker back to one 1,000-buck signup grant, with its paper positions, strategy signals
# and house-book bets deleted (racinglines users reset-fantasy, web/accounts.reset). Their strategy profiles are removed
# too: paper trading starts again once the user picks a strategy (/strategy/pick). maker and taker are never touched.
#
#   TARGET=prod|staging   which app and database (default staging)
#   APPLY=1               write; without it the run is a dry run that only prints the per-account counts
#
# APPLY=1 steps: a backup (its trailer checked), the reset in one transaction, then a data_changes note naming the backup.
# Rollback: restore that backup (vm.sh restore). Run after a race weekend's signal window closes (a day after the race),
# or the weekend's paper trades come back on the next signals run.
#
#   sudo -u racinglines TARGET=staging bash /opt/racinglines-staging/scripts/vm/reset_fantasy.sh            # dry run
#   sudo -u racinglines TARGET=staging APPLY=1 bash /opt/racinglines-staging/scripts/vm/reset_fantasy.sh    # write
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
if [ "${APPLY:-0}" != 1 ]; then
  exec $R users reset-fantasy
fi
mkdir -p data/backups/db
B=data/backups/db/$DB-before-fantasy-reset-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
echo "fantasy reset ($TARGET): backing up to $B"
DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' || { echo "STOP: backup $B is incomplete; nothing written"; exit 1; }
echo "backup $B ($(du -h "$B" | cut -f1))"
$R users reset-fantasy --apply --note "reset $(date -u +%Y-%m-%d)"
$R db changes --add "Fantasy reset ($TARGET): every account but maker and taker back to one 1,000 grant, paper positions, signals and house bets deleted (owner 2026-10-11); backup $B" >/dev/null
echo "data_changes note added"
