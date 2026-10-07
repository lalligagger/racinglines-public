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
#   sports  replay, then story (skips F1).
#   all     replay, then story, then f1, in one unit (the sports first: F1 has been backtested for days).
#
# Preflight (every mode, first minute): each sport's event count and its Kalshi links with a race attached. dry
# flags a sport with 0 of either as NOT READY; replay loads its results and identifies its links first (after the
# backup), and skips the sport with a STOP line if it is still not ready. A sport's untradeable Kalshi pull skips
# that sport, not the rest of the run.
#
# Every writing mode backs up first and checks the dump's trailer. Log: data/runs/logs/overnight-<mode>-<UTC>.log;
# markers overnight-<mode>.done / .failed. Refuses to start while a racinglines-live-* unit is active.
# Downhill is not run (owner, 2026-09-30). Nothing here touches the trading flags, a migration or the bucket.
set -eEuo pipefail
# TARGET=staging runs the same steps against staging (owner, 2026-10-07: parity rebuild on staging first): its env file,
# checkout and database, and staging's live units. The database container is production's, so DC (docker compose)
# always runs from /opt/racinglines. TARGET=prod, the default, is unchanged.
TARGET=${TARGET:-prod}
case "$TARGET" in
  prod)    ENV_FILE=/etc/racinglines.env;         APP=/opt/racinglines;         DB=racinglines;         LIVE_GLOB='racinglines-live-*' ;;
  staging) ENV_FILE=/etc/racinglines-staging.env; APP=/opt/racinglines-staging; DB=racinglines_staging; LIVE_GLOB='racinglines-staging-live-*' ;;
  *) echo "TARGET must be prod or staging, not $TARGET"; exit 2 ;;
esac
DC() { (cd /opt/racinglines && docker compose "$@"); }
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1   # the commands' own per-race and per-job lines reach the log as they happen, not in 8 KB blocks
cd "$APP"
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
# Progress (owner, 2026-09-30: clear but not too frequent; more inside a phase after the 12:59Z-13:44Z silence): one
# line when each phase starts (which also closes the one before), one when each step inside a phase starts (which
# closes the step before), a heartbeat every HEARTBEAT_MIN minutes inside a phase with the step, its race or job counter
# and the log's last line and age (QUIET after QUIET_MIN minutes without output), a summary line per sport, and a line
# at once on any failure or STOP. Each line is appended to overnight-progress.log and is the whole of
# overnight-status.txt (latest state only). Local files only.
PROGRESS=$LOGS/overnight-progress.log
STATUS=$LOGS/overnight-status.txt
PHASE_F=$LOGS/.overnight-phase
STEP_F=$LOGS/.overnight-step
HEARTBEAT_MIN=${HEARTBEAT_MIN:-5}   # owner rule 2026-09-30: a progress line at least every 5 minutes
QUIET_MIN=${QUIET_MIN:-30}
T_RUN=$(date +%s)
FAILS_F=$LOGS/.overnight-fails
echo 0 > "$FAILS_F"
fail() { echo $(( $(cat "$FAILS_F" 2>/dev/null || echo 0) + 1 )) > "$FAILS_F"; }
progress() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%MZ) [$MODE, $(( ($(date +%s) - T_RUN) / 60 )) min in, $(cat "$FAILS_F" 2>/dev/null || echo 0) failed] $*"
  echo "$line" >> "$PROGRESS" || true
  echo "$line" > "$STATUS" || true
  [ -n "${NO_ECHO:-}" ] || echo "$line"   # the heartbeat stays out of the run log, so the log's age is real output only
}
phase_line() {       # "<phase>, <minutes> min" plus the current step and job or race counts, from the phase and step files
  local name t0 step="" s0=""
  name=$(cut -d'|' -f2- "$PHASE_F" 2>/dev/null) || return 0
  t0=$(cut -d'|' -f1 "$PHASE_F" 2>/dev/null) || return 0
  if [ -f "$STEP_F" ]; then
    s0=$(cut -d'|' -f1 "$STEP_F" 2>/dev/null || true)
    step=" · step $(cut -d'|' -f2 "$STEP_F" 2>/dev/null || true): $(cut -d'|' -f3- "$STEP_F" 2>/dev/null || true), $(( ($(date +%s) - ${s0:-$t0}) / 60 )) min"
  fi
  echo "$name, $(( ($(date +%s) - t0) / 60 )) min$step$(.venv/bin/python scripts/vm/progress.py "$name" "$t0" "$LOG" "$s0" 2>/dev/null || true)"
}
last_output() {      # "last output N min ago: <the run log's last line>", QUIET after QUIET_MIN minutes
  local age last
  age=$(( ($(date +%s) - $(stat -c %Y "$LOG" 2>/dev/null || date +%s)) / 60 ))
  last=$(tail -c 4000 "$LOG" 2>/dev/null | tr '\r' '\n' | grep -v '^[[:space:]]*$' | tail -n 1 | cut -c1-160 || true)
  echo "$([ "$age" -ge "$QUIET_MIN" ] && echo 'QUIET: ')last output $age min ago: $last"
}
step() {             # a step inside a phase starts: "step <n>: <what> (step <n-1> took <m> min)"
  local n=1 took=""
  if [ -f "$STEP_F" ]; then
    n=$(( $(cut -d'|' -f2 "$STEP_F") + 1 ))
    took=" (step $(( n - 1 )) took $(( ($(date +%s) - $(cut -d'|' -f1 "$STEP_F")) / 60 )) min)"
  fi
  echo "$(date +%s)|$n|$*" > "$STEP_F"
  echo "-- $(date -u +%H:%M:%SZ) step $n: $*"
  progress "step $n: $*$took"
}
stop() { fail; progress "STOP: $*"; }
trap 'fail; progress "FAILED at line $LINENO during: $(phase_line) · $(last_output)"; echo "$LOG line $LINENO" > "$FAILED"' ERR
trap 'kill "${HB:-0}" 2>/dev/null || true; rm -f "$PHASE_F" "$STEP_F" "$FAILS_F"' EXIT
( trap - ERR EXIT; set +e
  while sleep "${HEARTBEAT_SEC:-$(( HEARTBEAT_MIN * 60 ))}"; do
    [ -f "$PHASE_F" ] && NO_ECHO=1 progress "still running: $(phase_line) · $(last_output)"
  done ) &
