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
#   VENUES="polymarket kalshi" (scored in the fit report)  SWEEP_VENUES="kalshi" (swept)
#   FILL="--taker-fill touch"  SELL_FLOORS="none edge"  APP=/opt/racinglines-staging  ENV_FILE=/etc/racinglines-staging.env
#
# Only Kalshi is swept by default: NASCAR's Polymarket race-win books are near-empty (Charlotte 2026: about $38 of taker
# trades over the last 2.5 days across 38 drivers, prices that are mids of empty books summing to 9 to 17), so the
# sweep's volume and coherence filters leave nothing to trade there. Each sweep runs with sell_floor none and edge
# (#225; edge is in-sample only, so both are reported), calibration off and on.
#
# Run on the VM as a transient unit (prints a progress line at least every 5 minutes):
#   sudo systemd-run --unit=rl-nascar-calib --uid=racinglines /opt/racinglines-staging/scripts/vm/nascar_calibration.sh
#   journalctl -fu rl-nascar-calib
# Output (needs closing-line value in the sweep, #223): data/runs/<sport>/calibration-<UTC>/ (fit.log, calibration.toml, report.md, races.csv, vs_<venue>.csv,
# sweep-<year>-<venue>-floor_<none|edge>-calib_<off|on>.txt, summary.md).
set -uo pipefail
SPORT=${SPORT:-nascar}
SEASONS=${SEASONS:-2023 2024 2025 2026}
SIMS=${SIMS:-4000}
SWEEP_YEARS=${SWEEP_YEARS:-2025 2026}
VENUES=${VENUES:-polymarket kalshi}
SWEEP_VENUES=${SWEEP_VENUES:-kalshi}
FILL=${FILL:---taker-fill touch}
SELL_FLOORS=${SELL_FLOORS:-none edge}
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
  for v in $SWEEP_VENUES; do
    for sf in $SELL_FLOORS; do
      for mode in off on; do
        name=$y-$v-floor_$sf-calib_$mode
        f=$OUT/sweep-$name.txt
        # shellcheck disable=SC2086
        extra=($FILL --sell-floor "$sf"); [ "$mode" = on ] && extra+=(--calib-power walk_forward)
        say "sweep $name: started"
        if nice $R strategy sweep "$SPORT" --year "$y" --venue "$v" --reliability "${extra[@]}" > "$f" 2>&1; then
          say "sweep $name: done"
        else
          rc=1; say "sweep $name: FAILED: $(tail -n 2 "$f" | tr '\n' ' ')"
        fi
      done
    done
  done
done

{
  echo "# $SPORT calibration run $(basename "$OUT")"
  echo
  cat "$OUT/report.md"
  echo
  echo "## Season sweeps, calibration off and on (P&L and CLV per strategy, as the sweep prints them)"
  echo
  echo "Venues swept: $SWEEP_VENUES. Fill: $FILL. Sell floor: $SELL_FLOORS."
  for f in "$OUT"/sweep-*.txt; do
    echo
    echo "### $(basename "$f" .txt)"
    echo
    echo '```'
    grep -E "^=== $SPORT|P&L .* races up" "$f" || echo "(no totals: see the file)"
    echo
    # --reliability: Brier, log loss and ECE of the model and the market, every tradeable stage
    awk '/^=== Calibration/{on=1} on&&/^=== /&&!/^=== Calibration/{on=0} on' "$f"
    echo '```'
  done
} > "$OUT/summary.md"
say "summary: $OUT/summary.md"
say "NASCAR-CALIB-DONE (exit $rc)"
exit $rc
