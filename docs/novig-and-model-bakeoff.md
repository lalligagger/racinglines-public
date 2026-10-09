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
| C | Plackett-Luce | Ranking likelihood over classifications (`choix`, per `docs/f1-reference.md`) | No (E7) |
| D | Market-implied strengths | Strengths fitted to exchange prices | No (E7) |
| 0 | Learns-nothing control | Uniform or prior only | Yes (global with a heavy prior) |

- **Same events, same cutoffs, same kinds:** F1 2024–26, NASCAR and MotoGP 2026, downhill 2021–26, scored on
  win, podium, top 10 and head-to-head; log loss and Brier, **paired by event with ±2 standard errors** (the generic
  `eval compare` of E5, built on the E4a prediction records).
- **Two scoreboards:** accuracy (the above), and money: each algorithm's prices against the recorded Kalshi and
  Polymarket tapes through the existing replays, because the F1 `gbm` model lost on accuracy but made money as maker
  profile K.
- **Golf** would be a fourth sport only if the owner wants a Novig model; it needs a data source probe first.

**Owner decisions:** (1) Novig: option 1, 2 or 3 above. (2) Build E5's generic `compare` first (Implement, Sonnet,
on the E4a records), then C (Plackett-Luce) as the first new algorithm (Own, Opus), then D? (3) Is golf in scope?
