# Road cycling: sportsbook lines

Road cycling has no exchange model yet (its Kalshi markets are tape-only, `docs/todo.md` U9), but its sportsbook
lines (race winner, head-to-head) are priced from results by the **book model**: the timed-runs engine
(`racinglines/models/timed_runs/model.py`, the downhill model) fitted on ProCyclingStats results.

Everything is data:

| What | Where |
| --- | --- |
| Which races to fetch, per kind of result | `sports/road_cycling.toml` `[results.itt]`, `[results.road]` |
| Model settings per kind: defaults, calibration grid, course and field rules, backtest races | `[model.itt]`, `[model.road]` |
| One race: course, start list file, the book's lines, the riders' full names | `sports/road_cycling/events/<id>.toml` |
| Results (gitignored, Mac only) | `data/raw/road_cycling/` |
| Outputs | `reports/<event id>/` |

A new race is a new event file. A new kind of race (a team time trial, a stage of a stage race) is a new
`[model.<kind>]` block plus a branch in `racinglines/models/cycling.py`'s `to_raw`.

## The two kinds

**`itt`: individual time trials.** Log finishing times, one run per rider per race. A per-rider climbing term (the
slope of a rider's residual log time on the course's climbing in m/km) is scaled by `climb_scale` for the event's
course (`distance_km`, `vert_m` in the event file).

**`road`: mass-start races.** Riders finish in bunches, so times say little. Each result becomes a pseudo-time:
the finisher's normal score `z = Φ⁻¹((position − 0.5) / finishers)`, as log time `0.01 · z`. The engine's race
effects are estimated through riders who meet across races, so a 10th place in a WorldTour race counts for more
than a 10th place in a weaker field. A stage race's final GC is a second result kind (`gc_weight`), because
climbers race few one-day races. A road incident is a DNF or a finish out of contention, so it is simulated as out.

**Training weight** per result = recency (`half_life` days) × course (`flat_weight` for races off the event's
terrain) × field (`weak_weight` below the strong-field rule) × kind (`gc_weight`). The simulation scales the
fitted noise by `noise_scale` and the incident rate by `incident_scale`.

**Head-to-heads** pay the better finisher; simulations where both riders are out are left out (void on most
books). **Stakes** are fractional Kelly on every positive edge (`--kelly 0.25` = quarter Kelly, `--bankroll`),
each sized on its own, with `thin_data` marking a rider with under 5 results.

## Workflow (Mac)

The cloud sandbox can't reach ProCyclingStats, so fetching runs on the Mac. Fetching is cached per page and safe to
re-run; it needs `pip install cloudscraper selectolax` (not in `requirements.txt`: nothing on the VM needs them). Pages are parsed by `racinglines/sources/pcs.py` itself, not the `procyclingstats` package, whose results selector stopped matching PCS on 2026-10-05. When a fetch fails, `racinglines cycling probe race/<slug>/<year>/result` saves the page and prints what parses.

```
# LOCAL (Mac)
racinglines cycling events
racinglines cycling fetch road --seasons 2020-2026
racinglines cycling startlist 2026-10-06-tre-valli-varesine
racinglines cycling price 2026-10-06-tre-valli-varesine --calibrate
racinglines cycling price 2026-10-06-tre-valli-varesine --settings-from reports/2026-10-06-tre-valli-varesine/calibration.csv
```

`--calibrate` grid-searches `[model.<kind>.grid]` walk-forward on the kind's backtest races since `--since`
(default 2021, five complete seasons): one fit per month on the months before, scored on the actual winner's log
loss and the pairwise log loss of the top 40 finishers, ranked by the mean rank of the two. It prints the chosen
setting's scores by season. `price` writes `settings.csv`, `futures.csv`, `matchups.csv` and `stakes.csv`.

## Decision log

| Date | Kind | Decision | Why | Supersedes |
| --- | --- | --- | --- | --- |
| 2026-10-05 | itt | Defaults half_life 365, flat_weight 1.0, weak_weight 0.4, noise_scale 1.15, incident_scale 1.0 | Walk-forward on 73 strong-field ITTs 2021–26: winner log loss 2.473, pairwise 0.590 (2.583 / 0.608 before); the model is not overconfident | — |
| 2026-10-05 | itt | Climbing term climb_scale 0.5, climb_prior 2 | Same backtest: winner log loss 2.376, pairwise 0.585; hilly ITTs 2.312 (2.391 without); a ±0.5% effect on the Euros course | — |
| 2026-10-05 | road | First version for Tre Valli Varesine; defaults are a guess until `--calibrate` runs on real results | No road results had been fetched | — |
| 2026-10-05 | both | One-off scripts (`scripts/oneoff/euro_itt_price.py`) folded into `racinglines cycling` | Owner: today's cycling work must be reusable, schema-driven model runs | — |
