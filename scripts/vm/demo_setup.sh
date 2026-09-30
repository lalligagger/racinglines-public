#!/usr/bin/env bash
# The multi-sport demo's paper rows (docs/paper-trading.md, "NASCAR and MotoGP"). Run on the VM as a transient systemd
# unit, never by hand in an SSH shell; the owner starts it with `bash scripts/deploy/vm.sh demo`, which runs:
#
#   sudo systemd-run --unit=rl-demo --uid=racinglines --setenv=RACINGLINES_SPORT_PAPER=1 /opt/racinglines/scripts/vm/demo_setup.sh
#
# Backup first (checked), then for NASCAR and MotoGP: the selection from the overnight settings grid
# (data/runs/replay-grid/<sport>, read-only), then `<sport> demo-history --grid ... --users maker,taker`: the taker
# replay's `update` trades stored as both demo accounts' backfilled paper positions on Kalshi (in-sample, labelled so;
# never buy_all). BOOK=best (default, best effort): each kind at its best total, else every kind at the best total, win
# or lose, so both sports get a record; BOOK=kinds is the strict rule (both seasons positive). The Pro account (maker) then shows its F1 maker record and the NASCAR / MotoGP taker record side by
# side. STEPS (default "kalshi polymarket forecast"): polymarket stores the same demo on Polymarket's NASCAR / MotoGP
# tape with the Kalshi grid's selection; forecast stores `<sport> forecast --save`, the model's price for the next
# scheduled races (the board's live prices). A sport with no grid is skipped with a SKIP line. Each run records a data_changes row naming the backup.
#
# Log: data/runs/logs/demo-setup-<UTC>.log; markers demo-setup.done / .failed. Refuses to start while a
# racinglines-live-* unit is active. Undo: `racinglines <sport> demo-history --reset --users maker,taker --backup FILE`.
# Touches no trading flag, no migration, no bucket, and never the F1 demo history.
set -eEuo pipefail
set -a; . /etc/racinglines.env; set +a
export PYTHONUNBUFFERED=1 RACINGLINES_SPORT_PAPER=1
cd /opt/racinglines
USERS=${USERS:-maker,taker}
STEPS=${STEPS:-kalshi polymarket forecast}   # vm.sh demo extra: STEPS="polymarket forecast"
BOOK=${BOOK:-best}   # best effort (owner 2026-09-30: paper P&L for as many sports as possible); kinds = the strict rule
LOGS=data/runs/logs
mkdir -p "$LOGS" data/backups/db
UTC=$(date -u +%Y%m%dT%H%M%SZ)
LOG=$LOGS/demo-setup-$UTC.log
DONE=$LOGS/demo-setup.done
FAILED=$LOGS/demo-setup.failed
rm -f "$DONE" "$FAILED"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "DEMO-SETUP FAILED at line $LINENO (log $LOG)"; date -u > "$FAILED"' ERR
R=.venv/bin/racinglines
if systemctl list-units --no-legend --plain --state=active,activating 'racinglines-live-*' | grep -q .; then
  echo "not starting: a live-event unit is active"; date -u > "$FAILED"; exit 1
fi
B=data/backups/db/racinglines-before-demo-setup-$UTC.sql.gz
docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B"
gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'
echo "backup $B ($(du -h "$B" | cut -f1))"
has() { case " $STEPS " in *" $1 "*) return 0 ;; esac; return 1; }
for S in nascar motogp; do
  G=data/runs/replay-grid/$S
  if ! ls "$G"/*/kalshi/summary.json >/dev/null 2>&1; then echo "SKIP $S: no settings grid in $G"; continue; fi
  if has kalshi; then
    echo "== $S kalshi: selection from $G"
    nice $R "$S" demo-history --pick "$G"
    echo "== $S kalshi: demo-history for $USERS"
    nice $R "$S" demo-history --grid "$G" --book "$BOOK" --users "$USERS" --backup "$B"
  fi
  if has polymarket; then     # no Polymarket grid: Kalshi's selection, traded on Polymarket's own tape and fees
    echo "== $S polymarket: demo-history for $USERS (settings from the Kalshi grid)"
    nice $R "$S" demo-history --grid "$G" --venue polymarket --grid-venue kalshi --book "$BOOK" --users "$USERS" --backup "$B"
  fi
done
if has forecast; then
  for S in nascar motogp; do
    echo "== $S forecast: the next races priced by the model"
    nice $R "$S" forecast --save --backup "$B"
  done
fi
echo "DEMO-SETUP DONE (log $LOG, backup $B)"
date -u > "$DONE"
