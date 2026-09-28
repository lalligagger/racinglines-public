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

**Status:** built and scheduled; waiting for Polymarket, which has listed no race
since round 15 (28 Aug 2026), so rounds 16–17 have nothing to trade · **Behavior
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

**Status:** Kalshi connector run against the live read-only API (2026-09-28, `markets/kalshi/`); F1 history for 2025 and 2026 pulled and archived in `data/archive/markets/kalshi/` ([Data changes](data-changes.md)); the maker replay and the demo maker's record read it (`f1 demo-history --venue kalshi`, [Kalshi history](kalshi-history.md)); the sweep and taker signals don't yet · **Start after** F1-8's first live weekends

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

The repository is private on GitHub only because a minimal data set (FastF1 raw
files, the Polymarket prices and trades archive, the database snapshot) is
committed so cloud runs can clone it, and that data isn't ours to publish. We
are open to beta testers and collaborators, and happy to share the pipeline and
web-app code with anyone interested: ask for invited access or a code-only copy.
