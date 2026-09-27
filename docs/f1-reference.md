# F1 modeling and market-making reference

Background for the [F1 roadmap](f1-roadmap.md): the model families and
market-making strategies worth investigating, the knobs that matter, and how
each maps onto what racinglines already does.

- **This page holds concepts and rationale.** What is *built* is documented in
  [Formula 1](f1.md) and [Market making](market-making.md). When an idea here
  ships, document it there and add a line to the changelog at the bottom.
- Links were checked in September 2026. Exchange APIs change often, so confirm
  API details against the live docs before coding against them.

## Starting point: what the baseline already does

The current F1 model (`racinglines/models/position_sim/`, see [Formula 1](f1.md))
is the **baseline**. Every idea on this page is measured against it and must
not break it.

| Concern | Baseline today |
| --- | --- |
| Car / driver split | Sector-type car model shared by both drivers (`CAR_PACE = "mean"`), driver offsets vs teammate, recency-weighted and ridge-shrunk |
| Practice | Practice-pace prior (added 2026-09-26) |
| Finishing | Ridge regression on grid, race/qualifying pace gaps, overtaking-ease and street interactions |
| Joint outcomes | 10,000-run simulation with teammate-shared noise, per-team DNF rates, season pace drift |
| Contracts priced | Win, podium, top 10, pole, head-to-head, top-scoring constructor, championships, season wins, standings head-to-head |
| As-of discipline | `price_race` with a hard cutoff; `Measurements.view(cutoff)`, `assert_no_leak` → `LeakageError` |
| Market data | Polymarket sync (Gamma), minute prices, trades, book snapshots (`markets record`) |
| Execution research | Maker replay (touch/through fills), weekend taker strategies, season strategy, season sweep |

**Known gaps, measured** (from [Formula 1](f1.md) and [TODO](todo.md)):

1. **Win after qualifying loses to a grid-only baseline** (Brier 0.033 vs
   0.031, backtest run 115). The front of the grid is underweighted.
2. **Pre-practice pricing got slightly worse** with the practice prior, because
   the finishing model now trains on practice-informed paces.
3. **Chaotic-race tail is missing:** backmarkers get almost no points chance
   (the Sainz–Alonso market).
4. **Correlated DNFs aren't simulated** (teammate DNF correlation +0.11), and
   top-scoring constructor got slightly worse with shared noise.
5. **Takers lose late in the weekend, makers win:** in the 2026 sweep (run 191,
   with the practice prior), the update-and-rebuy taker lost $479 and the maker
   replay made $751. The taker's losses are all after FP3 and qualifying,
   where Polymarket is sharper (race-winner Brier after qualifying: model 0.072,
   Polymarket 0.060). Pre-qualifying inventory is the biggest maker risk (Baku).

Everything below is framed as a way to close one of these gaps. An idea that
doesn't target a measured gap isn't a priority.

## Model families

### A. Gradient-boosted finishing model (challenger to the ridge stage)

**Where it fits.** Not a new pipeline: a drop-in alternative for step 4 of the
baseline (the finishing model), using the same inputs the ridge already sees
(`g`, `rp_rel`, `qp_rel`, `g_ease`, `rp_ease`, `street_g`) plus any new ones.

**Why.** Gap 1 looks like a shape problem: a linear term in normalized grid
can't make pole much more valuable than P3 while keeping P10 vs P13 small.
Trees capture that without hand-built terms, and a monotone constraint keeps
the grid effect sensible.

**Before building it, try the cheap version** (already on the TODO list): a
nonlinear grid prior inside the ridge, e.g. a few grid-bucket terms or a
spline. If that closes gap 1, the GBM isn't needed for it.

