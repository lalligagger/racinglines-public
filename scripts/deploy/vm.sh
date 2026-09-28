#!/usr/bin/env bash
# Deploy racinglines to its Compute Engine VM (racinglines.bet), from the owner's machine. See docs/vm-deploy.md.
#
#   bash scripts/deploy/vm.sh setup [branch]    # one time: packages, user, checkout (default main), venv, database, units
#   bash scripts/deploy/vm.sh restore           # one time: bucket's data folders + database dump -> the VM
#   bash scripts/deploy/vm.sh start [web]       # enable and start web, recorder, signals (web: the web app only)
#   bash scripts/deploy/vm.sh deploy [ref]      # checkout (default main), install, migrate, restart, smoke check
#   bash scripts/deploy/vm.sh public on|off     # testing before handover: the web app on http://<VM IP>:8000
#   bash scripts/deploy/vm.sh status | logs [unit] | ssh
#
# deploy refuses while a live event's unit is active on the VM (--force to override).
# Needs the gcloud CLI signed in to the project. SSH goes through IAP: the VM opens no ports (but see public).
set -euo pipefail
cd "$(dirname "$0")/../.."
PROJECT="${RL_GCP_PROJECT:-racinglines}"
VM="${RL_VM:-racinglines-vm}"
ZONE="${RL_ZONE:-us-west1-b}"
BUCKET="${RACINGLINES_GCS_BUCKET:-}"     # the new project's bucket (restore needs it)
APP=/opt/racinglines
log() { echo "[vm $(date -u +%H:%M:%S)] $*"; }
remote() { gcloud compute ssh "$VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "$1"; }
as_app() { remote "cd $APP && sudo -u racinglines -H env RACINGLINES_GCS_BUCKET=$BUCKET $1"; }
SERVICES="racinglines-web racinglines-recorder"

case "${1:-}" in
  setup)
    gcloud compute scp deploy/vm/setup.sh "$VM:/tmp/racinglines-setup.sh" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap
    remote "sudo REF=${2:-main} bash /tmp/racinglines-setup.sh"
    ;;
  restore)
    [ -n "$BUCKET" ] || { echo "set RACINGLINES_GCS_BUCKET to the racinglines project's bucket"; exit 1; }
    log "data folders, then the database dump (the VM's database is backed up first if it has tables)"
    as_app "bash scripts/cloud/bucket.sh pull"
    as_app "bash scripts/cloud/bucket.sh restore --yes"
    as_app "bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/alembic upgrade head'"
    ;;
  start)
    # before cutover start only the web app: a second recorder would split the book history across two databases
    units="$SERVICES racinglines-signals.timer"; [ "${2:-}" = web ] && units=racinglines-web
    remote "sudo systemctl enable --now $units && systemctl --no-pager status $units | grep -E '●|Active'"
    ;;
  deploy)
    ref="${2:-main}"; force="${3:-}"
    [ "$ref" = "--force" ] && { ref=main; force=--force; }
    active=$(remote "systemctl list-units --no-legend --state=active 'racinglines-live-*' | awk '{print \$1}'" || true)
    if [ -n "$active" ] && [ "$force" != "--force" ]; then
      echo "a live event is running on the VM ($active): not deploying. Add --force to deploy anyway."; exit 1
    fi
    log "deploy $ref"
    as_app "deploy/vm/update.sh $ref"
    remote "sudo install -m 644 $APP/deploy/vm/systemd/* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl try-restart $SERVICES racinglines-mcp"
    log "smoke check on the VM"
    remote "sleep 3; cd $APP && bash scripts/deploy/smoke.sh http://127.0.0.1:8000"
    ;;
  public)
    # Plain HTTP on a public port, for testing until racinglines.bet moves over; off at handover.
    # Passwords cross the internet unencrypted: sign in with the demo accounts only, never admin.
    dropin=/etc/systemd/system/racinglines-web.service.d/public.conf
    case "${2:-}" in
      on)
        gcloud compute firewall-rules describe rl-test-web --project "$PROJECT" >/dev/null 2>&1 ||
          gcloud compute firewall-rules create rl-test-web --project "$PROJECT" --network default \
            --allow tcp:8000 --target-tags rl-test-web --source-ranges 0.0.0.0/0
        gcloud compute instances add-tags "$VM" --project "$PROJECT" --zone "$ZONE" --tags rl-test-web
        remote "sudo mkdir -p ${dropin%/*} && printf '[Service]\nEnvironment=WEB_HOST=0.0.0.0\n' | sudo tee $dropin >/dev/null && sudo systemctl daemon-reload && sudo systemctl try-restart racinglines-web"
        ip=$(gcloud compute instances describe "$VM" --project "$PROJECT" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
        log "public: http://$ip:8000 (demo accounts only; vm.sh public off at handover)"
        ;;
      off)
        remote "sudo rm -f $dropin && sudo systemctl daemon-reload && sudo systemctl try-restart racinglines-web"
        gcloud compute instances remove-tags "$VM" --project "$PROJECT" --zone "$ZONE" --tags rl-test-web
        gcloud compute firewall-rules delete rl-test-web --project "$PROJECT" --quiet
        log "public port closed"
        ;;
      *) echo "usage: vm.sh public on|off"; exit 1 ;;
    esac
    ;;
  status)
    remote "cd $APP && git log -1 --format='deployed: %h %s (%cr)' && systemctl --no-pager list-units 'racinglines-*' 'cloudflared*' && systemctl --no-pager list-timers 'racinglines-*'"
    ;;
  logs)
    remote "sudo journalctl --no-pager -n 100 -u ${2:-racinglines-web}"
    ;;
  ssh)
    gcloud compute ssh "$VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap
    ;;
  *)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 1
    ;;
esac
