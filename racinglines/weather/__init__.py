"""
Weather forecasts the models can read (docs/weather.md): one provider-agnostic frame, saved per event and per issue.

    schema.py        the forecast frame: COLUMNS, validate, summary, save / load
    wunderground.py  the first provider: Weather Underground (The Weather Company's v3 API, a PWS owner's key).
                     Its endpoints and field names are unverified in the cloud: `racinglines weather probe` on the
                     Mac confirms them, and the captured response becomes the test fixture.

Nothing here runs by default, writes to the database, or touches the VM. The consumers (props.py rain and red-flag
rates, position_sim's disruption mixture) are wired separately.
"""

from racinglines.weather.schema import (  # noqa: F401
    COLUMNS,
    SESSIONS,
    load,
    save,
    summary,
    validate,
)
