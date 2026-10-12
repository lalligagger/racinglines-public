#!/usr/bin/env bash
# On the VM, as the racinglines user: move the checkout to a ref, install, migrate. Run by
# scripts/deploy/vm.sh deploy (which then restarts the services). See docs/vm-deploy.md.
#   deploy/vm/update.sh [ref]      # default main; a branch name or a commit
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
# all in a function: bash reads it whole before the checkout below rewrites this file
main() {
  cd /opt/racinglines
  venv_guard
  ref="${1:-main}"
  log() { echo "[update $(date -u +%H:%M:%S)] $*"; }

  git fetch --quiet --prune origin
  if git rev-parse --verify -q "origin/$ref^{commit}" >/dev/null; then target="origin/$ref"; else target="$ref"; fi
  sha=$(git rev-parse --verify "$target^{commit}")
  log "checkout $ref -> ${sha:0:12} (was $(git rev-parse --short=12 HEAD))"
  git checkout --quiet --detach "$sha"

  log "pip install"
  .venv/bin/pip install --quiet -r requirements.txt -e .
  imports_here

  log "database up"
  docker compose up -d --wait db

  log "alembic upgrade head"
  set -a; . /etc/racinglines.env; set +a
  .venv/bin/alembic upgrade head
  log "db seed (reference rows for every sport schema; idempotent upserts)"
  .venv/bin/racinglines db seed
  log "done: $(git log -1 --format='%h %s')"
}
main "$@"
