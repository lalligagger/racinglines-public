# Input frames

The first step of the [Engine roadmap](engine-roadmap.md#l1-canonical-input-frames) (phase E1): every sport's data in
one declared shape, so a model can be written against the frames instead of one sport's tables.

**Status:** built for F1 and downhill, read-only. The frames are views over what each model's `load()` already
returns. No model reads them yet: `DataView.asof` and the shared leak guard are E2. Owner decision D2 applies:
schemas are plain dataclasses plus tests, no `pandera`, no new dependency.

## The frames

Declared in `racinglines/frames/schema.py`: columns with dtype families, key columns and the `available_at` column.

| Frame | Key | F1 | Downhill |
|---|---|---|---|
| `entrants` | event, race, athlete | yes | yes (everyone with a row, DNS included) |
| `sessions` | event, session | yes | yes (a session is the event's day) |
| `classifications` | event, session, athlete | yes (every session) | yes (every run) |
| `conditions` | event, session | yes (qualifying and race) | no |
| `venue_features` | event | yes (the track profile) | no |
| `official_results` | event, athlete | yes (the race) | yes (completed events) |
| `laps` | event, session, athlete, lap | no | no |

`laps` is declared but neither adapter builds it: F1's `Measurements` keeps measures derived from the laps (deficits,
practice pace), not the laps. `market_links` and `market_quotes`, the exchange half of L1, come in a later task.

`session` uses the sport's own vocabulary: F1's `[sessions] minutes` names (`fp1`, `qual`, `race` ...), downhill's
`[rounds]` names (`practice`, `qual1`, `final` ...). `classifications.gap_ms` is the row's time minus the P1 row's.
`official_results` is what `results()` settles on, and the engine reads it only after pricing.

## `available_at`

Every row says when it became knowable, as naive UTC: the value an as-of view filters on (`available_at < cutoff`).
It is set on every row, and `validate` rejects a frame with a null.

| Rows | F1 | Downhill |
|---|---|---|
| `sessions`, `classifications` | the session's end: start plus `[sessions] minutes`, the same function `Measurements.view` gates with. No lag: `[stages] lag_minutes` moves a stage's cutoff, not the data | the end of the event's date (the frame has dates, not session times) |
| `official_results` | the race's end | the end of the event's date |
| `conditions`, `venue_features` | the race's end (the profile is built from race results) | none |
| `entrants` | the end of the driver's first session | the end of the event's date |

Two assumptions to review with E2:

- **Entrants are later than in life.** Entry lists are published before the weekend, but the tables don't say
  when. The models read them ungated ("identities and teams, never results": `entry_list` for F1, `event_starters`
  for downhill), so E2 must keep that exception.
- **Downhill is a day coarse.** The model trains on rows with `event_date < cutoff`. The frame agrees at every
  event's date and is at most one day stricter, never looser.

## Use

```python
from racinglines import sports
from racinglines.frames import frames_for, validate
from racinglines.models import race_model

model = race_model.get("f1")
frames = frames_for("f1", model.load(engine_url))     # {name: DataFrame}, only the frames sports/f1.toml declares
sports.frames("f1")                                   # the declared names; () for a sport with no [data] block
validate("classifications", frames["classifications"])   # FrameError lists every problem
```

`validate` checks that the declared columns are there, their dtype families, no nulls in non-nullable columns,
`available_at` set, and the key unique. Extra columns are allowed. `frames_for` validates what it builds, unless
called with `check=False`.

## The `[data]` block

```toml
[data]
frames = ["entrants", "sessions", "classifications", "official_results"]
```

A sport without the block declares none. List only frames the adapter can really build from its data.

## Add a sport

1. Write `racinglines/frames/<sport code>.py`: a `BUILDERS = {frame name: function(data)}` dict, where `data` is what
   the sport's model `load()` returns. Read-only: no new queries, and the model doesn't change. Build each frame
   with `shape(name, df)` from `racinglines/frames/_util.py` (declared columns, key order).
2. Set `available_at` per row and write the rule, and every assumption, in the module docstring.
3. Add `[data] frames` to `sports/<sport code>.toml`.
4. Add the sport to `tests/test_frames.py`: it produces exactly the frames it declares, every frame validates,
   `available_at` is set, and the frames show the same rows as the model's own as-of rule at a few cutoffs.
