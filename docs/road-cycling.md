# Road cycling

Road cycling is priced two ways, from the same ProCyclingStats results:

- **On the Markets board, by the one engine** (since 2026-10-12, provisional): `sports/road_cycling.toml` `[model]`
  declares the results input of `racinglines.models.model_global:GlobalModel`, like NASCAR and MotoGP. Results and
  upcoming start lists are loaded into the database, and `racinglines model forecast cycling --save` stores the run
  the board shows (win, podium, top 10 per rider; every head-to-head in the run). Admins only (`[sport] audience`), labelled
  baseline: every setting is a priori ([Board pricing](#board-pricing-the-one-engine) below).
- **Sportsbook lines, by the book model** (unchanged): the timed-runs engine
  (`racinglines/models/inputs/run_times/model.py`, the downhill model) fitted on the same results, below. It is a
  separate tool for pricing a bookmaker's lines, not the board's model.

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
re-run; it needs `pip install cloudscraper selectolax` (not in `requirements.txt`: nothing on the VM needs them). Pages are parsed by `racinglines/sources/pcs.py` itself, not the `procyclingstats` package, whose results selector stopped matching PCS on 2026-10-05. When a fetch fails, `racinglines data probe cycling race/<slug>/<year>/result` saves the page and prints what parses.

```
# LOCAL (Mac)
racinglines data events cycling
racinglines data fetch cycling road --seasons 2020-2026
racinglines data startlist cycling 2026-10-06-tre-valli-varesine
racinglines model price cycling 2026-10-06-tre-valli-varesine --calibrate
racinglines model price cycling 2026-10-06-tre-valli-varesine --settings-from reports/2026-10-06-tre-valli-varesine/calibration.csv
```

`--calibrate` grid-searches `[model.<kind>.grid]` walk-forward on the kind's backtest races since `--since`
(default 2021, five complete seasons): one fit per month on the months before, scored on the actual winner's log
loss and the pairwise log loss of the top 40 finishers, ranked by the mean rank of the two. It prints the chosen
setting's scores by season. `price` writes `settings.csv`, `futures.csv`, `matchups.csv` and `stakes.csv`.

## Calibration check: favourites vs long shots (Core backlog C48)

`racinglines model reliability cycling <kind>` refits walk-forward month by month (as `--calibrate` does) and records
every rider's win, top-3 and top-10 chance in every backtest race, DNFs included, against what happened. It prints
and writes to `reports/reliability-<kind>/`: `win_by_prob.csv` (riders bucketed by win chance), `win_by_rank.csv`,
`top3_by_rank.csv`, `top10_by_rank.csv` (by the model's rank: 1, 2-3, 4-5, 6-10, 11-20, 21+), each with
predicted vs actual rate and `z = (hits - expected) / sd` (z above 2: the bucket is under-rated), plus
`temperature.csv`, the power `a` in `p^a / Σp^a` that best fits the winners (above 1: favourites too long, long
shots too short). The temperature is fitted in-sample, so it is a diagnostic; any fix goes through the decision log.

```
# LOCAL (Mac)
racinglines model reliability cycling road --settings-from reports/<event>/settings.csv
racinglines model reliability cycling itt
```

## Board pricing: the one engine

What the engine reads: `events.source = "pcs_road"` (one-day races and stage-race final GCs from the road results file;
the ITT file is stored as `pcs_itt` and left out of the history), one `race` round per race, riders matched on their
PCS rider slug (`athlete_identifiers` scheme `pcs`, exact keys). A scheduled race is an event with status
`scheduled` and a `startlist` round: the forecast prices only races with their own start list (`[forecast] field =
"entry_list"`), and the results ingested for it later complete the same event. Settings: `[model.defaults]`, all a
priori (decision log 2026-10-12 in [F1 roadmap](f1-roadmap.md#decision-log)).

Every write needs a database dump under 24 hours old (`--backup`) and logs a `data_changes` row. In order, one
step at a time (the event file is `sports/road_cycling/events/<event>.toml`: `[event]` name, kind, date, pcs,
startlist_file; `<event>` below is its file name without `.toml`):

```
# LOCAL (Mac) — 1. this season's results and the race's start list (cached per page, safe to re-run)
racinglines data fetch cycling road --seasons 2020-2026
racinglines data startlist cycling <event>
```

```
# LOCAL (Mac) — 2. copy both files to the VM (data never arrives by merge)
gcloud compute scp data/raw/road_cycling/road_results_pcs.csv data/raw/road_cycling/<startlist_file> racinglines-vm:~/ --project racinglines --zone us-west1-b --tunnel-through-iap
```

The event file itself arrives with the code (a merge), or is copied the same way and given to `schedule` by its path.

```
# VM (production) — 3. back up the database, from the Mac; note the file it prints
bash scripts/deploy/vm.sh backup road-cycling-ingest
```

```
# VM (production) — 4. after `bash scripts/deploy/vm.sh ssh`: put the files in place, ingest, schedule, look at the forecast
sudo -u racinglines mkdir -p /opt/racinglines/data/raw/road_cycling
sudo install -o racinglines -g racinglines -m 644 ~/road_results_pcs.csv ~/<startlist_file> /opt/racinglines/data/raw/road_cycling/
cd /opt/racinglines
sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/racinglines data ingest cycling --backup <backup file>'
sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/racinglines data schedule cycling <event> --backup <backup file>'
sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/racinglines model forecast cycling'
```

```
# VM (production) — 5. store the forecast the board shows (undo: `racinglines model forecast cycling --undo <run id>`)
sudo -u racinglines -H bash -c 'set -a; . /etc/racinglines.env; set +a; .venv/bin/racinglines model forecast cycling --save --backup <backup file>'
```

`data ingest cycling` takes `--kind itt` for the ITT file and `--csv FILE` for a file elsewhere; it rebuilds only the
races whose rows changed (`--force`: all). A start list fetched again is loaded by running `schedule` again. The
forecast is not on the forecast-refresh timer (`scripts/vm/forecast-refresh.sh` runs NASCAR and MotoGP): re-run step 5
after new results or a new start list. To check the engine on the history: `racinglines backtest walk-forward
road_cycling --seasons 2025` (read-only).

What this doesn't do yet: no Kalshi cycling link is identified ([identity] has no resolver), so the board shows fair
prices with no exchange price beside them; head-to-heads are stored in the run (`race_predictions.extra.h2h`) for a
link to read, not shown as board columns; a rider with no stored result is priced at the field average with the
engine's extra spread for few starts.

## Decision log

| Date | Kind | Decision | Why | Supersedes |
| --- | --- | --- | --- | --- |
| 2026-10-05 | itt | Defaults half_life 365, flat_weight 1.0, weak_weight 0.4, noise_scale 1.15, incident_scale 1.0 | Walk-forward on 73 strong-field ITTs 2021–26: winner log loss 2.473, pairwise 0.590 (2.583 / 0.608 before); the model is not overconfident | — |
| 2026-10-05 | itt | Climbing term climb_scale 0.5, climb_prior 2 | Same backtest: winner log loss 2.376, pairwise 0.585; hilly ITTs 2.312 (2.391 without); a ±0.5% effect on the Euros course | — |
| 2026-10-05 | road | First version for Tre Valli Varesine; defaults are a guess until `--calibrate` runs on real results | No road results had been fetched | — |
| 2026-10-05 | both | One-off scripts (`scripts/oneoff/euro_itt_price.py`) folded into `racinglines cycling` | Owner: today's cycling work must be reusable, schema-driven model runs | — |
