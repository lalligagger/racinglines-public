#!/usr/bin/env bash
# The VM's off-site copy (docs/todo.md STG-5): one pass, started nightly by racinglines-offsite.timer on the VM (enable
# with `bash scripts/deploy/vm.sh offsite`, stop with `vm.sh offsite off`, last passes with `vm.sh offsite status`,
# one pass now with `vm.sh offsite run`). Every step is read-only on the VM's data; it only adds to the bucket:
#
#   1. a nightly dump of production's database, data/backups/db/racinglines-nightly-<UTC>.sql.gz (pg_dump, gzip,
#      checked for its trailer), skipped when the newest is under NIGHTLY_MIN_HOURS old (default 20: a deploy's
#      catch-up step doesn't dump again); the dumps beyond the newest NIGHTLY_KEEP (default 7) are deleted from the VM
#      only once the bucket holds them (this script's own nightly dumps only, never a pre-change backup)
#   2. gcloud storage rsync of data/backups (production's and staging's) -> backups/prod/, backups/staging/
#   3. gcloud storage rsync of data/archive/markets -> archive/markets/ (the recorder's Parquet history)
#
# rsync never deletes in the bucket (no --delete-unmatched-destination-objects). Bucket: RACINGLINES_OFFSITE_BUCKET
# (default the primary, racinglines-data-384052502248, docs/data-off-github.md). The VM's service account holds
# storage.objectUser there (checked 2026-10-14). A progress line every 5 minutes (CLAUDE.md, long-running jobs).
# Logs to the journal (journalctl -u racinglines-offsite) and data/runs/logs/offsite.log.
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
STG=${STG:-/opt/racinglines-staging}
BUCKET=gs://${RACINGLINES_OFFSITE_BUCKET:-racinglines-data-384052502248}
LOG=data/runs/logs/offsite.log
DUMPS=data/backups/db
KEEP=${NIGHTLY_KEEP:-7}
MIN_H=${NIGHTLY_MIN_HOURS:-20}
mkdir -p data/runs/logs "$DUMPS"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh offsite status: the timer, the newest nightly dump and the last passes
  systemctl --no-pager list-timers racinglines-offsite.timer | head -n 2
  echo "--- newest nightly dump: $(ls -1t $DUMPS/racinglines-nightly-*.sql.gz 2>/dev/null | head -n 1 || true)"
  echo "--- last passes ($LOG)"; tail -n 12 "$LOG" 2>/dev/null || echo "no pass yet"
  exit 0
fi

T0=$SECONDS
( while sleep "${HEARTBEAT_SEC:-300}" >/dev/null 2>&1; do echo "progress offsite: $(( (SECONDS - T0) / 60 )) min elapsed · $(cat "$LOG.step" 2>/dev/null)"; done ) &
BEAT=$!
trap 'kill $BEAT 2>/dev/null; rm -f "$LOG.step"' EXIT
step() { echo "$1" > "$LOG.step"; }

rc=0
# 1. the nightly dump
newest=$(ls -1t $DUMPS/racinglines-nightly-*.sql.gz 2>/dev/null | head -n 1)
if [ -n "$newest" ] && [ $(( $(date +%s) - $(stat -c %Y "$newest") )) -lt $(( MIN_H * 3600 )) ]; then
  say "dump: skipped, $newest is under $MIN_H h old"
else
  step "step 1 of 3: dumping production's database"
  b=$DUMPS/racinglines-nightly-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  if docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines </dev/null | gzip -6 > "$b" &&
     gunzip -c "$b" | tail -n 5 | grep -q 'PostgreSQL database dump complete'; then
    say "dump: $b ($(du -h "$b" | cut -f1))"
  else
    rm -f "$b"; rc=1; say "dump: FAILED, nothing kept"
  fi
fi

# 2. backups, production's and staging's
step "step 2 of 3: copying data/backups to $BUCKET/backups/"
for pair in "data/backups:prod" "$STG/data/backups:staging"; do
  src=${pair%:*}; dst=$BUCKET/backups/${pair##*:}
  [ -d "$src" ] || { say "backups: $src missing, skipped"; continue; }
  if out=$(nice gcloud storage rsync --recursive "$src" "$dst" 2>&1); then
    say "backups: $src -> $dst ($(echo "$out" | grep -c '^Copying') copied)"
  else
    rc=1; say "backups: $src -> $dst FAILED: $(echo "$out" | tail -n 2 | tr '\n' ' ')"
  fi
done

# the nightly dumps beyond the newest $KEEP, only the ones the bucket now holds at the same size
for old in $(ls -1t $DUMPS/racinglines-nightly-*.sql.gz 2>/dev/null | tail -n +$(( KEEP + 1 ))); do
  remote_size=$(gcloud storage objects describe "$BUCKET/backups/prod/db/${old##*/}" --format='value(size)' 2>/dev/null)
  if [ "$remote_size" = "$(stat -c %s "$old")" ]; then rm -f "$old" && say "dump: removed $old from the VM (in the bucket)"
  else say "dump: kept $old (not in the bucket at the same size)"; fi
done

# 3. the recorder's Parquet history
step "step 3 of 3: copying data/archive/markets to $BUCKET/archive/markets/"
if [ -d data/archive/markets ]; then
  if out=$(nice gcloud storage rsync --recursive data/archive/markets "$BUCKET/archive/markets" 2>&1); then
    say "archive: data/archive/markets -> $BUCKET/archive/markets ($(echo "$out" | grep -c '^Copying') copied)"
  else
    rc=1; say "archive: FAILED: $(echo "$out" | tail -n 2 | tr '\n' ' ')"
  fi
fi

say "pass done in $(( (SECONDS - T0) / 60 )) min, exit $rc"
exit $rc
