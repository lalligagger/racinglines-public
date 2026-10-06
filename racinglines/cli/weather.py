"""
racinglines weather <command>: weather forecasts for an event, in the provider-agnostic forecast frame
(racinglines/weather/; docs/weather.md). --provider picks the source: open_meteo (the default, no key) or
wunderground (optional, unverified, a PWS owner's key in $WUNDERGROUND_API_KEY).

    probe   Fetch the daily and hourly forecasts for --lat/--lon and write the responses untouched (any key left out)
            to --out (default data/raw/weather/<provider>/probe-<UTC time>.json); lists every declared field the
            response doesn't have (exit 1 when any is missing).
    fetch   Fetch, parse and save one issue for an event key (data/weather/<event_key>/), the raw response next to
            the probe's; print the summary per session. --session race=START/END (UTC, repeatable) labels the
            hourly rows inside that window; with a race window (open_meteo) it also saves the race's wet vote
            (weather/wet.py: seven global models, wet-<issued>.json), which the live book's race_rain and
            race_red_flag props read.
    show    Load the event's latest saved issue and print the summary per session, the daily rows and the wet vote.
    leads   For each race in --races (a CSV: race_id, event_key, venue_slug, race_start_utc; default every F1 race in
            the local database), the forecasts Open-Meteo issued 0 to 7 days before its window, per global model, to
            --out (one row per race, lead and model; open_meteo.LEAD_COLUMNS). Raw responses under
            data/raw/weather/open_meteo/leads/. Leads 1-7 exist from about February 2024; lead 0 earlier.
    backtest  The 5-day (--lead) wet-race forecast against every race since February 2024, walk-forward: rain,
            red flag, safety car and DNF count per method, the lead-time table, wet vs dry correlations. Reads the
            local database (or --history CSV: weather.wet.races()'s columns) and the leads CSV (--leads; default the
            committed fixture tests/fixtures/weather/open_meteo-leads-f1.csv). --out writes the per-race CSV.

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


def _provider(name):
    from racinglines.weather import open_meteo, wunderground
    return {"open_meteo": open_meteo, "wunderground": wunderground}[name]


def _fetch_raw(a, W, hourly=True):
    if W.SOURCE == "wunderground":
        return W.fetch_raw(a.lat, a.lon, W.api_key(), hourly=hourly)
    return W.fetch_raw(a.lat, a.lon, a.days)


def cmd_probe(a):
    from racinglines.weather import schema as S
    W = _provider(a.provider)
    out = a.out or S.root() / "raw" / "weather" / W.SOURCE / f"probe-{_stamp(datetime.now(UTC))}.json"
    if W.SOURCE == "wunderground":
        p, missing = W.probe(a.lat, a.lon, W.api_key(), out)
    else:
        p, missing = W.probe(a.lat, a.lon, out, a.days)
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
    W = _provider(a.provider)
    raw = _fetch_raw(a, W, hourly=not a.daily_only)
    issued = datetime.strptime(raw["fetched_utc"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)   # naive UTC
    rawp = S.root() / "raw" / "weather" / W.SOURCE / a.event_key / f"{_stamp(issued)}.json"
    rawp.parent.mkdir(parents=True, exist_ok=True)
    rawp.write_text(json.dumps(raw, indent=1))
    for k, v in raw.get("errors", {}).items():
        print(f"{k} error: {v}")
    sessions = dict(_window(s) for s in a.session or [])
    df = W.parse(raw, a.event_key, a.lat, a.lon, issued, sessions)
    p = S.save(df)
    print(f"wrote {p} ({len(df)} rows; raw {rawp})")
    _print_summaries(df)
    if "race" in sessions and W.SOURCE == "open_meteo":
        from racinglines.weather import wet as WET
        start = sessions["race"][0]
        v = WET.fetch_live(a.lat, a.lon, start)
        vp = WET.save_vote(a.event_key, start, a.lat, a.lon, v, issued)
        print(f"wet vote: {v['wet_votes']} of {v['models']} models forecast >= {WET.WET_MM} mm in the race window "
              f"(mean wettest hour {v['max_mm']:.2f} mm) -> {vp}")
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
    from racinglines.weather import wet as WET
    v = WET.load_vote(a.event_key)
    if v:
        print(f"\nwet vote issued {v['issued_utc']} ({v['lead_hours']} h before the race start {v['race_start_utc']}):"
              f" {v['wet_votes']} of {v['models']} models wet")
    return 0


def cmd_leads(a):
    import time

    import pandas as pd

    from racinglines import progress
    from racinglines.weather import open_meteo as OM
    from racinglines.weather import schema as S
    from racinglines.weather import wet as WET
    if a.races:
        races = pd.read_csv(a.races)
    else:
        from racinglines.db.config import get_engine
        with get_engine().connect() as c:
            h = WET.races(c)
        races = h.rename(columns={"slug": "venue_slug"})[["race_id", "event_key", "venue_slug", "start_utc"]] \
            .rename(columns={"start_utc": "race_start_utc"})
    leads = tuple(range(int(a.leads.split("-")[0]), int(a.leads.split("-")[-1]) + 1))
    venues = WET.venues()
    raw_dir = S.root() / "raw" / "weather" / OM.SOURCE / "leads"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for i, r in enumerate(races.to_dict("records")):
        progress.update(i, len(races), r["event_key"])
        v = venues.get(r["venue_slug"], {})
        if "lat" not in v:
            failed.append((r["event_key"], f"no coordinates for venue {r['venue_slug']!r}"))
            continue
        race = {**r, "lat": v["lat"], "lon": v["lon"]}
        path = raw_dir / f"{r['event_key']}.json"
        try:
            if path.exists():
                bodies = json.loads(path.read_text())
            else:
                bodies = OM.fetch_leads(v["lat"], v["lon"], r["race_start_utc"], leads)
                path.write_text(json.dumps(bodies))
                time.sleep(a.pause)
            got = OM.lead_rows(race, bodies, leads)
        except (RuntimeError, ValueError, KeyError) as ex:
            failed.append((r["event_key"], str(ex)[:200]))
            continue
        rows += got
        print(f"{r['event_key']} {r['venue_slug']}: leads {sorted({x['lead_days'] for x in got})}", flush=True)
    out = pd.DataFrame(rows, columns=list(OM.LEAD_COLUMNS))
    out.to_csv(a.out, index=False, float_format="%.3f")
    print(f"wrote {a.out}: {len(out)} rows, {out['race_id'].nunique()} of {len(races)} races")
    for k, e in failed:
        print(f"  failed {k}: {e}")
    return 1 if failed else 0


def cmd_backtest(a):
    import pandas as pd

    from racinglines.weather import wet as WET
    if a.history:
        hist = pd.read_csv(a.history)
    else:
        from racinglines.db.config import get_engine
        with get_engine().connect() as c:
            hist = WET.races(c)
    rows = WET.backtest(hist, pd.read_csv(a.leads) if a.leads else None)
    per, summ = WET.score(rows, hist, a.lead)
    f = "{:.4f}".format
    print(f"wet-race forecast, {a.lead} days ahead: {len(per)} races since {WET.FIRST_ARCHIVED:%Y-%m-%d}, "
          f"{int(per['wet'].sum())} wet, {int(per['red'].sum())} red-flagged")
    print(summ.dropna(axis=1, how="all").to_string(index=False, float_format=f))
    print("\nby lead (days before the race):")
    print(WET.leads_table(rows, hist).to_string(index=False, float_format=f))
    print("\nwet vs dry races since 2020:")
    print(WET.correlations(hist).to_string(float_format=f))
    if a.out:
        per.to_csv(a.out, index=False)
        print(f"\nwrote {a.out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines weather", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def provider(p):
        p.add_argument("--provider", choices=("open_meteo", "wunderground"), default="open_meteo",
                       help="forecast source (default open_meteo, no key)")
        p.add_argument("--days", type=int, default=16, help="open_meteo: days ahead, 1 to 16 (default 16)")

    p = sub.add_parser("probe", help="fetch once and write the raw response (the Mac, before anything else)")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--out", help="output JSON (default data/raw/weather/<provider>/probe-<UTC time>.json)")
    provider(p)
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("fetch", help="fetch, parse and save one forecast issue for an event")
    p.add_argument("event_key", help='the sportsbook event key, e.g. "2026-17"')
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    provider(p)
    p.add_argument("--session", action="append", metavar="NAME=START/END",
                   help="race | qual | sprint window in UTC (ISO times); repeatable")
    p.add_argument("--daily-only", action="store_true", help="wunderground: skip the hourly forecast")
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("show", help="print the latest saved issue's summary per session")
    p.add_argument("event_key")
    p.add_argument("--source", help="only this provider's issues (default: the latest of any)")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("leads", help="past races: the forecasts issued 0-7 days before each (Open-Meteo archive)")
    p.add_argument("--races", help="CSV: race_id, event_key, venue_slug, race_start_utc (default: the database)")
    p.add_argument("--out", required=True, help="output CSV")
    p.add_argument("--leads", default="1-7", help="lead days, e.g. 1-7")
    p.add_argument("--pause", type=float, default=1.0, help="seconds between races (polite pacing)")
    p.set_defaults(fn=cmd_leads)
    p = sub.add_parser("backtest", help="the wet-race forecast's walk-forward backtest (rain, red flag, SC, DNF)")
    p.add_argument("--lead", type=int, default=5, help="days before the race the forecast was issued (1 to 7)")
    p.add_argument("--history", help="a CSV of weather.wet.races() instead of the database")
    p.add_argument("--leads", help="the leads CSV (default the committed fixture)")
    p.add_argument("--out", help="write the per-race frame to this CSV")
    p.set_defaults(fn=cmd_backtest)
    a = ap.parse_args(argv)
    return a.fn(a)
