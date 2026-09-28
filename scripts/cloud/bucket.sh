#!/usr/bin/env bash
# The data bucket (Google Cloud Storage): everything a cloud session needs that isn't in git.
# See docs/data.md#data-bucket.
#
#   bash scripts/cloud/bucket.sh push      # local -> bucket: a database dump + the data folders
#   bash scripts/cloud/bucket.sh pull      # bucket -> local folders (not the database)
#   bash scripts/cloud/bucket.sh ls        # what's in the bucket
#
# Needs the gcloud CLI signed in with access to the bucket. Cloud sessions (no gcloud) use
# scripts/cloud/bucket.py instead.
set -euo pipefail
cd "$(dirname "$0")/../.."
BUCKET="${RACINGLINES_GCS_BUCKET:-racinglines-data-650570086451}"
PG_BIN="${PG_BIN:-$HOME/miniconda3-arm64/envs/racinglines-db/bin}"
# folders synced both ways: bucket prefix -> local path (data/pg, caches and logs are never synced)
FOLDERS=(
  "live:data/runs/live"
  "runs/f1:data/runs/f1"
  "raw/mtb_dh:data/raw/mtb_dh"
  "archive/markets:data/archive/markets"
)
log() { echo "[bucket $(date -u +%H:%M:%S)] $*"; }

case "${1:-}" in
  push)
    url=$(.venv/bin/python -c "from racinglines.db.config import database_url; print(database_url().replace('+psycopg', ''))")
    tmp=$(mktemp -d)
    # plain SQL, gzipped: restorable by an older psql (a cloud VM's Postgres may be older than ours)
    log "database dump (pg_dump, plain SQL, gzip)"
    "$PG_BIN/pg_dump" --no-owner --no-privileges "$url" | gzip -6 > "$tmp/racinglines.sql.gz"
    head=$(.venv/bin/python -c "
from sqlalchemy import text
from racinglines.db.config import get_engine
with get_engine().connect() as c: print(c.execute(text('select version_num from alembic_version')).scalar())")
    printf '{"created_at": "%s", "alembic_head": "%s", "bytes": %s}\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$head" "$(wc -c < "$tmp/racinglines.sql.gz" | tr -d ' ')" > "$tmp/manifest.json"
    gcloud storage rm "gs://$BUCKET/db/racinglines.dump" --quiet 2>/dev/null || true
    gcloud storage cp "$tmp/racinglines.sql.gz" "$tmp/manifest.json" "gs://$BUCKET/db/" --quiet
    rm -rf "$tmp"
    for f in "${FOLDERS[@]}"; do
      prefix=${f%%:*}; path=${f#*:}
      [ -d "$path" ] || continue
      log "$path -> gs://$BUCKET/$prefix"
      gcloud storage rsync --recursive "$path" "gs://$BUCKET/$prefix" --quiet
    done
    log "done"
    ;;
  pull)
    for f in "${FOLDERS[@]}"; do
      prefix=${f%%:*}; path=${f#*:}
      mkdir -p "$path"
      log "gs://$BUCKET/$prefix -> $path"
      gcloud storage rsync --recursive "gs://$BUCKET/$prefix" "$path" --quiet
    done
    ;;
  ls)
    gcloud storage du --summarize --readable-sizes "gs://$BUCKET"
    gcloud storage ls "gs://$BUCKET/*"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1
    ;;
esac
