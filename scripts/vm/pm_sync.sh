#!/usr/bin/env bash
# Polymarket market links sync: one pass, started every 5 minutes by racinglines-pm-sync.timer on the VM
# (enable with `bash scripts/deploy/vm.sh record`, stop with `vm.sh record off`).
# Syncs active Polymarket markets into market_links every 5 minutes during F1 race weekends, keeping
# prices fresh alongside live repricing strategy (every 5 min). Unlike the continuous markets-record
# service (trades/books), this service syncs market links and updates current bid/ask from Gamma API.
#
# Command: racinglines markets --exchange polymarket sync (markets/polymarket/sync.py)
#
# Polling strategy: runs 5-min cadence Thu-Sun UTC when F1 is in a race weekend. Off-weeks: exits
# cleanly (race_weekend.sh checks if event exists in next 7 days). Every pass: one market_links row
# upsert per outcome token, synced_at updated with current bid/ask/lastTradePrice from Gamma API.
# New markets appear as they open; resolved ones mark closed. API limit: the command's own (Gamma HTTP
# pacing, sources/http.py). One sync failing exits non-zero, so `systemctl status` shows it. Log lines
# go to journal (journalctl -u racinglines-pm-sync) and data/runs/logs/pm-sync.log. Status line:
#   2026-10-03T21:30:02Z polymarket f1 sync: 4 events, 34 links upserted (8 s)
#   2026-10-04T14:20:01Z polymarket f1: off-week, skipped
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
LOG=data/runs/logs/pm-sync.log
mkdir -p data/runs/logs

R=${R:-.venv/bin/racinglines}
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

# Check if F1 is in a race weekend; skip if off-week
if ! bash scripts/vm/race_weekend.sh f1 >/dev/null 2>&1; then
  say "polymarket f1: off-week, skipped"
  exit 0
fi

run() {
  local t0=$SECONDS out
  if out=$(nice $R markets --exchange polymarket sync 2>&1); then
    say "polymarket f1 sync: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
    return 0
  else
    say "polymarket f1 sync: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}

run
exit $?
