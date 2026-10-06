# Weather forecasts

Weather forecasts as one frame a model can read, whoever made the forecast (`racinglines/weather/`). Weather
Underground is the first provider. MVP status (2026-10-06): the frame, the save/load layout and the CLI are built and
tested offline. **The provider's endpoints and field names are unverified**. The cloud has no network to any weather
host, so they come from memory of the public API documentation. No response has been captured yet (see
[Unverified](#unverified-until-the-probe-runs)). No model reads the frame yet.

## The forecast frame

`racinglines/weather/schema.py`. One row per `(event_key, session, valid_utc)`. Times are naive UTC, as in
`position_sim` and the [L1 frames](frames.md).

| Column | Type | Meaning |
|---|---|---|
| `event_key` | str | the sportsbook event key, e.g. `2026-17` ([Sportsbook schema](sportsbook/index.md)) |
| `session` | str | `race`, `qual`, `sprint` (an hour inside that session's window), `day` (a daily forecast row) or `hour` (an hourly row outside every window given) |
| `valid_utc` | datetime | the time the row forecasts: the hour's start, or the provider's own time for a day |
| `issued_utc` | datetime | when the forecast was issued. Weather Underground: the fetch time, because the response's own issue time is not mapped yet |
| `precip_prob` | number, 0 to 1 | chance of precipitation |
| `precip_mm` | number, ≥ 0 | expected precipitation: the hour's, or the day's total |
| `temp_c` | number | air temperature (a day: the mean of its max and min) |
| `humidity` | number, 0 to 100 | relative humidity |
| `wind_kph` | number, ≥ 0 | wind speed |
| `condition` | str, nullable | the provider's own text ("Showers") |
| `source` | str | the provider code (`wunderground`) |
| `lat`, `lon` | number | where the forecast is for |

- `validate(df)` returns the frame, or raises `FrameError`. Its `problems` list every mismatch and name the column:
  a missing column, a wrong dtype (including a timezone-aware time), nulls where none are allowed, values out of range,
  an unknown session, or a duplicate key.
- `summary(df, session)` returns `{precip_prob: max, precip_mm: sum, temp_c: mean, wind_kph: max, issued_utc, source}`
  over the session's rows, or `None` when there are none.
- `save(df)` writes one issue to `data/weather/<event_key>/<source>-<issued YYYYmmddTHHMMSSZ>.parquet`, one event,
  source and issue per file. `load(event_key, source=None)` returns the latest issue. Both read `RACINGLINES_DATA`
  when they run. `data/` is gitignored, so forecasts never reach git.

## Weather Underground

`racinglines/weather/wunderground.py`. Weather Underground's forecasts are served by The Weather Company's API
(`api.weather.com`, the v3 endpoints). It takes an `apiKey` query parameter: the key a Weather Underground PWS owner
gets. Set it in `WUNDERGROUND_API_KEY` ([CLI reference](cli.md#racinglines-weather)).

- `fetch_raw(lat, lon, key, hourly=True)` fetches the daily forecast and, with `hourly=True`, the hourly one through
  the repo's paced, retried HTTP helper (`racinglines/sources/http.py`). It returns an envelope: `daily`, `hourly`,
  `errors`, `fetched_utc`, `lat` and `lon`, with the bodies untouched and the key left out. A failed hourly request
  is recorded under `errors.hourly` and the daily forecast is kept.
- `parse(raw, event_key, lat, lon, issued_utc, sessions=None)` builds the frame from the envelope. It writes one `day`
  row per day: precip_prob and wind are the larger of the day and night halves, humidity is their mean. It writes one
  row per hour, labelled with the session whose window holds it (`sessions = {"race": (start, end)}`), or `hour`.
  **A declared field the response doesn't have raises `WundergroundFieldError` naming it**, so a wrong field name can
  never produce silent NaN columns.
- `probe(lat, lon, key, out_path)` writes the envelope as fetched. It also lists every declared field the response
  doesn't have (`missing_fields`).

## Commands

```
racinglines weather probe --lat LAT --lon LON [--out FILE.json]
racinglines weather fetch EVENT_KEY --lat LAT --lon LON [--session race=START/END ...] [--daily-only]
racinglines weather show EVENT_KEY [--source wunderground]
```

- `probe` writes the untouched responses to `data/raw/weather/wunderground/probe-<UTC time>.json`, or to `--out`.
  It prints each body's fields and the declared fields that are missing, and exits 1 when any are missing.
- `fetch` fetches once and keeps the raw envelope under `data/raw/weather/wunderground/<event_key>/`. It parses and
  saves the issue, then prints the summary per session. `--session` takes ISO times in UTC (`race=2026-10-04T12:00/2026-10-04T14:00`)
  and repeats.
- `show` loads the latest saved issue and prints the summary per session, then the daily rows.

Nothing here runs by default, writes to the database, or touches the VM.

**Coordinates.** The event file (`docs/sportsbook/schemas/events-*.toml`) has no location yet, so the MVP takes
`--lat/--lon` by hand. The repo holds no circuit coordinates. Open item: the event file carries `[location] lat, lon`,
and `fetch` reads it from there.

## Probe first

The project rule for a new data source ([CLAUDE.md](https://github.com/lalligagger/racinglines-public/blob/main/CLAUDE.md),
"Database writes and new data sources") applies here. The owner's Mac probes before any scheduled or full run:

```
# LOCAL (Mac)
export WUNDERGROUND_API_KEY=...
racinglines weather probe --lat <lat> --lon <lon>
```

Then:

1. Fix any constant the probe lists as missing in `wunderground.py`.
2. Trim the probe file to a couple of days and hours, and replace `tests/fixtures/weather/wunderground-sample.json`
   with it. Today's fixture is hand-written to the declared shape, with coordinates (0, 0) as a placeholder, and is
   not a captured response.
3. Run `python -m pytest tests/test_weather.py`.
4. Note the key's rate limits and terms of use from the response headers and the account page.

## Unverified until the probe runs

Every one of these is marked in `wunderground.py` with `# unverified in the cloud: confirm with racinglines weather probe on the Mac`:

- Host and paths: `BASE_URL = https://api.weather.com`, `DAILY_PATH = /v3/wx/forecast/daily/5day`,
  `HOURLY_PATH = /v3/wx/forecast/hourly/2day`. Also whether a PWS key may call the hourly endpoint at all.
- Query: `geocode=lat,lon`, `format=json`, `units=m`, `language=en-US`, `apiKey`.
- Units under `units=m`: C, km/h, mm.
- Daily fields: `validTimeUtc` (epoch seconds), `temperatureMax`, `temperatureMin`, `qpf`, `narrative`, `daypart`.
  Inside `daypart[0]`: `precipChance`, `relativeHumidity`, `windSpeed`, two entries per day (day, then night, null
  once a half has passed).
- Hourly fields: `validTimeUtc`, `temperature`, `precipChance`, `qpf`, `relativeHumidity`, `windSpeed`,
  `wxPhraseLong`.
- Not mapped: the response's own issue time. `issued_utc` is the fetch time.
- The key's rate limits and terms of use.

## What the forecast is for

The frame is provider-agnostic, so other providers and other sports read it the same way:

- **F1 rain and red flags.** `racinglines/models/position_sim/props.py` prices `race_rain` and `race_red_flag` as
  per-circuit rates shrunk to the field's rate. Its docstring says "Rain uses the history only: no weather forecast".
  The race-window summary (`precip_prob`, `precip_mm`) is the input that would move those rates for this weekend.
- **Track conditions.** `position_sim`'s disruption mixture (`model.CHAOS`) is a race-level mixture in which some
  simulated races are disrupted, with more noise and more DNFs. "Disrupted" is learned from past races
  (`model.race_disruption`: safety-car share, red flag, rain share). A wet forecast could weight that branch for this
  race instead of the history alone.
- **Other sports.** Downhill (wet runs and conditions, `--conditions` on `mtb_dh live`), road cycling (wind on a
  time trial), NASCAR (rain delays) and sailing (wind) could read the same columns; none does yet.

Another worker is wiring the first two consumers. How a forecast moves a price is a tuned setting, so it needs a
decision-log entry in the [F1 roadmap](f1-roadmap.md) before it is treated as final. The wiring must keep the as-of rule: a backtest may read
only issues with `issued_utc` before its cutoff.
