#!/usr/bin/env bash
# The X reply bot (scripts/xbot/xbot.py) on the VM. Its own venv and state live in /var/lib/racinglines-xbot, the
# keys in /etc/racinglines-xbot.env (root:racinglines 640, written with read -s, never in the repo). It touches no
# database and no app code: a deploy neither starts nor stops it.
#
# Usage (as root on the VM; APP=<checkout> runs it from a checkout other than /opt/racinglines):
#   bash scripts/vm/xbot.sh setup              # create the venv (anthropic, pinned in scripts/xbot/requirements.txt)
#   bash scripts/vm/xbot.sh accounts           # the connected X accounts
#   bash scripts/vm/xbot.sh ask "TEXT"         # draft one answer and print it (nothing read from or sent to X)
#   bash scripts/vm/xbot.sh once               # one pass in the env file's XBOT_MODE (dry unless it says live)
#   bash scripts/vm/xbot.sh review             # draft new replies/tags, then approve, edit (vim) or skip each (needs ssh -t)
#   bash scripts/vm/xbot.sh fetch              # only draft new replies/tags into the review queue; posts nothing
#   bash scripts/vm/xbot.sh draft TWEET        # draft an answer to TWEET (id or x.com URL); nothing is posted
#   bash scripts/vm/xbot.sh reply TWEET [FILE] # post FILE, or that draft, as a reply to TWEET, by hand
#   bash scripts/vm/xbot.sh on [MIN]           # a pass every MIN minutes (default 5), transient timer rl-xbot
#   bash scripts/vm/xbot.sh off | status | log
#
# The timer is a transient unit (systemd-run): it does not survive a reboot; run `on` again after one.
set -euo pipefail
export PYTHONUNBUFFERED=1
APP="${APP:-/opt/racinglines}"
STATE=/var/lib/racinglines-xbot
ENV_FILE=/etc/racinglines-xbot.env
PY="$STATE/.venv/bin/python"
UNIT=rl-xbot
cd "$APP"

run() {
  [ -x "$PY" ] || { echo "xbot: no venv yet; run: bash scripts/vm/xbot.sh setup" >&2; exit 2; }
  [ -r "$ENV_FILE" ] || { echo "xbot: $ENV_FILE is missing" >&2; exit 2; }
  sudo -u racinglines -H bash -c "set -a; . $ENV_FILE; set +a; XBOT_STATE=$STATE exec $PY $APP/scripts/xbot/xbot.py \"\$@\"" xbot "$@"
}

case "${1:-}" in
  setup)
    install -d -o racinglines -g racinglines -m 750 "$STATE"
    sudo -u racinglines -H python3 -m venv "$STATE/.venv"
    sudo -u racinglines -H "$STATE/.venv/bin/pip" install -q -r "$APP/scripts/xbot/requirements.txt"
    echo "xbot: venv ready at $STATE/.venv"
    ;;
  accounts|ask|once|draft|reply|fetch|review)
    run "$@"
    ;;
  on)
    min="${2:-5}"
    case "$min" in ''|*[!0-9]*) echo "xbot: minutes must be a number" >&2; exit 2 ;; esac
    systemctl stop "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
    systemd-run --unit "$UNIT" --on-calendar "*:0/$min" --timer-property=Persistent=false --setenv=APP="$APP" \
      --property=TimeoutStartSec=4min /usr/bin/bash "$APP/scripts/vm/xbot.sh" once
    echo "xbot: a pass every $min min ($(grep -s '^XBOT_MODE=' "$ENV_FILE" || echo 'XBOT_MODE unset: dry'))"
    ;;
  off)
    systemctl stop "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
    echo "xbot: off"
    ;;
  status)
    systemctl --no-pager list-timers "$UNIT.timer" | head -n 2 || true
    grep -s '^XBOT_MODE=' "$ENV_FILE" || echo "XBOT_MODE unset: dry"
    tail -n 5 "$STATE/log.jsonl" 2>/dev/null || echo "xbot: no log yet"
    ;;
  log)
    tail -n "${2:-20}" "$STATE/log.jsonl"
    ;;
  *)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 1
    ;;
esac
