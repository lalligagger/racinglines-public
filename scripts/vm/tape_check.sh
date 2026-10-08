#!/usr/bin/env bash
# Missing or stale market tape, flagged instead of left as a silent gap (P0, 2026-10-07: the bets thread found
# no Kalshi links for Singapore on the Wednesday before it, and the newest Kalshi sync from Sunday 4 Oct). Read-only.
#
# Usage: tape_check.sh <exchange> <sport>
#
# For each of the sport's events from 3 days ago to LEAD_DAYS (default 7) ahead, not cancelled: the exchange's links
# with a race of that event, and the newest sync among them (market_links.synced_at). Prints one line per event:
#   OK   kalshi f1 <event key> <event name>: <n> links, last sync <h> h ago
#   WARN kalshi f1 <event key> <event name>: no links with this race (sync, then link)
#   WARN kalshi f1 <event key> <event name>: <n> links, last sync <h> h ago (over STALE_HOURS=3)
#   SKIP og f1: no race market on this exchange for this sport yet
# Exit 0 with no WARN line, 1 with any. The recorders (record_venues.sh, pm_sync.sh) call it after their sync and
# log its lines; `vm.sh record status` shows the latest.
set -euo pipefail
X="${1:?exchange}"
SPORT="${2:?sport}"
set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
cd "${APP:-/opt/racinglines}"
LEAD_DAYS=${LEAD_DAYS:-7}
STALE_HOURS=${STALE_HOURS:-3}
COMPETITION=$(awk '/^\[/{sec=$0} sec=="[competition]" && /^code *=/{gsub(/.*= *"|".*/, ""); print; exit}' "sports/$SPORT.toml" 2>/dev/null || true)
[ -n "$COMPETITION" ] || { echo "tape_check: no [competition] code in sports/$SPORT.toml" >&2; exit 2; }
case "$X" in *[!a-z0-9_]*) echo "tape_check: bad exchange '$X'" >&2; exit 2 ;; esac
case "$COMPETITION" in *[!a-z0-9_]*) echo "tape_check: bad competition code '$COMPETITION'" >&2; exit 2 ;; esac

QUERY="SELECT e.source_key, e.name, count(ml.id),
              coalesce(round(extract(epoch FROM now() - max(ml.synced_at)) / 3600.0, 1)::text, '')
       FROM events e
       JOIN seasons s ON s.id = e.season_id
       JOIN competitions c ON c.id = s.competition_id
       LEFT JOIN races ra ON ra.event_id = e.id
       LEFT JOIN market_links ml ON ml.race_id = ra.id AND ml.exchange = '$X'
       WHERE c.code = '$COMPETITION' AND e.status <> 'cancelled'
         AND e.start_date >= (now() at time zone 'utc')::date - 3
         AND e.start_date < (now() at time zone 'utc')::date + $LEAD_DAYS
       GROUP BY e.id, e.source_key, e.name, e.start_date ORDER BY e.start_date"

# An exchange that has never listed a race market for this sport (OG.com lists only season markets) has nothing to
# check: one SKIP line instead of a WARN per event
EVER=$(docker compose exec -T db psql -U racinglines racinglines -tA -c "SELECT count(*) FROM market_links ml
       JOIN competitions c ON c.id = ml.competition_id WHERE c.code = '$COMPETITION' AND ml.exchange = '$X'
       AND ml.race_id IS NOT NULL" | tr -d ' ')
if [ "${EVER:-0}" = 0 ]; then
  echo "SKIP $X $SPORT: no race market on this exchange for this sport yet"
  exit 0
fi

warn=0
while IFS='|' read -r key name links age; do
  [ -n "$key" ] || continue
  if [ "$links" -eq 0 ]; then
    echo "WARN $X $SPORT $key $name: no links with this race (sync, then link)"; warn=1
  elif [ -z "$age" ] || awk -v a="$age" -v h="$STALE_HOURS" 'BEGIN { exit !(a > h) }'; then
    echo "WARN $X $SPORT $key $name: $links links, last sync ${age:-never} h ago (over STALE_HOURS=$STALE_HOURS)"; warn=1
  else
    echo "OK   $X $SPORT $key $name: $links links, last sync $age h ago"
  fi
done < <(docker compose exec -T db psql -U racinglines racinglines -tA -F'|' -c "$QUERY")
exit $warn
