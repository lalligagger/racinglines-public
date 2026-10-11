#!/usr/bin/env bash
# Starts scripts/deploy/f1_push.sh by itself every F1 weekend, so nobody has to remember it. F1's timing archive answers
# 403 to the VM, so sessions reach it only from this Mac (docs/vm-deploy.md). A LaunchAgent runs this every 10 minutes:
# for each F1 event whose window is open (`racinglines live auto --list`: an hour before the book opens to a day after
# the results), it starts `caffeinate -i f1_push.sh <event>` unless one is already running or the race is already on
# the VM. f1_push.sh exits once the race is pushed. The Mac has to be awake and online: caffeinate keeps it from idling
# to sleep while the push runs, but a closed lid or no network still stops it.
#
#   bash scripts/deploy/f1_push_auto.sh install    # LOCAL (Mac): write and load the LaunchAgent (once)
#   bash scripts/deploy/f1_push_auto.sh remove     # unload and delete it
#   bash scripts/deploy/f1_push_auto.sh            # one pass (what the LaunchAgent runs)
#
# Each pass prints one line; logs: data/runs/logs/f1_push_auto.log and data/runs/logs/f1_push-<event>.log.
set -uo pipefail
export PYTHONUNBUFFERED=1 RACINGLINES_PROGRESS_SEC=0
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT=$(pwd)
PY="${PY:-.venv/bin/python}"
LABEL=bet.racinglines.f1push
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p data/runs/logs
log() { echo "[f1_push_auto $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

case "${1:-}" in
  install)
    [ "$(uname)" = Darwin ] || { echo "install is for the Mac (launchd)"; exit 1; }
    mkdir -p "$(dirname "$PLIST")"
    # launchd starts with a bare PATH: keep this shell's, so gcloud and the repo's tools are found. AbandonProcessGroup:
    # the f1_push started by a pass keeps running after the pass exits (launchd would otherwise kill it)
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/scripts/deploy/f1_push_auto.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH</string></dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>AbandonProcessGroup</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/runs/logs/f1_push_auto.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/runs/logs/f1_push_auto.log</string>
</dict></plist>
PL
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "loaded $LABEL: a pass every 10 minutes (log: data/runs/logs/f1_push_auto.log)"
    exit 0 ;;
  remove)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    exit 0 ;;
  "") ;;
  *) echo "usage: f1_push_auto.sh [install|remove]"; exit 1 ;;
esac

err=data/runs/logs/.f1_push_auto.err
if ! evs=$("$PY" -m racinglines live auto --list 2>"$err"); then
  log "couldn't list the open events: $(tail -n 1 "$err")"
  exit 1
fi
[ -n "$evs" ] || { log "no F1 event window open"; exit 0; }
RAW="$("$PY" -c 'from racinglines import paths; print(paths.F1_RAW)')"
for ev in $evs; do
  rr=$(printf %02d "$((10#${ev#*-}))")
  if pgrep -f "f1_push.sh $ev" >/dev/null; then
    log "$ev: f1_push already running"
  elif grep -qxF "${rr}_R.results.parquet" "$RAW/${ev%-*}/.pushed-$ev" 2>/dev/null; then
    log "$ev: the race is already on the VM"
  else
    nohup caffeinate -i bash scripts/deploy/f1_push.sh "$ev" >> "data/runs/logs/f1_push-$ev.log" 2>&1 &
    log "$ev: started f1_push (pid $!, log data/runs/logs/f1_push-$ev.log)"
  fi
done
