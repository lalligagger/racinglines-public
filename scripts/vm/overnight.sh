#!/usr/bin/env bash
# The overnight VM run (docs/overnight-vm-run.md). Run on the VM as a transient systemd unit, never by hand in an
# SSH shell (it survives SSH drops and a deploy's pause):
#
#   sudo systemd-run --unit=rl-overnight --uid=racinglines --setenv=MODE=dry /opt/racinglines/scripts/vm/overnight.sh
#
# MODE:
#   dry     read-only: counts, cores, memory and disk, each sport's tape probe and last-race replay, and the F1
#           golden check (profile A on 2026, not saved). Writes nothing.
#   f1      backup, then the F1 broad sweep (sweeps/overnight-vm.toml), search-report, promote the top 10 to 16k,
#           the 16k confirmations, search-report again; then the F1 walk-forward and the default F1 sweeps saved.
#   replay  backup, then for each of SPORTS (default "nascar motogp"): re-sync links on Kalshi and Polymarket, pull the tape
#           and replay it (Kalshi must be tradeable), the price-spike check, the replay saves, then a read-only
#           settings grid and its top 3 at 16k; then OG.com's read-only buy-all on F1 and NASCAR (PR #88).
#   story   the demo taker's walk-forward story (needs PR #87 deployed): backup; the evidence sweeps
#           (sweeps/demo-taker-story.toml); gate: scripts/vm/story_gate.py must print GATE OK, else stop with nothing
#           reset; then `f1 demo-history --reset --user taker`. Always --user taker: never the maker's record.
#   all     f1, then replay, then story, in one unit. Each starts only if the one before finished.
#
# Every writing mode backs up first and checks the dump's trailer. Log: data/runs/logs/overnight-<mode>-<UTC>.log;
# markers overnight-<mode>.done / .failed. Refuses to start while a racinglines-live-* unit is active.
# Downhill is not run (owner, 2026-09-30). Nothing here touches the trading flags, a migration or the bucket.
set -eEuo pipefail
set -a; . /etc/racinglines.env; set +a
cd /opt/racinglines
MODE=${MODE:-dry}
SPORTS=${SPORTS:-nascar motogp}
TOP=${TOP:-10}
GRID_HOURS=${GRID_HOURS:-3}
F1_EXTRAS=${F1_EXTRAS:-0}   # 1 also saves the F1 walk-forward and 4 default sweeps (about 2 h on 2 vCPU; not on the 3x3 path)
LOGS=data/runs/logs
mkdir -p "$LOGS" data/backups/db
UTC=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$LOGS/overnight-$MODE-$UTC.log
DONE=$LOGS/overnight-$MODE.done
FAILED=$LOGS/overnight-$MODE.failed
rm -f "$DONE" "$FAILED"
exec > >(tee -a "$LOG") 2>&1
# Progress (owner, 2026-09-30: clear but not too frequent): one line when each phase starts (which also closes the one
# before), a heartbeat every HEARTBEAT_MIN minutes inside a phase, and a line at once on any failure or STOP. Each line
# is appended to overnight-progress.log and is the whole of overnight-status.txt (latest state only). Local files only.
PROGRESS=$LOGS/overnight-progress.log
STATUS=$LOGS/overnight-status.txt
PHASE_F=$LOGS/.overnight-phase
HEARTBEAT_MIN=${HEARTBEAT_MIN:-45}
T_RUN=$(date +%s)
FAILS_F=$LOGS/.overnight-fails
echo 0 > "$FAILS_F"
fail() { echo $(( $(cat "$FAILS_F" 2>/dev/null || echo 0) + 1 )) > "$FAILS_F"; }
progress() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%MZ) [$MODE, $(( ($(date +%s) - T_RUN) / 60 )) min in, $(cat "$FAILS_F" 2>/dev/null || echo 0) failed] $*"
  echo "$line" >> "$PROGRESS" || true
  echo "$line" > "$STATUS" || true
  echo "$line"
}
phase_line() {       # "<phase>, <minutes> min" plus job counts, from the phase file
  local name t0
  name=$(cut -d'|' -f2- "$PHASE_F" 2>/dev/null) || return 0
  t0=$(cut -d'|' -f1 "$PHASE_F" 2>/dev/null) || return 0
  echo "$name, $(( ($(date +%s) - t0) / 60 )) min$(.venv/bin/python scripts/vm/progress.py "$name" "$t0" 2>/dev/null || true)"
}
stop() { fail; progress "STOP: $*"; }
trap 'fail; progress "FAILED at line $LINENO during: $(phase_line)"; echo "$LOG line $LINENO" > "$FAILED"' ERR
trap 'kill "${HB:-0}" 2>/dev/null || true; rm -f "$PHASE_F" "$FAILS_F"' EXIT
( trap - ERR EXIT; set +e
  while sleep "${HEARTBEAT_SEC:-$(( HEARTBEAT_MIN * 60 ))}"; do
    [ -f "$PHASE_F" ] && progress "still running: $(phase_line)"
  done ) &
