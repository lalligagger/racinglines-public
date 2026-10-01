#!/usr/bin/env bash
# On the VM, as the racinglines user: move the checkout to a ref, install, migrate. Run by
# scripts/deploy/vm.sh deploy (which then restarts the services). See docs/vm-deploy.md.
#   deploy/vm/update.sh [ref]      # default main; a branch name or a commit
set -euo pipefail
# all in a function: bash reads it whole before the checkout below rewrites this file
main() {
  cd /opt/racinglines
  ref="${1:-main}"
  log() { echo "[update $(date -u +%H:%M:%S)] $*"; }

  git fetch --quiet --prune origin
  if git rev-parse --verify -q "origin/$ref^{commit}" >/dev/null; then target="origin/$ref"; else target="$ref"; fi
  sha=$(git rev-parse --verify "$target^{commit}")
  log "checkout $ref -> ${sha:0:12} (was $(git rev-parse --short=12 HEAD))"
  git checkout --quiet --detach "$sha"

  log "pip install"
  .venv/bin/pip install --quiet -r requirements.txt -e .

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
