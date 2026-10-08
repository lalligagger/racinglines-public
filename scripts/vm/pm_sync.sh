#!/usr/bin/env bash
# Polymarket market links sync: one pass, started every 5 minutes by racinglines-pm-sync.timer on the VM
# (enable with `bash scripts/deploy/vm.sh record`, stop with `vm.sh record off`).
# Syncs active Polymarket markets into market_links every 5 minutes during F1 race weekends, keeping
# prices fresh alongside live repricing strategy (every 5 min). Unlike the continuous markets-record
# service (trades/books), this service syncs market links and updates current bid/ask from Gamma API.
#
# Command: racinglines markets --exchange polymarket sync (markets/polymarket/sync.py). Also (2026-10-08, after a
# comparison with a third-party book feed found no NASCAR/MotoGP Polymarket books and no trade tape between race pulls):
# every TRADES_MIN the recent trades of every open market (`trades --open --since-hours`), and for PM_SPORTS
# (nascar, motogp) a sync every SYNC_MIN and one book snapshot per open market on every pass.
#
# Polling strategy (owner, 2026-10-07): every 5-minute pass, every day, all day (WEEKEND_ONLY=1 brings back the old
# gate: only Thu to Sun of an F1 race weekend, scripts/vm/race_weekend.sh), then a tape check (scripts/vm/tape_check.sh,
# WARN lines in the log). Every pass: one market_links row
# upsert per outcome token, synced_at updated with current bid/ask/lastTradePrice from Gamma API.
# New markets appear as they open; resolved ones mark closed. API limit: the command's own (Gamma HTTP
# pacing, sources/http.py). One sync failing exits non-zero, so `systemctl status` shows it. Log lines
# go to journal (journalctl -u racinglines-pm-sync) and data/runs/logs/pm-sync.log. Status line:
#   2026-10-03T21:30:02Z polymarket f1 sync: 4 events, 34 links upserted (8 s)
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
LOG=data/runs/logs/pm-sync.log
mkdir -p data/runs/logs

R=${R:-.venv/bin/racinglines}
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh pm-sync status: the last passes
  systemctl --no-pager list-timers racinglines-pm-sync.timer | head -n 2
  echo "--- last passes ($LOG)"; tail -n 12 "$LOG" 2>/dev/null || echo "no pass yet"
  exit 0
fi

if [ "${WEEKEND_ONLY:-0}" = 1 ] && ! bash scripts/vm/race_weekend.sh f1 >/dev/null 2>&1; then
  say "polymarket f1: off-week, skipped (WEEKEND_ONLY=1)"
  exit 0
fi

PM_SPORTS=${PM_SPORTS:-nascar motogp}   # the tape-only sports' Polymarket markets: sync, books and trades here, since
                                        # the minute recorder (racinglines-recorder.service) books F1 only
SYNC_MIN=${SYNC_MIN:-60}                # their sync, every SYNC_MIN (F1's: every pass)
TRADES_MIN=${TRADES_MIN:-15}            # every sport's trade tape of open markets, the last TRADES_HOURS of it, every
TRADES_HOURS=${TRADES_HOURS:-2}         # TRADES_MIN (the overlap is deduplicated by uq_market_trade)
STATE=data/runs/pm-sync
mkdir -p "$STATE"

rc=0
run() {   # run <sport> <command> [args]: one line with the command's last output line and its time
  local t0=$SECONDS out
  if out=$(nice $R markets --exchange polymarket --sport "$1" "${@:2}" 2>&1); then
    say "polymarket $1 $2: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
    return 0
  else
    rc=1; say "polymarket $1 $2: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}
trades() {   # trades <sport>: the open markets' recent trades, every TRADES_MIN
  if [ -z "$(find "$STATE/trades-$1" -mmin -"$TRADES_MIN" 2>/dev/null)" ]; then
    run "$1" trades --open --since-hours "$TRADES_HOURS" && touch "$STATE/trades-$1"
  fi
}
check() {   # an upcoming event with no Polymarket links or a stale sync (scripts/vm/tape_check.sh): WARN lines in the log
  bash scripts/vm/tape_check.sh polymarket "$1" 2>&1 | while read -r line; do say "$line"; done || true
}

run f1 sync
check f1
trades f1
for s in $PM_SPORTS; do
  if [ -z "$(find "$STATE/sync-$s" -mmin -"$SYNC_MIN" 2>/dev/null)" ]; then
    run "$s" sync && touch "$STATE/sync-$s"
    check "$s"
  fi
  run "$s" books
  trades "$s"
done
exit $rc