HB=$!
R=.venv/bin/racinglines
PY=.venv/bin/python
QUEUE=sweeps/overnight-vm.toml
A_ARGS=(--taker-stages "after FP1,after FP2,after FP3,after SQ,after Sprint,after Quali" --min-edge 0.1 --min-edge-h2h 0.05)
Q() { DC exec -T db psql -U racinglines "$DB" -c "$1"; }
code_of() { case "$1" in nascar) echo nascar_cup ;; motogp) echo motogp_wc ;; *) echo "$1" ;; esac; }
ready() {            # "<events> <Kalshi links with a race>" for one sport (read-only)
  local co; co=$(code_of "$1")
  DC exec -T db psql -U racinglines "$DB" -tA -F' ' -c "SELECT
    (SELECT count(*) FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id WHERE co.code = '$co'),
    (SELECT count(*) FROM market_links ml JOIN competitions co ON co.id = ml.competition_id WHERE co.code = '$co' AND ml.exchange = 'kalshi' AND ml.race_id IS NOT NULL)"
}
sport_ready() {      # prints the preflight line; true if the sport has events and identified Kalshi links
  local ev id; read -r ev id <<< "$(ready "$1")"
  progress "preflight $1: ${ev:-0} events, ${id:-0} Kalshi links with a race"
  [ "${ev:-0}" -gt 0 ] && [ "${id:-0}" -gt 0 ]
}
prep() {             # load a sport's results and identify its Kalshi links (writes: runs after replay's backup)
  local S=$1
  say "$S: results and link identity (the database had none)"
  step "$S results fetch 2016-2026"
  if [ "$S" = nascar ]; then
    nice $R nascar fetch --years 2016-2026 --feeds race_list_basic,points-feed,weekend-feed || true
    step "$S results ingest 2016-2026"
    nice $R nascar ingest --years 2016-2026 --no-laps
  else
    nice $R motogp fetch --years 2016-2026 || true
    step "$S results ingest 2025-2026 (the seasons with Kalshi markets), then 2016-2024"
    # Newest first: ingest commits per event and stops at the first error, and the older seasons' pages have not
    # been ingested anywhere yet (the 2026-09-30 sports run failed here). An older season's error is logged, not fatal.
    nice $R motogp ingest --years 2025-2026
    nice $R motogp ingest --years 2016-2024 || progress "motogp ingest 2016-2024 failed (see the log): going on with 2025-2026"
  fi
  step "$S Kalshi link sync 2025, 2026"
  nice $R markets --exchange kalshi --sport "$S" sync --year 2025 --closed
  nice $R markets --exchange kalshi --sport "$S" sync --year 2026 --closed
  if [ "$S" = nascar ]; then step "nascar link --apply"; nice $R nascar link --apply --backup "$B"; fi
  $R db changes --add "Overnight run: $S results fetched and ingested 2016-2026, Kalshi links re-synced$([ "$S" = nascar ] && echo ' and identified (nascar link --apply)'); backup $B"
}
say() {             # a phase starts: close the one before, log the new one
  local prev=""
  if [ -f "$PHASE_F" ]; then prev="done: $(phase_line); "; fi
  echo "$(date +%s)|$*" > "$PHASE_F"
  rm -f "$STEP_F"
  echo "== $(date -u +%H:%M:%SZ) $*"
  progress "${prev}started: $*"
}
tally() {           # "<what>: <the last Pulled / Stored line since the sport started>" (read from the run log)
  local got
  got=$(tail -n +"$2" "$LOG" | grep -E '^(Pulled|Stored) ' | tail -n 1 || true)
  [ -z "$got" ] || progress "$1: $got"
}
sport_done() {      # one summary line per sport: "<sport> <finished|skipped> in <m> min · <tape and save counts>"
  local got
  got=$(tail -n +"$3" "$LOG" | grep -E '^(Pulled|Stored) ' | cut -d'.' -f1 | paste -sd ';' - | sed 's/;/; /g' || true)
  progress "sport $1 $4 in $(( ($(date +%s) - $2) / 60 )) min${got:+ · $got}"
}

