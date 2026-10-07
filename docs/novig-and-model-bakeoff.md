# Novig, and an A/B/C test of the prediction models

Best-effort investigation, started 2026-10-06 on the owner's ask: two people, $50 each plus promo credits on
Novig, and "a good time to A/B/C test the first-stage prediction models against each other (fundamentally different
algorithms)". Nothing here is built or placed yet. Anything that is a reading rather than what a source says is
marked *(inferred)*.

## Part 1: Novig

**What it is** (web search, 2026-10-06): a peer-to-peer sports exchange (an order book, no bookmaker margin). It
relaunched on 4 Aug 2026 as a CFTC-regulated prediction market under Ludlow Exchange LLC, live in 47 states (not AZ,
MI or NV). Pre-game trades and maker fills carry no fee; live (in-game) trades and parlays pay a taker fee. A new
account's promo is a trading bonus (about $25 after a $10 deposit), and referral credits expire in 7 days and need
$25 of further trading before they can be withdrawn. Sources: [Legal Sports Report](https://www.legalsportsreport.com/prediction-markets/novig-promo-code/),
[CBS Sports](https://cbssports.com/prediction/news/novig-promo-code/), [SBC Americas](https://sbcamericas.com/2026/08/04/novig-prediction-markets-relaunch/).

**What it lists, from a read-only probe of the public web app on the Mac** (2026-10-06, `app.novig.us`, its
JavaScript bundle only; no account, no API call). The app's sport list is American Football, Basketball, Baseball,
Ice Hockey, Soccer, Tennis, Boxing, MMA, eSports, Golf and Entertainment, and its leagues include `PGA`. There is
**no motorsport or cycling** sport or league in the app *(inferred from the bundle: the strings `NASCAR`, `IndyCar`,
`MotoGP` and `Formula 1` don't appear; `F1` appears only as a keyboard key)*. Golf is listed, and Novig has a
partnership with LIV Golf ([worldcasinodirectory](https://news.worldcasinodirectory.com/liv-golf-expands-reach-with-novig-prediction-market-deal-122352)).

**API:** the app talks to `api.novig.us` (`/v1/graphql`, `/nbx/v1`, `/recs/v1`). That is the app's own API, not a
documented public one. The terms page (`novig.us/legal/terms-and-conditions`) sits behind a CAPTCHA, so its rules on
automated access were **not read**. Per the probe-first rule (`CLAUDE.md`), nothing calls that API until the owner
has read the terms and a small read-only probe has been agreed.

**What this means for the $100:** racinglines prices motorsport and cycling, and Novig lists neither. Today we
have **no model for anything Novig lists**. Golf is the closest fit for our engine, but it has no model yet, and
golf is the sharpest market we've looked at (see the golf brief in the project thread). So the honest options are:

1. Treat the $100 and the credits as a test of Novig's mechanics (deposit, order book, settlement, withdrawal), not of
   racinglines, and record it as `source = unverified` in the tracker.
2. Hold the money until a racinglines model covers something Novig lists (golf being the candidate), or until Novig
   lists motorsport.
3. Use the exchange as a maker: no fees on maker fills, so a resting order at our fair value costs nothing if it
   doesn't fill. Only useful once we have a fair value for something it lists.

## Part 2: an A/B/C test of fundamentally different algorithms

**Has it been done?** Partly. The 2026-10-02 global-model validation (`reports/2026-10-02-global-model-validation/report.md`,
local only) scored three things on the same races: a learns-nothing control, each sport's own model and the
sport-agnostic global model. Race-win log loss (lower is better):

| Sport | Control | Own model | Global model |
|---|---|---|---|
| F1 (2024–26, 63 events) | 0.1812 | 0.1134 (lap and sector simulator) | 0.1476 |
| MotoGP | 0.1867 | 0.1936 | 0.1608 |
| NASCAR | 0.1211 | 0.1530 | 0.1085 |

That report's own caveats apply: the F1 simulator knows qualifying and the global model doesn't, MotoGP and
NASCAR data are thin, nothing is tuned, and there are no standard errors. The other cross-algorithm test on record is
the F1 `gbm` finishing model against the ridge baseline (`docs/f1-evaluation.md`, run 979): `gbm` was worse on
accuracy and wasn't promoted.

**What's missing** (`docs/engine-roadmap.md`, gaps G5 and G7): there is no harness that scores several algorithms
on the same events with paired standard errors outside F1 (`f1 compare` pairs two F1 runs only), and only three
algorithm families exist: the F1 simulator (ridge or `gbm`), the timed-runs engine (downhill, cycling) and the
global probit-strength model. Plackett-Luce and a market-implied model are planned, not built (engine roadmap E7).

**Proposed test**, in the order the engine roadmap already sets (E5, then E7). It needs a decision before any code:

| | Algorithm | Family | Built? |
|---|---|---|---|
| A | Each sport's own model (F1 simulator; timed runs for downhill) | Simulation from sessions or run times | Yes |
| B | Global model | Probit strength from finishing positions | Yes |
| C | Plackett-Luce | Ranking likelihood over classifications | Tested 2026-10-06, not adopted (Part 3) |
| D | Market-implied strengths | Strengths fitted to exchange prices | No (E7) |
| 0 | Learns-nothing control | Uniform or prior only | Yes (global with a heavy prior) |

- **Same events, same cutoffs, same kinds:** F1 2024–26, NASCAR and MotoGP 2026, downhill 2021–26, scored on
  win, podium, top 10 and head-to-head; log loss and Brier, **paired by event with ±2 standard errors** (the generic
  `eval compare` of E5, built on the E4a prediction records).
- **Two scoreboards:** accuracy (the above), and money: each algorithm's prices against the recorded Kalshi and
  Polymarket tapes through the existing replays, because the F1 `gbm` model lost on accuracy but made money as maker
  profile K.
- **Golf** would be a fourth sport only if the owner wants a Novig model; it needs a data source probe first.

## Part 3: Plackett-Luce tested (2026-10-06): not adopted

**What ran.** A first Plackett-Luce model (`racinglines/models/model_pl.py`, tests in `tests/test_model_pl.py`)
was added as a fourth column to the 2026-10-02 validation harness (`scripts/validate_global_model.py --pl`) and run
on the same events, seasons, seed and simulation count. It reads exactly the global model's history (finishing
positions only), so the comparison isolates the algorithm. Each past race's classified order is one Plackett-Luce
observation, weighted by the global model's recency decay (`half_life_days`), fitted by Hunter's MM algorithm with
`prior_weight` pseudo-comparisons against an average entrant; races are drawn by Gumbel-max, with the global
model's retirement draw. Nothing is tuned: every setting is the global model's default. The own, global and control
columns reproduce the 2026-10-02 report to the fourth decimal, so the runs are like for like.

**Results**, log loss over all scored seasons (lower is better; bold is the better of global and PL):

| Sport (events) | Kind | Own | Global | PL | Control |
|---|---|---|---|---|---|
| F1 (63) | race_win | 0.1134 | **0.1476** | 0.1556 | 0.1812 |
| F1 | race_podium | 0.2273 | **0.2965** | 0.3122 | 0.3852 |
| F1 | race_top10 | 0.4528 | 0.5453 | **0.5377** | 0.6481 |
| F1 | race_h2h | 0.4847 | 0.5612 | **0.5580** | 0.6515 |
| NASCAR (82) | race_win | 0.1530 | **0.1085** | 0.1151 | 0.1211 |
| NASCAR | race_podium | 0.4373 | **0.2407** | 0.2527 | 0.2713 |
| NASCAR | race_top10 | 1.1189 | **0.4904** | 0.4992 | 0.5547 |
| NASCAR | race_h2h | 1.4863 | **0.6083** | 0.6086 | 0.6634 |
| MotoGP (32) | race_win | 0.1936 | **0.1608** | 0.1620 | 0.1867 |
| MotoGP | race_podium | 0.4004 | 0.3242 | **0.3112** | 0.3985 |
| MotoGP | race_top10 | 0.9820 | 0.6134 | **0.5874** | 0.6765 |
| MotoGP | race_h2h | 1.0548 | 0.6331 | **0.6184** | 0.6814 |

**Verdict: not adopted.** PL beats the learn-nothing control everywhere, so it learns. But it loses to the global
model on **race win in all three sports and on podium in F1 and NASCAR**, the markets we actually trade, and never
comes near the F1 simulator. Its wins are in the middle of the field: F1 top 10 and head-to-head, and every MotoGP
kind but the win (MotoGP is 32 events, two seasons). The differences are small, and the harness prints no standard
errors, so only the direction is a finding: the per-kind margins are not tested for significance.

**Why** *(inferred, not tested separately)*:

1. **Every place counts the same.** A Plackett-Luce fit learns as much from a 14th-vs-15th swap as from who won, so
   the strengths are fitted mostly to the midfield (there are many more midfield places than podium places). That
   matches where it does well (top 10, head-to-head) and where it doesn't (win, podium). The global model's probit
   score spreads the front of the field further apart, so a win counts for more than a 10th place.
2. **Its race-day noise is fixed.** The Gumbel draw has one spread; the global model has `noise` and an extra
   spread for entrants with few starts (`uncertainty`). With no knob for how decisive a race is, PL can't sharpen
   its favourites in a sport where the best car wins often (F1) or flatten them where it doesn't.
3. **Retirements are left out of the order.** A retirement is information about reliability that PL ignores in
   the strengths (it only reaches the price through the shared DNF draw).
4. **Nothing is tuned,** for either model. A tuned PL (a temperature on the strengths, a weighting toward the
   front places) might close the gap. It isn't worth that work while it trails on the win market.

**Kept:** the model and the `--pl` flag stay in the repo as a baseline for E7 (no live path uses them), so the next
algorithm (market-implied strengths) is scored against it. Commands, on the Mac with the local database (read-only):

```
PYTHONPATH=. python scripts/validate_global_model.py f1     --seasons 2024 2025 2026 --pl
PYTHONPATH=. python scripts/validate_global_model.py motogp --seasons 2016 2026 --own-field --own-fill --pl
PYTHONPATH=. python scripts/validate_global_model.py nascar --seasons 2018 2019 2026 --own-field --own-fill --pl
```

**Owner decisions:** (1) Novig: option 1, 2 or 3 above. (2) Build E5's generic `compare` first (Implement, Sonnet,
on the E4a records, with paired standard errors), then D (market-implied)? C (Plackett-Luce) is tested above and not adopted. (3) Is golf in scope?
