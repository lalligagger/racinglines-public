#!/usr/bin/env bash
# Kalshi and OG.com recorder: one pass, started every 5 minutes by racinglines-record-venues.timer on the VM
# (enable with `bash scripts/deploy/vm.sh record`, stop with `vm.sh record off`). The Polymarket F1 recorder is
# racinglines-recorder.service (`markets record`); this is the same idea for the other two venues, built only from the
# existing read-only commands, so every exchange stays a schema, not new code:
#
#   racinglines markets --exchange kalshi --sport <s> sync | books      (markets/kalshi/sync.py)
#   racinglines markets --exchange og     --sport <s> sync | settle | books   (exchanges/og.toml, markets/exchange_driver.py)
#
# Polling strategy: runs 5-min cadence for each pair, but skips if that sport is not in a race weekend
# (Thu-Sun UTC when an event exists). Off-weeks: exits cleanly, conserving API quota. Every pass: one
# order-book snapshot per open market of each active PAIRS entry (market_book_snapshots, ON CONFLICT DO
# NOTHING). Every SYNC_MIN minutes (default 60): that pair's sync first (market links and quotes upserted:
# new markets appear, settled ones close). Every SETTLE_MIN minutes (default 60), after the sync, a schema exchange
# with a settlement feed (OG.com) records the outcomes of its closed links (`settle`: resolved_yes, and params
# settled_at; bounded by the schema's max_pages and resumed from where the last pass stopped, so a pass reads a few
# pages; Kalshi's outcomes come with its sync). Additive only; no trading, no buy-all. API limits are the
# commands' own (polite HTTP pacing, sources/http.py; OG schema caps). One pair failing doesn't stop
# others; the pass exits non-zero if any failed, so `systemctl status` shows it.
#
# The first pass on a box backs the database up first (syncs add links): data/backups/db/
# racinglines-before-record-venues-<UTC>.sql.gz, named in a data_changes note. Log lines go to the journal
# (journalctl -u racinglines-record-venues) and data/runs/logs/record-venues.log, one per pair per pass:
#   2026-10-01T00:05:02Z kalshi f1 books: 184 book snapshots stored (12 s)
#   2026-10-05T18:30:01Z og nascar: off-week, skipped
set -uo pipefail
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
export PYTHONUNBUFFERED=1
cd "${APP:-/opt/racinglines}"
PAIRS=${PAIRS:-kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp}
SYNC_MIN=${SYNC_MIN:-60}
SETTLE_MIN=${SETTLE_MIN:-60}
STATE=data/runs/record-venues
LOG=data/runs/logs/record-venues.log
mkdir -p "$STATE" data/runs/logs data/backups/db
R=${R:-.venv/bin/racinglines}
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

if [ "${1:-}" = status ]; then   # vm.sh record status: the last passes, and book snapshots per venue per 5 minutes
  systemctl --no-pager list-timers racinglines-record-venues.timer | head -n 2
  echo "--- last passes ($LOG)"; tail -n 12 "$LOG" 2>/dev/null || echo "no pass yet"
  echo "--- book snapshots stored per venue, per 5 minutes (UTC), last 30 minutes"
  docker compose exec -T db psql -U racinglines racinglines -c "
    SELECT to_char(date_trunc('hour', b.ts) + floor(extract(minute FROM b.ts) / 5) * interval '5 min', 'HH24:MI') AS utc,
           l.exchange, count(*) AS snapshots
    FROM market_book_snapshots b JOIN (SELECT DISTINCT token_id, exchange FROM market_links) l USING (token_id)
    WHERE b.ts > now() - interval '30 min' GROUP BY 1, 2 ORDER BY 1, 2"
  exit 0
fi

if [ ! -e "$STATE/backup" ]; then
  B=data/backups/db/racinglines-before-record-venues-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
  say "first pass: backing up to $B"
  docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$B" &&
    gunzip -c "$B" | tail -n 5 | grep -q 'PostgreSQL database dump complete' ||
    { say "BACKUP FAILED: nothing recorded"; rm -f "$B"; exit 1; }
  $R db changes --add "Kalshi and OG.com recorder on (racinglines-record-venues.timer, every 5 min: $PAIRS; syncs every $SYNC_MIN min, additive). Backup: $B" >/dev/null
  echo "$B" > "$STATE/backup"
  say "backup $B ($(du -h "$B" | cut -f1)), data_changes note added"
fi

rc=0
run() {   # run <exchange> <sport> <command>: one line with the command's last output line and its time
  local t0=$SECONDS out
  if out=$(nice $R markets --exchange "$1" --sport "$2" "$3" 2>&1); then
    say "$1 $2 $3: $(echo "$out" | tail -n 1) ($((SECONDS - t0)) s)"
  else
    rc=1; say "$1 $2 $3: FAILED ($((SECONDS - t0)) s): $(echo "$out" | tail -n 3 | tr '\n' ' ')"
    return 1
  fi
}
for p in $PAIRS; do
  x=${p%%:*}; s=${p#*:}; stamp="$STATE/sync-$x-$s"
  if bash scripts/vm/race_weekend.sh "$s" >/dev/null 2>&1; then
    if [ -z "$(find "$stamp" -mmin -"$SYNC_MIN" 2>/dev/null)" ]; then
      run "$x" "$s" sync && touch "$stamp"
    fi
    # a schema exchange's outcomes (exchanges/<x>.toml endpoints.settlements), after its sync, every SETTLE_MIN
    if [ -f "exchanges/$x.toml" ] && [ -z "$(find "$STATE/settle-$x-$s" -mmin -"$SETTLE_MIN" 2>/dev/null)" ]; then
      run "$x" "$s" settle && touch "$STATE/settle-$x-$s"
    fi
    run "$x" "$s" books
  else
    say "$x $s: off-week, skipped"
  fi
done
exit $rc
