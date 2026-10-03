#!/usr/bin/env bash
# FastF1 live recorder: one pass every 5 minutes (via systemd timer), polling for active F1 sessions
# and storing driver positions, lap times, and session status to the database.
#
#   racinglines record fastf1              # one pass: fetch current session and store snapshot
#   racinglines record fastf1 status       # show last passes and snapshots stored
#
# Every pass: detect current F1 event/session, fetch live timing data via FastF1, store one
# snapshot per session in fastf1_session_snapshots table with lap positions in fastf1_driver_positions.
# Additive only; new rounds appear when schedule updates. One session failing doesn't stop others.
# Log: data/runs/logs/record-fastf1.log
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
STATE=data/runs/record-fastf1
LOG=data/runs/logs/record-fastf1.log
mkdir -p "$STATE" data/runs/logs
R=${R:-.venv/bin/racinglines}
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh record fastf1 status
  echo "--- last passes ($LOG)"
  tail -n 12 "$LOG" 2>/dev/null || echo "no pass yet"
  $R f1 record --status 2>&1 || echo "DB unavailable"
  exit 0
fi

rc=0
say "fetching current F1 session"
if out=$($R f1 record 2>&1); then
  say "fastf1: $(echo "$out" | tail -n 1)"
else
  rc=1
  say "fastf1: FAILED: $(echo "$out" | tail -n 3 | tr '\n' ' ')"
fi
exit $rc
