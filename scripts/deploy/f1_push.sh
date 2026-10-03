#!/usr/bin/env bash
# An F1 weekend from the owner's Mac to the VM. F1's timing archive (livetiming.formula1.com) answers 403 to the VM's
# cloud address (3 Oct 2026: the 2026 index and every round 16 session), so FastF1 can't fetch there. This loop, run
# on the Mac, does both halves of the weekend:
#   - finished sessions: every look (default 5 min) it fetches each session once it is over (f1 fetch skips sessions
#     still running and those already on disk), copies the round's files to the VM's data folder and staging's, and
#     runs both live steps, which ingest and price them;
#   - live timing on staging: while a session runs, every RELAY_SEC (default 120 s, FastF1 allows ~500 calls an hour)
#     it takes the panel's snapshot (python -m racinglines.web.f1_live) and writes it to staging's
#     <data>/runs/f1_relay/<year>-<round>.json, which staging's live-timing button reads (web/f1_live.py).
# It stops once the race is there.
#
#   bash scripts/deploy/f1_push.sh 2026-16 [minutes between looks, default 5]
#
# Prints a progress line every look (at most 5 minutes apart). Needs the gcloud CLI signed in (as vm.sh) and the
# repo's .venv (PY=... to use another Python).
set -euo pipefail
export PYTHONUNBUFFERED=1 RACINGLINES_PROGRESS_SEC=0
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
EV="${1:?usage: f1_push.sh <year-round, e.g. 2026-16> [minutes]}"
EVERY="${2:-5}"
RELAY_SEC="${RELAY_SEC:-120}"
Y="${EV%-*}"
R="$((10#${EV#*-}))"
RR=$(printf %02d "$R")
PY="${PY:-.venv/bin/python}"
PROJECT="${RL_GCP_PROJECT:-racinglines}"
VM="${RL_VM:-racinglines-vm}"
ZONE="${RL_ZONE:-us-west1-b}"
remote() { gcloud compute ssh "$VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "$1"; }
log() { echo "[f1_push $(date -u +%H:%M:%S)] $*"; }
# an app copy's folders on the VM, "<F1 raw> <data>", from its checkout and env file; "none" when it isn't there
folders() { remote "[ -f $2 ] && cd $1 && sudo -u racinglines -H bash -c 'set -a; . $2; set +a; .venv/bin/python -c \"from racinglines import paths; print(paths.F1_RAW, paths.DATA)\"' || echo none" | tail -n 1; }

LOCAL="$("$PY" -c 'from racinglines import paths; print(paths.F1_RAW)')/$Y"
read -r REMOTE _ <<< "$(folders /opt/racinglines /etc/racinglines.env)"
case "$REMOTE" in /*) REMOTE="$REMOTE/$Y" ;; *) log "couldn't read the VM's data folder (got '$REMOTE')"; exit 1 ;; esac
# Staging (docs/vm-deploy.md "Staging") has its own data folder and can't fetch either. Empty when it isn't set up.
read -r STG_RAW STG_DATA <<< "$(folders /opt/racinglines-staging /etc/racinglines-staging.env)"
case "$STG_RAW" in /*) STG_RAW="$STG_RAW/$Y"; RELAY="$STG_DATA/runs/f1_relay" ;; *) STG_RAW=""; RELAY="" ;; esac
PUSHED="$LOCAL/.pushed-$EV"
mkdir -p "$LOCAL"
touch "$PUSHED"
# when each session is live (epoch seconds), from FastF1's schedule: "start end" per line
WINDOWS="$("$PY" - "$Y" "$R" <<'PYEOF' || true
import logging, sys
import fastf1, pandas as pd
from racinglines.sources.fastf1.fetch import SESSION_LENGTH
logging.getLogger("fastf1").setLevel(logging.ERROR)
ev = fastf1.get_event(int(sys.argv[1]), int(sys.argv[2]))
codes = {"Practice 1": "FP1", "Practice 2": "FP2", "Practice 3": "FP3", "Sprint Qualifying": "SQ",
         "Sprint Shootout": "SQ", "Sprint": "S", "Qualifying": "Q", "Race": "R"}
for i in range(1, 6):
    t, name = ev.get(f"Session{i}DateUtc"), str(ev.get(f"Session{i}"))
    if t is not None and not pd.isna(t) and name in codes:
        t = pd.Timestamp(t)
        print(int(t.timestamp()), int((t + SESSION_LENGTH[codes[name]]).timestamp()))
PYEOF
)"
live_now() {
  local now s e
  now=$(date +%s)
  while read -r s e; do
    [ -n "$s" ] && [ "$now" -ge "$((s - 300))" ] && [ "$now" -le "$e" ] && return 0
  done <<< "$WINDOWS"
  return 1
}
SUMMARY='import json, sys
d = json.load(sys.stdin)
print((d.get("session") or "no session") + ", " + str(len(d.get("drivers") or [])) + " drivers, " + str(d.get("laps"))
      + " laps" + ("; " + d["note"] if d.get("note") else ""))'
relay() {
  local out err="/tmp/f1_relay_$EV.err"
  if ! out=$("$PY" -m racinglines.web.f1_live "$Y" "$R" 2>"$err"); then
    log "live timing: snapshot failed: $(tail -n 1 "$err")"
    return 0
  fi
  if printf '%s' "$out" | remote "sudo -u racinglines mkdir -p $RELAY && sudo -u racinglines tee $RELAY/.$Y-$RR.json >/dev/null && sudo -u racinglines mv -f $RELAY/.$Y-$RR.json $RELAY/$Y-$RR.json" >/dev/null; then
    log "live timing to staging: $(printf '%s' "$out" | "$PY" -c "$SUMMARY")"
  else
    log "live timing: couldn't write to staging"
  fi
}

[ -n "$WINDOWS" ] || log "couldn't read the weekend's schedule from FastF1: finished sessions only, no live timing"
log "$EV: Mac $LOCAL -> VM $REMOTE${STG_RAW:+ and staging $STG_RAW}, a look every $EVERY min${RELAY:+; live timing to staging every $RELAY_SEC s while a session runs}"
T0=$(date +%s)
n=0
last=0
while true; do
  if [ "$(( $(date +%s) - last ))" -ge "$((EVERY * 60))" ]; then
    last=$(date +%s)
    n=$((n + 1))
    "$PY" -m racinglines f1 fetch --years "$Y" --rounds "$R" --sessions FP1,FP2,FP3,SQ,Q,S,R 2>&1 | grep -v "cleared FastF1" || true
    new=()
    all=()
    for f in "$LOCAL/${RR}"_*; do
      [ -f "$f" ] || continue
      b="${f##*/}"
      all+=("$b")
      grep -qxF "$b" "$PUSHED" || new+=("$b")
    done
    if [ "${#new[@]}" -gt 0 ]; then
      # the whole round each time (well under 1 MB): f1 ingest rebuilds a round from every file in the folder, so a
      # folder that only got the newest session (staging, set up mid-weekend) would drop the earlier ones
      tgz="/tmp/f1_push_${EV}_$$.tgz"
      COPYFILE_DISABLE=1 tar --no-xattrs -czf "$tgz" -C "$LOCAL" "${all[@]}"
      gcloud compute scp "$tgz" "$VM:/tmp/f1_push_$EV.tgz" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap
      stg=""
      [ -n "$STG_RAW" ] && stg=" && sudo -u racinglines mkdir -p $STG_RAW && sudo -u racinglines tar --warning=no-unknown-keyword -xzf /tmp/f1_push_$EV.tgz -C $STG_RAW && { ! systemctl is-enabled -q racinglines-staging-live-f1@$EV.timer || sudo systemctl start --no-block racinglines-staging-live-f1@$EV.service; } && echo 'on staging, files copied'"
      remote "sudo -u racinglines mkdir -p $REMOTE && sudo -u racinglines tar --warning=no-unknown-keyword -xzf /tmp/f1_push_$EV.tgz -C $REMOTE && sudo systemctl start --no-block racinglines-live-f1@$EV.service && echo 'on the VM, live step started'$stg; rm -f /tmp/f1_push_$EV.tgz"
      rm -f "$tgz"
      printf '%s\n' "${new[@]}" >> "$PUSHED"
      log "pushed ${#new[@]} files: ${new[*]}"
    fi
    have=$(grep -c . "$PUSHED" || true)
    log "progress f1_push: $(( ($(date +%s) - T0) / 60 )) min elapsed · look $n · $have files on the VM for round $RR"
    if grep -qxF "${RR}_R.results.parquet" "$PUSHED"; then
      log "the race is on the VM; done"
      exit 0
    fi
  fi
  if [ -n "$RELAY" ] && live_now; then
    relay
    sleep "$RELAY_SEC"
  else
    sleep 60
  fi
done
