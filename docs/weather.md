# Weather forecasts

Weather forecasts as one frame a model can read, whoever made the forecast (`racinglines/weather/`). **Open-Meteo is
the default provider**: free, no API key, global hourly and daily forecasts, verified by the probe of 2026-10-06
(Marina Bay, see [Probe of 2026-10-06](#probe-of-2026-10-06)). Weather Underground stays as an optional provider that
needs a PWS owner's key and is unverified. MVP status (2026-10-06): the frame, the save/load layout, the CLI and the
Open-Meteo parser are built and tested against a captured response. The F1 props read the wet-race vote ([Wet-race
forecast](#wet-race-forecast)); nothing else reads the frame yet.

## The forecast frame

`racinglines/weather/schema.py`. One row per `(event_key, session, valid_utc)`. Times are naive UTC, as in
`position_sim` and the [L1 frames](frames.md).

| Column | Type | Meaning |
|---|---|---|
| `event_key` | str | the sportsbook event key, e.g. `2026-17` ([Sportsbook schema](sportsbook/index.md)) |
| `session` | str | `race`, `qual`, `sprint` (an hour inside that session's window), `day` (a daily forecast row) or `hour` (an hourly row outside every window given) |
| `valid_utc` | datetime | the time the row forecasts: the hour's start, or the provider's own time for a day |
| `issued_utc` | datetime | when the forecast was issued: the fetch time (neither provider's response carries a model-run time we map) |
| `precip_prob` | number, 0 to 1 | chance of precipitation |
| `precip_mm` | number, ≥ 0 | expected precipitation: the hour's, or the day's total |
| `temp_c` | number | air temperature (a day: the mean of its max and min) |
| `humidity` | number, 0 to 100 | relative humidity |
| `wind_kph` | number, ≥ 0 | wind speed |
| `condition` | str, nullable | the provider's text ("Showers"); Open-Meteo: its WMO weather code's name ("Slight rain showers") |
| `source` | str | the provider code (`open_meteo`, `wunderground`) |
| `lat`, `lon` | number | where the forecast is for |

- `validate(df)` returns the frame, or raises `FrameError`. Its `problems` list every mismatch and name the column:
  a missing column, a wrong dtype (including a timezone-aware time), nulls where none are allowed, values out of range,
  an unknown session, or a duplicate key.
- `summary(df, session)` returns `{precip_prob: max, precip_mm: sum, temp_c: mean, wind_kph: max, issued_utc, source}`
  over the session's rows, or `None` when there are none.
- `save(df)` writes one issue to `data/weather/<event_key>/<source>-<issued YYYYmmddTHHMMSSZ>.parquet`, one event,
  source and issue per file. `load(event_key, source=None)` returns the latest issue. Both read `RACINGLINES_DATA`
  when they run. `data/` is gitignored, so forecasts never reach git.

## Open-Meteo (default)

`racinglines/weather/open_meteo.py`. One request to `https://api.open-meteo.com/v1/forecast` with no key returns both
blocks, up to 16 days ahead (`--days`, default 16):

- `hourly`: `time`, `temperature_2m` (C), `relative_humidity_2m` (%), `precipitation_probability` (%),
  `precipitation` (mm), `wind_speed_10m` (km/h), `weather_code` (WMO).
- `daily`: `time`, `temperature_2m_max`, `temperature_2m_min`, `precipitation_probability_max`, `precipitation_sum`,
  `relative_humidity_2m_mean`, `wind_speed_10m_max`, `weather_code`.
- `timeformat=unixtime`, so every time is a UTC epoch second. `timezone=auto`, so the daily rows are the venue's local
  calendar days: a `day` row's `valid_utc` is local midnight in UTC (Singapore, UTC+8: `2026-10-10 16:00` is race day,
  11 October). Hourly rows are unaffected.

`fetch_raw(lat, lon, days=16)` returns an envelope (`provider`, `fetched_utc`, `lat`, `lon`, `hourly`, `daily`, and
`meta`: the response's other fields, units included) through the repo's paced, retried HTTP helper
(`racinglines/sources/http.py`). `parse(raw, event_key, lat, lon, issued_utc, sessions=None)` writes one `day` row per
day (`temp_c` the mean of max and min) and one row per hour, labelled with the session whose window holds it
(`sessions = {"race": (start, end)}`) or `hour`. **A field the response doesn't have raises `OpenMeteoFieldError`
naming it**, so a renamed field can never produce silent NaN columns. `condition` is the weather code's name from
Open-Meteo's WMO code table. `probe(lat, lon, out_path)` writes the envelope as fetched and lists any missing field.

### Probe of 2026-10-06

From the owner's Mac, read-only, for Marina Bay (lat 1.2914, lon 103.8640: approximate public-map coordinates; the
API snapped them to its grid point 1.3005, 103.8626, elevation 7 m):

```
# LOCAL (Mac)
racinglines weather probe --lat 1.2914 --lon 103.8640 --out data/raw/weather/open_meteo/probe-2026-17-singapore.json
```

HTTP 200, 384 hourly and 16 daily entries, every requested field present, units as stated above. The response sends
no rate-limit headers. A trimmed copy (48 hours, 2 days) is `tests/fixtures/weather/open_meteo-sample.json`.

### Licence: an open item for the owner

Open-Meteo's free API is for **non-commercial use** (fair use, about 10,000 calls a day; the data is CC BY 4.0, so a
page that shows it credits Open-Meteo). Commercial use needs Open-Meteo's paid API plan, a different host and an
`apikey` parameter. racinglines plans billing in 2027: before that, the owner decides between Open-Meteo's paid plan
and another source. Not implemented, for comparison: **MET Norway's Locationforecast**
(`api.met.no`) is free including commercial use (CC BY 4.0) and needs an identifying `User-Agent`, but its
precipitation probability is not available everywhere.

Past forecasts for the backtest come from two more Open-Meteo endpoints, under the same licence: see
[Forecasts of past races](#forecasts-of-past-races).

## Weather Underground (optional, unverified, needs a PWS key)

`racinglines/weather/wunderground.py`, used with `--provider wunderground`. Weather Underground's forecasts are served
by The Weather Company's API (`api.weather.com`, the v3 endpoints), which takes the key a Weather Underground personal
weather station owner gets, in `WUNDERGROUND_API_KEY` ([CLI reference](cli.md#racinglines-weather)). The owner has no
station, so this provider has never been probed: **every endpoint path, query parameter and field name in it is
unverified** (written from memory of the public API documentation, each constant marked in the module), and its test
fixture `tests/fixtures/weather/wunderground-sample.json` is hand-written to the declared shape. If a key ever exists,
`racinglines weather probe --provider wunderground --lat ... --lon ...` on the Mac lists the declared fields the
response lacks; fix those, replace the fixture with a trimmed capture, and drop the "unverified" marks.

## Commands

```
racinglines weather probe --lat LAT --lon LON [--out FILE.json] [--provider open_meteo|wunderground] [--days N]
racinglines weather fetch EVENT_KEY --lat LAT --lon LON [--session race=START/END ...] [--provider ...] [--days N]
racinglines weather show EVENT_KEY [--source open_meteo]
```

- `probe` writes the untouched response to `data/raw/weather/<provider>/probe-<UTC time>.json`, or to `--out`.
  It prints each body's fields and the requested fields that are missing, and exits 1 when any are missing.
- `fetch` fetches once and keeps the raw envelope under `data/raw/weather/<provider>/<event_key>/`. It parses and
  saves the issue, then prints the summary per session. `--session` takes ISO times in UTC
  (`race=2026-10-11T12:00/2026-10-11T14:00`) and repeats. `--daily-only` applies to Weather Underground only.
- `show` loads the latest saved issue and prints the summary per session, then the daily rows.

Nothing here runs by default, writes to the database, or touches the VM.

**Coordinates.** The event file (`docs/sportsbook/schemas/events-*.toml`) has no location yet, so the MVP takes
`--lat/--lon` by hand. The repo holds no circuit coordinates. Open item: the event file carries `[location] lat, lon`,
and `fetch` reads it from there.

## Probe first

The project rule for a new data source ([CLAUDE.md](https://github.com/lalligagger/racinglines-public/blob/main/CLAUDE.md),
"Database writes and new data sources") applies to every provider: the owner's Mac probes before any scheduled or full
run, the captured response becomes the test fixture, and the field names come from it. Open-Meteo passed on
2026-10-06; Weather Underground has not been probed.

se's own issue time. `issued_utc` is the fetch time.
- The key's rate limits and terms of use.

## Wet-race forecast

`racinglines/weather/wet.py`: a probability that an F1 race is wet (`p_wet`), made the same way live and in the
backtest, and the backtest itself.

- **The vote.** Seven global models (`open_meteo.MODELS`: ECMWF IFS, GFS, ICON, GEM, JMA, CMA, BOM) each vote "wet"
  when they forecast at least `WET_MM` = 0.1 mm in any hour of the window from one hour before the start to three
  after (`WINDOW_H`). Open-Meteo doesn't archive precipitation probability, so a probability can't be backtested; the
  vote can.
- **Shrunk to climatology.** `p_wet = (wet votes + 3 × climatology) / (models + 3)`, where climatology is the circuit's
  past wet share shrunk to the field's (`props.rate(hist, venue, "wet")`) and 3 (`PRIOR_VOTES`) is its weight in
  votes, because the models are correlated. The settings were fixed before the backtest, not tuned on it.
- **Live.** `racinglines weather fetch <event> --lat --lon --session race=START/END` saves the vote next to the issue
  (`data/weather/<event>/wet-<issued>.json`, with the lead in hours). The live book's props
  (`pipelines/live_f1.prop_markets`) read the latest vote issued before now and price `race_rain` at `p_wet` and
  `race_red_flag` with `props.rate_wx(p_wet)`. The safety car stays on its history. `[live.props] weather = false`
  turns it off. With no saved vote nothing changes, so a deploy moves no live price until someone runs `weather fetch`.
- **Venues.** `racinglines/weather/venues.toml`: the 34 venue slugs in the database, with coordinates from Jolpica's
  circuit list (the Ergast successor), retrieved 2026-10-06.

### Forecasts of past races

`racinglines weather leads` writes, for every past race, what each model forecast for its window 0 to 7 days before
(`open_meteo.LEAD_COLUMNS`: precipitation summed over start to start + 2 h, mean temperature, max wind, max weather
code, and the wettest hour in the vote window). Probe of 2026-10-06, raw responses under
`data/raw/weather/open_meteo/probe-leads-*.json` on the Mac:

- **Previous Runs API** (`previous-runs-api.open-meteo.com/v1/forecast`, `<variable>_previous_day<N>`): leads 1 to 7
  (day 8 is null). All seven models from about February 2024. Before that, JMA alone has leads (1 to 4 in
  2020, 1 to 7 in 2021 to 2023); the others are null. The fixture covers all 147 races at lead 0 and every lead JMA has. Precipitation, temperature, wind and weather code exist at every lead;
  **precipitation probability is null at every lead**.
- **Historical Forecast API** (`historical-forecast-api.open-meteo.com/v1/forecast`): lead 0 only (each run's first
  hours). It accepts `precipitation_previous_day5` but returns nulls.
- No rate-limit headers and no errors over about 300 requests; one empty body during a fast probe loop.

The committed copy, `tests/fixtures/weather/open_meteo-leads-f1.csv`, lets the cloud rerun the backtest with no
network ([fixture README](https://github.com/lalligagger/racinglines-public/blob/main/tests/fixtures/weather/README.md)).

### Backtest of 2026-10-06

**Naming (owner, 2026-10-06):** a weather-aware method, model variant or strategy is its base name + `-WX`
(`wet.wx_name`): the backtest's `circuit-WX` is the circuit-history price with the forecast in it, `climatology-WX`
the wet/dry mixture with the forecast's `p_wet` instead of the circuit's wet share. No trading strategy (A, C, K,
T1–T10) or position-model variant is weather-aware yet. The sweeps trade win, podium, head-to-head, constructor and
pole, which no weather input touches, so no `A-WX` exists until one does.

`racinglines weather backtest --lead 5`, walk-forward: each race is priced from the races before it (2020 on) and the
vote issued 5 days before it. That covers 63 races from 2024-01 to 2026-15: 13 wet, 6 red-flagged.

| Prop | Method | Brier | Log loss |
|---|---|---|---|
| Rain | circuit history | 0.1668 | 0.5155 |
| Rain | **circuit-WX** (the forecast, 5 days out) | **0.1232** | **0.3876** |
| Red flag | climatology (circuit's wet share) | 0.0915 | 0.3361 |
| Red flag | climatology-WX (`rate_wx(p_wet)`) | 0.0917 | 0.3372 |
| Red flag | wet oracle (the realised flag) | 0.0900 | 0.3273 |
| Safety car | climatology | 0.2667 | 0.7278 |
| Safety car | climatology-WX | 0.2679 | 0.7303 |

| DNFs per race | MAE | Poisson deviance |
|---|---|---|
| field mean | 1.416 | 1.373 |
| climatology-WX (wet and dry means mixed by p_wet) | 1.411 | 1.378 |
| wet oracle | 1.407 | 1.383 |

Rain by lead (Brier; the circuit's history is 0.1668 at every lead): 1 day 0.093, 2 days 0.104, 3 days 0.113,
4 days 0.113, **5 days 0.123**, 6 days 0.115, 7 days 0.135. Paired against the history, the 5-day forecast is better
by 0.044 (se 0.021); at 1 day by 0.074 (se 0.024). Calibration at 5 days (races, mean p_wet, wet share): p ≤ 0.15:
33, 0.08, 0.03; 0.15 to 0.3: 14, 0.23, 0.29; 0.3 to 0.5: 7, 0.44, 0.43; over 0.5: 9, 0.63, 0.56.

Wet vs dry, 2020 to 2026-15 (146 races): red flags in 29 % of 34 wet races against 11 % of 112 dry ones, safety cars
59 % against 57 %, and 2.71 DNFs per race against 2.42.

**What it shows.** Five days out, the forecast is a clearly better price for `race_rain` than the circuit's history,
so the live book now uses it. For the red flag, the long-run link with rain is real (29 % against 11 %), but in these
63 races even a perfect rain forecast barely helps (6 red flags, 2 of them in wet races), and the 5-day forecast
matches climatology. It stays wired as designed (decision log of 2026-10-06), and it's neutral here. The safety car
has no wet effect: unchanged. DNFs run about 12 % higher in the wet, but conditioning the race's DNF count on the
forecast doesn't improve it, so no DNF setting changes. The position simulation's `dnf_prob` and its disruption
mixture are not touched.

**What it doesn't show.** 63 races and 13 wet ones is a small sample: the red-flag and DNF results have wide error
bars. "Wet" is any rain sample during the race (`rain_share > 0`), which counts a brief shower; a heavier definition
might link to red flags more strongly. The live vote can use fewer models than seven (5 for 2026-17: two models'
horizons or archives end sooner), and so did the backtest after mid-2025. Open-Meteo snaps to its grid, about 10 km.

## What the forecast is for

The frame is provider-agnostic, so other providers and other sports read it the same way:

- **F1 rain and red flags.** Wired: see [Wet-race forecast](#wet-race-forecast).
- **Track conditions.** `position_sim`'s disruption mixture (`model.CHAOS`) is a race-level mixture in which some
  simulated races are disrupted, with more noise and more DNFs. "Disrupted" is learned from past races
  (`model.race_disruption`: safety-car share, red flag, rain share). A wet forecast could weight that branch for this
  race instead of the history alone.
- **Other sports.** Downhill (wet runs and conditions, `--conditions` on `mtb_dh live`), road cycling (wind on a
  time trial), NASCAR (rain delays) and sailing (wind) could read the same columns; none does yet.

How a forecast moves a price is a tuned setting, so it has a decision-log entry in the [F1 roadmap](f1-roadmap.md)
(2026-10-06, provisional). The wiring keeps the as-of rule: `load_vote` reads only votes issued before now, and the
backtest uses only runs issued before each race.
