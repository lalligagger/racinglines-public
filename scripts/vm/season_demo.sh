#!/usr/bin/env bash
# The alpha's season demo database (owner, 2026-10-13 06:36-06:37Z: every user on a random strategy at various
# participation rates through the 2026 F1 season, "its own demo db (not regular staging db)", one that persists and is
# picked "with a switch on deploy to staging"). Run on the VM as a transient systemd unit; the owner starts it with
# `bash scripts/deploy/vm.sh staging demo-db build`, which runs:
#
#   sudo systemd-run --unit=rl-season-demo --uid=racinglines /opt/racinglines-staging/scripts/vm/season_demo.sh
#
# Steps, all on racinglines_staging_demo (a database in production's Postgres container, beside racinglines_staging):
#   1. COPY=1, or the first run: back the demo database up if it exists, drop it, and copy SOURCE (default racinglines,
#      production, only read: pg_dump | psql as `vm.sh staging reset` does, without subscriptions or publications, so a
#      mirror's replication never follows the copy). Otherwise the existing demo database is backed up and kept.
#   2. alembic upgrade head, db seed, users setup on the demo database only (refused for any other DATABASE_URL).
#   3. Production's market archive (data/archive, read) copied into staging's data folder, where the replays read the
#      cold rows the recorder moved out of Postgres; the season's FastF1 schedule likewise when staging has none.
#   4. racinglines users season-demo --seed SEED --year YEAR --apply (racinglines/fantasy/season_demo.py), then a
#      data_changes note naming the backup.
#
# Staging serves it only after `bash scripts/deploy/vm.sh staging db demo` (and back: `vm.sh staging db main`).
# Log: data/runs/logs/season-demo-<UTC>.log in staging's checkout; markers season-demo.done / .failed. Touches no
# trading flag, no production row (production is only read), and never racinglines_staging.
# A progress line every 5 minutes: the racinglines heartbeat (RACINGLINES_PROGRESS_SEC) with the weekend it is on.
set -eEuo pipefail
STG=/opt/racinglines-staging
APP=/opt/racinglines
ENV_FILE=/etc/racinglines-staging.env
DB=racinglines_staging_demo
SOURCE=${SOURCE:-racinglines}
SEED=${SEED:-2026}
YEAR=${YEAR:-2026}
DC() { (cd "$APP" && docker compose "$@"); }
psql_() { DC exec -T db psql -U racinglines "$@" </dev/null; }
case "$SOURCE" in racinglines|racinglines_staging) ;; *) echo "SOURCE must be racinglines or racinglines_staging"; exit 2 ;; esac
set -a; . "$ENV_FILE"; set +a
export DATABASE_URL="${DATABASE_URL%/*}/$DB" PYTHONUNBUFFERED=1
case "$DATABASE_URL" in */racinglines_staging_demo) ;; *) echo "refusing: DATABASE_URL is not $DB"; exit 1 ;; esac
cd "$STG"
LOGS=data/runs/logs
mkdir -p "$LOGS" data/backups/db
UTC=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$LOGS/season-demo-$UTC.log
rm -f "$LOGS/season-demo.done" "$LOGS/season-demo.failed"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "SEASON-DEMO FAILED at line $LINENO (log $LOG)"; date -u > "$LOGS/season-demo.failed"' ERR
R=.venv/bin/racinglines
exists=$(psql_ -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | tail -n 1)
B=""
if [ "$exists" = 1 ]; then
  B=data/backups/db/$DB-before-season-demo-$UTC.sql.gz
  DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" </dev/null | gzip -6 > "$B"
  gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' || { echo "STOP: backup $B is incomplete; nothing written"; exit 1; }
  echo "backup $B ($(du -h "$B" | cut -f1))"
fi
if [ "$exists" != 1 ] || [ "${COPY:-0}" = 1 ]; then
  echo "== $DB: a fresh copy of $SOURCE ($SOURCE is only read)"
  psql_ -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)"
  psql_ -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DB"
  (cd "$APP" && set -o pipefail && docker compose exec -T db pg_dump --no-owner --no-privileges --no-subscriptions \
     --no-publications -U racinglines "$SOURCE" | docker compose exec -T db psql -q -U racinglines -d "$DB" -v ON_ERROR_STOP=0 >/dev/null)
  echo "$DB has $(psql_ -d "$DB" -tAc "SELECT count(*) FROM users" | tail -n 1) users"
else
  echo "== $DB exists; kept (COPY=1 re-copies it from $SOURCE)"
fi
echo "== migrations, seed and the fantasy tables ($DB only)"
.venv/bin/alembic upgrade head
$R db seed
$R users setup
echo "== production's market archive -> $STG/data/archive (production is only read)"
mkdir -p data/archive "data/raw/f1/fastf1/$YEAR"
# staging's data/archive may already be production's (a symlink): then there is nothing to copy
if [ -d "$APP/data/archive" ] && [ "$(readlink -f "$APP/data/archive")" != "$(readlink -f data/archive)" ]; then
  cp -a -u "$APP/data/archive/." data/archive/
fi
s=data/raw/f1/fastf1/$YEAR/schedule.parquet
[ -f "$s" ] || { [ -f "$APP/$s" ] && cp -a "$APP/$s" "$s"; } || true
echo "== the draw (seed $SEED)"
nice $R users season-demo --seed "$SEED" --year "$YEAR" --apply
$R db changes --add "Season demo ($DB): every fantasy player on a random alpha style, weekend share and follow rate through $YEAR so far, seed $SEED (owner 2026-10-13); backup ${B:-none (a new database)}" >/dev/null
echo "SEASON-DEMO DONE (log $LOG, backup ${B:-none}); serve it with: bash scripts/deploy/vm.sh staging db demo"
date -u > "$LOGS/season-demo.done"
