#!/usr/bin/env bash
# Deploy racinglines to its Compute Engine VM (racinglines.bet), from the owner's machine. See docs/vm-deploy.md.
#
#   bash scripts/deploy/vm.sh setup [branch]    # one time: packages, user, checkout (default main), venv, database, units
#   bash scripts/deploy/vm.sh restore           # one time: bucket's data folders + database dump -> the VM
#   bash scripts/deploy/vm.sh start [web]       # enable and start web, recorder, signals (web: the web app only);
#                                               # on the Mac it first stops the Mac's recorder and signals agents
#   bash scripts/deploy/vm.sh live <event> [off] # a live event's timer on the VM (live/f1/<event>.toml): enable
#                                               # and start it (a step every 5 minutes), or off: stop and disable it
#   bash scripts/deploy/vm.sh record [off|status] # the Kalshi and OG.com recorder (scripts/vm/record_venues.sh): a pass
#                                               # every 5 minutes (the first one backs the database up); status: last
#                                               # passes and book snapshots per venue per 5 minutes
#   bash scripts/deploy/vm.sh switch <NAME> on|off # an app switch (RACINGLINES_*, e.g. RACINGLINES_OG_VENUE) in
#                                               # /etc/racinglines.env, web app restarted; never a trading flag
#   bash scripts/deploy/vm.sh deploy [ref]      # checkout (default main), install, migrate, restart, smoke check
#   bash scripts/deploy/vm.sh public on|off     # testing before handover: the web app on http://<VM IP>:8000
#   bash scripts/deploy/vm.sh demo [status|extra] # the multi-sport demo: switches on, NASCAR/MotoGP paper rows and
#                                               # forecasts (backup first); extra: only the Polymarket rows and forecasts
#   bash scripts/deploy/vm.sh status | logs [unit] | ssh
#
# deploy never refuses for a live event: it pauses the VM's timers (live-event steps, signals), waits for a step in
# progress, deploys, then resumes them with one catch-up step each (every step is idempotent and catches up).
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
PAUSED=/var/lib/racinglines/deploy-paused    # timers a deploy paused and hasn't resumed yet (deploy resumes them)

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
    # after cutover, the Mac's LaunchAgents must not record too (docs/vm-deploy.md "Cutover"); bootout is idempotent
    # here and undone by `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`
    if [ "${2:-}" != web ] && command -v launchctl >/dev/null; then
      for a in bet.racinglines.recorder bet.racinglines.signals; do
        launchctl print "gui/$(id -u)/$a" >/dev/null 2>&1 && launchctl bootout "gui/$(id -u)/$a" && log "stopped the Mac's $a"
      done
    fi
    remote "sudo systemctl enable --now $units && systemctl --no-pager status $units | grep -E '●|Active'"
    ;;
  live)
    ev="${2:-}"
    [ -n "$ev" ] && [ -f "live/f1/$ev.toml" ] || { echo "usage: vm.sh live <event> [off], with live/f1/<event>.toml in the repo"; exit 1; }
    t="racinglines-live-f1@$ev.timer"
    if [ "${3:-}" = off ]; then
      remote "sudo systemctl disable --now $t && echo '$t: off'"
    else
      # before the book opens a step finds nothing due and exits, so enabling early is harmless
      remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t"
    fi
    ;;
  record)
    t=racinglines-record-venues.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/record_venues.sh status" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh record [off|status]"; exit 1 ;;
    esac
    ;;
  switch)
    name="${2:-}"; val=""
    case "${3:-}" in on) val=1 ;; off) val=0 ;; esac
    case "$name" in
      *TRADING*) echo "trading flags are never set by vm.sh: they need the owner's sign-off and a hand edit"; exit 1 ;;
      RACINGLINES_[A-Z0-9_]*) ;;
      *) name="" ;;
    esac
    [ -n "$name" ] && [ -n "$val" ] || { echo "usage: vm.sh switch RACINGLINES_<NAME> on|off"; exit 1; }
    remote "sudo sed -i -E '/^$name=/d' /etc/racinglines.env && echo '$name=$val' | sudo tee -a /etc/racinglines.env >/dev/null && sudo systemctl try-restart racinglines-web && sudo grep -E '^$name=' /etc/racinglines.env"
    ;;
  deploy)
    ref="${2:-main}"
    [ "$ref" = "--force" ] && { log "--force is no longer needed: deploy pauses and resumes live events"; ref="${3:-main}"; }
    # Pause, don't refuse. The timers (racinglines-live-f1@<event>.timer, racinglines-signals.timer) start oneshot
    # steps every 5 minutes; stop them and wait for a step already running ("activating"), so no step runs while
    # update.sh rewrites the checkout. Each step is idempotent and catches up: an F1 live step does every update
    # that fell due meanwhile, and its crowd batch covers the whole window since the last update
    # (pipelines/live_f1.py due, _crowd); signals inserts with ON CONFLICT DO NOTHING. What was paused is written to
    # $PAUSED on the VM first, so a deploy that dies half-way is resumed by the next one (and `status` shows it).
    # The recorder's restart costs at most one book snapshot, which no exchange keeps.
    units=$(remote "set -o pipefail; a=\$(systemctl list-units --no-legend --plain --state=active 'racinglines-*.timer' 'racinglines-live-dh@*.service' | awk '{print \$1}') || exit 1; { echo \"\$a\"; cat $PAUSED 2>/dev/null || true; } | tr ' ' '\n' | sort -u" | tr '\n' ' ') ||
      { echo "couldn't list the VM's timers: nothing paused, nothing deployed"; exit 1; }
    timers=""; dh=""; live=""; steps=""
    for u in $units; do
      case "$u" in
        racinglines-live-dh@*) dh="$dh $u" ;;
        *.timer) timers="$timers $u"; steps="$steps ${u%.timer}.service"
                 case "$u" in racinglines-live-*) live="$live ${u%.timer}.service" ;; esac ;;
      esac
    done
    [ -n "$dh" ] && log "WARNING: a downhill loop is running ($dh ). Deploy doesn't restart it: it keeps the code it loaded, and a later lazy import may read the new files. Deploy after the final if you can."
    if [ -n "$timers" ]; then
      trap 'echo "deploy stopped early: these timers may still be paused:$timers"; echo "  the next vm.sh deploy resumes them (they are listed in $PAUSED on the VM), or by hand: bash scripts/deploy/vm.sh ssh, then: sudo systemctl start$timers"' EXIT
      log "pausing:$timers"
      remote "sudo mkdir -p ${PAUSED%/*} && echo '$timers' | sudo tee $PAUSED >/dev/null && sudo systemctl stop$timers"
      log "waiting up to 5 minutes for a step in progress"
      rc=0
      remote "for i in \$(seq 60); do systemctl list-units --no-legend --plain --state=activating$steps | grep -q . || exit 0; sleep 5; done; echo 'still running:'; systemctl list-units --no-legend --plain --state=activating$steps | awk '{print \$1}'; exit 1" || rc=$?
      if [ "$rc" -ne 0 ]; then
        remote "sudo systemctl start$timers && sudo rm -f $PAUSED" && trap - EXIT
        if [ "$rc" -eq 1 ]; then
          echo "a step was still running after 5 minutes (above): nothing deployed, timers resumed. A hung step: bash scripts/deploy/vm.sh logs <unit>, then on the VM: sudo systemctl stop <unit>"
        else
          echo "lost the connection while waiting (ssh exit $rc): nothing deployed"
        fi
        exit 1
      fi
    fi
    log "deploy $ref"
    as_app "deploy/vm/update.sh $ref"
    remote "sudo install -m 644 $APP/deploy/vm/systemd/* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl try-restart $SERVICES racinglines-mcp"
    if [ -n "$timers" ]; then
      # the live events' catch-up step first (it and signals both price a stage whose data landed during the pause)
      if [ -n "$live" ]; then
        log "catch-up step:$live"
        remote "sudo timeout 300 systemctl start$live" || log "the catch-up step didn't finish cleanly within 5 minutes (still running, it carries on under systemd): bash scripts/deploy/vm.sh logs <unit>"
      fi
      log "resuming:$timers"
      remote "sudo systemctl start$timers && sudo rm -f $PAUSED"
      trap - EXIT
    fi
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
  demo)
    # The multi-sport demo (docs/webapp.md "Every sport's status"): RACINGLINES_SPORT_STATUS=1 (Markets: every sport's
    # data, model and backtest status) and RACINGLINES_SPORT_PAPER=1 (NASCAR / MotoGP demo paper rows on Positions and
    # Strategy) in /etc/racinglines.env, the web app restarted, then scripts/vm/demo_setup.sh as the transient unit
    # rl-demo (backup first, then both sports' demo-history for maker and taker). `demo status`: the unit and its log.
    if [ "${2:-}" = status ]; then
      remote "systemctl --no-pager status rl-demo 2>/dev/null | grep -E 'Active' || echo 'rl-demo: not running'; cd $APP; ls -1t data/runs/logs/demo-setup.done data/runs/logs/demo-setup.failed 2>/dev/null; f=\$(ls -1t data/runs/logs/demo-setup-*.log 2>/dev/null | head -1); [ -n \"\$f\" ] && grep -E '^(backup|==|SKIP|DEMO-SETUP|nascar|motogp|maker|taker|Stored|Deleted|FAIL)' \"\$f\" | grep -vE '^(maker|taker) (nascar|motogp) ' | tail -n 20; true"
      exit 0
    fi
    remote "systemctl is-active --quiet rl-demo" && { echo "rl-demo is already running: bash scripts/deploy/vm.sh demo status"; exit 1; }
    log "switches on: RACINGLINES_SPORT_STATUS=1 RACINGLINES_SPORT_PAPER=1, web app restarted"
    remote "sudo sed -i -E '/^RACINGLINES_SPORT_(STATUS|PAPER)=/d' /etc/racinglines.env && printf 'RACINGLINES_SPORT_STATUS=1\nRACINGLINES_SPORT_PAPER=1\n' | sudo tee -a /etc/racinglines.env >/dev/null && sudo systemctl try-restart racinglines-web"
    log "starting rl-demo (backup, then NASCAR and MotoGP demo-history for maker and taker)"
    steps="kalshi polymarket forecast"; [ "${2:-}" = extra ] && steps="polymarket forecast"
    remote "sudo systemctl reset-failed rl-demo 2>/dev/null; sudo systemd-run --unit=rl-demo --uid=racinglines --setenv=RACINGLINES_SPORT_PAPER=1 '--setenv=STEPS=$steps' $APP/scripts/vm/demo_setup.sh"
    log "started: Markets shows every sport now; the NASCAR and MotoGP paper rows fill in as rl-demo runs. Check: bash scripts/deploy/vm.sh demo status"
    ;;
  status)
    # git runs as the app user: /opt/racinglines is owned by racinglines, and git refuses another user's repository
    remote "cd $APP && sudo -u racinglines -H git log -1 --format='deployed: %h %s (%cr)' && systemctl --no-pager list-units 'racinglines-*' 'cloudflared*' && systemctl --no-pager list-timers 'racinglines-*' && { test -s $PAUSED && echo \"PAUSED by an unfinished deploy (the next deploy resumes them): \$(cat $PAUSED)\" || true; }"
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
