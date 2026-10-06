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
