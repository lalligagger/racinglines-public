#!/usr/bin/env bash
# Race-win calibration of a results-level sport (default NASCAR; C48 at the results level, docs/f1-calibration.md
# "Other sports"): fit the walk-forward table, score the race-win log loss before and after it and beside each venue's
# price, then run the season sweep without and with it so P&L and CLV (metrics.clv) can be read side by side.
#
# Read-only on the database: every connection is opened with default_transaction_read_only=on (PGOPTIONS), so it can
# read staging's live mirror of production. The fitted table goes to the output folder; for the "on" sweeps it is
# copied to sports/<sport>/calibration.toml in this checkout and removed again at the end (never committed from here).
#
#   SPORT=nascar  SEASONS="2023 2024 2025 2026" (races fitted)  SIMS=4000  SWEEP_YEARS="2025 2026"
#   VENUES="polymarket kalshi"  APP=/opt/racinglines-staging  ENV_FILE=/etc/racinglines-staging.env
#
# Run on the VM as a transient unit (prints a progress line at least every 5 minutes):
#   sudo systemd-run --unit=rl-nascar-calib --uid=racinglines /opt/racinglines-staging/scripts/vm/nascar_calibration.sh
#   journalctl -fu rl-nascar-calib
# Output: data/runs/<sport>/calibration-<UTC>/ (fit.log, calibration.toml, report.md, races.csv, vs_<venue>.csv,
# sweep-<year>-<venue>-<off|on>.txt, summary.md).
set -uo pipefail
SPORT=${SPORT:-nascar}
SEASONS=${SEASONS:-2023 2024 2025 2026}
SIMS=${SIMS:-4000}
SWEEP_YEARS=${SWEEP_YEARS:-2025 2026}
VENUES=${VENUES:-polymarket kalshi}
APP=${APP:-/opt/racinglines-staging}
ENV_FILE=${ENV_FILE:-/etc/racinglines-staging.env}
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1 PGOPTIONS="-c default_transaction_read_only=on"
cd "$APP"
PY=.venv/bin/python
R=.venv/bin/racinglines
OUT=data/runs/$SPORT/calibration-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$OUT"
LOG=$OUT/run.log
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }
T0=$SECONDS
( while sleep 300; do say "progress: $(( (SECONDS - T0) / 60 )) min elapsed"; done ) &
BEAT=$!
TABLE=sports/$SPORT/calibration.toml
PLACED=""
cleanup() { kill "$BEAT" 2>/dev/null; [ -n "$PLACED" ] && rm -f "$TABLE" && rmdir "sports/$SPORT" 2>/dev/null; true; }
trap cleanup EXIT

say "$SPORT calibration from $(git rev-parse --short HEAD) on ${DATABASE_URL##*/} (read-only) -> $OUT"
# shellcheck disable=SC2086
if ! $PY scripts/models/fit_calibration.py --sport "$SPORT" --seasons $SEASONS --sims "$SIMS" --check \
     --out "$OUT/calibration.toml" --report "$OUT" 2>&1 | tee -a "$OUT/fit.log"; then
  say "STOP: the fit failed (fit.log)"; exit 1
fi
[ -s "$OUT/calibration.toml" ] || { say "STOP: no table written"; exit 1; }
say "fit done: $(grep -c '^\[\[fit\]\]' "$OUT/calibration.toml") rows"

if [ -e "$TABLE" ]; then
  say "$TABLE already exists in this checkout: the 'on' sweeps use it as it is (not the table just fitted)"
else
  mkdir -p "sports/$SPORT" && cp "$OUT/calibration.toml" "$TABLE" && PLACED=1
fi
rc=0
for y in $SWEEP_YEARS; do
  for v in $VENUES; do
    for mode in off on; do
      f=$OUT/sweep-$y-$v-$mode.txt
      extra=(); [ "$mode" = on ] && extra=(--calib-power walk_forward)
      say "sweep $y $v calibration $mode: started"
      if nice $R strategy sweep "$SPORT" --year "$y" --venue "$v" --reliability "${extra[@]}" > "$f" 2>&1; then
        say "sweep $y $v calibration $mode: done"
      else
        rc=1; say "sweep $y $v calibration $mode: FAILED: $(tail -n 2 "$f" | tr '\n' ' ')"
      fi
    done
  done
done

{
  echo "# $SPORT calibration run $(basename "$OUT")"
  echo
  cat "$OUT/report.md"
  echo
  echo "## Season sweeps, calibration off and on (P&L and CLV per strategy, as the sweep prints them)"
  for f in "$OUT"/sweep-*.txt; do
    echo
    echo "### $(basename "$f" .txt)"
    echo
    echo '```'
    grep -E "^=== $SPORT|P&L .* races up" "$f" || echo "(no totals: see the file)"
    echo '```'
  done
} > "$OUT/summary.md"
say "summary: $OUT/summary.md"
say "NASCAR-CALIB-DONE (exit $rc)"
exit $rc
