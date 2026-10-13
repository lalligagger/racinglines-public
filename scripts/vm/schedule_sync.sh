#!/usr/bin/env bash
# Session start times kept loaded: one pass, started every 6 hours by racinglines-schedule-sync.timer on the VM (enable
# with `bash scripts/deploy/vm.sh schedule`, stop with `vm.sh schedule off`, last passes with `vm.sh schedule status`).
#
#   racinglines data schedule <sport> --through <today + THROUGH_DAYS>          a dry run first, always
#   racinglines data schedule <sport> --through ... --apply --backup <dump>     only when it would add or move a session
#
# The F1 ingest keeps the scheduled rounds of sessions still to come (db/schedule.clear_for_ingest), so this pass is
# the safety net: a session the calendar moved, a weekend newly in the window, a round an older ingest dropped. A pass
# with nothing to add or move writes nothing and takes no backup. One that writes backs the database up first, unless
# its last backup is under 23 hours old (the command refuses one over 24): data/backups/db/
# racinglines-before-schedule-sync-<UTC>.sql.gz, named in a data_changes note, and the command adds its own note.
# Rollback: `racinglines data schedule f1 --undo --backup <that dump>` (scheduled rounds only).
#
# SPORTS (default "f1"; "f1 nascar" adds NASCAR's race-list times) and THROUGH_DAYS (default 70) can be set in the
# env file. Logs to the journal (journalctl -u racinglines-schedule-sync) and data/runs/logs/schedule-sync.log.
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
STATE=data/runs/schedule-sync
LOG=data/runs/logs/schedule-sync.log
mkdir -p "$STATE" data/runs/logs data/backups/db
R=${R:-.venv/bin/racinglines}
SPORTS=${SPORTS:-f1}
THROUGH=$(date -u -d "+${THROUGH_DAYS:-70} days" +%F)
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh schedule status: the timer and the last passes
  systemctl --no-pager list-timers racinglines-schedule-sync.timer | head -n 2
  echo "--- last passes ($LOG)"; tail -n 12 "$LOG" 2>/dev/null || echo "no pass yet"
  exit 0
fi

backup() {   # the newest backup this script took if under 23 hours old, else a fresh one; prints its path
  local b
  b=$(cat "$STATE/backup" 2>/dev/null)
  if [ -n "$b" ] && [ -s "$b" ] && [ $(( $(date +%s) - $(stat -c %Y "$b") )) -le 82800 ]; then echo "$b"; return 0; fi
  b=data/backups/db/racinglines-before-schedule-sync-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines </dev/null | gzip -6 > "$b" &&
    gunzip -c "$b" | tail -n 5 | grep -q 'PostgreSQL database dump complete' || { rm -f "$b"; return 1; }
  $R db changes --add "session schedule sync (racinglines-schedule-sync.timer): backup $b" >/dev/null || true
  echo "$b" > "$STATE/backup"
  say "backup $b ($(du -h "$b" | cut -f1)), data_changes note added" >&2
  echo "$b"
}

rc=0
for sport in $SPORTS; do
  t0=$SECONDS
  if ! out=$(nice $R data schedule "$sport" --through "$THROUGH" 2>&1); then
    rc=1; say "$sport: dry run FAILED: $(echo "$out" | tail -n 3 | tr '\n' ' ')"; continue
  fi
  totals=$(echo "$out" | grep '^Totals:' | tail -n 1)
  if ! echo "$totals" | grep -Eq '(: |, )[1-9][0-9]* (added|moved)'; then
    say "$sport through $THROUGH: nothing to add or move (${totals#Totals: }; $((SECONDS - t0)) s)"; continue
  fi
  echo "$out" | grep -E '(added|moved)' | sed 's/^/  /' | tee -a "$LOG"
  if ! b=$(backup); then rc=1; say "$sport: BACKUP FAILED: nothing written"; continue; fi
  if out=$(nice $R data schedule "$sport" --through "$THROUGH" --apply --backup "$b" 2>&1); then
    say "$sport through $THROUGH: $(echo "$out" | tail -n 1) (${totals#Totals: }; backup $b; $((SECONDS - t0)) s)"
  else
    rc=1; say "$sport: write FAILED: $(echo "$out" | tail -n 3 | tr '\n' ' ')"
  fi
done
exit $rc