HB=$!
R=.venv/bin/racinglines
PY=.venv/bin/python
QUEUE=sweeps/overnight-vm.toml
A_ARGS=(--taker-stages "after FP1,after FP2,after FP3,after SQ,after Sprint,after Quali" --min-edge 0.1 --min-edge-h2h 0.05)
Q() { docker compose exec -T db psql -U racinglines racinglines -c "$1"; }
say() {             # a phase starts: close the one before, log the new one
  local prev=""
  if [ -f "$PHASE_F" ]; then prev="done: $(phase_line); "; fi
  echo "$(date +%s)|$*" > "$PHASE_F"
  echo "== $(date -u +%H:%M:%SZ) $*"
  progress "${prev}started: $*"
}

LIVE=$(systemctl list-units --no-legend --plain --state=active,activating 'racinglines-live-*' || true)
if [ -n "$LIVE" ]; then
  progress "not starting: a live-event unit is active"
  echo "$LIVE"
  echo "live event active" > "$FAILED"
  exit 1
fi

machine() {
  echo "cores $(nproc), memory $(free -g | awk '/^Mem:/ {print $2}') GB, free disk $(df -BG --output=avail . | tail -1 | tr -d ' ')"
  if [ "$(nproc)" -lt 2 ] || [ "$(free -g | awk '/^Mem:/ {print $2}')" -lt 6 ]; then echo "WARNING: under 2 cores or 6 GB: the F1 search runs 2 at once and will be slow or run out of memory (plan: resize first)"; fi
  if [ "$(df -BG --output=avail . | tail -1 | tr -dc 0-9)" -lt 5 ]; then echo "less than 5 GB free disk: not starting"; return 1; fi
}
counts() {
  Q "SELECT co.code, s.year, count(DISTINCT e.id) AS races FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id WHERE e.status = 'completed' AND s.year >= 2024 GROUP BY 1, 2 ORDER BY 1, 2"
  Q "SELECT co.code, ml.exchange, count(*) AS links, count(ml.race_id) AS with_race FROM market_links ml JOIN competitions co ON co.id = ml.competition_id GROUP BY 1, 2 ORDER BY 1, 2"
  Q "SELECT 'model_runs' AS t, count(*) FROM model_runs UNION ALL SELECT 'race_predictions', count(*) FROM race_predictions UNION ALL SELECT 'market_trades', count(*) FROM market_trades UNION ALL SELECT 'market_price_history', count(*) FROM market_price_history"
}
backup() {
  B=data/backups/db/racinglines-before-overnight-$1-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B"
  gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'
  progress "backup $B ($(du -h "$B" | cut -f1))"
}
golden() {
  say "F1 golden check (profile A, 2026, not saved; passes if update P&L is +843 to +1,643)"
  nice $R f1 --variant gridq+pretrain+reset sweep --year 2026 --no-fetch "${A_ARGS[@]}"
}
f1() {
  backup f1
  START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  say "F1 broad sweep (4k)"
  nice $R f1 search "$QUEUE"
  nice $R f1 search-report "$QUEUE"
  $PY scripts/vm/promote_16k.py "$QUEUE" --top "$TOP"
  say "F1 top $TOP at 16k"
  nice $R f1 search "$QUEUE"
  nice $R f1 search-report "$QUEUE"
  cp "$QUEUE" data/runs/search/overnight-vm/queue-promoted.toml
  git checkout -- "$QUEUE"                         # keep the checkout clean for the next vm.sh deploy
  EXTRAS="not run (F1_EXTRAS=0)"
  if [ "$F1_EXTRAS" = 1 ]; then
    say "F1 walk-forward and default sweeps, saved"
    nice $R backtest walk-forward f1 --save
    nice $R f1 sweep --year 2025 --no-fetch --save --reliability
    nice $R f1 sweep --year 2026 --no-fetch --save --reliability
    nice $R f1 sweep --year 2025 --no-fetch --venue kalshi --save --reliability
    nice $R f1 sweep --year 2026 --no-fetch --venue kalshi --save --reliability
    EXTRAS="saved"
  fi
  Q "SELECT model, kind, count(*) FROM model_runs WHERE created_at >= '$START' GROUP BY 1, 2 ORDER BY 1, 2"
  $R db changes --add "Overnight F1 on the VM from $START: search overnight-vm (broad at 4k, top $TOP at 16k; data/runs/search/overnight-vm/), f1 walk-forward and default sweeps 2025-2026 on polymarket and kalshi $EXTRAS; backup $B"
}
replay() {
  $PY -c "import sys; from racinglines.markets.kalshi.sync import history_rows as h; sys.exit(0 if not h('t', [dict(yes_bid=dict(close=0), yes_ask=dict(close=100), end_period_ts=0)]) else 1)" \
    || { stop "this checkout still stores an empty Kalshi book's candle as a 0.50 price (kalshi/sync.py history_rows): deploy the candle fix before pulling tape"; return 1; }
  backup replay
  START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  for S in $SPORTS; do
    say "$S: links, tape, replay"
    nice $R markets --exchange kalshi --sport "$S" sync --year 2025 --closed
    nice $R markets --exchange kalshi --sport "$S" sync --year 2026 --closed
    nice $R markets --sport "$S" sync --year 2025 --closed
    nice $R markets --sport "$S" sync --year 2026 --closed
    nice $R "$S" replay --years 2016-2026 --venue kalshi --tape pull --backup "$B" --require-tradeable
    nice $R "$S" replay --years 2016-2026 --venue polymarket --tape pull --backup "$B"
    $PY scripts/vm/replay_grid.py spikes "$S" kalshi
    $PY scripts/vm/replay_grid.py spikes "$S" polymarket || true
    say "$S: replay saves"
    RACINGLINES_PREDICTION_RECORDS=1 nice $R "$S" replay --years 2016-2026 --save --backup "$B"
    say "$S: settings grid on Kalshi (read-only), stops starting runs after $GRID_HOURS h"
    G=data/runs/replay-grid/$S
    mkdir -p "$G"
    T0=$(date +%s)
    for Y in 2026 2025; do for E in 0.05 0.08 0.10 0.15; do for V in 50 200; do
      if [ $(( $(date +%s) - T0 )) -gt $(( GRID_HOURS * 3600 )) ]; then echo "grid: time up, skipping $Y e$E v$V"; continue; fi
      nice $R "$S" replay --years "$Y" --venue kalshi --min-edge "$E" --min-volume "$V" --out "$G/$Y-e$E-v$V" > "$G/$Y-e$E-v$V.log" 2>&1 \
        || { fail; progress "grid run failed: $S $Y edge $E floor $V (see $G/$Y-e$E-v$V.log)"; }
    done; done; done
    $PY scripts/vm/replay_grid.py rank "$G" --top 3 | tee "$G/rank.txt"
    { grep '^TOP ' "$G/rank.txt" || true; } | while read -r _ E V; do for Y in 2026 2025; do
      nice $R "$S" replay --years "$Y" --venue kalshi --min-edge "$E" --min-volume "$V" --sims 16000 --out "$G/$Y-e$E-v$V-s16000" > "$G/$Y-e$E-v$V-s16000.log" 2>&1 \
        || { fail; progress "grid 16k run failed: $S $Y edge $E floor $V"; }
    done; done
    $PY scripts/vm/replay_grid.py rank "$G" --top 3
  done
  say "OG.com: buy-all on its recorded prices (read-only; OG.com lists only season markets, no MotoGP)"
  if grep -q '"buy-all"' racinglines/cli/markets.py; then
    mkdir -p data/runs/replay-grid/og
    for S in f1 nascar; do
      nice $R markets --exchange og --sport "$S" buy-all --out "data/runs/replay-grid/og/$S.csv" || { fail; progress "OG.com buy-all $S failed (see the log)"; }
    done
  else
    echo "OG.com: this checkout has no buy-all (PR #88 not deployed): skipped"
  fi
  counts
  grep -h "batch replay-" "$LOG" || true
  $R db changes --add "Overnight replay on the VM from $START: $SPORTS link syncs (closed included), tape pulls, replay saves (batches in $LOG), read-only settings grid in data/runs/replay-grid/; backup $B"
}

