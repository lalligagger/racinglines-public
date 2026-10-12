#!/usr/bin/env bash
# On the VM, as the racinglines user: move the STAGING checkout to a ref, install, migrate the staging
# database. Run by `scripts/deploy/vm.sh staging deploy [ref]` (piped over ssh; it then restarts
# racinglines-staging-web). The production checkout, database, units and timers are never touched: there is
# no pause, no untrack, no `docker compose up`, and alembic refuses any DATABASE_URL that isn't racinglines_staging.
#   deploy/vm/staging/update.sh [ref]      # default staging; a branch name or a commit
set -euo pipefail
# Production and staging must not share a venv: one's `pip install -e .` re-points the other's imports (2026-10-12:
# /opt/racinglines-staging/.venv was a symlink to production's, so prod jobs ran staging code). Refuse before any change.
venv_guard() {
  local p=${1:-/opt/racinglines/.venv} s=${2:-/opt/racinglines-staging/.venv} v
  for v in "$p" "$s"; do
    if [ -L "$v" ]; then echo "refusing: $v is a symlink (to $(readlink -f "$v")); give it its own venv (docs/vm-deploy.md#separate-venvs)"; exit 1; fi
  done
  if [ -e "$p" ] && [ -e "$s" ] && [ "$(readlink -f "$p")" = "$(readlink -f "$s")" ]; then
    echo "refusing: $p and $s are the same venv (docs/vm-deploy.md#separate-venvs)"; exit 1
  fi
}
# after `pip install -e .`: this venv must import racinglines from this checkout (-I: not from the current directory)
imports_here() {
  local f; f=$(.venv/bin/python -I -c 'import racinglines; print(racinglines.__file__)')
  case "$f" in "$PWD"/*) ;; *) echo "refusing: $PWD/.venv imports racinglines from $f, not this checkout"; exit 1 ;; esac
}
main() {
  STG=/opt/racinglines-staging
  ENVF=/etc/racinglines-staging.env
  DB=racinglines_staging
  cd "$STG"
  venv_guard
  ref="${1:-staging}"
  log() { echo "[staging-update $(date -u +%H:%M:%S)] $*"; }
  [ -f "$ENVF" ] || { echo "$ENVF missing: run bash scripts/deploy/vm.sh staging setup first"; exit 1; }

  git fetch --quiet --prune origin
  if git rev-parse --verify -q "origin/$ref^{commit}" >/dev/null; then target="origin/$ref"; else target="$ref"; fi
  sha=$(git rev-parse --verify "$target^{commit}")
  log "checkout $ref -> ${sha:0:12} (was $(git rev-parse --short=12 HEAD))"
  git checkout --quiet --detach "$sha"

  log "pip install"
  .venv/bin/pip install --quiet -r requirements.txt -e .
  imports_here

  set -a; . "$ENVF"; set +a
  case "$DATABASE_URL" in
    */$DB) ;;
    *) echo "refusing to migrate: DATABASE_URL in $ENVF is not $DB"; exit 1 ;;
  esac
  [ "${RACINGLINES_ENV:-}" = staging ] || { echo "refusing: RACINGLINES_ENV in $ENVF is not staging"; exit 1; }
  log "alembic upgrade head ($DB)"
  .venv/bin/alembic upgrade head
  log "db seed ($DB)"
  .venv/bin/racinglines db seed
  log "done: $(git log -1 --format='%h %s')"
}
main "$@"
