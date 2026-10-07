# F1 roadmap

A phased plan for extending the F1 model and market-making tools, written for a
coding agent and the people reviewing its work. The concepts and links behind
each phase are in the [F1 reference](f1-reference.md). What already exists is
documented in [Formula 1](f1.md), [Market making](market-making.md) and
[Testing](testing.md).

Phases are named **F1-0 … F1-9** so they don't collide with the platform
phases in [Project history](history.md) (data layout, one package, sport
schemas). Each phase starts only after the owner confirms it.

**Priorities across everything, F1 phases included, are on the
[Roadmap](todo.md#priorities).** The top priority this week is the
[F1 live test](f1-live-roadmap.md) (round 16, 2–4 Oct 2026), part of F1-8.

## Ground rules

### 1. The baseline stays in place

The current `position_sim` model is the baseline and stays the default until a
challenger beats it under the promotion rule below.

- **Every new behavior ships behind a switch that defaults to today's behavior.**
  With the default, every existing stage produces the same output, and the
  existing golden files still pass untouched.
- **Challengers plug into the existing pricing path.** Anything that prices a
  race goes through `position_sim.pricing.price_race` and reads data through
  `Measurements.view(cutoff)`, so it inherits the as-of cutoff and
  `assert_no_leak` for free. No second pricing path.
- **Nothing is renamed or moved.** No existing module, function, CLI command,
  table or config value changes name or location.

### 2. No arbitrary code changes

A change belongs in a phase only if it does one of these:

- closes a measured gap (listed in the [reference](f1-reference.md#starting-point-what-the-baseline-already-does));
- is required by a phase's deliverable;
- fixes something that is broken.

Refactors "while you're in there" are out of scope. If one seems necessary, add
it to the Decision Log with the reason and wait for approval.

### 3. Structural changes: the complete list

These are the only structural changes this roadmap makes. Anything else needs a
Decision Log entry and approval first.

| Change | F1 phase | Why it's needed |
| --- | --- | --- |
| Add `f1-roadmap.md` and `f1-reference.md` to `mkdocs.yml` nav | 0 | The docs site is how docs are read; two nav lines under Background, no other doc moves |
| A `racinglines f1 compare RUN_A RUN_B` command | 1 | The paired ± 2 SE tables are the promotion rule's evidence; until now they came from one-off scripts |
| Sport schemas `sports/*.yaml`, read by existing code | platform (between 0 and 1) | The owner's goal that sport differences live in configuration. **Additive only:** nothing moves or is renamed, and every golden file stays unchanged |
| Optional dependency extras for LightGBM (and later PyMC/NumPyro) | 2, 6 | Keeps `racinglines check` and the regression suite runnable without heavy packages. Not added to the pinned `requirements.txt` unless a challenger is promoted |
| A finishing-model switch inside `position_sim` (default: the current ridge) | 2 | A challenger must use the same inputs, simulation and pricing to be a fair comparison and to inherit the leakage guards |
| New files inside existing packages (e.g. `position_sim/finishing_gbm.py`) | 2–4 | New code sits next to the code it extends; no new top-level packages |
| New model family `racinglines/models/rank_logit/` | 6 (optional) | A different kind of model (fit on finishing orders, sampled with Gumbel-max) that doesn't belong inside `position_sim`. It must feed the same pricing path; if no clean seam exists, propose the smallest one in the Decision Log before coding |
| New venue package `racinglines/markets/kalshi/` | 9 (was 5, optional) | Kalshi lists F1. Mirrors `markets/polymarket/` and registers in `markets/venues`; order placement behind a flag, off by default |
| A settings schema (`pipelines/sweep_settings.py`), strategy profiles (`pipelines/profiles.py`) and the signal engine (`pipelines/signals.py`, `racinglines f1 signals`) with tables `strategy_signals` and `paper_positions` | 8 | Paper trading must run the backtest's own code on live data, and any combo found must be recreatable. New files and tables only; defaults reproduce the old sweep exactly |
| New source `racinglines/sources/openf1/` | 7 (optional) | Only for in-race trading, which needs a live feed; FastF1's archive arrives after sessions end |

### 4. Tests must keep passing

Before starting, build the fixtures and write your local golden baseline:

```
python -m pytest -m "not live"            # fixtures and goldens are pinned in git (scripts/fetch_test_fixtures.py --refresh rebuilds them)
```

For every change:

- Run `racinglines check`. Then run `python -m pytest -m "not live"`; it must
  pass against the **unchanged** golden files. Run `python -m pytest` too when
  the live database is available.
- Put new behavior in **new tests with their own golden files**
  (`tests/golden/<new_stage>.json`), built on the existing fixtures where
  possible.
- If new fixture data is needed, add a new flag to `scripts/fetch_test_fixtures.py`.
  Never change what `--f1` or `--mtb` produce.
- Tests that need an optional package start with `pytest.importorskip(...)`, so
  the suite still passes without it.
- Extend `racinglines/testing/synthetic.py` additively, so the quick check also
  covers new code where that's practical.
- Every new pricing or trading path gets a **leakage rule test**: inject data
  after the cutoff and expect `LeakageError`, or check that the quote doesn't
  change (the `PublicView` pattern in `tests/test_replay.py`).
- `tests/test_no_data_in_git.py` must keep passing. Fixtures and golden files
  stay local.

`UPDATE_GOLDEN=1` is allowed only in a promotion change (below). The stages
that change must be exactly the ones downstream of what was changed, as in the
table at the end of [Testing](testing.md#stages-covered).

### 5. Promotion rule: when a challenger becomes the default

All of these, in one change:

1. A full backtest (`racinglines f1 backtest --save`) of challenger vs baseline
   over every race, with paired differences ± 2 standard errors at each pricing
   stage.
2. Better on the target metric by more than 2 SE, and no market type worse by
   more than 2 SE at any stage.
3. The season sweep re-run with the challenger (pricing is cached, so this is
   quick).
4. Results tables added to [Formula 1](f1.md#results) in the existing style
   (differences are new − old, negative is better).
5. A Decision Log entry.
6. `UPDATE_GOLDEN=1 python -m pytest` in the same change, with the changed
   stages listed in the commit message.

Market-making settings follow the project's own rule: **no tuning on one
event.** Tune only after the replay has run across every race with a recorded
tape.

### 6. Keeping the docs current

- **Built features** are documented where they already live: [Formula 1](f1.md)
  for the model, [Market making](market-making.md) for trading,
  [CLI reference](cli.md) for new commands or flags. Match the existing style:
  short sentences, tables, ± 2 SE.
- **The [Roadmap](todo.md) is the task list** and sets the priorities. Phases below
  point at its items rather than copying them. Tick items there when done, and add
  new ones there.
- **This file:** update each phase's Status, and add Decision Log rows. Never
  delete a row; add a new one that supersedes it.
- **[F1 reference](f1-reference.md):** when work changes the understanding
  behind an idea (a knob mattered, a strategy didn't work), update the section
  and its changelog.
- **Project history:** add a line to [history](history.md) when something ships,
  following that page's existing format.
- **README:** if headline numbers change, run `python scripts/build_readme.py`.

## Phases

Phases are ordered by the measured gaps they close. Each one lists its target
gap, what it changes, and what "done" means.

### F1-0: Docs integration and baseline check

**Status:** done 2026-09-26 · **Behavior change:** none

- ~~Add both pages to the `mkdocs.yml` nav.~~ Done: under Background. The
  pre-push hook (`scripts/hooks/pre-push`) runs `mkdocs build --strict`.
- ~~Build fixtures and write the local golden baseline.~~ Done: 20 golden files;
  `racinglines check` 21/21, `pytest` 118 passed.
- ~~Record the reference runs in the Decision Log.~~ Done: backtest run 115,
  sweep run 191, season strategy run 113.
- ~~**Read-only check:** does `racinglines/markets/polymarket/trade` sign
  CLOB V2 orders?~~ **No.** It uses the V1 `py-clob-client` (0.34.6).
  Polymarket's changelog says V1 SDKs and V1-signed orders stopped working on
  2026-04-28, and Python code must move to `py-clob-client-v2`. Logged as a
  separate fix (see the Decision Log and [Roadmap](todo.md#market-making)).
  Nothing is at risk meanwhile: trading is off by default, and read-only market
  data doesn't use the client.
- ~~**Operations:** make `markets record` run through every race weekend.~~
  Done: it runs as a LaunchAgent (`bet.racinglines.recorder`, see
  [CLI](cli.md#running-the-recorder-persistently)) that starts at login and
  restarts on exit. F1-4 depends on this recorded book depth.

**Done when:** docs build, suite green, reference runs logged.

### F1-1: Evaluation additions (report-only)

**Status:** done 2026-09-27 · **Target:** better measurement for every later phase

**Outcome:** `racinglines f1 compare RUN_A RUN_B [--reliability]` prints the paired
± 2 SE tables (Brier and log loss, which the backtest already recorded) and
calibration bins. Backtests now keep each driver's probabilities for this.
The sweep scores model vs Polymarket for every market kind. `racinglines f1
matrix` summarizes every variant × strategy. No existing golden file changed.

- Add log loss and reliability curves to the F1 backtest report, per market type
  and pricing stage.
- Model-vs-Polymarket Brier per stage: the season sweep already reports it
  for win and pole over 2026 (sweep run 191). Extend it to every market type.
- Add `racinglines f1 compare RUN_A RUN_B`: the paired ± 2 SE tables used in
  [Formula 1](f1.md#results). The Lab has no such comparison (the tables so far
  came from one-off scripts); it can show the command's output later.
- Keep the new metrics **out of existing golden fingerprints**. Write them as
  separate outputs with their own tests, so no existing golden file changes.

**Done when:** one command produces the comparison tables for two saved runs.

### F1-2: Finishing-model challengers (reference model A)

**Status:** done 2026-09-27; nothing promoted (owner: iterate first). Paper-trading profile A uses `gridq+pretrain+reset` through its settings · **Target:** gap 1 (win after qualifying loses to grid-only) and gap 2 (pre-practice regression)

**Outcome** (tables in [Formula 1](f1.md#model-variants-f1-roadmap-f1-2-f1-3)):

- step 1, `grid`: closes gap 1 after qualifying but is worse before it;
  `gridq` (the term only once the grid is known) keeps the gain with no loss;
- step 2, `pretrain`: closes gap 2;
- step 3, `gbm` (run 665): worse than baseline (teammate h2h at every stage;
  podium and win log loss before and after qualifying), so not promoted;
- `gridq + pretrain` meets the backtest half of the promotion rule;
- follow-up, `reset` (run 837): better in new-regulations seasons, including
  2022; `gridq + pretrain + reset` (run 854) is the most accurate combination.
  Not promoted (owner: iterate first).
- The `params-4h` cloud search (2025 and 2026) confirmed `gridq+pretrain+reset`
  as the taker's model (profile A) and found `gbm` best for the conservative
  maker (profile C), although `gbm` loses on accuracy.

Steps, cheapest first:

1. **Nonlinear grid term in the ridge** (TODO: "grid-position prior"): grid
   buckets or a spline, behind a config flag.
2. **Stage-specific training** (TODO: pre-practice got worse): train the
   finishing model on no-practice paces for pre-FP1 pricing, behind a flag.
3. **GBM finishing model** (`position_sim/finishing_gbm.py`, LightGBM as an
   optional extra), selected by the finishing-model switch. Same inputs as the
   ridge, monotone constraints on grid and pace gaps, and σ from out-of-time
   residuals so the simulation's spread stays comparable.

Each step is evaluated with F1-1's comparison. Promote a step only under the
promotion rule. Step 3 is skipped if steps 1–2 close gap 1.

**Done when:** each step has a comparison table in [Formula 1](f1.md#results)
and a Decision Log entry (promoted or not).

### F1-3: Simulation tail and props (reference model C1)

**Status:** model part done 2026-09-27; props priced for the live book 2026-09-28 (opt-in, `models/position_sim/props.py`), not yet mapped in the Polymarket sync · **Target:** gaps 3 and 4, plus unpriced prop markets

**Outcome:** `tail` (disrupted-race mixture + correlated retirements) is neutral:
no metric moves beyond 2 SE at any stage, so it isn't promoted. Props are
deferred (Decision Log).

All inside the existing simulator, each behind its own switch (default off):

- **Chaotic-race mixture:** per-circuit `p_chaos` from `laps` track status and
  the weather in `rounds.extra`, shrunk to the field average; inflated noise and
  DNF rates in chaotic runs.
- **Correlated DNFs:** a shared team DNF draw sized to the measured +0.11.
- **Prop pricing:** safety car, red flag and rain probabilities per circuit from
  the same history. Add new prediction kinds and map them in the Polymarket
  sync's classifier.

**Done when:** comparison tables for top-scoring constructor, top 10 and
head-to-head, plus a calibration check for the props.

### F1-4: Maker inventory and timing (reference strategies 1 and 3)

**Status:** done 2026-09-27, except the queue model, liquidity rewards and Kelly caps; tuned in the `params-4h` search · **Target:** gap 5 (pre-qualifying inventory, adverse selection)

**Outcome:** the maker options and the stage-aware taker are in the sweep, with
rule tests. Results are in the [model × strategy matrix](market-making.md#model-strategy-matrix).
None of the maker options beats the default maker, and the stage-aware taker's
gain is in-sample.

Everything goes into the existing maker replay as options. Today's settings
stay the default, and `tests/test_replay.py` keeps passing unchanged.

- **Queue model on recorded book snapshots** (TODO), as a third fill rule next
  to touch and through.
- **Inventory skew with an Avellaneda-Stoikov-style option:** skew grows with
  time to the *next information event*, not just to resolution.
- **Pre-qualifying flatten or hedge** (TODO), with a configurable target.
- ~~**Pull windows for every session type.**~~ Already the case: each replay
  stage ends at the next session's start (practice included), and quotes are
  pulled 15 min before it.
- **Markout-driven widening:** use `markout_60m` per market type and stage as an
  input, not just a report.
- **Polymarket liquidity rewards** in replay P&L as a separate line.
- **Optional:** fractional-Kelly caps as an alternative to fixed share limits.
- **Stage-aware taker** (reference strategy 3, for the weekend taker): stop
  re-trading after FP3 and qualifying. In sweep run 191, trades after FP1, FP2
  and the sprint made +$1,944, while trades after FP3 and qualifying lost
  −$2,353. Judge it on events after Baku, not by tuning on these.

**Precondition for tuning:** the replay has run across every race with a
recorded tape. Met 2026-09-27: every 2025 and 2026 weekend with a Polymarket
tape, searched over 1,161 settings combos in the cloud (`params-4h`, see
[Cloud sweeps](cloud-sweep.md)); tuned on 2026, confirmed on 2025. The
queue model waits for recorded book depth (F1-8 collects it).

**Done when:** each option has rule tests (in the style of `test_replay.py`) and
a sweep comparison against the current defaults.

### F1-5: Linked-market quoting (reference strategy 2)

**Status:** deferred (unchanged 2026-09-27) · **Target:** the "re-quote linked markets" TODO

**Why deferred:** the model's prices are coherent by construction (one
simulation), and between pricing stages our fair values don't move, so "re-quote
when one book moves" would mean pricing from market data, which the project
rules out. What's left is hedging a fill in a more liquid linked market, which
needs order-book depth to replay honestly: recorded from 2026-09-26 on
(`markets record`). Revisit once several weekends of books are recorded.

- Coherence checks across win / podium / head-to-head / constructor from the
  simulation's joint output, reported alongside the existing group-sum check.
- In the replay: re-quote all linked markets when the model or one book moves;
  optional hedge into the more liquid leg with a leg-risk timeout.
- **Optional second venue:** only after confirming another venue lists F1 with
  real depth and compatible resolution rules. Store resolution rules per market
  and refuse to treat markets as linked if they differ.

**Done when:** replay comparison shows whether linked re-quoting helps, across
all recorded tapes.

### F1-6 (optional): Plackett-Luce challenger (reference model B)

**Status:** not started · **Start only if** F1-2 and F1-3 leave a gap, or per-market
uncertainty is wanted for maker spreads

- `racinglines/models/rank_logit/` with PyMC or NumPyro as an optional extra.
- Output feeds the same pricing path (see the structural-changes table).
- Judged as a challenger under the promotion rule, or used only as a per-market
  uncertainty input for F1-4 spreads.

### F1-7 (optional): In-race trading (reference model C2)

**Status:** out of scope · **Start only if** the owner decides to trade during
races

- Needs a live source (`racinglines/sources/openf1/`) and a lap-level simulator.
  Both are new capabilities; nothing existing changes.
- Race-time pricing still goes through an as-of cutoff, with the same leakage
  tests.
- **No new live order path by default.** Replay first, and any live trading
  requires the owner's explicit approval.

### F1-8: Live paper-trade validation (Polymarket)

**Status:** built and scheduled for Polymarket; waiting for a venue to list a race. Since 2026-09-29 also built for Kalshi (signal engine `venue` setting, PR #34; `f1 reconcile`, PR #37; `f1 scorecard`, PR #28; championship sleeve, PR #29); the first live weekend is round 16.
Polymarket has listed none since round 15 (28 Aug 2026). Since 2026-09-28 the phase runs on
**every venue that lists** (Kalshi via F1-9, pulled forward), judged by the pre-registered
[validation plan](paper-trading.md#validation-plan); calendar on the [Roadmap](todo.md#race-weekends-to-31-december) · **Behavior
change:** none to pricing or the backtest; recommendations and paper fills only

**Built** (2026-09-27): the signal engine (`racinglines f1 signals`, run by the
LaunchAgent `bet.racinglines.signals` every 5 minutes) prices each stage as its
session data arrives, with the backtest's own code, and records each profile's
recommendations and paper positions. Profile **A** (update taker,
`gridq+pretrain+reset`, min edge 0.10, 0.05 on head-to-head, no pre-weekend
stage) runs for the demo taker; profile **C** (conservative maker on `gbm`,
5-pt disagreement filter, 25-share quotes) for the demo maker.
`scripts/signals_parity.py` checks that a replay of the engine equals the sweep's
trades on a past weekend (2026 round 15: 11 of 11 taker trades and the maker's
15 fills identical). No order is placed (`POLYMARKET_TRADING_ENABLED` unset).
Details: [Paper trading](paper-trading.md).

To do (items in [Roadmap](todo.md#paper-trading)):

- Run A and C live on every weekend Polymarket lists, through 2026 and into 2027.
- After each weekend, compare live paper fills and markouts with the backtest's
  replay of the same weekend under the conservative "through" fill rule; log the
  markouts.
- Walk-forward re-run of A, A-lite, C, B (#06) and A′ (#08) with rounds 16–17 added.
- Bankroll-aware sizing and a deployed-capital cap per account.

With no Polymarket markets for round 16 (the Bahrain GP at Sepang, 2–4 Oct 2026), its first live F1 test
is a mock private book on all of Polymarket's usual race markets, updated at session ends, as trialled on
the Whistler downhill final: [F1 live test](f1-live-roadmap.md).

**Done when:** 4–6 live weekends are logged and compared with the backtest, and
the owner has decided on sizing (e.g. A-lite → A). Real orders need F1-9's CLOB
V2 item and the owner's explicit approval.

### F1-9: More exchanges (Kalshi, others)

**Status:** built (2026-09-29, PRs #26, #27, #34–#37, #41, #44): Kalshi connector run against the live read-only API (2026-09-28, `markets/kalshi/`); F1 history for 2025 and 2026 pulled and archived in `data/archive/markets/kalshi/` ([Data changes](data-changes.md)); the maker replay, the sweep and the taker signals all read it (`venue = kalshi`); tape-only NASCAR, MotoGP and IndyCar syncs (U9, fixture-tested); OG.com added as the first schema exchange (`exchanges/og.toml`, read-only). Open: the Kalshi recorder on the VM (U2), the first live run of the U9 tapes, and freezing profile K · **Pulled forward** (2026-09-28): the Kalshi recorder and Kalshi paper signals (Roadmap U1, U2, U5) come before F1-8's first live weekends, since Kalshi may be the only venue listing races this year

- **Kalshi connector** in `racinglines/markets/kalshi/`, mirroring
  `markets/polymarket/`: markets and resolution rules, prices, trade tape, and
  order placement behind a flag (off by default). Registered in `markets/venues`,
  so the sweep, signals and the Markets page read it like Polymarket.
- Store each market's resolution rules; never treat markets on two venues as
  linked when the rules differ.
- **Polymarket CLOB V2:** migrate `markets/polymarket/trade.py` to
  `py-clob-client-v2` before any real Polymarket order (see F1-0).
- Other exchanges only if they list motorsport or cycling with real depth.

**Done when:** Kalshi's F1 markets replay in the sweep and appear in paper
signals, with leakage-rule tests like Polymarket's.

**Met 2026-09-29** (PRs #34, #41): Kalshi's F1 markets replay in the sweep and appear in paper signals. Exchange coverage by sport: [Coverage](coverage.md).

## Decision log

| Date | Phase | Decision | Why | Supersedes |
| --- | --- | --- | --- | --- |
| 2026-09-26 | — | Roadmap aligned to the existing repo; `position_sim` is the baseline and stays the default | Avoid parallel pipelines; keep the golden suite meaningful | — |
| 2026-09-26 | 0 | Reference runs: backtest 115 (129 races, three stages), sweep 191 (2026 rounds 1–15, practice prior), season strategy 113 | The sweep was re-priced with the practice prior after the roadmap was drafted; run 96 is superseded | — |
| 2026-09-26 | — | Phases renamed F1-0 … F1-7 | Avoid confusion with the platform phases in the project history | — |
| 2026-09-26 | — | Platform phase 3 (sport schemas) is additive only, scheduled between F1-0 and F1-1 | Owner's decision: keep schema-driven sport differences without breaking the "nothing moves" rule | — |
| 2026-09-26 | 1 | Add a `f1 compare` command; the Lab has no paired comparison to reuse | The promotion rule needs repeatable ± 2 SE tables | — |
| 2026-09-26 | 4 | Add the stage-aware taker to F1-4 | Sweep run 191's stage split is the clearest measured taker gap | — |
| 2026-09-26 | 0 | Order signing is V1 and broken on production. Fix separately: migrate `trade.py` to `py-clob-client-v2`, with dry-run tests, before anyone enables trading | Polymarket changelog: no V1 compatibility since 2026-04-28. Kept out of F1-0 (read-only check) | — |
| 2026-09-26 | 0 | Market recorder runs as a LaunchAgent (KeepAlive, 60 s restart throttle), logging to `data/runs/logs/record.log` | A plain background process doesn't survive a reboot; F1-4 needs continuous book depth | — |
| 2026-09-26 | 0 | F1-0 done | Docs build, suite green (118), reference runs logged | — |
| 2026-09-27 | platform | Sport schemas are TOML (`sports/*.toml`), read with the standard library; the registry, both models, the sweep and the venue matrix take their constants from them | No new dependency (no YAML library is installed); constants proved identical before and after, goldens unchanged | the YAML plan |
| 2026-09-27 | 1 | Variant switches live in `model.py` (defaults = baseline) and are named in `variants.py`; `--variant` on the `f1` command; stored sweep stages, season forecasts and runs record their variant; the web app reads baseline runs only | One pricing path; a variant's cached pricing is never mixed with another's | — |
| 2026-09-27 | 2 | GBM uses scikit-learn's HistGradientBoostingRegressor instead of LightGBM | Already a dependency (no optional extra needed); supports monotone constraints and sample weights | the LightGBM extra |
| 2026-09-27 | 2 | `gridq` added after seeing that `grid` hurt when the grid is simulated | Restricting the term to known grids is the principled reading; flagged as a choice made on this data | — |
| 2026-09-27 | 2 | Recommend promoting `gridq + pretrain` (run 423 vs 193: better at every stage it touches, worse nowhere) | Meets the backtest half of the promotion rule; promotion changes live prices, so it waits for the owner | — |
| 2026-09-27 | 2 | `gbm` not promoted (run 665 vs 193: worse on teammate h2h at every stage, on podium and win log loss before and after qualifying; better nowhere) | Fixed settings, no tuning; the ridge with `gridq` already captures the front-of-grid curve | — |
| 2026-09-27 | 3 | `tail` not promoted | Neutral at every stage (no metric beyond 2 SE) | — |
| 2026-09-27 | 3 | Prop markets (safety car, red flag, rain) deferred | No strategy trades them yet, and calibrating them needs the prop markets' history mapped in the sync classifier; the per-circuit rates now exist (`race_disruption`) | — |
| 2026-09-27 | 4 | Maker options chosen a priori (flatten fully before qualifying at mid ± 1¢; info skew ×(1 + 2·e^(−t/2h)); 1.5× half-spread on kinds with negative cumulative 60-min markouts in earlier weekends) | No tuning on the 2026 sweep | — |
| 2026-09-27 | 4 | Queue model, liquidity rewards and Kelly caps deferred | No historical book depth or reward data for the 2026 weekends; Kelly caps are optional | — |
| 2026-09-27 | 5 | F1-5 deferred | See the phase: coherent by construction; hedging needs recorded depth | — |
| 2026-09-27 | 2 | Owner: no promotion or default change for now; keep iterating on the variants and combos | Owner's decision | — |
| 2026-09-27 | — | Championship checkpoints (`f1 season-checkpoints`): enter pre-season, after 3 and after 6 GPs (owner's choice), hold, score each over the next 3 GPs and to date with P&L, drift toward our fair value and the edge-closing slope | The update-every-race strategy mostly measures reaction speed; fixed entries and equal windows compare models without picking the windows after the fact | — |
| 2026-09-27 | 2 | `reset` variant: in a new-regulations season (`sports/f1.toml` `[regulations] resets`), earlier seasons' car pace weighted ×0.25 | The 2026 checkpoints showed the car-pace layer carrying 2025 over (McLaren 84% pre-season). The weight is set a priori, and it's judged on 2022 too, since the idea came from 2026 data | — |
| 2026-09-27 | — | `users.prefs` (nullable JSONB, migration `5b1e0c7d2a41`) for the Lab's Edge Finder combos and last-used job knobs | Owner: settings follow the account; the database is the source of truth for history and setup, the browser only for view state. Additive column | — |
| 2026-09-27 | — | Owner: the repo is private; a minimal data set is committed (FastF1 raw files, the Polymarket prices/trades archive, cloud search results), allow-listed in `.gitignore` and `tests/test_no_data_in_git.py` | Cloud sweep sessions clone the repo and can't be copied into; the owner preferred this over a storage bucket. Remove from history before any public release | the "zero data in git" rule |
| 2026-09-27 | — | 2025 Polymarket markets synced (`pm-sync --closed`): 2025 title formats ("F1 X Grand Prix Winner", "– Pole Winner", "Which Constructor scores the most points?", "Head to Head Matchups") and Grand Prix name aliases (Brazilian → São Paulo, …) added to the classifier, after the 2026 forms | 2025 is the held-out season for everything built on 2026. Every stored 2026 title classifies exactly as before (checked) | — |
| 2026-09-27 | — | Cloud sweeps: `racinglines f1 search` runs a queue of sweeps in parallel and re-reads the queue so an agent can steer it; protocol in [Cloud sweeps](cloud-sweep.md), with a held-out-season rule for anything tuned | Long unattended searches overfit 15-24 weekends unless tuning and confirmation use different seasons | — |
| 2026-09-27 | — | One settings schema (`racinglines/pipelines/sweep_settings.py`) drives the sweep flags, the Lab's Edge Finder sweep form, search queues and saved params; stage prices are cached by model settings + the data each stage saw | Owner: any combo found must be recreatable in the Lab; defaults reproduce the old sweep exactly (checked, zero differences) | the four taker knobs |
| 2026-09-27 | — | Searches: 2026 (every raced weekend) is the primary window; 2025 is "live from its first race", a secondary, stable-rules window; each season's default baseline runs in every search on the same data; the cloud agent may add new switches in code under the ground rules | Owner's choices; results labelled robust / 2026-specific / not better | — |
| 2026-09-27 | — | All HTTP data sources paced per host and retried with backoff (`racinglines/sources/http.py`); FastF1 keeps its own limiter | Owner: respect API limits; two Polymarket timeouts during the 2025 download | ad-hoc retries |
| 2026-09-27 | 4 | `min_edge_h2h`: a separate minimum edge for head-to-head markets (empty = same as `min_edge`); unset optional settings are left out of the settings hash | With it, A makes +$1,243 in 2026 and +$1,363 in 2025 (+$1,232 / +$1,237 without). Leaving unset optionals out keeps every earlier run's key, so cached stages and saved runs still match | — |
| 2026-09-27 | 8 | Paper-trading defaults: profile **A** (update taker, `gridq+pretrain+reset`, min edge 0.10 / 0.05 h2h, no pre-weekend stage) for the demo taker, profile **C** (conservative maker, `gbm`, max disagreement 0.05, 25-share quotes) for the demo maker; live from round 16 of 2026 | The only two `params-4h` candidates profitable in both 2025 and 2026 with small drawdowns. Recommendations and paper fills only; the signal engine reuses the backtest's code, checked by `scripts/signals_parity.py` | — |
| 2026-09-27 | 8 | Demo accounts' history is evidence-driven: weekends before live paper trading are backtest replays (flagged `detail.backfill`), and the maker's strategy switches follow a fixed rule on walk-forward Edge Finder evidence (`pipelines/story.py`) | A demo track record must be reproducible and must not use hindsight; labelled as a replay in the app | — |
| 2026-09-27 | — | Web routes renamed to match their pages (Markets, Strategy, Positions, My Book, Lab); every old URL redirects (`web/legacy.py`) | A page's name and its URL should agree; redirects keep bookmarks and links working | the old routes |
| 2026-09-27 | — | Cloud runs load a database snapshot (`racinglines db snapshot-export` / `snapshot-import`, `data/archive/db/`) plus exported market links, prepared by `scripts/cloud/prepare.sh` | An exact replica (same ids, same prices) makes cloud results identical to local ones and needs no network beyond PyPI and GitHub | `f1 ingest` + `pm-sync` on the VM |
| 2026-09-27 | 9 | New phases F1-8 (live paper-trade validation) and F1-9 (more exchanges); the Kalshi package moves from F1-5 to F1-9 | Trading on any exchange only after paper-trade validation; Kalshi lists F1 | the Kalshi row under F1-5 |
| 2026-09-28 | 8 | Order signing moves to CLOB V2 (`py-clob-client-v2==1.2.0`); V1 client removed. Dry runs sign with the local order builder (V2 struct, domain version `POLYMARKET_ORDER_VERSION`, default 2), no network; live orders ask the CLOB for its version | V1 orders stopped working on 2026-04-28, so there is no working behaviour to keep behind a switch. The client’s `create_order` calls the CLOB for the tick size and version even in a dry run. Not verified against the live CLOB: no order sent | the V1 client |
| 2026-09-28 | 8 | Bankroll-aware sizing and a deployed-capital cap are optional sweep settings (`bankroll`, `max_deployed`, unset = today’s fixed sizing). The taker is now a per-market stepper (`taker_weekend._Market`); with a cap, markets are stepped in time order and buys over the cap are cut to fit | Default results identical to the old taker on 2,400 random synthetic weekend × parameter combinations, and the 2026 sweep reproduces +$1,874.01 for the stage-aware taker. Choosing a rule waits for live weekends | — |
| 2026-09-28 | 2 | A Monte Carlo seed setting (`seed`, a model setting, unset = today's fixed 42) for the sweep, the search and the signal engine's profiles | A search's noise replicates re-ran the same draw; independent seeds show whether a winner is noise. Unset leaves every model key, cached stage run and price unchanged (pinned in the tests) | — |
| 2026-09-28 | 3 | Props priced outside the simulator (`models/position_sim/props.py`): safety car, red flag and rain as per-circuit rates shrunk to the field rate (prior 16 races), fastest lap from the stage run's finishing odds × how often each finishing bucket set it; listed in a live book only when its `[live.markets] kinds` names them | Walk-forward on 2022–2026 (107 races, `f1 props --check`), per-circuit rates don't beat the field rate within the noise (Brier: safety car 0.2535 vs 0.2525, red flag 0.1128 vs 0.1113, rain 0.1754 vs 0.1765, SE ≈ 0.013–0.02), and lighter shrinkage (4) was worse; the prior was picked on the same data. Fastest lap isn't calibrated yet: it needs stored stage runs for past races (the bucket's dump). The sync classifier still leaves Polymarket's prop markets unmodeled | the simulator-based props |
| 2026-09-28 | 9 | Kalshi connector (`markets/kalshi/`) writes the same tables as Polymarket (`market_links` with `exchange='kalshi'`, one row per market's YES contract; `market_trades`, `market_price_history`, `market_book_snapshots`), keeps each market's rules in `params.rules`, and gates orders like Polymarket (post-only, a notional cap, `KALSHI_TRADING_ENABLED`). Built early at the owner's request | Owner asked for it (2026-09-28). The cloud network blocks Kalshi and there are no credentials, so it's tested on mocked responses shaped like the API docs; the title wording, series tickers and field names need checking against the live API before anything reads it | — |
| 2026-09-28 | 4 | The maker replay's positions table keeps its columns when a weekend has no markets of the chosen kinds, so it summarises to a zero total | The fix for the h2h-only crash on 2025 (no h2h markets before round 8). Weekends with markets are unchanged; rounds 8–9 h2h-only run end to end on the bucket's database | — |
| 2026-09-28 | 4 | The stage-aware taker stays a flagged, in-sample reference strategy; no profile adopts it | Out of sample on 2025 it lost $316 over 23 weekends (+$1,874 in-sample on 2026); 2025's best update-taker stage was after qualifying, the stage it skips | — |
| 2026-09-28 | — | Proposed Google Cloud shape: Cloud SQL + Cloud Run (one image, a service for the web app, jobs for the recorder, signal engine, live events and sweeps) + Scheduler, the bucket mounted as the data root, IAM database login, no service-account keys | Scales to zero between race weekends; every piece is already a CLI subcommand; `RACINGLINES_DATA` already moves the data root. A proposal: nothing built | a VM running today's LaunchAgents as cron jobs |
| 2026-09-28 | 2 | New variant `rookie` (`model.ROOKIE_CARRY`, off by default): a finished rookie season's teammate comparisons count 0.25 in the driver offsets, for both drivers of the team-event; drivers already in the data's first season aren't treated as rookies | The weight is set a priori, like `reset`'s. Judged on all 129 races and per season (runs 1288, 1289): win odds improve before qualifying, teammate h2h better in 2026 and worse in 2021, so not promoted | faster forgetting for every driver (a shorter driver half-life), not tried |
| 2026-09-28 | — | Downhill points tables per era live in `points_schemes`, entered from a TOML file (`sports/points/uci_dhi_wc.toml`); the model reads them only with `--points db`, by setting the three table globals per season (`points.use`) | No plumbing through every function, and the default path is untouched. Placeholders stay marked (`official = false`) until the owner enters the UCI scales; committed standings are TOML because git ignores CSVs | a points argument threaded through the season and weekend functions |
| 2026-09-28 | — | Downhill UCI IDs: a separate `uci_id` field and a `uci` athlete identifier matched first; the parser's `rider_id` stays name-based; existing duplicates are merged by an explicit command, never automatically | Old files and today's model inputs stay identical; a merge changes history, so the owner runs it | switching `rider_id` to `uci:<id>` in the parser |
| 2026-09-28 | 8, 9 | Strategy to the end of 2026 ([Strategy 2026](strategy-2026.md)): real markets first on any venue (T1), tapes of unmodeled sports recorded (T2), private books only where no venue lists (T3). Kalshi work pulled ahead of F1-8's first weekends; A and C frozen to 31 Dec; a Kalshi-tuned maker K chosen by its own sweep; validation rules pre-registered in [Paper trading](paper-trading.md#validation-plan) | Polymarket has listed no race since 28 Aug; C loses on Kalshi's 2026 tape (−$119) while it earns on Polymarket's (+$653); the taker needs ~40 live weekends to prove, the maker ~17 | F1-9 "start after F1-8's first live weekends" |
| 2026-09-29 | 9 | Kalshi maker profile K chosen by its own sweep on Kalshi's tape: `gbm`, 2¢ quotes, `max_disagree` 0.10, 25 shares, `maker_min_volume_24h` 400. 2026 +$490, 2025 **+$659** (16k simulations: +$453 / +$741). Freezing is the owner's call | Held-out rule (2026 primary, 2025 confirm) and the 16,000-simulation confirmation; beats profile C by +$609 (2026) and +$150 (2025, within the noise). The first 2025 figure, +$855, missed Imola 2025 (Kalshi-only listing, −$195): sweeps now read the venue from the profile | the first K table, +$855 |
| 2026-09-29 | — | Sweeps run in grid mode (up to N sweeps of one season and model per process), the rating history is built lazily and can be cached, and `parallel` defaults to every core; Kalshi's maker and taker fees are defined once on the venue classes | The 106-job Kalshi search fell from 59 to 21 minutes with identical saved runs (checked to the cent) | one process per job |
| 2026-09-29 | 9 | Exchanges are schemas, not code: `exchanges/<code>.toml` read by one generic driver (`markets/exchange_driver.py`). OG.com is the first, read-only, off by default (`RACINGLINES_OG_VENUE`); its fair-price indicator is an indicator only, with no backtest (about a month of history, asks-only books at 1–4¢). Polymarket and Kalshi keep their own packages for now | Owner's standing principle (2026-09-29): a new venue should be a config file, not new code paths. The $0.02 fee is from reviews and is unconfirmed | — |
| 2026-09-29 | — | CLAUDE.md is the standing process note for Claude Code sessions: environments, model tiers, dev cycle (one thread per task), pre-merge checks, report format, safety rails | Owner asked for one place for how the sessions work; the domain lives here and in the Roadmap | — |
| 2026-09-30 | 8 | Three opt-in sweep settings from the Monaco 2026 Hadjar check (all unset by default, so every result and key is unchanged): `thin_edge_mult` (a taker trades a market under the volume floor when the edge is at least that many times the minimum and a recorded book, at most 10 min old, shows size at the touch; buys only, stake capped at that size), `market_kinds` accepts `race_top10` (Kalshi's top-10 finishers, a group of ten for the coherence check; not in the default set, taker only since the maker replay never modelled it), `coherence_tol_by_kind` (per-kind group tolerance over 0.25, e.g. `race_podium=0.35`). No default changes; a tuned value needs a search on 2025 and 2026 and its own entry here | Hadjar's Monaco podium markets (Polymarket 3.5c with $1-10 traded in the prior 24 h, Kalshi 2-7c with $15-44) failed the $50 volume floor at every stage, and the podium group sum failed the 25% tolerance at three stage/venue pairs; the floor cannot see whether a book had size. Owner asked for all three to be built (2026-09-30). The live `call` on the Markets page still applies the plain volume floor | — |
| 2026-09-30 | 9 | NASCAR / MotoGP taker replay (`racinglines nascar replay`, `motogp replay`; `pipelines/position_replay.py`), off by default, a separate path from the F1 sweep. A priori settings in `sports/<code>.toml` `[replay]`, none tuned: stages T-3d / T-1d / race eve (hours from 00:00 UTC on race day), the F1 taker's defaults (min edge 0.05, $250 per edge, $50 cap, 1¢ cost), the F1 volume floor ($50 / 24 h) and coherence tolerance (0.25) on race-win and top-3 groups only, model seed 7, the schema's `pricing_model` with its default settings. Kalshi's taker fee is reported and netted | No evidence yet on these sports, so nothing is chosen from their data; any change after the first replay needs its own entry and a held-out season, as the F1 rule. Top-5/10/20 listings are often partial, so their sums are not checked | — |
| 2026-09-30 | 9 | Owner: the new sports and exchanges are on by default. NASCAR's board columns are win / top 3 / top 10 and MotoGP's is win (`standard_kinds`); MotoGP's matcher is its `[identity]` resolver, so the Kalshi, Polymarket and OG.com syncs now fill rider, race and kind on MotoGP links (`prediction` stays `unmodeled`); `nascar replay` / `motogp replay` run on every exchange the sport lists by default (`--venue all`); their `--save` writes prediction records and sims unless `RACINGLINES_PREDICTION_RECORDS=0` | Owner's instruction, 2026-09-30 03:07Z. Still off: every F1 default and output (unchanged), the #81 switches (`thin_edge_mult`, top-10 as a traded kind, `coherence_tol_by_kind`), any tuned taker setting, the trading flags; `--save` still needs a fresh backup | the replay-only `[replay]` note of the entry above |
| 2026-09-30 | 9 | Bug fix, owner's call: the NASCAR and MotoGP recent-form weights (`recency_decay`) now run from e^-decay on the oldest race in the window to 1 on the latest; they ran the other way, so a driver's oldest result counted most. Changes every NASCAR/MotoGP walk-forward, search and replay price (no goldens pin them); F1 and downhill untouched | The owner: backtests of these sports are meaningless with the weights reversed. `recency_decay` keeps its default (2.5), still untuned; any earlier NASCAR/MotoGP search ranking is void | — |
| 2026-09-30 | 9 | Two more NASCAR / MotoGP model fixes before the backfill: (1) `MotoGPRace.load` reads the race round only (it joined every session the ingest stores, so practice, qualifying and sprint classifications counted as race form); (2) `history_races` keeps the last N races and team form averages the team's last `recent_races` races (each race's mean over its entries, recency-weighted), where both counted result rows (a two-car team's 6 "races" were 3) | Owner: the backtest must be right before the overnight backfill. Changes NASCAR/MotoGP prices only; `recent_races` and `history_races` keep their defaults, untuned | — |
| 2026-09-30 | 9 | The weekend taker replay pays the venue's taker fee (`TakerParams.taker_fee`, from `venue_replay.EXCHANGES`: Kalshi 0.07 × contracts × P × (1 − P) per order, rounded up to the cent; Polymarket 0) | Kalshi taker sweeps charged only the flat 1¢ cost. Polymarket's rate is 0, so every Polymarket result is unchanged (tested) | — |
| 2026-09-30 | 9 | Kalshi taker results are left out of every ranking until the replay fills at a tradeable price | Kalshi's stored price is each candle's last trade, and thin books print at extremes: 1.67% of Kalshi F1 points are 15+ points off their rolling median (5.6% on head-to-heads) against 0.06% on Polymarket. The taker buys at those prints (taker-resweep report, section 3). Needs a bid/ask re-pull from a machine with Kalshi access | — |
| 2026-09-30 | 8 | Taker re-sweep (`sweeps/taker-resweep.toml`, 212 sweeps, 16k confirmations): **A stays the core taker**; the Pro shortlist is T1-T10 (A and its nearest variants, and the stage-aware taker on A's settings), the recommended blend TB = A's update + stage-aware takers at half stake each (16k: 2026 +2,048, 2025 +989); Basic draws 3 of the 10 per account from a fixed seed. No default changes; PR #81's switches stay off (`thin_edge_mult` inert on history, podium coherence 0.35 within noise) | Held-out rule with a measured noise floor (update ±400, others ±700). Nothing beats A beyond noise in both seasons; volume floor 0 excluded (untradeable last prices); the blend was chosen on both seasons, so it has no held-out season | profile A as Basic's only strategy |
| 2026-09-30 | 9 | NASCAR Cup season forecast (`racinglines nascar season`, `models/nascar_season.py`), read-only and off by default (`RACINGLINES_NASCAR_SEASON=1`): the rest of the season from the points standings through the 2026 Chase (top 16 on points, reset 2100/2075/2065/2060/2055 then −5 to 2000, 10 races, no eliminations; 55 for a win), each race priced by the schema's `pricing_model`. A priori settings, none tuned: stage finishes = the race order re-drawn with N(0, 5 places), the one bonus point a race to the best of the order re-drawn with N(0, 6), 4,000 sims, seed 7, the race model's defaults except `noise`, which is measured (the SD of each finish around the driver's previous-6-race mean over the last two seasons) because the default 2.0 gave the points leader 94.6% on the Mac spot check against 40-55% on all three exchanges; the replay keeps 2.0 (an owner decision to change). Today's standings come from NASCAR's points feed when on disk (penalties, official seeds) | No season-market history to tune on yet; races are simulated independently (no form drift, no track types), which understates the spread, so the prices are an indicator, not a trading input. The bonus point's rule is inferred from the 2026 feeds. Any tuning needs its own entry | — |
| 2026-09-30 | 9 | Overnight VM run (106-job broad sweep at 4k, top 10 at 16k; report `reports/2026-09-30-overnight-vm-run/report.md`): **profile A stays the core taker**; no default changes. NASCAR × Kalshi taker grid: defaults stay (min edge 0.05, $50 floor), nothing tuned | Held-out rule, noise floor ±352: no setting beats A by more than that in both seasons (best 2026 gains `reset_weight=0.5` +400, gbm half-life 90 +405, both within noise or negative in 2025; best 2025 gain +222). NASCAR is +4.2k to +5.5k in 2026 (19-21 of 32 races up) but loses in every setting in 2025 (−242 to −390, 1-2 of 8 races up) on Kalshi last-trade prices: 2026-specific, not robust | — |
| 2026-10-05 | 3 | **Kalshi takers fill at the touch, by default.** On Kalshi a taker buys YES at the ask and sells at the bid (NO: buys at 1 − bid, sells at 1 − ask), plus `TakerParams.cost` (slippage beyond the touch) and Kalshi's taker fee; the edge each side needs is `fair − ask` (YES) or `bid − fair` (NO). The quote is the recorded order book when a snapshot is at most 10 min old (`venue_replay.Kalshi.BOOK_AGE`; books every 5 min on the VM since 2026-09-30), else the last hourly candle's closing bid and ask (`market_price_history.bid/ask`, backfilled 2025-01-01 to 2026-10-05), else the old rule (last trade ± cost). Applies to the sweep, the Lab and live signals on Kalshi; Polymarket and OG.com stages carry no quote and are unchanged | Owner's call (2026-10-05). The candle's last trade is not a price a taker could have had: 4.5 % of backfilled F1 hours have it outside the closing quote (median 1¢, up to 90¢ near settlement), and the old rule ignored the spread. The Kalshi taker results in [Kalshi history](kalshi-history.md) were computed under the old rule and are re-run on the VM after this change (`f1 sweep --venue kalshi`) | Kalshi taker fills at the candle price ± cost |
| 2026-10-05 | 8 | Rolling Kelly sizing is an optional sweep setting (`kelly`, a fraction; unset = today's linear sizing, so every result and settings key is unchanged). With `bankroll` set, a taker's stake is `kelly × (q − c) / (1 − c) × balance` at the touch, capped by `max_stake` × the bankroll scale and `max_deployed`. The search report adds P&L without the best two events and a shape label (steady / long-shot / loses; renamed steady / concentrated / mixed / losing on 2026-10-06, owner), and can rank at 16k (`rank_sims`). Queue `sweeps/strategy-review.toml`: every profile on Polymarket and Kalshi, half- and quarter-Kelly on $10,000 ($500 a market, $2,500 a weekend), and the every-kind variant. | The owner's strategy review (2026-10-05): profile A on Kalshi rested on two weekends a season, so every strategy is re-checked for long-shot vs steady before the next race weekend. Kelly is a sizing option for the review; no profile uses it until the results are in. | |
| 2026-10-06 | 8 | Strategy review ([Strategy review](strategy-review.md), 80 jobs at 16k on Polymarket and Kalshi, 2026 and 2025): **A (T1) stays the core taker; full size on Polymarket, small on Kalshi** until live weekends show its Kalshi edge isn't a few long shots; Kelly stays a review option, with quarter-Kelly preferred over half-Kelly if sizing ever moves to a bankroll. No default changes. | Polymarket T1 is steady (+1,375 / +1,432, still +112 / +350 without each season's best two weekends). Every Kalshi taker is concentrated or mixed: up in 2026 on Australia, negative in 2025 without its best two. Kelly totals come mostly from two compounding weekends and assume unlimited depth at the touch; QK T1 beats HK T1 in both seasons without the best two on Polymarket. | |
| 2026-10-04 | 3 | **Provisional.** New variant `fastlap` (`model.FASTEST_LAP`, off by default): the race simulation draws the fastest lap, the quickest classified car on race pace `rp` (with the simulation's pace shock) plus noise `FL_SIGMA` = 0.006 of a lap, `FL_RHO` = 0.3 of it shared by teammates; stored as `race_predictions.extra.fl_prob`, kind `race_fastest_lap` in `markets/kinds.py`, read by `db.reads.model_prob`, so Kalshi's `KXF1FASTLAP` links get a fair value from runs priced with the variant. Drawn on a side stream seeded from the main one without advancing it, so every other price is byte-identical with the switch on or off. No live config or profile turns it on | The owner wants the fastest lap from the core engine, not the history-based `props.fl_probs`. Both noise values are set a priori, not fitted: the race-pace surprise (≥ 0.3 %, `TEAM_DRIFT_SD`; teammate correlation +0.63) and a best-lap-vs-median term of the same size, in quadrature. A retired car never sets it, and no late fresh-tyre effect (no data for one here). **Uncalibrated:** score `extra.fl_prob` against Kalshi's resolved markets (`market_links.resolved_yes`, prediction `race_fastest_lap`) on the VM before the owner turns it on, with its own Decision Log entry | `props.fl_probs` as the fastest-lap price for these links (declined; the live props book keeps it) |
| 2026-10-04 | 3 | Kalshi's top 5 (`KXF1TOP5`) and biggest mover (`KXF1BIGGESTMOVER`) are priced from the race simulation: kinds `race_top5` (classified in the top 5) and `race_biggest_mover` in `markets/kinds.py`, stored by `position_sim` as `extra.top5_prob` / `extra.mover_prob` from the draws it already makes (no new randomness, every other output unchanged). Biggest mover: among the cars that finish, the largest gain from the simulated grid to the finish; nobody wins if no one gained; **every driver tied on that gain counts as YES**. Both kinds are left out of the default record and walk-forward sets (`Kind.default = False`) | The owner asked to link every market we can. Kalshi's rule says "the largest positive differential between their starting grid position and their finishing position" and doesn't say how a tie resolves; YES for each tied driver is the literal reading. The simulated grid is the qualifying order, so grid penalties and pit-lane starts aren't modelled, and a retired car is never the mover. **Unchecked:** neither price is scored against Kalshi's resolved markets yet, and our settlement returns no result for the mover (the results store no starting grid) | Leaving both unmodeled |
| 2026-10-06 | 3 | **Provisional.** Red flag and safety car given wet or dry (`models/position_sim/props.py`): a race is `wet` when any weather sample had rain (`rain_share > 0`, the `race_rain` rule); `rate_given` is the circuit's rate among its wet (dry) races shrunk to the field's wet (dry) rate, itself shrunk to the overall field rate (both with `PRIOR_N` 16); `rate_wx` = p_wet × wet rate + (1 − p_wet) × dry rate, with the circuit's shrunk wet share when no p_wet is given. `f1 props --check` adds `climatology` and `wet_oracle` (p_wet = the realised wet flag), and `--history <csv>` runs it without a database. **Nothing is on by default:** the live book keeps `rate()`; `market_set(..., p_wet=)` prices race_red_flag (`WX_KINDS`) with `rate_wx` only when a probability of rain is passed, which a weather forecast (`racinglines/weather`) will supply; the safety car is left on `rate()` after the numbers below | 2020–2026 history (147 races): red flags in 10 of 35 wet races, 12 of 112 dry. Walk-forward 2022–2026, 108 races, PRIOR_N 16, Brier (se): red flag circuit 0.1119 (0.0201), field 0.1105 (0.0203), climatology 0.1109 (0.0209), **wet oracle 0.1057 (0.0198)**, log loss 0.3872 → 0.3666; safety car circuit 0.2529, field 0.2518, climatology 0.2516, wet oracle 0.2575 (worse). Paired against circuit: red flag wet oracle −0.0062 (se 0.0045), climatology −0.0011 (0.0012); safety car wet oracle +0.0046 (0.0027). PRIOR_N 8 is worse for every shrunk method (the field rate doesn't use it). So a good rain forecast is worth something for red flags only (about 1.4 se, an upper bound), climatology adds nothing, and the safety car should stay on `rate()`. Lighter field-level shrinkage (2 races, tried ad hoc) changed nothing | — |
| 2026-10-06 | 3 | **Provisional.** Retirement kinds in `markets/kinds.py`, all `default=False` (summary, records and walk-forward unchanged): `race_retire` (1 − classified; settles True on DNF or DSQ, void on DNS or a driver absent from the results), `race_n_retirements` (DNF + DSQ over a line), `race_first_retirement` and `race_first_retirement_team` under a **uniform timing assumption**: the simulation draws who retires, not when, so every retiring car in a simulation is equally likely to be first out (P = mean of dnf / n_dnf, 0 when nobody retires); settled on a `laps_completed` column of the results frame (fewest laps among DNFs, ties all YES; None without it; NO for everyone when nobody retires). Owner (same day): `race_second_retirement` and `race_third_retirement` carry the same timing assumption (P = the first-retirement share in simulations with at least n retirements; settled by competition ranking on laps completed, so a tied place leaves the next one empty), and the team versions `race_team_any_classified` and `race_team_both_points` (n = 10) join `race_team_both_classified`. DNF calibration check: `f1 props --dnf-check <csv>` (`models/position_sim/dnf_check.py`) | Position simulation `dnf_prob`, live default variant gridq+pretrain+reset, latest as-of run per race with the qualifying order known, 829 rows, 40 races (2025-01 to 2026-16); 815 scored (10 DNS, 4 without a result left out). Mean predicted DNF 12.4 %, realised 13.5 % (2.52 vs 2.75 per race). Brier: model 0.1140 (se 0.0088), field rate (in-sample) 0.1168, race mean 0.1167; paired, the model beats both by 0.0028 (se 0.0017 / 0.0015). By bucket (n, mean p, realised): 0–5 % 31, 4.1 %, 3.2 %; 5–10 % 245, 8.3 %, 13.1 %; 10–15 % 384, 12.2 %, 9.9 %; 15–20 % 97, 17.0 %, 17.5 %; 20 %+ 58, 27.4 %, 37.9 %: slightly under-predicted overall and too compressed at the top. First retirement has no timing to test; it waits for laps completed in the results | — |
| 2026-10-06 | 3 | **Provisional.** Wet-race forecast into the props (`racinglines/weather/wet.py`, [Weather: wet-race forecast](weather.md#wet-race-forecast)): seven Open-Meteo global models each vote wet when they forecast ≥ 0.1 mm in any hour from start − 1 h to start + 3 h; `p_wet = (votes + 3 × climatology) / (models + 3)`, climatology the circuit's shrunk wet share. All four settings (models, 0.1 mm, the window, prior 3 votes) were fixed before the backtest, not tuned on it. **On when a vote is saved:** `racinglines weather fetch ... --session race=...` writes it, and the live book prices `race_rain` at `p_wet` and `race_red_flag` with `rate_wx(p_wet)`; the safety car stays on `rate()`; DNFs and the position simulation are unchanged; `[live.props] weather = false` turns it off. No vote, no change. Naming (owner): a weather-aware method, variant or strategy is its base name + `-WX` | `racinglines weather backtest --lead 5`, walk-forward, 63 races 2024-01 to 2026-15 (13 wet, 6 red), the vote issued 5 days before each race (Previous Runs API; fixture `tests/fixtures/weather/open_meteo-leads-f1.csv`). Rain Brier: circuit history 0.1668, **circuit-WX 0.1232** (paired −0.044, se 0.021; log loss 0.516 → 0.388); by lead 1–7 days 0.093, 0.104, 0.113, 0.113, 0.123, 0.115, 0.135. Red flag: climatology 0.0915, climatology-WX 0.0917, wet oracle 0.0900 (neutral; 2 of 6 red flags were wet). Safety car: climatology 0.2667, climatology-WX 0.2679 (no effect, stays off). DNFs per race: wet 2.71 vs dry 2.42 (2020–2026, 34 wet of 146), but the forecast-mixed count doesn't beat the field mean (MAE 1.411 vs 1.416, Poisson deviance 1.378 vs 1.373), so no DNF change. Prior 1 / 3 / 7 votes: rain Brier 0.125 / 0.123 / 0.128 (information only) | — |
| 2026-10-06 | 3 | **Provisional.** Sprint stage = the GP finishing model with the schema's sprint points and the SQ grid (`sports/f1.toml` `[sessions.sim]`: `sprint = {grid_from = "sprint_qual", grid_from_by_year = {2021 = "qual"}, points = "sprint", dnf_scale = 0.5}`; `models/position_sim/pricing.price_stages`). The grid is SQ's laps ranked by best valid lap once SQ has run (FastF1 stores SQ without positions), else simulated from qualifying pace; after the sprint, its actual result. **`grid_from_by_year`**: in 2021 Friday's qualifying set the sprint grid (no Sprint Qualifying), so the 2021 sprints take their grid from `qual` (`model.grid_source`). **`dnf_scale` 0.5**: each driver's GP DNF rate × 0.5 in the sprint, until it is refit after the 2023–25 sprint backfill (12 more weekends). No sprint grid weight or noise setting. Drawn on a side stream, so every Grand Prix price is byte-identical. Writes `extra.sprint_win_prob` / `sprint_pole_prob`, which `db.reads.model_prob` already reads before the race-odds stand-in. **Validated on 13 sprint weekends** (`racinglines f1 sprint-check`, owner's local database, 2026-10-06, at this commit). With the grid session's order known, sprint-winner Brier 0.0322 (stage) vs 0.0369 (GP-win stand-in), paired diff −0.0047 (se 0.0009), log-loss diff −0.0194 (se 0.0032), the stage ahead on 12 of 13 weekends (Monza 2021 +0.0003). Before the grid session the stage is a coin flip against the stand-in (diff +0.0002, se 0.0003). Observed DNF share 7.1 % (sprint) vs 14.8 % (GP), ratio 0.48; simulated 5.9 % vs 11.8 %, so the model under-predicts retirements at both. Before the per-year grid source the two 2021 weekends lost to the stand-in (grid simulated: Brier 0.0342 vs 0.0328 and 0.0389 vs 0.0327); from `qual` they are 0.0323 vs 0.0328 and 0.0327 vs 0.0324 | `dnf_scale`: on the 13 stored sprints vs the GPs of the same weekends (owner's local database, 2026-10-06), the DNF share is 7.0 % vs 14.4 %. Context, not settings (same 13 weekends): grid-to-finish Spearman 0.865 (sprint) vs 0.770 (GP), and pole converts to a win 69 % vs 46 %. So a sprint follows its grid more closely than a GP; a sprint-specific grid weight waits for the backfill and its own row. The shape (a second `simulate_race` with sprint points) is what the season forecast already does for sprint points | Sprint winner and sprint pole priced from the race's win and pole odds (U5 stand-in, kept as the fallback for runs without the stage) |
| 2026-10-06 | 3 | **Provisional, not promoted.** `model-WX`, the retirement twin of the weather-aware props (`models/position_sim/dnf_check.py`, [F1: weather-aware (-WX) variants](f1.md#weather-aware-wx-variants)): each driver's `dnf_prob` times `props.wx_scale` (the circuit's retirement rate at the forecast's `p_wet` over the same at its usual wet share), the forecast being `weather/wet.p_wet_series` (the 5-day Open-Meteo vote shrunk to the circuit's wet share, as the wet-race row above). It is a check only: **no default changed**, the live book's retirement and classification kinds keep the run's `dnf_prob`, and `gridq+pretrain+reset-WX` stays unbuilt (todo P2). **model-WX is not better than model** | `racinglines f1 props --dnf-check <dnf_asof.csv> --history <history.csv> --forecast tests/fixtures/weather/open_meteo-leads-f1.csv --lead 5`: the same as-of export as the DNF calibration row (829 rows, 40 races 2025-01 to 2026-16, gridq+pretrain+reset), 815 rows scored (10 DNS, 4 without a result), all 40 races with a forecast and a history row (history 147 races). Brier: model 0.1140 (se 0.0088), model-WX 0.1140 (se 0.0088); paired model-WX − model +0.00007 (se 0.00009; log loss 0.3884 → 0.3885). The scale is small: 0.961 to 1.064 across the 40 races (median 0.991), so the forecast barely moves a driver's price, and where it does it doesn't help. Same forecast in `f1 props --check --history <history.csv> --forecast ... --lead 5` (64 races 2024-02 on): climatology-WX − climatology red flag +0.0005 (se 0.0029), safety car +0.0012 (se 0.0010), both not better, as in the backtest above | — |
| 2026-10-07 | 3 | **Provisional.** New variant `flpos` (`model.FL_FROM = "position"` with `FASTEST_LAP`, off by default; no live config or profile turns it on): the fastest lap goes to one classified car, drawn with weight `band rate(finishing position) × exp(−(race pace − quickest classified pace) / pace_scale)` from `sports/f1/fastest_lap.toml`, so it follows the simulated result and the car. Band rates P1 36/108, P2 18/108, P3–8 38/648, P9+ 15/1042 (bands set by eye on the counts before any backtest, sparse tail pooled); `pace_scale` 0.0217 of a lap. Drawn on the fastest lap's side stream, so every other price is byte-identical. Used by combo pricing (`markets/combos.py`, Lab job `f1_combo`) | **A priori from history, not tuned on a backtest.** VM `laps`/`results`, 108 Grands Prix 2022–26 (fastest non-deleted race lap): the winner set it 36 times (33 %), P2 18; 0 of 258 DNFs. `pace_scale` is the one fitted number: a conditional logit with log(band rate) as offset and each car's realized median-lap gap, MLE k = 1/pace_scale = 46 (se 15); NLL 306.8 uniform, 242.2 bands, 236.5 bands + pace. Free band weights + pace fit history better (225.6, scale 0.0077) but on the simulation's pre-race pace gave the winner the fastest lap only 20 % on Singapore 2026 (run 9652's paces and win odds, emulated); the chosen form gives 37 % there (P(FL given a win) 44 % Antonelli, 28 % Gasly; history 33 % 2022–26, 42 % 2025–26), against 11.8 % for `fastlap` (owner's Mac). Per-driver habits (2024–26 winner-sets-FL: Verstappen 7/18, Antonelli 5/8) not modelled. **To score:** `fl_prob` against Kalshi's resolved `KXF1FASTLAP` markets before any live use, with its own row | `fastlap` (race pace + noise; the winner sets it far too rarely); position only (ignores the car: a midfield winner gets the leader's chance); free band weights + pace (fitted on realized pace, too weak on pre-race pace) |
| 2026-10-07 | 9 | Parity sprint C2: the season sweep runs for any sport whose schema has a `[sweep]` table (`pipelines/season_sweep.py`; `racinglines nascar sweep`, `motogp sweep`; search jobs `kind = "sweep"`), on Polymarket, Kalshi and OG.com (`markets/venue_replay.py` EXCHANGES). NASCAR / MotoGP use their `[replay]` stages, kinds, group targets and pricing model; a priori, none tuned: the F1 taker and maker defaults, the stage-aware taker skips `race eve` (`[sweep] late_stages`), the maker stops quoting at 00:00 UTC on race day (`quote_until_hours = 0`, the race's start time isn't in the schema), one pricing per race seeded by the event key so a race prices the same alone or in its season. Owner: the earlier weekend-based backtest stays available as an explicit stage mode, the `stages` setting ("weekend" = fixed `[replay]` stages, one pricing per race; "sessions" = the session schedule), unset = the schema's `[sweep] stages` (F1 sessions, NASCAR / MotoGP weekend), so old results stay reproducible beside a session-aware path. Every sweep run's params now carry `sport` and `venue`; F1 pages read F1 sweeps only. OG.com's taker pays its schema's flat $0.02 per contract on the cost per share | No result from these sweeps yet: nothing is chosen from their data. F1 is unchanged (goldens byte-identical); its sweep may now also take `--venue og` | — |
| 2026-10-07 | 9 | **Proposed, staging only, owner to confirm.** GlobalModel for NASCAR and MotoGP: `[sport] pricing_model` in `sports/nascar.toml` and `sports/motogp.toml` is now `racinglines.models.model_global:GlobalModel` (the replay, the sport forecast, the season forecasts and the paper backfill all read it), at its a priori defaults (noise 0.8 strength units, half-life 240 days, prior weight 3, uncertainty 0.5, retirements on, team prior off; no `[model.defaults]`, nothing tuned). The earlier models stay runnable as `[sport] challengers` (`backtest walk-forward <sport> --model nascar_results | nascar_recent_form | motogp_results | motogp_recent_form`). Every model now prices the event's start list (its entrants less DNS in the walk-forward; the race's stored sessions, else the last race's field, in the forecast), not everyone ever seen (core backlog C5); the season forecasts' "auto" noise in places applies only to a model whose noise is in places | The 2026-10-07 algorithm A/B/C study (`/mnt/project-files/research/algo-abc/REPORT.md` and `run/tables.md`, not in the repo; 2025-26 races scored, G = GlobalModel at unbound defaults, A = the form model's `price`): NASCAR (74 races) win log loss G 3.1046 vs A 5.1841 (G minus A -2.0796 [-2.7217, -1.4657], better), head-to-head log loss G 0.6189 vs A 1.4958 (uniform 0.6931); MotoGP (37 races) win log loss G 2.2821 vs A 2.7363 (-0.4542 [-1.2097, +0.2179], noise), head-to-head G 0.5794 vs A 0.6266, top-10 Brier better (-0.0288 [-0.0467, -0.0106]). The form model fixes noise at 2.0 places and lets every car finish (C6). Not shown: the study priced every entrant seen, not the start list; pairwise Elo beat G on head-to-head in both sports; no market or P&L comparison. Changes every NASCAR/MotoGP price; F1 and downhill untouched | `[sport] pricing_model` of the 2026-09-30 "NASCAR / MotoGP taker replay" entry (the sport's own model) |
| 2026-10-07 | 9 | Parity sprint C5, settlement parity. **One top-n rule:** a top-n market is YES when the driver is classified (results status `OK`) and placed in the top n (`markets/payoffs.top_n`, used by `kinds.settle`, the declarative `top` / `position` predicates, the walk-forward, `position_replay` and `season_sweep` (both now settle through `kinds.settle`), the private book, `venue_replay` and the maker replay). That is the walk-forward's rule; the replay's (any listed place, so a NASCAR car out of the race still counted by its place by laps) is gone. A head-to-head goes by position, a driver with no position behind one with a position (the walk-forward said NO there, the replay YES: now YES), neither placed NO (the walk-forward's; the replay left it undecided). **Biggest mover settles** from the race round's stored grid (`results.extra.grid`) by the 2026-10-04 rule; undecided without a stored slot or when a pit-lane starter could be the mover. `racinglines markets --exchange X settle-check` (and `--exchange og settle --check`) lists every link where our outcome differs from the exchange's `resolved_yes` | No venue's top-n, head-to-head or biggest-mover rule text is recorded in the repo (Kalshi keeps it on each link as `params.rules`, on the VM only), so the walk-forward's rule is kept and is **unverified**: owner to confirm against Kalshi's NASCAR top-n rules (does a DNF car's place count?) and how venues count a pit-lane start. Not a tuned setting. F1's walk-forward, private-book and weekend-sweep top-n settlement is unchanged (it already was this rule); NASCAR replays and sweeps change on every DNF placed in a market's top n | the replay's own settlement (2026-09-30 entry: "the result settles by classified position") |
| 2026-10-07 | 9 | **Provisional, a priori, nothing tuned.** NASCAR pole and fastest lap (parity sprint C12b): the GlobalModel draws side classifications for the same start list, named in `sports/<sport>.toml` `[model]`: `sessions = ["qual"]` (the qualifying order from past `qual` rounds, `stage_rank["qual"]`, prices `race_pole`) and `best_lap = "race_fastest_lap"` (the order of each past race's best lap from the `laps` table, the car drawn first sets the fastest lap, prices `race_fastest_lap` and `race_constructor_fastest_lap`). Each is the race's structure on its own history: field-size-free strength z, recency half-life, prior weight, noise and uncertainty at the race's settings (240 days, 3, 0.8, 0.5), no retirements, no team or rating prior. Drawn on a side generator seeded from the shared one without advancing it (salt 7401), so every race price is unchanged. Settled from the stored data: the race's `qual` round (`qual_position`; a rained-out qualifying writes none: undecided) and the race's laps (a `race_fastest_lap` column, only when `laps_complete`). Their links are not filed as modeled yet (`[markets] kinds` unchanged: `tests/test_classify_parity.py` pins `race_pole` as unmodeled; the lead decides); MotoGP names `sessions = ["qual"]`, inert until its qualifying is backfilled. The walk-forward now scores indicator kinds | Kalshi lists `KXNASCARPOLE` (pole 0/12 races) and `KXNASCARFASTLAP` (fastest lap 0/21) for NASCAR (parity plan, 2026-10-07); 270 qualifying rounds and laps for 279 races are stored (same plan). Not shown: no walk-forward or market score of either kind on real data yet (the sandbox has no NASCAR database); the settings are the race's, not fitted to qualifying or lap times; whether Kalshi settles a rained-out qualifying on the formula grid is unknown | — |

## Open questions

- Do live paper fills match the backtest? The replay's "through" rule is
  conservative, but live queues and competing makers may fill less (F1-8).
- How much to size up after validation, and on what evidence (A-lite → A)?
- Kalshi's F1 depth and resolution rules: enough to quote, or only to take (F1-9)?
- Are the search's noise ranges real? The Monte Carlo seed is fixed, so noise
  replicates aren't independent until a seed setting exists.
- Sprint weekends: does the F1-2 stage-specific training need separate
  handling for sprint-format stages?
- Should maker spreads come from per-market model uncertainty (F1-6) or from
  measured markouts (F1-4)? F1-4 showed markout-driven widening doesn't help on
  2026; live markouts from F1-8 are the next evidence.
- Which sport next? F1 and UCI downhill are the endpoints for audience and
  expected liquidity; candidates in between are in [Roadmap](todo.md#business-and-collaborators).

## Collaborators and beta testers

We're looking for beta testers and collaborators! Try the app at
[racinglines.bet](https://racinglines.bet), and if you'd like to help, test, or just say hi, drop us a line at
[hello@racinglines.bet](mailto:hello@racinglines.bet?subject=racinglines%20beta%20tester%20%2F%20collaborator).
We'd love to hear from you. The [contributor guide](contributing.md) says how to get set up.
