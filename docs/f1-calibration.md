# F1 calibration power (C48)

The F1 sector simulation is too flat: it gives favourites too little and long shots too much. Over 2025, drivers it
priced at 5 to 10% to win won 2.0% of the time, and drivers it priced at 10 to 35% won more often than it said
(reliability bins of the uncalibrated sweep below). The sweep setting `calib_power` corrects this with one number per
stage group, fitted walk-forward on earlier races only. It is **off by default**: unset, every model key and every
price is unchanged.

## What it does

The simulation's win chances p_i become q_i = p_i^a / Σ_j p_j^a. With a > 1 the favourites get more and the long
shots less. Each simulated race is then resampled with weight q(winner) / p(winner), so every market priced from the
same draws (podium, top 10, head-to-head, constructor, pole before qualifying) moves with the win price and stays
coherent with it. The resample draws from a side random stream, so nothing else drawn in the pricing path changes.

Code: [racinglines/models/calibration.py](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/models/calibration.py),
hooked into `price_race` in `racinglines/models/inputs/laps_pricing.py`. The sprint's own race and the season forecast
are not calibrated.

| `calib_power` | Meaning |
| --- | --- |
| unset (default) | off: no key change, prices byte-identical |
| a number, 1 to 10 | that power at every stage (1 = off) |
| `walk_forward` | the power from [sports/f1/calibration.toml](https://github.com/lalligagger/racinglines-public/blob/main/sports/f1/calibration.toml) for the price's cutoff and stage group |

It is the same setting on every surface: `racinglines strategy sweep f1 --calib-power walk_forward`, the Lab's sweep form
(All settings → Model), and the MCP `run_job` settings object (`{"calib_power": "walk_forward"}`; `list_job_types`
lists it). The event diagnostic and combo
prices take it too: `racinglines model diagnostic f1 ... --calib-power walk_forward`, `racinglines model combo f1
... --calib-power walk_forward`, and the `calib_power` field of the Lab's Event diagnostic and Combo forms (and their
MCP `run_job` params).

To compare one event's prices without and with it, as of one cutoff (read-only, nothing saved):

```
# LOCAL (Mac) or VM
python scripts/models/calib_ab.py --event 2026-18 --cutoff 2026-10-14T06:55 [--calib-power walk_forward] [--csv FILE]
```


## The walk-forward table

Each row of `calibration.toml` is the power (a = 1.0 to 4.0 in steps of 0.1) that minimised the race winner's log loss
over every Grand Prix finished before the row's `from` date, fitted separately for:

- `grid`: the stage after qualifying, when the starting grid is known;
- `nogrid`: every earlier stage (pre-weekend, practice, sprint qualifying, sprint).

A price uses the latest row whose `from` is on or before its cutoff date. `from` is two days after the last race in
the fit, because a night race can end after midnight UTC. No row exists until 8 races have finished, and before that
the power is 1 (off). With `walk_forward`, the table's hash is part of the model key, so a refitted table prices
afresh instead of reusing cached runs.

The current table holds 32 rows from 39 Grands Prix (2025-01 to 2026-15). The latest row is grid 2.3, nogrid 2.1, and
it applies to every race after 2026-15 until the table is refitted.

### Rebuild

```
# LOCAL (Mac) or VM: the as-of prices it fits on come from an uncalibrated sweep
racinglines strategy sweep f1 --variant gridq+pretrain+reset --year 2025 --no-fetch --reliability --sims 4000
racinglines strategy sweep f1 --variant gridq+pretrain+reset --year 2026 --no-fetch --reliability --sims 4000
python scripts/models/fit_calibration.py --sims 4000 --check
```

`--check` runs the leakage check on the real data (below) before it writes the table. `--csv FILE` fits rows exported
from another database instead.

## Leakage check

Every power used for a race is fitted only on races that finished before it. Three things enforce this:

1. **By construction.** Row k is fitted on races 1 to k−1 and applies from two days after race k−1. Every price of
   race k has a cutoff before race k's start, so it can only reach rows fitted on earlier races.
2. **On the real data** (`fit_calibration.py --check`): for every cut point k, the results of race k and every later
   race are scrambled (each winner moved to another driver) and the table is refitted. If any row that applies before
   race k changes, the check fails. On the current table: 31 cut points, no earlier row changed.
3. **In the test suite** (`tests/test_calib_power.py`): the same scramble on synthetic races, with a guard that the
   scramble does move later rows (so the test can fail). The suite also checks that each row's `from` is after its
   last race and before the race it prices, that a cutoff before `from` never gets that row, and that unset changes
   no key or price.

What this does not rule out: the base model's other settings were tuned on the same seasons, in hindsight, and the
power method was chosen after seeing that the model is flat. Those are selection effects, not data leaks, and only
races after 2026-10-14 are a clean out-of-sample test.

## Results

Sweeps of the default model (`gridq+pretrain+reset`, 4,000 sims, Polymarket tape), with `calib_power` unset and then
set to `walk_forward`. Lower is better for log loss and ECE.

| Race-win prices | 2025 off | 2025 walk_forward | 2026 off | 2026 walk_forward | Market |
| --- | --- | --- | --- | --- | --- |
| Log loss | 0.1694 | 0.1627 | 0.2244 | 0.2194 | 0.1439 (2025), 0.2222 (2026) |
| Brier | 0.0507 | 0.0499 | 0.0662 | 0.0654 | 0.0445 (2025), 0.0674 (2026) |
| ECE | 0.0313 | 0.0240 | 0.0232 | 0.0191 | 0.0087 (2025), 0.0194 (2026) |

Paper P&L on the recorded tape, per strategy:

| Strategy | 2025 off | 2025 walk_forward | 2026 off | 2026 walk_forward |
| --- | --- | --- | --- | --- |
| update | +728.80 | +1,386.44 | +241.97 | +858.88 |
| hold | −737.48 | −496.67 | +835.44 | +1,400.46 |
| last | −727.33 | −160.06 | +486.05 | +979.18 |
| early | −322.85 | −238.75 | +2,264.01 | +3,165.43 |
| maker | −652.11 | +429.96 | +933.13 | +1,307.52 |
| maker_flat | −1,004.35 | +317.53 | +402.36 | +692.69 |
| maker_skew | −699.85 | +398.50 | +978.72 | +1,180.86 |
| maker_widen | −623.70 | +315.11 | +751.48 | +1,129.37 |
| maker_all | −795.54 | +53.20 | +310.09 | +562.44 |

All 18 strategy-seasons improve. In 2026 the calibrated win prices beat the market's log loss (0.2194 against 0.2222);
in 2025 they are still well behind it. Head-to-head and podium scores move little or get slightly worse, and the 2025
podium sample is only 3 prices.

Reliability of the race-win prices, 2025 (observed win rate per bin of the model's price):

| Model price | Off: n | Off: won | Walk-forward: n | Walk-forward: won |
| --- | --- | --- | --- | --- |
| 5–10% | 246 | 2.0% | 172 | 2.9% |
| 10–20% | 327 | 19.6% | 201 | 24.4% |
| 20–35% | 86 | 34.9% | 109 | 24.8% |
| 35–50% | 13 | 53.8% | 39 | 41.0% |

The 10 to 20% bin is still under-priced after calibration (z = 4.2), so one power does not fix every bucket.

## Status

Optional and off by default (decision log, 2026-10-14). Making `walk_forward` the default goes through the
[promotion rule](f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default) and is the owner's call.
