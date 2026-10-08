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
| C | Plackett-Luce | Ranking likelihood over classifications | Tested, not adopted (Part 3) |
| D | Market-implied strengths | Strengths fitted to exchange prices | No (E7) |
| 0 | Learns-nothing control | Uniform or prior only | Yes (global with a heavy prior) |

- **Same events, same cutoffs, same kinds:** F1 2024–26, NASCAR and MotoGP 2026, downhill 2021–26, scored on
  win, podium, top 10 and head-to-head; log loss and Brier, **paired by event with ±2 standard errors** (the generic
  `eval compare` of E5, built on the E4a prediction records).
- **Two scoreboards:** accuracy (the above), and money: each algorithm's prices against the recorded Kalshi and
  Polymarket tapes through the existing replays, because the F1 `gbm` model lost on accuracy but made money as maker
  profile K.
- **Golf** would be a fourth sport only if the owner wants a Novig model; it needs a data source probe first.

## Part 3: Plackett-Luce tested (2026-10-06/07): not adopted

The full study is in `racinglines/research/algo_abc/` (engine roadmap E7, PR #82): walk-forward on 2025–26 F1,
MotoGP, NASCAR and downhill finishing orders, with race-level bootstrap intervals. Plackett-Luce was worse than the
global model on race-win log loss in all four sports (95% intervals exclude 0) and tied or worse on head-to-heads,
so it is not adopted; pairwise Elo beat the global model on head-to-heads in three sports.

An independent first check on 2026-10-06 agreed: a Plackett-Luce model on exactly the global model's history, run as
a fourth column of `scripts/validate_global_model.py` on the 2026-10-02 events (the own, global and control columns
reproduced that report to the fourth decimal), lost to the global model on race win in F1 (0.1556 vs 0.1476),
NASCAR (0.1151 vs 0.1085) and MotoGP (0.1620 vs 0.1608), and on podium in F1 and NASCAR, while doing slightly better
on F1 top 10 and head-to-head and on most MotoGP kinds. Likely reasons *(inferred)*: Plackett-Luce weighs every
place equally, so it fits the midfield more than the front; its race-day noise is fixed (no `noise` knob); it
ignores retirements in the strengths. That prototype was not kept: the research package above supersedes it.

**Owner decisions:** (1) Novig: option 1, 2 or 3 above. (2) Build E5's generic `compare` first (Implement, Sonnet,
on the E4a records, with paired standard errors), then D (market-implied)? C (Plackett-Luce) is tested and not adopted (Part 3). (3) Is golf in scope?

## Part 4: every timed session as a market (plan, 2026-10-07)

Owner ask: support every timed session of a race week (practice, qualifying, sprint qualifying, sprints, stages),
because each one generates exchange markets or sportsbook lines. Inventory of what exists (read from the code on
2026-10-07; file:line in the thread report), then the work, in order.

| Sport | Session | Priced today? | Venue sync / book map | Settles? | Data ingested? |
|---|---|---|---|---|---|
| F1 | FP1, FP2, FP3 | Only by a local, untracked script (`scripts/price_specials.py` and `position_sim/specials.py`, excluded in the Mac's `.git/info/exclude`): qualifying pace plus noise at an in-sample 0.3 scale, stake zeroed as `thin` | Book A names `fp1_win` (proposed kind only) | No (not in `kinds.py`) | FP1–3 fetched only on request (`f1 fetch` defaults to Q, S, R); practice rows carry no time or position |
| F1 | Sprint qualifying | Yes, `race_sprint_pole` (stage sims) | Kalshi, Polymarket, Book A | Yes (order from laps) | When fetched |
| F1 | Sprint | Yes, `race_sprint_win` (podium, top 8, head-to-head, constructor kinds exist, off by default) | Kalshi, Polymarket, Books A and C | Yes | Yes |
| F1 | Qualifying | Yes, `race_pole`; no Q1/Q2/Q3 exit markets | Kalshi, Polymarket | Pole yes; `race_biggest_mover` can't settle (no grid stored) | Yes |
| F1 | Race | Yes (win, podium, top 5/10, head-to-head, constructor, fastest lap, props) | All three venues | Yes | Yes |
| NASCAR | Practice, qualifying, stages 1–2 | No (results parsed, stage results ingested, no kinds) | Kalshi tape only | No | Yes |
| MotoGP | Practice, qualifying, sprint | No (only the race is ingested; the sprint is "not ingested yet") | Kalshi tape only | No | No |
| Downhill | Qualifying, semi | `race_make_final` only | Kalshi | Yes | Yes |
| Road cycling, IndyCar | Stages, GC, every session | No (tape only) | Kalshi tape only | No | Cycling results on the Mac |

**Ground rule: weekend mode stays (owner, 2026-10-07).** Every step below is behind a switch whose default is
today's weekend-based pricing (one race priced at each stage, no practice or qualifying sessions simulated). With the
switch off, the F1 backtests, `f1 compare`, the sweeps, the replays and the golden tests (`tests/golden/`) are
byte-identical to before. The session model is a new mode next to it, never a replacement; the decision to make it a
default goes through the promotion rule ([F1 roadmap](f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default))
with a decision-log entry. PR #82's combo pricing and `flpos` fastest lap already follow this (off every default
path; other prices byte-identical).

**Work, in order** (owner decides scope; nothing started beyond PR #82):

| # | Task | Role | Done when |
|---|---|---|---|
| S0 | **Owner decision:** the practice and session pricing code is local only and excluded from git on purpose (`.git/info/exclude`, commit `eeab36d`). Keep it private, or move it into the repo? Everything below assumes it moves in | Decide | — |
| S1 | Fetch FP1–3 and SQ by default on race weekends, and ingest practice lap times and the classification by best lap (the settlement source for practice markets) | Implement | A practice session's order is stored and matches FastF1's; golden tests unchanged |
| S2 | Register session kinds: `fp1_win`, `fp2_win`, `fp3_win` (and top-N), `qual_win` alias of pole, Q1/Q2 exits; `settle_from` the session's order | Implement | `kinds.py` settles each from a stored session; book schemas validate them |
| S3 | One simulated weekend (new mode, off by default): practice, SQ, sprint, qualifying and race drawn in the same simulations, so session and combo markets share one joint draw; calibrate the practice noise (now 0.3, in sample) and the qualifying-to-race link walk-forward (the fastest-lap link starts from PR #82's `flpos`), with decision-log entries | Own | Simulated rates match history (pole-sitter wins about 59%, winner fastest lap about 33%, practice winner vs pole); paired Brier vs today's stand-ins; with the mode off, goldens and backtests byte-identical |
| S4 | Combos (built in PR #82: `markets/combos.py`, Lab job `f1_combo`) read the S3 sims when the mode is on | Implement | A win + pole combo priced from one weekend draw; mode off: PR #82's behaviour unchanged |
| S5 | NASCAR stage winners and qualifying (results already ingested) | Implement | Stage kinds price from the race sims and settle from stored stage results |
| S6 | MotoGP sprint and qualifying (probe the source from the Mac first) | Own | Sprint results ingested; sprint and race priced |
| S7 | Store the starting grid so `race_biggest_mover` settles | Implement | The kind settles on R16 |

Cycling stages and IndyCar sessions stay out until those sports have models.
