#!/usr/bin/env bash
# Deploy racinglines to its Compute Engine VM (racinglines.bet), from the owner's machine. See docs/vm-deploy.md.
#
#   bash scripts/deploy/vm.sh setup [branch]    # one time: packages, user, checkout (default main), venv, database, units
#   bash scripts/deploy/vm.sh restore           # one time: bucket's data folders + database dump -> the VM
#   bash scripts/deploy/vm.sh start [web]       # enable and start web, recorder, signals (web: the web app only);
#                                               # on the Mac it first stops the Mac's recorder and signals agents
#   bash scripts/deploy/vm.sh live <event> [off] # a live event on the VM: an F1 spec with a [window] turns on live
#                                               # auto (below; it stops by itself a day after the results), one
#                                               # without (a rehearsal) its own timer, a step every 5 minutes;
#                                               # live/mtb_dh/<event>.toml: its poll loop; off: disable the per-event unit
#   bash scripts/deploy/vm.sh live auto [off]    # every F1 event whose window is open, from the committed specs, one
#                                               # step each every 5 minutes: no event is started or stopped by hand
#   bash scripts/deploy/vm.sh record [off|status] # the Kalshi and OG.com recorder (scripts/vm/record_venues.sh): a pass
#                                               # every 5 minutes (the first one backs the database up); status: last
#                                               # passes and book snapshots per venue per 5 minutes
#   bash scripts/deploy/vm.sh record fastf1 [on|off|status] # the FastF1 session recorder (scripts/vm/record_fastf1.sh):
#                                               # a pass every 5 minutes on F1 race weekends; status: is-enabled,
#                                               # next run, last passes and snapshots stored
#   bash scripts/deploy/vm.sh pm-sync [off|status]# Polymarket market links sync (scripts/vm/pm_sync.sh): a pass
#                                               # every 5 minutes, every day (WEEKEND_ONLY=1: race weekends only);
#                                               # status: last passes
#   bash scripts/deploy/vm.sh forecast [off|status] # forecast refresh (scripts/vm/forecast-refresh.sh): a pass every
#                                               # 30 minutes; NASCAR and MotoGP forecasts only on their race weekends
#                                               # (scripts/vm/race_weekend.sh), F1 once per new race result;
#                                               # status: last passes
#   bash scripts/deploy/vm.sh schedule [off|status] # session start times (scripts/vm/schedule_sync.sh): a dry run every
#                                               # 6 hours, a backup and the write only when a session is added or moved
#   bash scripts/deploy/vm.sh offsite [off|status|run] # nightly off-site copy (scripts/vm/offsite.sh): prod dump, data/backups and
#                                               # data/archive/markets to the primary bucket; adds there, never deletes
#   bash scripts/deploy/vm.sh switch <NAME> on|off # an app switch (RACINGLINES_*, e.g. RACINGLINES_OG_VENUE) in
#                                               # /etc/racinglines.env, web app restarted; never a trading flag
#   bash scripts/deploy/vm.sh deploy [ref]      # checkout (default main), install, migrate, restart, smoke check
#   bash scripts/deploy/vm.sh docs              # build the docs site on the VM (site/, served at /docs); deploy does it too
#   bash scripts/deploy/vm.sh internal-docs <dir>   # copy a built book (its index.html folder) to data/internal-docs/ on
#                                               # production and staging: /docs/internal/, admins only. Data, never in git
#   bash scripts/deploy/vm.sh backup <purpose>  # the VM database to data/backups/db/racinglines-before-<purpose>-<UTC>.sql.gz
#   bash scripts/deploy/vm.sh repoint           # one time: the VM checkout fetches from REPO_URL (fetch only, no file
#                                               # touched); deploy refuses until the checkout's origin is REPO_URL
#   bash scripts/deploy/vm.sh public on|off     # testing before handover: the web app on http://<VM IP>:8000
#   bash scripts/deploy/vm.sh demo [status|extra] # the multi-sport demo: switches on, NASCAR/MotoGP paper rows and
#                                               # forecasts (backup first); extra: only the Polymarket rows and forecasts
#   bash scripts/deploy/vm.sh accounts [off]    # beta sign-up: back up the database, create the accounts schema and
#                                               # fantasy-bucks ledger (racinglines users setup, idempotent), switch
#                                               # RACINGLINES_SIGNUP on, check /signup; off: the switch off (the ledger stays)
#   bash scripts/deploy/vm.sh postgres logical  # one time, before `mirror on`: production's Postgres with wal_level=logical
#                                               # (restarts the database: seconds; timers paused and resumed like deploy)
#   bash scripts/deploy/vm.sh mirror plan|on [data|accounts|all] | status | repair | off
#                                               # staging as a live copy of production (racinglines/db/mirror.py): the
#                                               # scope's tables follow production within seconds, staging's own rows
#                                               # sit on top. plan: read-only preview; on: backs staging up first.
#                                               # docs/vm-deploy.md "Staging: the data mirror"
#   bash scripts/deploy/vm.sh staging setup [ref] | deploy [ref] [--db demo|main] | status | logs | reset | off | live <event>|auto [off]
#   bash scripts/deploy/vm.sh staging demo-db build|status  # the season demo's own database racinglines_staging_demo
#                                               # (scripts/vm/season_demo.sh, backup first; it persists across deploys)
#   bash scripts/deploy/vm.sh staging db demo|main|status   # which database staging serves (/etc/racinglines-staging-db.env),
#                                               # then a staging deploy of the current checkout; CI deploys keep it
#                                               # staging.racinglines.bet: a second app copy on the VM (port 8010,
#                                               # its own database racinglines_staging and data folder; live: its own
#                                               # run of a live event, like `vm.sh live`). deploy never pauses
#                                               # production's timers or touches its database; CI runs it on a merge
#                                               # to the `staging` branch (deploy/ci/staging.yml). docs/vm-deploy.md "Staging"
#   bash scripts/deploy/vm.sh status | logs [unit] | ssh
#
# deploy never refuses for a live event: it pauses the VM's timers (live-event steps, signals), waits for a step in
# progress, deploys, then resumes them with one catch-up step each (every step is idempotent and catches up).
# Needs the gcloud CLI signed in to the project. SSH goes through IAP: the VM opens no ports (but see public).
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"
SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then SCRIPT_DIR="."; fi
cd "$SCRIPT_DIR/../.."
PROJECT="${RL_GCP_PROJECT:-racinglines}"
VM="${RL_VM:-racinglines-vm}"
ZONE="${RL_ZONE:-us-west1-b}"
BUCKET="${RACINGLINES_GCS_BUCKET:-}"     # the new project's bucket (restore needs it)
APP=/opt/racinglines
REPO_URL="${RL_REPO_URL:-https://github.com/lalligagger/racinglines-public.git}"   # where the VM checkout fetches from (vm.sh repoint)
log() { echo "[vm $(date -u +%H:%M:%S)] $*"; }
remote() { gcloud compute ssh "$VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap --command "$1"; }
as_app() { remote "cd $APP && sudo -u racinglines -H env RACINGLINES_GCS_BUCKET=$BUCKET $1"; }
SERVICES="racinglines-web racinglines-recorder"
PAUSED=/var/lib/racinglines/deploy-paused    # timers a deploy paused and hasn't resumed yet (deploy resumes them)
# production and staging each need their own venv (docs/vm-deploy.md#separate-venvs): checked before a deploy changes anything
venv_check() {
  remote 'p=/opt/racinglines/.venv; s=/opt/racinglines-staging/.venv
    for v in $p $s; do if [ -L $v ]; then echo "refusing: $v is a symlink (to $(readlink -f $v))"; exit 1; fi; done
    if [ -e $p ] && [ -e $s ] && [ "$(readlink -f $p)" = "$(readlink -f $s)" ]; then echo "refusing: $p and $s are the same venv"; exit 1; fi' ||
    { echo "production and staging must not share a venv (docs/vm-deploy.md#separate-venvs): nothing paused, nothing deployed"; exit 1; }
}

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
    ev="${2:-}"; pre=""
    # auto: every F1 event whose window is open, from the committed specs (no per-event start or stop by hand)
    if [ "$ev" = auto ]; then t="racinglines-live-auto.timer"
    elif [ -n "$ev" ] && [ -f "live/f1/$ev.toml" ]; then t="racinglines-live-f1@$ev.timer"
      # an F1 spec with a [window]: live auto owns it, from an hour before the book opens to a day after the results
      # (cli/live.py due_specs), so nothing is left stepping once it is complete; a per-event timer would step the
      # settled event every 5 minutes until turned off. `off` still disables a per-event timer left on from before;
      # a rehearsal spec (no [window]) keeps its own timer.
      if [ "${3:-}" != off ] && grep -q '^\[window\]' "live/f1/$ev.toml"; then
        log "$ev has a [window]: enabling live auto, which steps it until a day after its results (no per-event timer)"
        t="racinglines-live-auto.timer"; pre="{ sudo systemctl disable --now racinglines-live-f1@$ev.timer 2>/dev/null || true; } && "
      fi
    elif [ -n "$ev" ] && [ -f "live/mtb_dh/$ev.toml" ]; then t="racinglines-live-dh@$ev.service"   # the poll loop, no timer
    else echo "usage: vm.sh live <event>|auto [off], with live/f1/<event>.toml or live/mtb_dh/<event>.toml in the repo"; exit 1; fi
    if [ "${3:-}" = off ]; then
      remote "sudo systemctl disable --now $t && echo '$t: off'"
    else
      # before the book opens a step finds nothing due and exits, so enabling early is harmless
      remote "${pre}sudo systemctl enable --now $t && systemctl --no-pager list-timers $t; systemctl --no-pager is-active $t"
    fi
    ;;
  record)
    if [ "${2:-}" = fastf1 ]; then
      # the FastF1 session recorder (scripts/vm/record_fastf1.sh), F1 race weekends only. It has stored no row on the VM
      # so far: F1's timing archive answers 403 there (docs/vm-deploy.md), and its log says BLOCKED when it does
      t=racinglines-record-fastf1.timer
      case "${3:-}" in
        off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
        status) remote "systemctl is-enabled $t; systemctl --no-pager list-timers $t | head -n 2; cd $APP && sudo -u racinglines -H scripts/vm/record_fastf1.sh status" ;;
        ""|on) remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
        *) echo "usage: vm.sh record fastf1 [on|off|status]"; exit 1 ;;
      esac
      exit 0
    fi
    t=racinglines-record-venues.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/record_venues.sh status" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh record [off|status]"; exit 1 ;;
    esac
    ;;
  forecast)
    t=racinglines-forecast-refresh.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/forecast-refresh.sh status" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh forecast [off|status]"; exit 1 ;;
    esac
    ;;
  schedule)
    t=racinglines-schedule-sync.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/schedule_sync.sh status" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh schedule [off|status]"; exit 1 ;;
    esac
    ;;
  offsite)
    t=racinglines-offsite.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/offsite.sh status" ;;
      run) remote "sudo systemctl start racinglines-offsite.service; cd $APP && sudo -u racinglines -H tail -n 8 data/runs/logs/offsite.log" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh offsite [off|status|run]"; exit 1 ;;
    esac
    ;;
  pm-sync)
    t=racinglines-pm-sync.timer
    case "${2:-}" in
      off) remote "sudo systemctl disable --now $t && echo '$t: off'" ;;
      status) remote "cd $APP && sudo -u racinglines -H scripts/vm/pm_sync.sh status" ;;
      "") remote "sudo systemctl enable --now $t && systemctl --no-pager list-timers $t" ;;
      *) echo "usage: vm.sh pm-sync [off|status]"; exit 1 ;;
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
    # tail: a fresh CI runner's first ssh prints its key generation on stdout ahead of the command's own output
    origin=$(as_app "git remote get-url origin" | tail -n 1) || { echo "couldn't reach the VM: nothing paused, nothing deployed"; exit 1; }
    [ "$origin" = "$REPO_URL" ] || { echo "the VM checkout fetches from $origin, not $REPO_URL: run bash scripts/deploy/vm.sh repoint first. Nothing paused, nothing deployed."; exit 1; }
    venv_check
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
    before=""
    if [ -n "$timers" ]; then
      # a failure before the checkout moved (fetch, unknown ref) changed nothing, so the timers resume; after it moved,
      # they stay paused so no step runs on a half-updated checkout
      stopped_early() {
        if [ -n "$before" ] && [ "$(as_app "git rev-parse HEAD" 2>/dev/null | tail -n 1)" = "$before" ] &&
           remote "sudo systemctl start$timers && sudo rm -f $PAUSED"; then
          echo "deploy failed before the checkout changed: nothing deployed, timers resumed:$timers"; return
        fi
        echo "deploy stopped early: these timers may still be paused:$timers"
        echo "  the next vm.sh deploy resumes them (they are listed in $PAUSED on the VM), or by hand: bash scripts/deploy/vm.sh ssh, then: sudo systemctl start$timers"
      }
      trap stopped_early EXIT
      log "pausing:$timers"
      remote "sudo mkdir -p ${PAUSED%/*} && echo '$timers' | sudo tee $PAUSED >/dev/null && sudo systemctl stop$timers"
      log "waiting up to 5 minutes for a step in progress"
      rc=0
      # A signals pass can outlast the wait (about 6 minutes on 2026-10-12, so with its 5-minute timer one is nearly
      # always running): when it is the only step left it is stopped. Safe to cut short: each profile's signals and
      # positions are one transaction, inserts are ON CONFLICT DO NOTHING, and the resumed timer runs a fresh pass
      # (pipelines/signals.py _run_one, store). Live-event and other steps still get the full wait.
      remote "for i in \$(seq 60); do systemctl list-units --no-legend --plain --state=activating$steps | grep -q . || exit 0; sleep 5; done; left=\$(systemctl list-units --no-legend --plain --state=activating$steps | awk '{print \$1}'); if [ \"\$left\" = racinglines-signals.service ]; then echo 'stopping the signals pass still running (the resumed timer runs a fresh one)'; sudo systemctl stop racinglines-signals.service && exit 0; fi; echo 'still running:'; echo \"\$left\"; exit 1" || rc=$?
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
    before=$(as_app "git rev-parse HEAD" | tail -n 1)
    # files the current commit tracks and $ref doesn't: backed up, then untracked, so the checkout keeps them on disk
    # the script goes over ssh's stdin (no temp file on the VM: one left by another ssh user can't be overwritten)
    remote "cd $APP && sudo -u racinglines -H bash -s -- $ref" < deploy/vm/untrack.sh
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
      log "timers running (one 'active' per timer):"
      remote "systemctl is-active$timers"
    fi
    # after the timers resume (it doesn't need them paused); fail-soft, piped over ssh like untrack.sh
    log "docs site (/docs)"
    remote "cd $APP && sudo -u racinglines -H bash -s" < deploy/vm/build_docs.sh || log "docs build didn't finish: /docs keeps its old site (bash scripts/deploy/vm.sh docs to retry)"
    log "smoke check on the VM"
    remote "sleep 3; cd $APP && bash scripts/deploy/smoke.sh http://127.0.0.1:8000"
    ;;
  docs)
    remote "cd $APP && sudo -u racinglines -H bash -s" < deploy/vm/build_docs.sh
    ;;
  internal-docs)
    # The internal onboarding book (a built Jupyter Book's _build/html): data, not code, so it never goes through git.
    # Replaces data/internal-docs/ in production and staging; web/info_routes.py serves it to admins at /docs/internal/.
    src="${2:?usage: vm.sh internal-docs <built html folder, e.g. ~/Documents/racinglines/jb/book/_build/html>}"
    [ -f "$src/index.html" ] || { echo "no index.html in $src: build the book first (jupyter-book build <book>)"; exit 1; }
    tgz="$(mktemp -d)/internal-docs.tgz"
    COPYFILE_DISABLE=1 tar -czf "$tgz" -C "$src" .           # no macOS ._ files
    log "copying $(du -h "$tgz" | cut -f1) to the VM"
    gcloud compute scp "$tgz" "$VM:/tmp/internal-docs.tgz" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap
    rm -rf "$(dirname "$tgz")"
    remote 'set -e; chmod 644 /tmp/internal-docs.tgz
      for app in /opt/racinglines /opt/racinglines-staging; do
        [ -d "$app" ] || continue
        sudo -u racinglines -H bash -c "set -e; t=$app/data/internal-docs; rm -rf \$t.new; mkdir -p \$t.new
          tar -xzf /tmp/internal-docs.tgz -C \$t.new; rm -rf \$t.old; if [ -e \$t ]; then mv \$t \$t.old; fi
          mv \$t.new \$t; rm -rf \$t.old; echo \"\$t: \$(find \$t -type f | wc -l) files\""
      done
      rm -f /tmp/internal-docs.tgz'
    log "done: https://racinglines.bet/docs/internal/ and https://staging.racinglines.bet/docs/internal/ (admins only)"
    ;;
  backup)
    purpose="${2:-}"; case "$purpose" in ""|*[!a-z0-9-]*) echo "usage: vm.sh backup <purpose> (lowercase letters, digits, -)"; exit 1 ;; esac
    remote "cd $APP && sudo -u racinglines -H bash -c 'set -euo pipefail; mkdir -p data/backups/db; b=data/backups/db/racinglines-before-$purpose-\$(date -u +%Y%m%dT%H%M%SZ).sql.gz; docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > \$b; ls -lh \$b'"
    ;;
  repoint)
    # set-url and fetch only: the checkout, its files and the running services are untouched until the next deploy
    # one bash -c so every step runs as the app user (a bare && chain only sudoes the first command)
    as_app "bash -c \"git remote set-url origin $REPO_URL && git fetch --quiet --prune origin && git remote get-url origin && git log -1 --format='checkout still at %h %s'\""
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
  accounts)
    # Beta sign-up (racinglines/web/accounts.py). A DB write, so a backup first; a deploy never does this.
    # Rollback: `vm.sh accounts off` (sign-up closed); the empty accounts schema is harmless and can stay.
    if [ "${2:-}" = off ]; then exec bash "$SCRIPT_PATH" switch RACINGLINES_SIGNUP off; fi
    bash "$SCRIPT_PATH" backup accounts-setup
    log "creating the accounts schema and ledger (idempotent)"
    as_app "bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/racinglines users setup'"
    bash "$SCRIPT_PATH" switch RACINGLINES_SIGNUP on
    remote "sleep 3; curl -s -o /dev/null -w 'GET /signup: %{http_code}\\n' http://127.0.0.1:8000/signup"
    log "sign-up is open at https://racinglines.bet/signup (accounts: /admin/users)"
    ;;
  postgres)
    # One time, before `vm.sh mirror on` (docs/vm-deploy.md "Staging: the data mirror"): production's Postgres with
    # wal_level=logical, so it can publish tables to staging. The setting needs a restart of the database container
    # (seconds): the timers are paused and resumed as a deploy does, and the app services restart after it.
    # max_slot_wal_keep_size caps what a stalled mirror can make production keep on disk (past it the mirror breaks,
    # never production). No row is read or written.
    [ "${2:-}" = logical ] || { echo "usage: vm.sh postgres logical"; exit 1; }
    pgq() { as_app "docker compose exec -T db psql -U racinglines -d postgres -tAc \"$1\"" | tail -n 1; }
    if [ "$(pgq 'SHOW wal_level')" = logical ]; then log "wal_level is already logical: nothing to do"; exit 0; fi
    timers=$(remote "systemctl list-units --no-legend --plain --state=active 'racinglines-*.timer' | awk '{print \$1}'" | tr '\n' ' ')
    steps=""; for u in $timers; do steps="$steps ${u%.timer}.service"; done
    resume() { if [ -n "$timers" ]; then remote "sudo systemctl start $timers && sudo rm -f $PAUSED" && log "timers resumed: $timers"; fi; }
    trap resume EXIT
    if [ -n "$timers" ]; then
      log "pausing: $timers"
      remote "sudo mkdir -p ${PAUSED%/*} && echo '$timers' | sudo tee $PAUSED >/dev/null && sudo systemctl stop $timers"
      remote "for i in \$(seq 60); do systemctl list-units --no-legend --plain --state=activating $steps | grep -q . || exit 0; sleep 5; done; echo 'a step is still running after 5 minutes: nothing changed'; exit 1"
    fi
    log "wal_level=logical, max_slot_wal_keep_size=2GB, then restarting the database container"
    pgq "ALTER SYSTEM SET wal_level = logical" >/dev/null
    pgq "ALTER SYSTEM SET max_slot_wal_keep_size = '2GB'" >/dev/null
    as_app "docker compose restart db" >/dev/null
    remote "cd $APP && for i in \$(seq 30); do sudo -u racinglines -H docker compose exec -T db pg_isready -U racinglines -q && exit 0; sleep 2; done; echo 'database not ready after 60 s'; exit 1"
    remote "sudo systemctl try-restart $SERVICES racinglines-mcp racinglines-staging-web"
    log "wal_level is now $(pgq 'SHOW wal_level')"
    remote "sleep 3; cd $APP && bash scripts/deploy/smoke.sh http://127.0.0.1:8000"
    ;;
  mirror)
    # Staging as a live copy of production (racinglines/db/mirror.py; docs/vm-deploy.md "Staging: the data mirror").
    # Runs from staging's checkout with staging's env file. Production is reached by a read-only replication role; its
    # catalog gets that role, a publication and a slot (on/off), and no production row is ever written.
    STG=/opt/racinglines-staging
    m() { remote "cd $STG && sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines-staging.env; set +a; PYTHONUNBUFFERED=1 .venv/bin/python -m racinglines.db.mirror $1'"; }
    scope="${3:-all}"
    case "$scope" in data|accounts|all) ;; *) echo "scope: data | accounts | all"; exit 1 ;; esac
    case "${2:-}" in
      plan) m "plan --scope $scope" ;;
      status|repair) m "$2" ;;
      on)
        log "backing up racinglines_staging first (staging rows production doesn't have as-is are replaced: mirror plan counts them)"
        remote "cd $APP && sudo -u racinglines -H bash -c 'set -euo pipefail; mkdir -p $STG/data/backups/db; b=$STG/data/backups/db/racinglines_staging-before-mirror-\$(date -u +%Y%m%dT%H%M%SZ).sql.gz; docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines_staging | gzip -6 > \$b; ls -lh \$b'"
        m "on --scope $scope"
        # production's market archive (Parquet: the rows its recorder moves out of Postgres, which the mirror then
        # deletes from staging too) is read in place; staging never archives (markets/store.py refuses)
        log "staging reads production's data/archive in place"
        remote "sudo -u racinglines -H bash -c 'set -e; t=$STG/data/archive; if [ -d \$t ] && [ ! -L \$t ]; then mv \$t \$t.pre-mirror; fi; ln -sfn $APP/data/archive \$t; ls -ld \$t'"
        remote "sudo install -m 644 $STG/deploy/vm/systemd/racinglines-staging-mirror-check.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now racinglines-staging-mirror-check.timer && systemctl is-active racinglines-staging-mirror-check.timer"
        ;;
      off)
        remote "sudo systemctl disable --now racinglines-staging-mirror-check.timer 2>/dev/null || true"
        m off
        log "staging keeps its rows as of now, and still reads production's data/archive"
        ;;
      *) echo "usage: vm.sh mirror plan [scope] | on [scope] | status | repair | off   (scope: data | accounts | all)"; exit 1 ;;
    esac
    ;;
  staging)
    # Staging on the same VM (docs/vm-deploy.md "Staging"): /opt/racinglines-staging, racinglines_staging in production's
    # Postgres container, /etc/racinglines-staging.env, racinglines-staging-web on 127.0.0.1:8010. None of these commands
    # reads $PAUSED, stops a timer, runs untrack.sh or opens /etc/racinglines.env for writing: production is untouched.
    STG=/opt/racinglines-staging
    SU=racinglines-staging-web
    as_stg() { remote "cd $STG && sudo -u racinglines -H $1"; }
    case "${2:-}" in
      setup)
        # piped over ssh (the VM needs none of these files yet); REF: the branch to check out (default staging, else main)
        log "staging setup (checkout, venv, database copy, env file, unit)"
        remote "sudo REF=${3:-staging} RESET_DB=0 bash -s" < deploy/vm/staging/setup.sh
        ;;
      reset)
        log "staging reset: drop racinglines_staging and copy production's rows again (production is only read)"
        remote "sudo REF=${3:-staging} RESET_DB=1 bash -s" < deploy/vm/staging/setup.sh
        ;;
      deploy)
        ref="${3:-staging}"
        case "$ref" in --db) ref=staging; set -- "$1" "$2" staging "$3" "${4:-}" ;; esac
        if [ "${4:-}" = --db ]; then
          case "${5:-}" in demo|main) bash "$SCRIPT_PATH" staging db "$5" --no-deploy ;;
            *) echo "usage: vm.sh staging deploy [ref] [--db demo|main]"; exit 1 ;; esac
        fi
        origin=$(as_stg "git remote get-url origin" | tail -n 1) || { echo "couldn't reach the VM or $STG is missing: run bash scripts/deploy/vm.sh staging setup first"; exit 1; }
        [ "$origin" = "$REPO_URL" ] || { echo "$STG fetches from $origin, not $REPO_URL: nothing deployed"; exit 1; }
        venv_check
        # Check for concurrent staging workflow runs and warn (but don't block)
        if command -v gh >/dev/null 2>&1; then
          if gh run list --workflow staging.yml --status in_progress --limit 1 2>/dev/null | grep -q .; then
            echo "warning: a staging workflow run is in progress; deploys share one queue"
          fi
        fi
        log "staging deploy $ref (production's timers keep running)"
        remote "cd $STG && sudo -u racinglines -H bash -s -- $ref" < deploy/vm/staging/update.sh
        remote "sudo install -m 644 $STG/deploy/vm/systemd/$SU.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart $SU && sleep 3 && systemctl is-active $SU"
        # staging's own /docs (its checkout's site/), fail-soft like production's
        log "docs site (/docs)"
        remote "sudo -u racinglines -H bash -s -- $STG" < deploy/vm/build_docs.sh || log "docs build didn't finish: staging's /docs keeps its old site"
        log "smoke check on the VM (expects the staging instance: X-Racinglines-Env: staging)"
        remote "cd $STG && SMOKE_EXPECT_ENV=staging bash scripts/deploy/smoke.sh http://127.0.0.1:8010"
        ;;
      db)
        # the database switch: demo = the season demo's racinglines_staging_demo, main = racinglines_staging (the
        # default). One override file the web unit reads after its env file; staging deploys (CI too) keep it.
        DBENV=/etc/racinglines-staging-db.env
        case "${3:-}" in
          demo)
            remote "cd /opt/racinglines && sudo -u racinglines docker compose exec -T db psql -U racinglines -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='racinglines_staging_demo'\" | grep -q 1" ||
              { echo "no racinglines_staging_demo yet: bash scripts/deploy/vm.sh staging demo-db build first"; exit 1; }
            remote "u=\$(sudo grep -E '^DATABASE_URL=' /etc/racinglines-staging.env | tail -n 1 | cut -d= -f2-); echo \"DATABASE_URL=\${u%/*}/racinglines_staging_demo\" | sudo tee $DBENV.tmp >/dev/null && sudo install -o root -g racinglines -m 640 $DBENV.tmp $DBENV && sudo rm -f $DBENV.tmp && echo 'staging database: demo (racinglines_staging_demo)'" ;;
          main)
            remote "sudo rm -f $DBENV && echo 'staging database: main (racinglines_staging)'" ;;
          status|"")
            remote "if [ -f $DBENV ]; then echo 'staging database: demo'; sudo cat $DBENV | sed 's/:[^:@]*@/:***@/'; else echo 'staging database: main (racinglines_staging)'; fi"
            exit 0 ;;
          *) echo "usage: vm.sh staging db demo|main|status"; exit 1 ;;
        esac
        [ "${4:-}" = --no-deploy ] && exit 0
        ref=$(as_stg "git rev-parse HEAD" | tail -n 1)
        log "redeploying staging's checkout ${ref:0:12} on the switched database"
        exec bash "$SCRIPT_PATH" staging deploy "$ref"
        ;;
      demo-db)
        case "${3:-status}" in
          build)
            remote "sudo systemctl is-active --quiet rl-season-demo && { echo 'rl-season-demo is already running'; exit 1; }; sudo systemctl reset-failed rl-season-demo 2>/dev/null; sudo systemd-run --unit=rl-season-demo --uid=racinglines --setenv=SEED=${SEED:-2026} --setenv=YEAR=${YEAR:-2026} --setenv=COPY=${COPY:-0} --setenv=SOURCE=${SOURCE:-racinglines} bash $STG/scripts/vm/season_demo.sh && echo 'started rl-season-demo: bash scripts/deploy/vm.sh staging demo-db status'" ;;
          status)
            remote "systemctl --no-pager is-active rl-season-demo; cd $STG && ls -t data/runs/logs/season-demo-*.log 2>/dev/null | head -n 1 | xargs -r tail -n 15; ls data/runs/logs/season-demo.done data/runs/logs/season-demo.failed 2>/dev/null || true" ;;
          *) echo "usage: vm.sh staging demo-db build|status (env SEED, YEAR, COPY=1 re-copies, SOURCE=racinglines|racinglines_staging)"; exit 1 ;;
        esac
        ;;
      status)
        remote "cd $STG 2>/dev/null && sudo -u racinglines -H git log -1 --format='staging: %h %s (%cr)' || echo 'staging: not set up'; systemctl --no-pager list-units '$SU*' 'racinglines-staging-live-*' 'racinglines-staging-mirror-*' ; systemctl --no-pager list-timers 'racinglines-staging-live-*' 'racinglines-staging-mirror-*' ; curl -s -o /dev/null -w 'GET http://127.0.0.1:8010/login: %{http_code}  X-Racinglines-Env: %header{x-racinglines-env}\n' http://127.0.0.1:8010/login || true"
        ;;
      logs)
        remote "sudo journalctl --no-pager -n 100 -u $SU"
        ;;
      off)
        remote "sudo systemctl disable --now $SU && echo '$SU: off (the checkout, database and env file stay)'"
        ;;
      live)
        # staging's own live run (its data folder and database), the twin of `vm.sh live`; production's are untouched
        ev="${3:-}"; pre=""
        if [ "$ev" = auto ]; then u="racinglines-staging-live-auto"; t="${u}.timer"
        elif [ -n "$ev" ] && [ -f "live/f1/$ev.toml" ]; then u="racinglines-staging-live-f1@"; t="${u}$ev.timer"
          # as `vm.sh live`: an F1 spec with a [window] is stepped by staging's live auto, not a per-event timer
          if [ "${4:-}" != off ] && grep -q '^\[window\]' "live/f1/$ev.toml"; then
            log "$ev has a [window]: enabling staging's live auto, which steps it until a day after its results"
            u="racinglines-staging-live-auto"; t="${u}.timer"
            pre="{ sudo systemctl disable --now racinglines-staging-live-f1@$ev.timer 2>/dev/null || true; } && "
          fi
        elif [ -n "$ev" ] && [ -f "live/mtb_dh/$ev.toml" ]; then u="racinglines-staging-live-dh@"; t="${u}$ev.service"
        else echo "usage: vm.sh staging live <event>|auto [off], with live/f1/<event>.toml or live/mtb_dh/<event>.toml in the repo"; exit 1; fi
        if [ "${4:-}" = off ]; then
          remote "sudo systemctl disable --now $t && echo '$t: off'"
        else
          remote "${pre}sudo install -m 644 $STG/deploy/vm/systemd/${u}.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now $t && systemctl --no-pager is-active $t"
        fi
        ;;
      *) echo "usage: vm.sh staging setup [ref] | deploy [ref] [--db demo|main] | db demo|main|status | demo-db build|status | status | logs | reset | off | live <event> [off]"; exit 1 ;;
    esac
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
