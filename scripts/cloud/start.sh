#!/usr/bin/env bash
# Bring up racinglines on a fresh Linux machine (a Claude cloud session VM, Ubuntu 24.04):
# Python env, PostgreSQL, and the database built from the data set committed in the repo
# (data/raw/f1, data/archive/markets). Safe to re-run. See docs/cloud-sweep.md.
#
#   bash scripts/cloud/start.sh              # full bring-up (~5-10 min)
#   SKIP_SYSTEM=1 DATABASE_URL=... bash scripts/cloud/start.sh   # only the database steps (local rehearsal)
#
# Network: PyPI + GitHub (Python, packages) only. The database comes from the committed snapshot
# (racinglines db snapshot-export): an exact replica, so seeded prices match the exporting machine.
set -euo pipefail
cd "$(dirname "$0")/../.."
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://racinglines:racinglines@localhost:5432/racinglines}"
log() { echo "[start $(date -u +%H:%M:%S)] $*"; }
as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi; }

if [ -z "${SKIP_SYSTEM:-}" ]; then
    log "python: .venv (3.14) + requirements"
    command -v uv >/dev/null || python3 -m pip install -q --user uv || pip install -q uv
    export PATH="$HOME/.local/bin:$PATH"
    [ -x .venv/bin/python ] || uv venv -q --python 3.14 .venv
    uv pip install -q --python .venv/bin/python -r requirements.txt -e .

    log "postgresql: start, role and database 'racinglines'"
    as_root service postgresql start >/dev/null
    for _ in $(seq 1 30); do pg_isready -q && break; sleep 1; done
    psql_su() { as_root su postgres -c "psql -v ON_ERROR_STOP=1 -tAc \"$1\""; }
    [ "$(psql_su "SELECT 1 FROM pg_roles WHERE rolname = 'racinglines'")" = 1 ] ||
        psql_su "CREATE ROLE racinglines LOGIN SUPERUSER PASSWORD 'racinglines'"
    [ "$(psql_su "SELECT 1 FROM pg_database WHERE datname = 'racinglines'")" = 1 ] ||
        psql_su "CREATE DATABASE racinglines OWNER racinglines"
fi

RL=.venv/bin/racinglines
# The data bucket (docs/data.md#data-bucket), when the environment has its key: the data folders
# git doesn't carry, and a full dump of the owner's database (model runs, signals, positions, books)
if [ -n "${RACINGLINES_GCS_HMAC_ID:-}" ] && [ -z "${SKIP_BUCKET:-}" ]; then
    log "data bucket: pull";                            .venv/bin/python scripts/cloud/bucket.py pull
fi
if [ -f data/archive/bucket-db/racinglines.sql.gz ] && [ -z "${SKIP_BUCKET:-}" ]; then
    # a full replica of the owner's database, replacing the committed snapshot's subset
    log "database: restore the bucket's full dump"
    psql_url=${DATABASE_URL/+psycopg/}
    psql "${psql_url%/*}/postgres" -v ON_ERROR_STOP=1 -qc "DROP DATABASE IF EXISTS racinglines WITH (FORCE)" \
        -c "CREATE DATABASE racinglines OWNER racinglines"
    gunzip -c data/archive/bucket-db/racinglines.sql.gz | psql "$psql_url" -q -v ON_ERROR_STOP=0 2>&1 \
        | grep -v "transaction_timeout" | tail -3 || true
fi
log "schema + reference data";                         $RL db init
if [ -f data/archive/bucket-db/racinglines.sql.gz ] && [ -z "${SKIP_BUCKET:-}" ]; then
    log "database: from the bucket (skipping the committed snapshot)"
elif [ -f data/archive/db/manifest.json ]; then
    # exact replica of the exporting database (same ids -> identical seeded prices)
    log "model tables from the committed snapshot";      $RL db snapshot-import
else
    log "F1 results, laps, track profiles (2020-2026)"; $RL f1 ingest --years 2020-2026 | tail -2
    # market links from the committed file (no Polymarket access needed); pm-sync only if it's missing
    if [ -f data/archive/markets/polymarket/links/market_links.parquet ]; then
        log "Polymarket market links (committed file)"; $RL f1 pm-links-import
    else
        log "Polymarket market links (API)";            $RL f1 pm-sync --year 2025 --closed
                                                        $RL f1 pm-sync --year 2026 --closed
    fi
fi
log "check";                                            $RL check --offline | tail -3
log "ready: DATABASE_URL=$DATABASE_URL"
