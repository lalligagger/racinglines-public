#!/usr/bin/env bash
# NASCAR forecast refresh: one pass, started every 30 minutes by racinglines-forecast-refresh.timer on the VM
# (enable with `bash scripts/deploy/vm.sh forecast`, stop with `vm.sh forecast off`). Runs the NASCAR forecast
# after each race to keep pricing fresh.
#
#   racinglines nascar forecast --save --backup <path>
#
# Every pass: updates the cached forecast with the latest race results and market conditions.
# Logs to the journal (journalctl -u racinglines-forecast-refresh) and data/runs/logs/forecast-refresh.log.
#
# The first pass on a box backs the database up first: data/backups/db/
# racinglines-before-forecast-refresh-<UTC>.sql.gz, named in a data_changes note.
#
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
STATE=data/runs/forecast-refresh
LOG=data/runs/logs/forecast-refresh.log
mkdir -p "$STATE" data/runs/logs data/backups/db
R=${R:-.venv/bin/racinglines}
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh forecast status: the last passes
  systemctl --no-pager list-timers racinglines-forecast-refresh.timer | head -n 2
  echo "--- last passes ($LOG)"; tail -n 10 "$LOG" 2>/dev/null || echo "no pass yet"
  exit 0
fi

if [ ! -e "$STATE/backup" ]; then
  B=data/backups/db/racinglines-before-forecast-refresh-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  say "first pass: backing up to $B"
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B" &&
    gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' ||
    { say "BACKUP FAILED: nothing refreshed"; rm -f "$B"; exit 1; }
  $R db changes --add "NASCAR forecast refresh on (racinglines-forecast-refresh.timer, every 30 min). Backup: $B" >/dev/null
  echo "$B" > "$STATE/backup"
  say "backup $B ($(du -h "$B" | cut -f1)), data_changes note added"
fi

rc=0
run() {   # run <sport>: refresh forecast for a sport
  local t0=$SECONDS out
  if out=$(nice $R "$1" forecast --save 2>&1); then
    say "$1 forecast: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
  else
    rc=1; say "$1 forecast: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}

run nascar
exit $rc
