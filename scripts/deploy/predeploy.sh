#!/usr/bin/env bash
# Branch pre-deploy gate for staging and production.
#
#   bash scripts/deploy/predeploy.sh --staging [ref]
#   bash scripts/deploy/predeploy.sh --prod [ref]
#   bash scripts/deploy/predeploy.sh --all [ref]
#
# By default this targets the real staging host (`https://staging.racinglines.bet`). The staging
# hostname must exist in Cloudflare and point to the tunnel; there is no temp tunnel fallback.
# The final prod path still uses the normal VM deploy flow (`scripts/deploy/vm.sh deploy`).
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"
SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then SCRIPT_DIR="."; fi
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:---staging}"
REF="${2:-main}"
STAGING_URL="${STAGING_URL:-https://staging.racinglines.bet}"
PROD_URL="${PROD_URL:-https://racinglines.bet}"

run_smoke() {
  local url="$1"
  echo "[predeploy] smoke check: $url"
  echo "[predeploy] gate is valid-auth only: no failed-login probes, no rate-limit poisoning"
  bash scripts/deploy/smoke.sh "$url"
}

staging_gate() {
  echo "[predeploy] staging target: $STAGING_URL"
  run_smoke "$STAGING_URL"
  echo "[predeploy] staging host accepted the branch"
}

prod_gate() {
  echo "[predeploy] prod deploy: $REF"
  bash scripts/deploy/vm.sh deploy "$REF"
  run_smoke "$PROD_URL"
}

case "$MODE" in
  --staging|-s|staging)
    staging_gate
    ;;
  --prod|-p|prod)
    prod_gate
    ;;
  --all|-a|all)
    staging_gate
    prod_gate
    ;;
  --help|-h|help)
    echo "usage: bash scripts/deploy/predeploy.sh [--staging|--prod|--all] [ref]"
    echo "default: --staging main"
    echo "STAGING_URL=https://staging.racinglines.bet bash scripts/deploy/predeploy.sh --all main"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    echo "usage: bash scripts/deploy/predeploy.sh [--staging|--prod|--all] [ref]" >&2
    exit 2
    ;;
 esac
