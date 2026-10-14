<!-- Captured by scripts/docs/capture_examples.py (id help-weather, scripts/docs/examples.toml) on 2026-10-14 05:12 UTC, commit 3ed9335+dirty, 0.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines weather -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines weather [-h] {probe,fetch,show,leads,backtest} ...

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

positional arguments:
  {probe,fetch,show,leads,backtest}
    probe               fetch once and write the raw response (the Mac, before anything else)
    fetch               fetch, parse and save one forecast issue for an event
    show                print the latest saved issue's summary per session
    leads               past races: the forecasts issued 0-7 days before each (Open-Meteo archive)
    backtest            the wet-race forecast's walk-forward backtest (rain, red flag, SC, DNF)

options:
  -h, --help            show this help message and exit
```
<!-- --8<-- [end:output] -->
