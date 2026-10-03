#!/usr/bin/env bash
# An F1 weekend's sessions from the owner's Mac to the VM. F1's timing archive (livetiming.formula1.com) answers 403
# to the VM's cloud address (3 Oct 2026: the 2026 index and every round 16 session), so FastF1 can't fetch there.
# This loop, run on the Mac, fetches each session once it has started (f1 fetch skips sessions not started and those
# already on disk; one still running or unpublished fails and is tried again next look), copies new session files to
# the VM's data folder and runs the event's live step, which ingests and prices them. It stops once the race is there.
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
Y="${EV%-*}"
R="${EV#*-}"
RR=$(printf %02d "$((10#$R))")
PY="${PY:-.venv/bin/python}"
PROJECT="${RL_GCP_PROJECT:-racinglines}"
VM="${RL_VM:-racinglines-vm}"
ZONE="${RL_ZONE:-us-west1-b}"
remote() { gcloud compute ssh "$VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "$1"; }
log() { echo "[f1_push $(date -u +%H:%M:%S)] $*"; }

LOCAL="$("$PY" -c 'from racinglines import paths; print(paths.F1_RAW)')/$Y"
REMOTE="$(remote "cd /opt/racinglines && sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/python -c \"from racinglines import paths; print(paths.F1_RAW)\"'" | tail -n 1)/$Y"
case "$REMOTE" in /*) ;; *) log "couldn't read the VM's data folder (got '$REMOTE')"; exit 1 ;; esac
PUSHED="$LOCAL/.pushed-$EV"
mkdir -p "$LOCAL"
touch "$PUSHED"
log "$EV: Mac $LOCAL -> VM $REMOTE, a look every $EVERY min"
T0=$(date +%s)
n=0
while true; do
  n=$((n + 1))
  "$PY" -m racinglines f1 fetch --years "$Y" --rounds "$R" --sessions FP1,FP2,FP3,SQ,Q,S,R 2>&1 | grep -v "cleared FastF1" || true
  new=()
  for f in "$LOCAL/${RR}"_*; do
    [ -f "$f" ] || continue
    b="${f##*/}"
    grep -qxF "$b" "$PUSHED" || new+=("$b")
  done
  if [ "${#new[@]}" -gt 0 ]; then
    tgz="/tmp/f1_push_${EV}_$$.tgz"
    COPYFILE_DISABLE=1 tar --no-xattrs -czf "$tgz" -C "$LOCAL" "${new[@]}"
    gcloud compute scp "$tgz" "$VM:/tmp/f1_push_$EV.tgz" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap
    remote "sudo -u racinglines mkdir -p $REMOTE && sudo -u racinglines tar --warning=no-unknown-keyword -xzf /tmp/f1_push_$EV.tgz -C $REMOTE && rm -f /tmp/f1_push_$EV.tgz && sudo systemctl start --no-block racinglines-live-f1@$EV.service && echo 'on the VM, live step started'"
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
  sleep $((EVERY * 60))
done