LIVE=$(systemctl list-units --no-legend --plain --state=active,activating "$LIVE_GLOB" || true)
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
  B=data/backups/db/$DB-before-overnight-$1-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
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
    step "F1 walk-forward"
    nice $R backtest walk-forward f1 --save
    step "F1 sweep 2025 Polymarket"
    nice $R f1 sweep --year 2025 --no-fetch --save --reliability
    step "F1 sweep 2026 Polymarket"
    nice $R f1 sweep --year 2026 --no-fetch --save --reliability
    step "F1 sweep 2025 Kalshi"
    nice $R f1 sweep --year 2025 --no-fetch --venue kalshi --save --reliability
    step "F1 sweep 2026 Kalshi"
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
  local NS I=0 T_S L_S
  NS=$(wc -w <<< "$SPORTS")
  for S in $SPORTS; do
    I=$(( I + 1 )); T_S=$(date +%s); L_S=$(( $(wc -l < "$LOG") + 1 ))
    progress "sport $I of $NS: $S"
    if ! sport_ready "$S"; then
      prep "$S" || progress "$S: loading results failed (see the log); the preflight below decides"
      if ! sport_ready "$S"; then stop "$S still has no events or no Kalshi links with a race after loading its results: skipped"; sport_done "$S" "$T_S" "$L_S" skipped; continue; fi
    fi
    say "$S: links, tape, replay"
    step "$S Kalshi link sync 2025, 2026"
    nice $R markets --exchange kalshi --sport "$S" sync --year 2025 --closed
    nice $R markets --exchange kalshi --sport "$S" sync --year 2026 --closed
    step "$S Polymarket link sync 2025, 2026"
    nice $R markets --sport "$S" sync --year 2025 --closed
    nice $R markets --sport "$S" sync --year 2026 --closed
    step "$S Kalshi tape pull and replay 2016-2026"
    nice $R "$S" replay --years 2016-2026 --venue kalshi --tape pull --backup "$B" --require-tradeable \
      || { stop "$S: no tradeable Kalshi market (see the log's NO MARKETS / NO TAPE / NOT TRADED lines): skipped"; sport_done "$S" "$T_S" "$L_S" skipped; continue; }
    tally "$S Kalshi" "$L_S"
    step "$S Polymarket tape pull and replay 2016-2026"
    nice $R "$S" replay --years 2016-2026 --venue polymarket --tape pull --backup "$B"
    tally "$S Polymarket" "$L_S"
    step "$S price-spike check"
    $PY scripts/vm/replay_grid.py spikes "$S" kalshi
    $PY scripts/vm/replay_grid.py spikes "$S" polymarket || true
    say "$S: replay saves"
    RACINGLINES_PREDICTION_RECORDS=1 nice $R "$S" replay --years 2016-2026 --save --backup "$B"
    tally "$S saves" "$L_S"
    say "$S: settings grid on Kalshi (read-only), stops starting runs after $GRID_HOURS h"
    G=data/runs/replay-grid/$S
    mkdir -p "$G"
    T0=$(date +%s)
    for Y in 2026 2025; do for E in 0.05 0.08 0.10 0.15; do for V in 50 200; do
      if [ $(( $(date +%s) - T0 )) -gt $(( GRID_HOURS * 3600 )) ]; then echo "grid: time up, skipping $Y e$E v$V"; continue; fi
      nice $R "$S" replay --years "$Y" --venue kalshi --min-edge "$E" --min-volume "$V" --out "$G/$Y-e$E-v$V" > "$G/$Y-e$E-v$V.log" 2>&1 \
        || { fail; progress "grid run failed: $S $Y edge $E floor $V (see $G/$Y-e$E-v$V.log)"; }
    done; done; done
    step "$S grid ranking"
    $PY scripts/vm/replay_grid.py rank "$G" --top 3 | tee "$G/rank.txt"
    progress "$S grid top 3 (edge, floor): $(grep '^TOP ' "$G/rank.txt" | cut -d' ' -f2- | paste -sd ';' - | sed 's/;/; /g' || true)"
    step "$S grid top 3 at 16k (6 runs)"
    { grep '^TOP ' "$G/rank.txt" || true; } | while read -r _ E V; do for Y in 2026 2025; do
      nice $R "$S" replay --years "$Y" --venue kalshi --min-edge "$E" --min-volume "$V" --sims 16000 --out "$G/$Y-e$E-v$V-s16000" > "$G/$Y-e$E-v$V-s16000.log" 2>&1 \
        || { fail; progress "grid 16k run failed: $S $Y edge $E floor $V"; }
    done; done
    $PY scripts/vm/replay_grid.py rank "$G" --top 3
    sport_done "$S" "$T_S" "$L_S" finished
  done
  say "OG.com: buy-all on its recorded prices (read-only; OG.com lists only season markets, no MotoGP)"
  if grep -q '"buy-all"' racinglines/cli/markets.py; then
    mkdir -p data/runs/replay-grid/og
    for S in f1 nascar; do
      step "OG.com buy-all $S"
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
  B=data/backups/db/$DB-before-demo-taker-story-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
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
NOT_READY=""
for S in $SPORTS; do if ! sport_ready "$S"; then NOT_READY="$NOT_READY $S"; fi; done
if [ -n "$NOT_READY" ]; then progress "NOT READY:$NOT_READY (0 events or 0 Kalshi links with a race)$([ "$MODE" = dry ] || echo '; replay loads their results first')"; fi
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
  sports) replay; story ;;
  all) replay; story; f1 ;;
  *) echo "MODE must be dry, f1, replay, story, sports or all"; exit 1 ;;
esac
echo "mode=$MODE sports=$SPORTS log=$LOG" > "$DONE"
progress "done: $(phase_line); FINISHED, marker $DONE"
rm -f "$PHASE_F"
