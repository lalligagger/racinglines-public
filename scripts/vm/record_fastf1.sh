#!/usr/bin/env bash
# FastF1 live recorder: one pass every 5 minutes (via systemd timer) during F1 race weekends.
# Polls for active F1 sessions and stores driver positions, lap times, and session status to the database.
# (enable with `bash scripts/deploy/vm.sh record fastf1`, stop with `vm.sh record fastf1 off`, last passes:
# `vm.sh record fastf1 status`). `vm.sh record` alone is the Kalshi and OG.com recorder, not this one.
#
#   racinglines data record f1              # one pass: fetch current session and store snapshot
#   racinglines data record f1 --status     # show last passes and snapshots stored
#
# Source check (2026-10-11): F1's timing archive (livetiming.formula1.com/static, which FastF1 reads) answered 403 to
# the VM's address since 3 Oct 2026 (docs/vm-deploy.md), and fastf1_session_snapshots had 0 rows. Each race-weekend
# pass therefore asks for the archive's season index first (the URL racinglines/testing/checks.py checks) and, on a
# 403, logs "fastf1: BLOCKED" and exits non-zero without loading any session, so the log and `systemctl status` say why
# nothing is stored. Whether the timer is removed or pointed at another source waits for the owner's probe.
#
# Polling strategy: runs 5-min cadence Thu-Sun UTC when F1 is in a race weekend. Off-weeks: exits
# cleanly, conserving API quota. Every pass: detect current F1 event/session, fetch live timing data
# via FastF1, store one snapshot per session in fastf1_session_snapshots table with lap positions in
# fastf1_driver_positions. Additive only; new rounds appear when schedule updates. One session failing
# doesn't stop others. Log lines go to data/runs/logs/record-fastf1.log and journal (journalctl -u
# racinglines-record-fastf1):
#   2026-10-03T18:30:02Z fastf1: 3 snapshots stored (12 s)
#   2026-10-04T14:20:01Z f1: off-week, skipped
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
  $R data record f1 --status 2>&1 || echo "DB unavailable"
  exit 0
fi

# Check if F1 is in a race weekend; skip if off-week
if ! bash scripts/vm/race_weekend.sh f1 >/dev/null 2>&1; then
  say "f1: off-week, skipped"
  exit 0
fi

code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://livetiming.formula1.com/static/$(date -u +%Y)/Index.json" 2>/dev/null)
if [ "$code" = 403 ]; then
  say "fastf1: BLOCKED: livetiming.formula1.com answered HTTP 403 to this host; no session loaded, nothing stored"
  exit 1
fi

rc=0
say "fetching current F1 session (timing archive index: HTTP ${code:-no answer})"
if out=$($R data record f1 2>&1); then
  say "fastf1: $(echo "$out" | tail -n 1)"
else
  rc=1
  say "fastf1: FAILED: $(echo "$out" | tail -n 3 | tr '\n' ' ')"
fi
if echo "$out" | grep -qE '\b403\b|Forbidden'; then
  rc=1
  say "fastf1: BLOCKED: the output names an HTTP 403 (Forbidden) from the source"
fi
exit $rc
