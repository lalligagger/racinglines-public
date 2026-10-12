#!/usr/bin/env bash
# Record the /term page's F1 parts (racinglines/web/term/f1-singapore.toml: the 2026 Singapore GP on the real data and
# the real Kalshi and Polymarket tapes) on the VM, where that data is. Staging only (owner, 2026-10-11 21:47Z).
#
#   TARGET=staging     which app and database (staging only, unless the owner says otherwise)
#   PART=f1-singapore  the steps file (demos.toml `parts`)
#
# Steps: a backup of the database (its trailer checked; a replay saves any stage pricing it is missing as a diagnostic
# model run), the recording (scripts/demo/record_term.py --run --part PART --out OUT: each step in one fresh folder,
# nothing in the checkout changes), a data_changes note naming the backup, and OUT packed as OUT.tar.gz. Copy that to
# the Mac, unpack it into racinglines/web/term/ and render with `python scripts/demo/record_term.py`. Progress: a line
# per step as it finishes, and a heartbeat every HEARTBEAT_MIN minutes.
#
# Run on the VM as a transient unit, e.g.
#   sudo systemd-run --unit=rl-record-term --uid=racinglines /opt/racinglines-staging/scripts/vm/record_term_f1.sh
#   sudo journalctl -fu rl-record-term
set -uo pipefail
TARGET=${TARGET:-staging}
case "$TARGET" in
  staging) ENV_FILE=${ENV_FILE:-/etc/racinglines-staging.env}; APP=${APP:-/opt/racinglines-staging}; DB=racinglines_staging ;;
  prod)    ENV_FILE=${ENV_FILE:-/etc/racinglines.env};         APP=${APP:-/opt/racinglines};         DB=racinglines ;;
  *) echo "TARGET must be staging or prod, not $TARGET"; exit 2 ;;
esac
DC() { (cd "${DC_DIR:-/opt/racinglines}" && docker compose "$@"); }   # the database container is production's
set -a; . "$ENV_FILE"; set +a
export PYTHONUNBUFFERED=1
cd "$APP"
PART=${PART:-f1-singapore}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=${OUT:-$APP/data/term/$PART-$STAMP}
HEARTBEAT_MIN=${HEARTBEAT_MIN:-5}
mkdir -p data/runs/logs data/backups/db "$(dirname "$OUT")"
LOG=data/runs/logs/record-term-$PART-$STAMP.log
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

B=data/backups/db/$DB-before-record-term-$PART-$STAMP.sql.gz
say "record $PART on $TARGET: backing up to $B"
DC exec -T db pg_dump --no-owner --no-privileges -U racinglines "$DB" | gzip -6 > "$B"
if ! gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete'; then
  say "STOP: backup $B is incomplete; nothing recorded"
  exit 1
fi
say "backup $B ($(du -h "$B" | cut -f1))"

T0=$SECONDS
( while sleep $((HEARTBEAT_MIN * 60)); do say "progress record-term: $(( (SECONDS - T0) / 60 )) min elapsed"; done ) &
BEAT=$!
trap 'kill $BEAT 2>/dev/null' EXIT
rc=0
.venv/bin/python scripts/demo/record_term.py --run --part "$PART" --out "$OUT" 2>&1 | while read -r l; do say "$l"; done
rc=${PIPESTATUS[0]}
kill $BEAT 2>/dev/null

.venv/bin/racinglines db changes --add "Recorded the /term part $PART on $TARGET (scripts/vm/record_term_f1.sh; a replay may have saved missing stage pricings as diagnostic runs); backup $B" >/dev/null \
  && say "data_changes note added" || { rc=1; say "data_changes note FAILED"; }
if [ "$rc" = 0 ]; then
  tar -czf "$OUT.tar.gz" -C "$OUT" . && say "packed $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1))"
fi
say "RECORD-TERM-DONE (exit $rc)"
exit "$rc"
