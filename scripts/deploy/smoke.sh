#!/usr/bin/env bash
# Smoke check of a running web app: the same check for local, the temp tunnel, the VM and racinglines.bet.
# See docs/vm-deploy.md.
#
#   bash scripts/deploy/smoke.sh http://127.0.0.1:8000
#   bash scripts/deploy/smoke.sh https://<temp>.trycloudflare.com
#   bash scripts/deploy/smoke.sh https://racinglines.bet
#
# Signs in with HTTP Basic as the demo accounts (SMOKE_PASSWORD, default the public demo password).
# Read-only: GET requests only. Exit 1 if any check fails.
#
# SMOKE_EXPECT_ENV=staging adds one check: /login must answer with the header X-Racinglines-Env: staging
# (the app sends it when RACINGLINES_ENV is set), so a staging deploy proves it reached the staging instance
# and not production. Unset, nothing changes.
#
# IMPORTANT: the default smoke gate must never test a bad password. The app rate-limits failed Basic
# auth requests by client IP for 15 minutes, so a wrong-password probe warms the same bucket used by the
# real maker/taker checks and creates a false predeploy failure. If we intentionally need the throttle
# path, use the explicit --auth-throttle mode against a fresh client/IP or after resetting the app.
set -uo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"
URL="${1:?usage: smoke.sh <base url> [--auth-throttle]}"; URL="${URL%/}"
MODE="${2:-normal}"
PW="${SMOKE_PASSWORD:-password}"
fail=0

check() {   # check <expected status> <label> <curl args...>
  local want=$1 label=$2; shift 2
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@")
  if [ "$got" = "$want" ]; then echo "ok    $got  $label"; else echo "FAIL  $got  $label (wanted $want)"; fail=1; fi
}

if [ "$MODE" = "--auth-throttle" ]; then
  echo "[smoke] explicit auth-throttle probe"
  check 401 "GET /markets with a wrong password" -u "maker:not-the-password-$RANDOM" "$URL/markets"
  [ $fail = 0 ] && echo "smoke: throttle check passed ($URL)" || echo "smoke: throttle check FAILED ($URL)"
  exit $fail
fi

check 200 "GET /login" "$URL/login"
if [ -n "${SMOKE_EXPECT_ENV:-}" ]; then
  got_env=$(curl -s -o /dev/null -w '%header{x-racinglines-env}' --max-time 30 "$URL/login")
  if [ "$got_env" = "$SMOKE_EXPECT_ENV" ]; then echo "ok    env  X-Racinglines-Env: $got_env"
  else echo "FAIL  env  X-Racinglines-Env: '${got_env:-none}' (wanted $SMOKE_EXPECT_ENV: this is not the $SMOKE_EXPECT_ENV instance)"; fail=1; fi
fi
check 401 "GET /markets without credentials" "$URL/markets"
for path in /markets /pitch /racinglines101; do
  for user in maker taker; do check 200 "GET $path as $user" -u "$user:$PW" "$URL$path"; done
done
check 200 "GET /book/quotes as maker" -u "maker:$PW" "$URL/book/quotes"
check 403 "GET /book/quotes as taker (maker-only)" -u "taker:$PW" "$URL/book/quotes"

[ $fail = 0 ] && echo "smoke: all checks passed ($URL)" || echo "smoke: FAILED ($URL)"
exit $fail
