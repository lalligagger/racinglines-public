#!/usr/bin/env bash
# NASCAR, MotoGP and F1 forecast refresh: one pass, started every 30 minutes by racinglines-forecast-refresh.timer on the VM
# (enable with `bash scripts/deploy/vm.sh forecast`, stop with `vm.sh forecast off`). Runs the NASCAR and MotoGP forecasts
# after each race to keep pricing fresh, and the F1 forecast (the championship fairs) once per new F1 classification.
#
#   racinglines nascar fetch|ingest --years <this year>     NASCAR results first (race weekends and Mondays UTC)
#   racinglines nascar forecast --save --backup <path>
#   racinglines motogp forecast --save --backup <path>
#   racinglines f1 forecast --year <this year> --save        only when a race classification arrived since the last
#                                                            F1 pass (count kept in data/runs/forecast-refresh/f1-results;
#                                                            the first pass only starts the count)
#
# Every pass: updates the cached forecasts with the latest race results and market conditions. F1 waits for the
# classification on purpose: a forecast saved mid-weekend would also re-price that weekend's race with a cutoff later
# than its live stage runs, so after the flag the race page's pre-race price would switch to it.
# Logs to the journal (journalctl -u racinglines-forecast-refresh) and data/runs/logs/forecast-refresh.log.
#
# A pass backs the database up first when there is no backup yet or the last one is over 23 hours old (forecast --save
# refuses a dump older than 24 hours): data/backups/db/racinglines-before-forecast-refresh-<UTC>.sql.gz, named in a
# data_changes note.
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

B=$(cat "$STATE/backup" 2>/dev/null)
if [ -z "$B" ] || [ ! -s "$B" ] || [ $(( $(date +%s) - $(stat -c %Y "$B") )) -gt 82800 ]; then
  B=data/backups/db/racinglines-before-forecast-refresh-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  say "backing up to $B (none yet, or the last one is over 23 h old)"
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B" &&
    gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' ||
    { say "BACKUP FAILED: nothing refreshed"; rm -f "$B"; exit 1; }
  $R db changes --add "NASCAR, MotoGP and F1 forecast refresh (racinglines-forecast-refresh.timer, every 30 min), daily backup: $B" >/dev/null
  echo "$B" > "$STATE/backup"
  say "backup $B ($(du -h "$B" | cut -f1)), data_changes note added"
fi

rc=0
run() {   # run <sport>: refresh forecast for a sport if in race weekend
  local sport=$1 t0=$SECONDS out
  if ! bash scripts/vm/race_weekend.sh "$sport" >/dev/null 2>&1; then
    say "$sport forecast: off-week, skipped"
    return 0
  fi
  if out=$(nice $R "$sport" forecast --save --backup "$B" 2>&1); then
    say "$sport forecast: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
  else
    rc=1; say "$sport forecast: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}

f1() {   # the F1 forecast, once per new race classification of this season
  local year t0=$SECONDS n last out
  year=$(date -u +%Y)
  n=$(docker compose exec -T db psql -U racinglines racinglines -tAc "
    SELECT count(*) FROM rounds ro JOIN races ra ON ra.id = ro.race_id JOIN events e ON e.id = ra.event_id
    JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
    WHERE co.code = 'f1_wdc' AND s.year = $year AND ro.kind = 'race'
      AND EXISTS (SELECT 1 FROM results r WHERE r.round_id = ro.id AND r.position IS NOT NULL)" </dev/null) ||
    { rc=1; say "f1 forecast: FAILED to count classifications"; return 1; }
  last=$(cat "$STATE/f1-results" 2>/dev/null)
  if [ -z "$last" ]; then                  # first pass: start counting from here (the count may be mid-weekend)
    echo "$n" > "$STATE/f1-results"
    say "f1 forecast: first pass, counting from $n classifications this season"
    return 0
  fi
  if [ "$n" = "$last" ]; then
    say "f1 forecast: no new classification ($n this season), skipped"
    return 0
  fi
  if out=$(nice $R f1 forecast --year "$year" --save 2>&1); then
    echo "$n" > "$STATE/f1-results"
    say "f1 forecast: $(echo "$out" | tail -n 1) after classification $n ($((SECONDS - t0)) s)"
  else
    rc=1; say "f1 forecast: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}

results() {   # NASCAR results: fetch and ingest this season's feeds before the forecast, so a race's result (and the
  # entry list it carries) is stored the same night. Race weekends, plus Mondays UTC: a Sunday-night race ends after
  # midnight UTC. fetch asks again for a race of the last 3 days, so a feed stored mid-race is replaced.
  local year t0=$SECONDS out
  year=$(date -u +%Y)
  if ! bash scripts/vm/race_weekend.sh nascar >/dev/null 2>&1 && [ "$(date -u +%u)" != 1 ]; then
    say "nascar results: off-week, skipped"
    return 0
  fi
  # the feeds and lap setting of overnight.sh's results step, so races it already stored are left unchanged
  out=$(nice $R nascar fetch --years "$year" --feeds race_list_basic,points-feed,weekend-feed 2>&1) ||
    say "nascar results: fetch had errors, ingesting what is stored: $(echo "$out" | tail -n 2 | tr '\n' ' ')"
  if out=$(nice $R nascar ingest --years "$year" --no-laps 2>&1); then
    say "nascar results: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
  else
    rc=1; say "nascar results: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
  fi
}

results
run nascar
run motogp
f1
exit $rc
