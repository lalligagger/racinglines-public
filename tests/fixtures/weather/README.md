# Weather fixtures

`wunderground-sample.json` is **hand-written** to the field names declared in `racinglines/weather/wunderground.py`,
which are unverified in the cloud (no network to any weather host). It is not a captured response, and its
coordinates (0, 0) are a placeholder, not a venue. To replace it, on the Mac:

    racinglines weather probe --lat <lat> --lon <lon> --out tests/fixtures/weather/wunderground-sample.json

then trim the bodies to a few days and hours, and fix any constant the probe lists as missing.
