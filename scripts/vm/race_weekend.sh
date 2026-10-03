#!/usr/bin/env bash
# Check if a sport is currently in a race weekend (Thurs-Sun UTC).
# Used by all polling scripts to control when data syncing runs.
#
# Usage: race_weekend.sh <sport> [--verbose]
#        exit 0 = in a race weekend, run polling
#        exit 1 = off-week or no events, skip polling
#
# Example: if race_weekend.sh f1; then racinglines markets --exchange polymarket sync; fi

set -euo pipefail

SPORT="${1:-f1}"
VERBOSE="${2:-}"

if [ -z "$SPORT" ]; then
  echo "Usage: race_weekend.sh <sport> [--verbose]" >&2
  exit 1
fi

set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
cd "${APP:-/opt/racinglines}"

# Get UTC day of week (0=Sunday, 1=Monday, ..., 4=Thursday)
NOW_UTC=$(date -u +%s)
DOW=$(date -u -d @"$NOW_UTC" +%w)  # 0=Sun, 1=Mon, ..., 4=Thu, ..., 6=Sat

# Race weekend = Thursday (4) through Sunday (0), inclusive
# In UTC terms: Thu=4, Fri=5, Sat=6, Sun=0
RACE_WEEKEND=0
if [ "$DOW" -ge 4 ] || [ "$DOW" -eq 0 ]; then
  RACE_WEEKEND=1
fi

# Query: is there an active event for this sport in the next 7 days?
# (backup check: if DB query fails, assume not a race weekend)
if [ "$RACE_WEEKEND" -eq 1 ]; then
  NOW=$(date -u +%Y-%m-%dT%H:%M:%S)
  WEEK_LATER=$(date -u -d @"$((NOW_UTC + 604800))" +%Y-%m-%dT%H:%M:%S)

  QUERY="SELECT COUNT(*) FROM events e
         JOIN seasons s ON e.season_id = s.id
         JOIN competitions c ON s.competition_id = c.id
         WHERE c.code IN (SELECT competition_code FROM (
           SELECT 'f1_wdc' as competition_code WHERE '$SPORT' = 'f1'
           UNION SELECT 'nascar_cup' WHERE '$SPORT' = 'nascar'
           UNION SELECT 'motogp' WHERE '$SPORT' = 'motogp'
           UNION SELECT 'indycar' WHERE '$SPORT' = 'indycar'
           UNION SELECT 'road_cycling' WHERE '$SPORT' = 'cycling'
           UNION SELECT 'mtb_dh' WHERE '$SPORT' = 'mtb_dh'
         ) AS c_map)
         AND e.start_date >= '$NOW'::timestamp AND e.start_date < '$WEEK_LATER'::timestamp;"

  COUNT=$(docker compose exec -T db psql -U racinglines racinglines -t -c "$QUERY" 2>/dev/null | tr -d ' ' || echo "0")
  if [ "$COUNT" -eq 0 ]; then
    RACE_WEEKEND=0
  fi
fi

if [ "$RACE_WEEKEND" -eq 1 ]; then
  [ -n "$VERBOSE" ] && echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) race_weekend: $SPORT is in a race weekend, polling enabled"
  exit 0
else
  [ -n "$VERBOSE" ] && echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) race_weekend: $SPORT is off-week, polling disabled"
  exit 1
fi
