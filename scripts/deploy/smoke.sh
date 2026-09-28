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
set -uo pipefail
URL="${1:?usage: smoke.sh <base url>}"; URL="${URL%/}"
PW="${SMOKE_PASSWORD:-password}"
fail=0

check() {   # check <expected status> <label> <curl args...>
  local want=$1 label=$2; shift 2
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@")
  if [ "$got" = "$want" ]; then echo "ok    $got  $label"; else echo "FAIL  $got  $label (wanted $want)"; fail=1; fi
}

check 200 "GET /login" "$URL/login"
check 401 "GET /markets without credentials" "$URL/markets"
check 401 "GET /markets with a wrong password" -u "maker:not-the-password-$RANDOM" "$URL/markets"
for path in /markets /events /athletes /pitch /racinglines101; do
  for user in maker taker; do check 200 "GET $path as $user" -u "$user:$PW" "$URL$path"; done
done
check 200 "GET /book/quotes as maker" -u "maker:$PW" "$URL/book/quotes"
check 403 "GET /book/quotes as taker (maker-only)" -u "taker:$PW" "$URL/book/quotes"

[ $fail = 0 ] && echo "smoke: all checks passed ($URL)" || echo "smoke: FAILED ($URL)"
exit $fail
