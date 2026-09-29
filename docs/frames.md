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
| `sessions` | event, session | yes | yes (a round is dated by its weekend) |
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
| `sessions`, `classifications` | the session's end: start plus `[sessions] minutes`, the same function `Measurements.view` gates with. No lag: `[stages] lag_minutes` moves a stage's cutoff, not the data | noon UTC of the day after the weekend's last day, parsed from the event name (the frame has one date, not session times) |
| `official_results` | the race's end | the same, the weekend's end |
| `conditions`, `venue_features` | the race's end (the profile is built from race results) | none |
| `entrants` | the end of the driver's first session | the same, the weekend's end |

**Sources publish whole sessions.** No source we have is live: FastF1's archive publishes a session's results and
laps only after the session has ended, and ChronoRace's downhill results come per round. So every row of a
session-keyed frame (`classifications`, `laps`, `conditions`) is available at its session's end, never at the time of
the lap or split inside it. `frames_for` enforces this with `check_release`: within one (event, session) every row has
the same `available_at`, and none is earlier than that session's `end` in the `sessions` frame. A frame whose source
really does date each row as it happens (a live timing feed, if one is ever added) is listed in `[data] live`, and
only then may its rows carry their own times.

Every `available_at` is never earlier than the source really published the row; it may be later. That is the
invariant behind the choices below, and the reason a coarse or late date is acceptable and an early one is not.

Three assumptions to review with E2:

- **Entrants are later than in life.** Entry lists are published before the weekend, but the tables don't say
  when. The models read them ungated ("identities and teams, never results": `entry_list` for F1, `event_starters`
  for downhill), so E2 must keep that exception.
- **Downhill is a weekend coarse.** The model trains on rows with `event_date < cutoff`. The frame agrees with that
  day rule at every event date; later than it inside a weekend; the tables have no end date, so the end is parsed
  from the event name ("August 21-23": the last day of the range, or the event date plus two days when the name has
  none) and dated noon UTC of the day after. An `events.end_date` column set at ingest replaces the parse (an E2
  prerequisite for downhill: a DB migration, so a backup and owner sign-off).
- **F1 sessions are dated at their end, but the model reads the schedule ungated.** The `sessions` frame dates a
  session's `start` and `end` at the session's end, while `Measurements.sessions` reads the weekend schedule with no
  gate (the backtest's anchors, `price_race`'s `event_sessions` and `sessions_used`, `testing/checks.py`; the
  `pre_weekend` golden depends on it). E2 reads `start` from the ungated sessions frame, like entrants.

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
live = []          # frames whose source dates each row as it happens; none today
```

A sport without the block declares none. List only frames the adapter can really build from its data. `live`
defaults to empty: every session-keyed frame is then released a whole session at a time, after it ends.

## Add a sport

1. Write `racinglines/frames/<sport code>.py`: a `BUILDERS = {frame name: function(data)}` dict, where `data` is what
   the sport's model `load()` returns. Read-only: no new queries, and the model doesn't change. Build each frame
   with `shape(name, df)` from `racinglines/frames/_util.py` (declared columns, key order).
2. Set `available_at` per row and write the rule, and every assumption, in the module docstring.
3. Add `[data] frames` to `sports/<sport code>.toml`.
4. Add the sport to `tests/test_frames.py`: it produces exactly the frames it declares, every frame validates,
   `available_at` is set, and the frames show the same rows as the model's own as-of rule at a few cutoffs.