| Knob | Why it matters |
| --- | --- |
| `objective` | Regression on normalized finishing position (matches the ridge target) or LambdaRank grouped by race |
| `num_leaves`, `min_data_in_leaf` | Main overfitting controls. About 20 drivers × 24 races a year is small data |
| `learning_rate` + early stopping | Tuned on later races only, never a random split |
| `monotone_constraints` | Worse grid never improves the expected finish; same for pace gaps |
| `feature_fraction`, `bagging_fraction` | Extra regularization |
| Recency weights | Same half-life idea the car model uses |

**Output contract.** The simulation needs a finishing score *and* a noise σ.
The ridge gives σ from residuals; a GBM must do the same from out-of-time
residuals, or the simulation's spread (and therefore every probability) changes.

**Links**

- LightGBM parameters: <https://lightgbm.readthedocs.io/en/latest/Parameters.html>
- LightGBM tuning: <https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html>
- scikit-learn calibration curves (for F1-1's reliability plots): <https://scikit-learn.org/stable/modules/calibration.html>

### B. Bayesian hierarchical Plackett-Luce (research challenger)

A generative model of the whole finishing order: strength = driver skill +
car pace (random walk over races) + track-cluster effect, with a separate DNF
hazard. Win probability is `softmax(θ)`; other markets come from sampling orders
(Gumbel-max trick: add Gumbel noise to θ and sort).

```
P(order π) = Π_i  exp(θ[π_i]) / Σ_{j ≥ i} exp(θ[π_j])
```

**Why it's lower priority here than in a greenfield project.** Its main selling
point is coherent prices for every contract from one distribution, and the
baseline's simulation already gives that. Its ridge shrinkage and recency
weighting play the role of partial pooling. What B would still add:

- **Posterior uncertainty per driver and team,** which could set maker spreads
  per market instead of one global half-spread.
- **An independent second opinion** built on finishing orders alone, useful for
  spotting where the pace-based model is wrong.
- **A principled prior reset** for regulation changes.

Build it only if the roadmap reaches that phase, and only as a challenger.

| Knob | Why it matters |
| --- | --- |
| Prior SD, driver vs car | Car/driver attribution. In the baseline, the car explains 61% of qualifying spread and 86% of race pace |
| Random-walk step `τ_car` | How fast car pace moves; larger at known upgrade races |
| Track clusters | Could reuse `track_profiles` (speed index, street, overtaking ease) |
| DNF hazard priors | Per team; ties into gap 4 |
| Inference | NUTS for accuracy; NumPyro or variational inference for race-weekend speed |

**Links**

- van Kesteren & Bergkamp (2023), *Bayesian analysis of Formula One race results*:
  <https://arxiv.org/abs/2203.08489> (open access:
  <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10660124/>)
- PyMC: <https://www.pymc.io/> · NumPyro: <https://num.pyro.ai/> (the optional extras named in the roadmap)
- `choix` (fast Plackett-Luce / Bradley-Terry estimates): <https://github.com/lucasmaystre/choix>

### C. Race-event simulation: two levels

The baseline simulates *positions*, not laps. That leaves two separate needs.

**C1. Richer position-level simulation (inside the existing simulator).**
Targets gaps 3 and 4 and the unpriced props:

- **Chaotic-race mixture:** with probability `p_chaos` (per circuit, from
  history), inflate finishing noise and DNF rates. `p_chaos` can be estimated
  from the `laps` table's track status (safety car, VSC, red flag) and the
  rain columns in `rounds.extra`.
- **Correlated DNFs:** a shared team DNF draw, sized to the measured +0.11.
- **Props:** safety car / red flag / rain probabilities per circuit, from the
  same track-status history. These markets are already synced with prices but
  have no model price.

| Knob | Why it matters |
| --- | --- |
| `p_chaos` per circuit (shrunk to the field) | How often a race is chaotic |
| Noise and DNF multipliers in chaos | How chaotic |
| Team DNF correlation | Constructor and points markets |
| SC / red-flag rates per circuit | Prop markets |

