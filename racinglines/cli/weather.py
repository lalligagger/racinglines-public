"""
racinglines weather <command>: weather forecasts for an event, in the provider-agnostic forecast frame
(racinglines/weather/; docs/weather.md). Weather Underground is the only provider; its key is $WUNDERGROUND_API_KEY.

    probe   Fetch the daily and hourly forecasts for --lat/--lon and write the responses untouched (key left out) to
            --out (default data/raw/weather/wunderground/probe-<UTC time>.json); lists every declared field the
            response doesn't have. Run it on the Mac first: the endpoints and fields are unverified in the cloud.
    fetch   Fetch, parse and save one issue for an event key (data/weather/<event_key>/), the raw response next to
            the probe's; print the summary per session. --session race=START/END (UTC, repeatable) labels the
            hourly rows inside that window.
    show    Load the event's latest saved issue and print the summary per session and the daily rows.

Nothing here runs by default, writes to the database, or touches the VM. The event file has no location yet, so
--lat/--lon are given by hand.
"""

import argparse
import json
from datetime import UTC, datetime


def _print_summaries(df):
    from racinglines.weather import schema as S
    print(f"{df['event_key'].iloc[0]} · {df['source'].iloc[0]} · issued {df['issued_utc'].iloc[0]:%Y-%m-%d %H:%M} UTC"
          f" · {df['lat'].iloc[0]}, {df['lon'].iloc[0]}")
    for s in S.SESSIONS:
        m = S.summary(df, s)
        if m is None:
            continue
        print(f"  {s:<7} rows {int((df['session'] == s).sum()):>3}  precip_prob {m['precip_prob']:.2f}  "
              f"precip_mm {m['precip_mm']:.1f}  temp_c {m['temp_c']:.1f}  wind_kph {m['wind_kph']:.0f}")


def _stamp(t):
    return t.strftime("%Y%m%dT%H%M%SZ")


def _window(spec):
    name, _, span = spec.partition("=")
    start, _, end = span.partition("/")
    if not (name and start and end):
        raise SystemExit(f"--session {spec!r}: expected NAME=START/END, e.g. race=2026-10-04T12:00/2026-10-04T14:00")
    return name, (datetime.fromisoformat(start), datetime.fromisoformat(end))


def cmd_probe(a):
    from racinglines.weather import schema as S
    from racinglines.weather import wunderground as W
    out = a.out or S.root() / "raw" / "weather" / W.SOURCE / f"probe-{_stamp(datetime.now(UTC))}.json"
    p, missing = W.probe(a.lat, a.lon, W.api_key(), out)
    raw = json.loads(p.read_text())
    print(f"wrote {p}")
    for k in ("daily", "hourly"):
        body = raw.get(k)
        print(f"  {k}: " + (f"fields {sorted(body)}" if isinstance(body, dict) else "none"))
    for k, v in raw.get("errors", {}).items():
        print(f"  {k} error: {v}")
    print("missing declared fields: " + (", ".join(missing) if missing else "none"))
    return 1 if missing else 0


def cmd_fetch(a):
    from racinglines.weather import schema as S
    from racinglines.weather import wunderground as W
    raw = W.fetch_raw(a.lat, a.lon, W.api_key(), hourly=not a.daily_only)
    issued = datetime.strptime(raw["fetched_utc"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)   # naive UTC
    rawp = S.root() / "raw" / "weather" / W.SOURCE / a.event_key / f"{_stamp(issued)}.json"
    rawp.parent.mkdir(parents=True, exist_ok=True)
    rawp.write_text(json.dumps(raw, indent=1))
    for k, v in raw.get("errors", {}).items():
        print(f"{k} error: {v}")
    df = W.parse(raw, a.event_key, a.lat, a.lon, issued, dict(_window(s) for s in a.session or []))
    p = S.save(df)
    print(f"wrote {p} ({len(df)} rows; raw {rawp})")
    _print_summaries(df)
    return 0


def cmd_show(a):
    from racinglines.weather import schema as S
    try:
        df = S.load(a.event_key, a.source)
    except FileNotFoundError as ex:
        print(ex)
        return 1
    _print_summaries(df)
    days = df[df["session"] == "day"]
    if len(days):
        print()
        print(days[["valid_utc", "precip_prob", "precip_mm", "temp_c", "humidity", "wind_kph", "condition"]]
              .to_string(index=False, float_format="%.2f"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines weather", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="fetch once and write the raw response (the Mac, before anything else)")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--out", help="output JSON (default data/raw/weather/wunderground/probe-<UTC time>.json)")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("fetch", help="fetch, parse and save one forecast issue for an event")
    p.add_argument("event_key", help='the sportsbook event key, e.g. "2026-17"')
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--session", action="append", metavar="NAME=START/END",
                   help="race | qual | sprint window in UTC (ISO times); repeatable")
    p.add_argument("--daily-only", action="store_true", help="skip the hourly forecast")
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("show", help="print the latest saved issue's summary per session")
    p.add_argument("event_key")
    p.add_argument("--source", help="only this provider's issues (default: the latest of any)")
    p.set_defaults(fn=cmd_show)
    a = ap.parse_args(argv)
    return a.fn(a)
