#!/usr/bin/env bash
# Tape backfill: every trade and price history point the venues' own APIs still serve, for every exchange and sport we
# record, into the database. One-off (owner, 2026-10-08: "backfill all venues based on discovered gaps ... using the
# direct venue API hits"), after a comparison with a third-party book feed found gaps: no Kalshi trades stored after
# 29 Sep, no NASCAR/MotoGP Polymarket tape, new F1 markets booked late. Order books can't be backfilled: no venue serves
# book history, so those gaps stay; the recorders (record_venues.sh, pm_sync.sh) fill them from now on.
#
#   TARGET=prod|staging   which app and database (default prod; as scripts/vm/overnight.sh)
#   START=2026-09-01      price history from this UTC day (trades: every trade since START)
#   PAIRS="kalshi:f1 ..." exchange:sport pairs (default below: every pair the recorders cover)
#
# Steps: a backup (its trailer checked), then per pair a sync (new links), the trades since START and the hourly price
# history since START (Kalshi candles, Polymarket price points, OG.com minute prices clipped to the month it keeps),
# then a data_changes note naming the backup. Additive: rows are upserted (uq_market_trade, price-history keys), never
# deleted. One pair failing doesn't stop the others; the run exits non-zero if any failed. Progress: a line per step
# with its time, plus each racinglines command's own heartbeat every 5 minutes (racinglines/progress.py).
#
# Run on the VM as a transient unit, e.g.
#   sudo systemd-run --unit=rl-backfill-tape --uid=racinglines --setenv=TARGET=prod /opt/racinglines/scripts/vm/backfill_tape.sh
set -uo pipefail
TARGET=${TARGET:-prod}
case "$TARGET" in
  prod)    ENV_FILE=${ENV_FILE:-/etc/racinglines.env};         APP=${APP:-/opt/racinglines};         DB=racinglines ;;
  staging) ENV_FILE=${ENV_FILE:-/etc/racinglines-staging.env}; APP=${APP:-/opt/racinglines-staging}; DB=racinglines_staging ;;
  *) echo "TARGET must be prod or staging, not $TARGET"; exit 2 ;;
esac
DC() { (cd "${DC_DIR:-/opt/racinglines}" && docker compose "$@"); }   # the database container is production's
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1
cd "$APP"
START=${START:-2026-09-01}
PAIRS=${PAIRS:-kalshi:f1 kalshi:nascar kalshi:motogp og:f1 og:nascar polymarket:f1 polymarket:nascar polymarket:motogp}
R=${R:-.venv/bin/racinglines}
mkdir -p data/runs/logs data/backups/db
LOG=data/runs/logs/backfill-tape-$(date -u +%Y%m%dT%H%M%SZ).log
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }
HOURS=$(( ($(date -u +%s) - $(date -u -d "$START" +%s)) / 3600 + 1 ))
NOW=$(date -u +%Y-%m-%dT%H:%M)

B=data/backups/db/$DB-before-backfill-tape-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
say "backfill $TARGET from $START ($HOURS h): backing up to $B"
DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
if ! gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'; then
  say "STOP: backup $B is incomplete; nothing written"
  exit 1
fi
say "backup $B ($(du -h "$B" | cut -f1))"

rc=0
run() {   # run <exchange> <sport> <command> [args]: one line with the command's last output line and its time
  local t0=$SECONDS out
  say "$1 $2 $3: started"
  # the command's own 5-minute progress lines go to the journal as they come (a step can run for an hour); the rest
  # is captured for the step's one summary line
  if out=$(nice $R markets --exchange "$1" --sport "$2" "${@:3}" 2>&1 |
           tee >(grep --line-buffered '^progress' | while read -r l; do say "$1 $2 $3: $l" >&2; done)); then
    say "$1 $2 $3: $(echo "$out" | grep -v '^progress' | tail -n 1) ($((SECONDS - t0)) s)"
  else
    rc=1; say "$1 $2 $3: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
  fi
}
for p in $PAIRS; do
  x=${p%%:*}; s=${p#*:}
  run "$x" "$s" sync
  run "$x" "$s" trades --since-hours "$HOURS"
  case "$x" in
    kalshi)     run "$x" "$s" history --start "${START}T00:00" --end "$NOW" --period 60 ;;
    polymarket) run "$x" "$s" history --start "${START}T00:00" --end "$NOW" --fidelity 60 ;;
    *)          run "$x" "$s" history --start "${START}T00:00" ;;
  esac
done
$R db changes --add "Tape backfill ($TARGET): trades and hourly price history since $START from the venues' APIs for $PAIRS; backup $B" >/dev/null \
  && say "data_changes note added" || { rc=1; say "data_changes note FAILED"; }
say "BACKFILL-DONE (exit $rc)"
exit $rc