**C2. Lap-level in-play simulator (a new capability).**
Lap time = base pace + tyre degradation + fuel + traffic, plus stochastic pit
stops, safety cars and failures, repriced from the live race state. It is only
worth building if racinglines starts trading *during* races, which it
deliberately doesn't today ("the race itself is never traded"). It would need a
live feed, because FastF1's archive arrives after sessions end.

**Links**

- FastF1 (current source): <https://docs.fastf1.dev/>
- OpenF1 (real-time API; only needed for C2): <https://openf1.org/>

### Evaluation conventions

Match what the project already reports:

- **Brier scores** per market type and pricing stage (before practice / before
  qualifying / after qualifying), against uniform and grid baselines.
- **Paired differences, challenger − baseline, ± 2 standard errors over races.**
  Negative is better. This is how every model change in [Formula 1](f1.md) is
  judged, and it's the promotion rule in the roadmap.
- **Worth adding:**
    - log loss (punishes confident misses that Brier forgives);
    - reliability curves;
    - model-vs-market Brier per stage for every market type. The sweep already
      reports it for win and pole over 2026.
- Polymarket prices are never used to fit or price anything, only compared
  afterwards. Keep it that way; a model that uses market prices can't measure
  edge against them.

## From the joint distribution to contract prices

Already implemented for the markets listed in [Formula 1 → Polymarket
alignment](f1.md#polymarket-alignment). Two points matter for new work:

- **Structural relations to check** (used by strategy 2 below): win ≤ podium ≤
  top 10 per driver; win probabilities sum to 1; a team's "top-scoring
  constructor" price relates to its drivers' points distribution; head-to-heads
  must match the simulated orders.
- **Market groups that don't add up.** The diagnostic page already excludes
  groups whose prices don't sum to about their number of winners. For
  comparisons, normalize a coherent group proportionally before computing edge.
  The Shin or power methods are optional refinements.

## Market-making strategies

A maker's entry is the price at which someone else trades against a resting
quote. The goal: fills only at better than fair value, and not from takers who
know more.

The existing maker replay (`racinglines/markets/strategies/maker_replay.py`)
already does a simple version of all three strategies. Its current knobs, from
[Market making](market-making.md):

| Knob | Current value |
| --- | --- |
| Quote | Post-only, fair ± half-spread, shifted against inventory; never crosses |
| Skip rules | Price outside 3–97¢; under $100 traded in 24 h; fair more than 15 points from the market |
| Size limits | 50 shares per quote, 250 per market |
| Risk | $1,000 worst-case loss per event |
| Timing | Quotes pulled 15 min before qualifying and the race; positions held to the result |
| Fills | Touch (optimistic) vs through (conservative) bounds |

### 1. Inventory-skewed quoting (Avellaneda-Stoikov)

The replay's "shifted against its inventory" is the right idea in simple form.
Avellaneda-Stoikov gives it a principled shape:

```
reservation price  r = p − q·γ·σ²·(T − t)
total spread       δ_a + δ_b = γ·σ²·(T − t) + (2/γ)·ln(1 + γ/k)
```

`p` is fair probability, `q` is inventory, `γ` is risk aversion, `σ²` is price
variance (for a binary, about `p(1 − p)`, scaled by time to resolution), and
`k` is how fast order arrivals fall off with distance from the mid.

**Binary adaptations:**

- Quoting in log-odds space respects the 0–1 bounds.
- Keep the 3–97¢ skip rule. Relative error is largest at the extremes.

**Why it matters here:** Baku's losses were two shorts that hit the 250-share
limit before qualifying. A skew that grows with `(T − t)` to the next
information event (not just to resolution) pushes inventory down before
qualifying automatically.

**Links**

- Avellaneda & Stoikov (2008): <https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf>
- `hftbacktest` (queue-position modeling, for F1-4's queue fill rule): <https://github.com/nkaz001/hftbacktest>

### 2. Linked-market coherence

F1 markets are linked (win / podium / head-to-head / constructor /
championship), and the simulation prices them all from one distribution. The
strategy:

- quote passively where a linked market is out of line with the others;
- re-quote every linked market when the model or one book moves (already a
  TODO: "re-quote linked markets automatically");
- optionally hedge a fill in a more liquid linked market.

The Baku tape shows the practical limit: win had $68k of volume, head-to-head
$482, and top-constructor $0. Hedging only works where the hedge leg trades.

**Cross-venue** (e.g. Kalshi) is the same idea across exchanges. Worth it only
if another venue lists F1 with real depth, and only when resolution rules
match. Rules that differ on penalties, disqualifications or timing make a
"hedge" a bet on the stewards.

| Knob | Why it matters |
| --- | --- |
| Minimum coherence gap | Must exceed fees + hedge slippage + model error |
| Hedge ratio | Legs aren't perfectly correlated |
| Leg-risk timeout | Longest time an unhedged fill is held |
| Liquidity floor per leg | Don't quote a leg you can't exit |

### 3. Information-timed quoting

The weekend's information arrives on a schedule, and the sweep shows where it
bites: in sweep run 191, the update-and-rebuy taker lost −$1,187 after FP3
and −$1,166 after qualifying, but made +$1,944 after FP1, FP2 and the sprint.

- **Defensive:** pull or widen before every session, not only qualifying and
  the race. Flatten or hedge inventory before qualifying (a TODO, and the Baku
  lesson).
- **Offensive:** re-enter right after the stage's as-of reprice, while the book
  is thin.
- **Toxicity:** the replay already reports `markout_60m`. Using it *as an
  input* (widen or cut size where markouts are persistently negative, per
  market type and stage) turns a report into a control.

| Knob | Why it matters |
| --- | --- |
| Pull window per session type | Currently 15 min, qualifying and race only |
| Pre-qualifying inventory target | Flatten fully, or to a cap |
| Re-entry delay after a stage | Time for the reprice to land |
| Markout horizon and threshold | When to widen |
| Spread multiplier per stage | Tighter when the model is well informed |

### Position sizing

The weekend taker targets $250 × edge (max $50 per market). Fractional Kelly is
the principled alternative. For a YES contract at price `c` with fair `p > c`:

```
f* = (p − c) / (1 − c)       # full Kelly, fraction of bankroll
```

Use a quarter to a half of `f*`, and shrink `p` toward the market price in line
with measured calibration error. Given how the sweep went for takers, this is
more useful for sizing maker inventory caps than for taking.

## Venues

**Polymarket** (current venue)

- Docs: <https://docs.polymarket.com/> · machine-readable index: <https://docs.polymarket.com/llms.txt>
- Changelog: <https://docs.polymarket.com/changelog>. **CLOB V2 went live on
  2026-04-28;** V1 SDKs and V1-signed orders no longer work on production.
  Confirm `racinglines/markets/polymarket/trade` signs V2 orders.
- Liquidity rewards for resting quotes near the mid:
  <https://docs.polymarket.com/market-makers/liquidity-rewards>. These aren't in
  the replay's P&L yet and may be a real part of maker returns.
- No historical order-book API, which is why `markets record` must run through
  every race weekend.

**Kalshi** (possible second venue)

- Docs: <https://docs.kalshi.com/> · index: <https://docs.kalshi.com/llms.txt>
- Demo environment: <https://docs.kalshi.com/getting_started/demo_env>

Confirm venue eligibility for your jurisdiction, fees, tick sizes and rate
limits before relying on any hard-coded value.

## Changelog

| Date | Change |
| --- | --- |
| 2026-09-26 | First version, aligned to the existing position_sim baseline, maker replay and season sweep. |
| 2026-09-26 | Moved into the docs site. Gap 5 and strategy 3 updated to sweep run 191 (practice prior); model-vs-market Brier by stage noted as partly available. |
| 2026-09-26 | Trimmed general references (textbooks, unused tools, duplicate papers); kept links tied to a roadmap phase. |
