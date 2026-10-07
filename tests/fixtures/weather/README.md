# Weather fixtures

`open_meteo-sample.json` is a **captured** response: the probe of 2026-10-06 for Marina Bay (lat 1.2914, lon 103.864,
approximate public-map coordinates), `racinglines weather probe --lat 1.2914 --lon 103.8640`, trimmed to the first 48
hours and 2 days. Open-Meteo needs no key, so there was nothing to strip. To refresh it, probe again and trim the
`hourly` and `daily` arrays the same way; the tests' expected numbers come from this file.

`wunderground-sample.json` is **hand-written** to the field names declared in `racinglines/weather/wunderground.py`,
which are unverified in the cloud (no network to any weather host). It is not a captured response, and its
coordinates (0, 0) are a placeholder, not a venue. To replace it, on the Mac:

    racinglines weather probe --lat <lat> --lon <lon> --out tests/fixtures/weather/wunderground-sample.json

then trim the bodies to a few days and hours, and fix any constant the probe lists as missing.

## Forecasts of past races (the wet-race backtest)

- `open_meteo-leads-f1.csv`: for every F1 race 2020-01 to 2026-16 (147), the forecasts Open-Meteo issued 0 to 7 days
  before its window, one row per race, lead and global model (`racinglines/weather/open_meteo.py`, `LEAD_COLUMNS`).
  Pulled 2026-10-06 on the owner's Mac with

      racinglines weather leads --races races.csv --out tests/fixtures/weather/open_meteo-leads-f1.csv

  where `races.csv` is the local database's race list (`weather.wet.races()`: race_id, event_key, venue_slug,
  race_start_utc) plus 2026-16 (Kuala Lumpur, 2026-10-04 07:00 UTC, not in the local database yet). URLs:
  `https://previous-runs-api.open-meteo.com/v1/forecast` (leads 1-7: `<variable>_previous_day<N>`) and
  `https://historical-forecast-api.open-meteo.com/v1/forecast` (lead 0), both with `models=` the seven of
  `open_meteo.MODELS`, hourly `precipitation, temperature_2m, wind_speed_10m, weather_code`, `timeformat=unixtime`.
  The raw responses are under `data/raw/weather/open_meteo/leads/` on the Mac (not committed). `precip_prob` is
  blank everywhere: Open-Meteo does not archive precipitation probability at any lead.
- `f1-wet-history.csv`: the 146 races' outcomes the backtest scores against (`weather.wet.races()` on the local
  database, 2026-10-06: race_id, event_key, venue_id, slug, start, start_utc, sc, red, rain_share, n_ok, n_dnf).
  `racinglines weather backtest --history tests/fixtures/weather/f1-wet-history.csv` runs with no database or network.
- `open_meteo-previous-runs-sample.json`: one Previous Runs response (Marina Bay, 2024-09-22, leads 1-7, the seven
  models), cut to 06:00-17:00 UTC, for the window-arithmetic tests.

  Values are the API's own: one JMA row (2024-06, lead 6) has `precip_mm` −0.2 and `max_hour_mm` −0.1, a negative
  forecast Open-Meteo passes through; the vote counts it as dry.
