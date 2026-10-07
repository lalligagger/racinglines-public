#!/usr/bin/env bash
# Check if a sport is currently in a race weekend (Thurs-Sun UTC).
# Used by all polling scripts to control when data syncing runs.
#
# Usage: race_weekend.sh <sport> [--verbose] [--lead]
#        exit 0 = in a race weekend, run polling
#        exit 1 = off-week or no events, skip polling
#        --lead: any day of the week, not only Thu to Sun: exit 0 while an event is in the same window (3 days ago to
#        LEAD_DAYS, default 7, ahead). The recorders use it to sync market links ahead of the weekend, so markets
#        listed Mon to Wed are linked and quoted before the race weekend starts (P0, 2026-10-07: the bets thread found
#        no Kalshi links for Singapore on the Wednesday before it).
#
# Example: if race_weekend.sh f1; then racinglines markets --exchange polymarket sync; fi
#
# <sport> is a sport code (a file in sports/: f1, nascar, motogp, road_cycling, mtb_dh, ...); its competition code
# comes from that file's [competition] code, so the gate never needs its own list of sports.
# On Thu to Sun UTC, an event counts while its start_date is from 3 days ago to 7 days ahead. start_date is race day
# for F1 but the Friday for MotoGP (date_start), so this keeps race day, a MotoGP weekend's Sunday and a race that
# ends after midnight UTC (Las Vegas) polling, and still drops last weekend's event by Thursday.

set -euo pipefail

SPORT="${1:-f1}"
VERBOSE=""
LEAD=""
for a in "${@:2}"; do
  case "$a" in
    --verbose) VERBOSE=1 ;;
    --lead) LEAD=1 ;;
  esac
done
LEAD_DAYS=${LEAD_DAYS:-7}

if [ -z "$SPORT" ]; then
  echo "Usage: race_weekend.sh <sport> [--verbose]" >&2
  exit 1
fi

set -a; . "${ENV_FILE:-/etc/racinglines.env}"; set +a
cd "${APP:-/opt/racinglines}"

# The sport's competition code, from sports/<sport>.toml [competition] code
TOML="sports/$SPORT.toml"
COMPETITION=$(awk '/^\[/{sec=$0} sec=="[competition]" && /^code *=/{gsub(/.*= *"|".*/, ""); print; exit}' "$TOML" 2>/dev/null || true)
if [ -z "$COMPETITION" ]; then
  echo "race_weekend: no [competition] code in $TOML (unknown sport '$SPORT')" >&2
  exit 1
fi

# Get UTC day of week (0=Sunday, 1=Monday, ..., 4=Thursday); RACE_WEEKEND_NOW (epoch seconds) overrides now, for tests
NOW_UTC=${RACE_WEEKEND_NOW:-$(date -u +%s)}
# An epoch second formatted in UTC: GNU date (the VM) takes -d @SECONDS, BSD date (macOS, where the tests also run)
# takes -r SECONDS; GNU first, so the VM's path is unchanged
utc() { date -u -d @"$1" "$2" 2>/dev/null || date -u -r "$1" "$2"; }
DOW=$(utc "$NOW_UTC" +%w)  # 0=Sun, 1=Mon, ..., 4=Thu, ..., 6=Sat

# Race weekend = Thursday (4) through Sunday (0), inclusive
# In UTC terms: Thu=4, Fri=5, Sat=6, Sun=0
RACE_WEEKEND=0
if [ "$DOW" -ge 4 ] || [ "$DOW" -eq 0 ] || [ -n "$LEAD" ]; then
  RACE_WEEKEND=1
fi

# Query: is there an active event for this sport in the next 7 days?
# (backup check: if DB query fails, assume not a race weekend)
if [ "$RACE_WEEKEND" -eq 1 ]; then
  FROM=$(utc "$((NOW_UTC - 3 * 86400))" +%Y-%m-%d)
  AHEAD=604800; [ -n "$LEAD" ] && AHEAD=$((LEAD_DAYS * 86400))
  WEEK_LATER=$(utc "$((NOW_UTC + AHEAD))" +%Y-%m-%d)

  QUERY="SELECT COUNT(*) FROM events e
         JOIN seasons s ON e.season_id = s.id
         JOIN competitions c ON s.competition_id = c.id
         WHERE c.code = '$COMPETITION' AND e.status <> 'cancelled'
         AND e.start_date >= '$FROM'::date AND e.start_date < '$WEEK_LATER'::date;"

  COUNT=$(docker compose exec -T db psql -U racinglines racinglines -t -c "$QUERY" 2>/dev/null | tr -d ' ' || echo "0")
  if [ -z "$COUNT" ] || [ "$COUNT" -eq 0 ]; then
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