story() {
  $PY -c "import inspect, sys; from racinglines.pipelines import story; sys.exit(0 if 'taker' in inspect.signature(story.decisions).parameters else 1)" \
    || { stop "no taker story in this checkout: merge PR #87 and run vm.sh deploy first"; return 1; }
  B=data/backups/db/racinglines-before-demo-taker-story-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B"
  gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'
  progress "backup $B ($(du -h "$B" | cut -f1))"
  START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  say "demo taker story: evidence sweeps"
  mkdir -p data/runs/search
  nice $R f1 search sweeps/demo-taker-story.toml > data/runs/search/demo-taker-story.log 2>&1
  tail -n 1 data/runs/search/demo-taker-story.log
  grep -Eq "search: finished \((1[6-9]|[2-9][0-9]) done\)" data/runs/search/demo-taker-story.log \
    || { stop "the evidence search didn't finish 16 sweeps (data/runs/search/demo-taker-story.log): nothing reset"; return 1; }
  say "demo taker story: gate"
  $PY scripts/vm/story_gate.py || { stop "the taker story's gate: the taker's backfill was not reset"; return 1; }
  say "demo taker story: rebuild the taker's backfill (taker only)"
  nice $R f1 demo-history --reset --user taker
  $R db changes --add "Demo taker walk-forward story on the VM from $START: evidence sweeps (search demo-taker-story), gate passed, taker backfill rebuilt with f1 demo-history --reset --user taker (TW1 2025 r1-8, TW2 from r9); backup $B"
}

say "$MODE run for $SPORTS: checks and counts"
machine
counts
case "$MODE" in
  dry)
    for S in $SPORTS; do
      $PY scripts/vm/replay_grid.py spikes "$S" kalshi || true
      nice $R "$S" replay --years 2026 --events latest --tape probe
      nice $R "$S" replay --years 2026 --events latest
    done
    golden
    echo "dry run done: nothing written" ;;
  f1) f1 ;;
  replay) replay ;;
  story) story ;;
  all) f1; replay; story ;;
  *) echo "MODE must be dry, f1, replay, story or all"; exit 1 ;;
esac
echo "mode=$MODE sports=$SPORTS log=$LOG" > "$DONE"
progress "done: $(phase_line); FINISHED, marker $DONE"
rm -f "$PHASE_F"
