# Engine roadmap: standard inputs, composable models, standard outputs

**Status:** approved by the owner on 2026-09-29 (E0 done: decisions D1–D6 taken as recommended, see the
[decision log](#decision-log)). Built so far: E1a, the L1 frame schemas with the F1 and downhill adapters
([Frames](frames.md), PR #73), and E4a, prediction records beside `race_predictions` with one kind registry, behind
`RACINGLINES_PREDICTION_RECORDS`, default off ([Prediction records](backtest-core.md#prediction-records), PR #76).
Next in order: E1b market frames, E2 the as-of view and leak guard. The task-by-task implementation plan (twelve
tasks, roles, files, tests, backups) is the owner's "Engine Implementation Plan" page; the phases here are its skeleton.

**The goal.** A model is developed once, joins "the engine", and runs on any sport and any exchange that
has the data it needs. For that we need three things:

- **standard schemas for what goes into a model**;
- **a model contract that allows challengers and combinations**;
- **standard records for what comes out**, so every model, sport and venue shares one set of backtest,
  scorecard and report tools.

This page continues [Backtest core](backtest-core.md), whose six steps are done. Backtest core standardized
**running** models. This roadmap standardizes the **data going into them and the results coming out**, and
the one piece between those two ends that is still missing: **combining models**.

## What backtest core already gives us (keep it)

| Piece | Where | Keep as |
|---|---|---|
| Pricing-model contract: `load`, `events` (with a cutoff), `history`, `price → OutcomeSims`, `results` | `models/race_model.py` | The core of the model contract. Extended in E3, not replaced |
| `OutcomeSims`: simulated finishing orders, finish flags, rounds reached, points, groups | `models/outcomes.py` | **The seam between models and markets.** Unchanged |
| Market kinds: a fair value from `OutcomeSims` and settlement from the result, one definition per kind | `markets/kinds.py` | The one kind registry (E4 merges the second list into it) |
| Walk-forward engine, calibration, stages from the schema | `core/` | Unchanged; E5 reports on top of them |
| Replay venues with an as-of `view(market, t)` and fees | `markets/venue_replay.py` | The trading-side venue interface. E2 adds a pricing-side read |
| Search, held-out labels, seed replicates, stable candidate ids | `pipelines/search*.py` | Unchanged |
| Sport schemas `sports/<code>.toml`, exchange schemas `exchanges/<code>.toml` | `sports.py`, `exchanges.py` | Extended with `[models]` (E3) and `[data]` capabilities (E1) |

## The gaps (measured in the code, 2026-09-29)

| # | Gap | Evidence | Blocks |
|---|---|---|---|
| G1 | **No standard input schema.** Each model's `load()` reads its own frames: F1 builds `Measurements` (sector deficits, practice, profiles), downhill a tidy runs frame | `position_sim/pricing.py:56`, `race_model.py` `TimedRuns.load` | Moving a model to another sport; algorithms that need only results (Plackett-Luce) |
| G2 | **The leak guard is F1-only.** `Measurements.view(cutoff)`, `assert_no_leak` and `LeakageError` know F1 session names. Downhill and any new model rely on convention | `pricing.py:46–100` | Trusting a new model's backtest |
| G3 | **Market prices can't be a model input.** Venues exist only on the trading side | `venue_replay.view` is used by the sweep, not by `price` | Model × market combination and market-implied strengths (algorithms A and B in the [models research](#related)) |
| G4 | **Two F1 pricing paths.** `PositionSim` (walk-forward) prices only before the race. Stage pricing (the sweep, signals, forecast) goes through `price_race` directly. The contract has one cutoff per event, not events × stages | `race_model.py:127`, `weekend_sweep.py`, `signals.py` | Scoring any F1 challenger at every stage through the engine |
| G5 | **No composition, one model per sport.** `pricing_model` names one class. Variants are module-level globals toggled by a context manager, so two variants can't coexist in one process | `sports/f1.toml:10`, `variants.py:53` | Ensembles, challengers side by side, a combiner that reads two models' outputs |
| G6 | **Outputs are wide and split.** `race_predictions` has fixed columns (win, podium, top 10, make_final) plus `extra` JSON. Kinds are defined twice (`markets/kinds.py`, `db/reads.py` `PREDICTION_KINDS`), and `reads.py` branches per kind. `OutcomeSims` isn't kept, so a new kind can't be priced on an old run | `db/models.py:234`, `reads.py:170–262` | Adding a kind or a sport without touching reads; re-pricing history |
| G7 | **Evaluation and reports are per sport.** `f1 backtest`, `compare`, `matrix` and `scorecard` are F1-only. `mtb_dh backtest` is the legacy path. There's no generic report builder (an open question in `CLAUDE.md`) | `position_sim/evaluate.py`, `pipelines/scorecard.py` | One comparison, one scorecard and one report format for every model |
| G8 | **Consumers hard-code sports.** `SPORT_OF` in the MCP server, competition tuples in the web views, one job type per sport | `mcp/tools.py:19`, `web/views.py:350,704`, `web/jobs.py:123` | A new sport appearing in the app without code |
| G9 | **Exchange ingest isn't uniform.** Polymarket and Kalshi have their own packages and F1-title regex classifiers. OG.com uses the schema driver with rules in its TOML | `polymarket/sync.py:73`, `kalshi/sync.py:100`, `exchange_driver.py` | Linking a new sport's markets to kinds on every venue |
| G10 | **Sport-shaped tables.** `laps` has F1 columns (three sectors, four speed traps, tyres), and `track_profiles` is computed from F1 timing only | `db/models.py:386,412` | Lap-level models for NASCAR / MotoGP |

## The architecture

```
 sources/<sport>/*      exchanges (polymarket, kalshi, schema driver)
        │                         │
        ▼                         ▼
 ┌──────────────── L1 canonical frames (schemas, `available_at` on every row) ─────────────────┐
 │ entrants · sessions · classifications · laps* · conditions · venue_features*                  │
 │ market_links (kind, subject) · market_quotes (bid/ask/mid/volume) · official_results (settle)  │
 └───────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                             │  L2 DataView.asof(cutoff): one leak guard for all
                                             ▼
 ┌──────── L3 models: requires={frames}, price(view, event, stage, settings, rng) → OutcomeSims ───┐
 │ base models (position_sim, timed_runs, plackett_luce, market_implied)                          │
 │ combiners (market × model, ensembles): take other models' OutcomeSims and/or market_quotes      │
 └───────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                             │  markets/kinds (one registry)
                                             ▼
 ┌──────── L4 standard outputs ───────────────────────────────────────────────────────────────────┐
 │ Prediction records (long): run · model_id · event · stage · cutoff · kind · subject · fair · se │
 │ OutcomeSims archive (optional parquet) · model_runs (provenance)                                │
 └───────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                             ▼
 L5 evaluation: scores vs result, vs venue mid at the cutoff, paired compare, promotion check
 L6 report bundles: report.json + report.md + img/ → HTML / PDF (markdown_html)
 L7 consumers: web, MCP, live, signals read L4 and the sport registry only
```

`*` = optional frames. A sport declares which frames it has, and a model declares which it needs.

### L1: Canonical input frames

Each frame is a declared schema (columns, types, keys) with an **`available_at`** column: when the row became
knowable. For session data that's the session's end, with no lag added (`Measurements.view` gates on the end;
`[stages] lag_minutes` moves a stage's cutoff, not the data). No source is live, so session-keyed frames are released
a whole session at a time. For a market quote it's the quote's timestamp. A sport's adapter produces the frames from its tables. The first version is read-only views over
today's tables, with no migration.

| Frame | Key columns | F1 | Downhill | NASCAR (planned) | Tape-only sports |
|---|---|---|---|---|---|
| `entrants` | event, race, athlete | ✓ | ✓ start lists | ✓ | from links only |
| `sessions` | event, session (the sport's vocabulary from `[sessions]` / `[rounds]`), start, end | ✓ | ✓ rounds | ✓ practice / qual / stages | – |
| `classifications` | event, session, athlete, position, status, time_ms, gap, grid, points | ✓ | ✓ runs | ✓ | – |
| `laps` | event, session, athlete, lap, time_ms, sector times[], pit, track_status | ~ derived measures only until E2 | ✗ (splits instead) | ~ lap time, flag | – |
| `conditions` | event, session, weather fields | ✓ | ✗ | ~ | – |
| `venue_features` | event, features map (the sport defines the keys) | ✓ `track_profiles` | ~ venue history | track type | – |
| `market_links` | exchange, token, kind, subject(s), race, params, rules | ✓ | – | ✓ | ✓ |
| `market_quotes` | exchange, token, ts, bid, ask, mid, last, volume_24h | ✓ | – | ✓ | ✓ |
| `official_results` | event, athlete, position, status, points, rounds reached | ✓ | ✓ | ✓ | ✓ from settlement |

`official_results` is kept separate on purpose. The engine reads it only after pricing, to settle, which is
what `results()` does today.

**The sport schema gains a `[data]` table** listing the frames it provides, e.g. F1's `frames = ["entrants",
"sessions", "classifications", "conditions", "venue_features", "official_results"]` (`laps` joins when E2 passes
the raw laps to the adapter). That list plus each model's `requires` gives the **capability matrix** of which models
can run on which sport. `live` in the same table names the frames whose source dates each row as it happens; it
defaults to empty, so every session-keyed frame is released a whole session at a time (`check_release`).

### L2: One as-of view and one leak guard

`DataView.asof(frames, cutoff)` filters every frame to `available_at < cutoff` and records an audit, the same
thing `Measurements.view` does for F1 today but generic.

- `Measurements` becomes a model-specific **feature builder on top of the view**. F1 goldens are unchanged.
- Downhill gets the guard for free.
- Market quotes go through the same view (G3). A combiner can't see a price from after the cutoff, and the
  staleness and volume filters are shared with `venue_replay.view`.

### L3: Model contract v2, registry and composition

Additive to today's contract:

| Addition | Why |
|---|---|
| `requires: set[str]` of L1 frames | Capability check. The engine refuses to run a model on a sport that lacks its frames |
| `stages(event)` and `price(view, event, stage, …)` | Events × stages (G4). F1's stage pricing moves behind the contract, so every challenger is scored at every stage |
| Settings on the instance, not module globals | Two variants, or a base model and its combiner, in one process (G5). Variants become settings presets |
| `model_id = name@version:settings_key` | One identity in `model_runs`, predictions, reports and promotion |
| `[models]` in the sport schema: `default`, `challengers = [...]` | Several models per sport. The promotion rule picks the default |
| **Combiner** models: `inputs = [model_ids]`, optional `market_quotes`, output `OutcomeSims` | Algorithm A (Benter-style model × market) as reweighting of the base model's simulations, and ensembles |

A combiner is an ordinary model whose inputs include other models' outputs, so the walk-forward, search and
reports treat it like any other.

The one generic operation it needs is **`tilt(sims, target_win_probs)`**: reweight simulated races so the win
marginals match the target. It belongs in `models/outcomes.py`, next to `OutcomeSims`.

### L4: Standard outputs

- **Prediction records, long format:** one row per (run, event, stage, kind, subject), with `cutoff`, `fair`,
  the Monte Carlo standard error `se`, `n_sims`, `model_id` and `params` (n, opponent, team).
  - One kind registry (`markets/kinds.py`) defines what's valid.
  - `reads.py` loses its per-kind branches.
  - `race_predictions` keeps being written alongside the new records until every reader has moved.
- **An `OutcomeSims` archive,** optional, as Parquet per run and stage: 10,000 × 22 int8 is about 220 kB, so
  about 35 MB for a full F1 season at 7 stages. A new kind can then be priced on an old run without re-running
  the model.
- **`model_runs`** stays the provenance row: code version, settings, data through.

### L5: Generic evaluation

These tools are built on Prediction ⨝ official_results ⨝ market_quotes at the cutoff, so they work for any
model, sport and venue:

| Tool | Replaces or generalizes |
|---|---|
| `racinglines eval scores RUN` | Brier, log loss, ECE per kind × stage (`f1 backtest`'s tables, `mtb_dh backtest --reliability`) |
| `racinglines eval compare RUN_A RUN_B` | `f1 compare` (paired ± 2 SE, reliability bins) |
| `racinglines eval scorecard RUN --venue V` | `f1 scorecard` (model vs venue mid at the cutoff) |
| `racinglines eval promote RUN --against DEFAULT` | The promotion rule as a check, and a draft decision-log entry |

The F1 commands stay as thin wrappers with identical output.

### L6: Report bundles

This answers the open question in `CLAUDE.md` (a generic report pipeline) with a single command,
`racinglines report build <folder>`. A report folder holds:

- `report.json`: runs, `model_id`s, settings keys, data through, the tables as data;
- `report.md` and `img/`;
- the HTML/PDF, rendered with `markdown_html.render`, as `live report` already does.

The report types are templates over L4/L5:

- **model card**: what the model requires, the sports it can run on, its scores per kind × stage, its known
  weaknesses;
- **backtest**;
- **compare**;
- **weekend scorecard**;
- **search** (`search_report`);
- **live event** (`live_report`).

Every template follows the `CLAUDE.md` quality bar: numbers over adjectives, and a closing section on what's next
or what wasn't shown.

### L7: Consumers read the registry

The web app, MCP server, job types and live pages take the list of sports and the competition → sport map from
`sports/*.toml` (G8), and predictions from L4. After that, a sport with a schema, frames and a model appears in
the app with no code change.

### Exchanges (L1's other half)

Every exchange produces the same two frames, `market_links` and `market_quotes`, plus fees and rules, and maps
contracts to `(kind, subject)`:

- New venues go through the schema driver.
- Kalshi and Polymarket keep their packages (they work, and they're money-adjacent). Only their classifiers move
  toward per-sport **rules in TOML**, as `og.toml` does (G9). That's what lets a NASCAR or MotoGP market become
  a priced kind without Python.

## Capability matrix (E0, as of 2026-09-29)

Which L1 frames each sport can produce **from the tables it has today**, and which frames each model needs. A
model runs on a sport only when every frame it requires is in the sport's row. This is the table E1's `[data]`
blocks are checked against; it is written from the sport schemas (`sports/*.toml`, `model_family`) and the
ingest code, not from a running database.

| Sport (`code`) | entrants | sessions | classifications | laps | conditions | venue_features | market_links | market_quotes | official_results |
|---|---|---|---|---|---|---|---|---|---|
| `f1` | ✓ | ✓ | ✓ | ~ derived measures | ✓ | ✓ `track_profiles` | ✓ | ✓ | ✓ |
| `mtb_dh` | ✓ start lists | ✓ rounds | ✓ runs | ✗ (splits) | ✗ | ~ venue history | – (no venue lists it) | – | ✓ |
| `nascar` | ✓ after `nascar ingest` | ✓ incl. stages | ✓ | ~ lap time, flag (D5) | ~ | ~ track type | ✓ (#67, #69) | ✓ Kalshi, Polymarket, OG.com | ✓ after `nascar ingest` |
| `indycar` | from links only | – | – | – | – | – | ✓ | ✓ Kalshi, Polymarket | ✓ from settlement only |
| `motogp` | from links only | – | – | – | – | – | ✓ | ✓ Kalshi, Polymarket | ✓ from settlement only |
| `le_mans` | from links only | – | – | – | – | – | ✓ | ✓ Kalshi | ✓ from settlement only |
| `road_cycling` | from links only | – | – | – | – | – | ✓ | ✓ Kalshi | ✓ from settlement only |
| `sailgp` | from links only | – | – | – | – | – | ✓ | ✓ Kalshi | ✓ from settlement only |

`✓` today's tables hold it · `~` partial or planned · `–` nothing to build it from · `✗` the sport has no such
thing. NASCAR's `✓ after` cells depend on the onboarding thread's `nascar ingest` run on the VM.

| Model | Requires | Runs today on | Can run after E1–E7 on |
|---|---|---|---|
| `position_sim` (F1 baseline) | entrants, sessions, classifications, laps, conditions, venue_features | `f1` | `f1` only (its features are F1's sectors and practice) |
| `timed_runs` (downhill) | entrants, sessions, classifications | `mtb_dh` | `mtb_dh`; any timed sport that fills those three |
| `market_implied` (E7, algorithm B) | market_links, market_quotes | – | every sport with a tape: all eight |
| `plackett_luce` (E7) | classifications (official_results to settle) | – | `f1`, `mtb_dh`, `nascar` |

So the first cross-sport proof (E7) has exactly one candidate: `plackett_luce` and `market_implied` on `nascar`,
compared against `market_implied` alone on the five tape-only sports.

## Phases

The ground rules are the [F1 roadmap](f1-roadmap.md#ground-rules)'s:

- every step behind a switch that defaults to today's behaviour;
- goldens byte-identical;
- no renames;
- a decision-log entry for anything structural.

**Calendar constraint:** profiles A and C are frozen and signals run live through 31 Dec. So any phase that
changes the **live pricing or signal path** waits until after Abu Dhabi (6 Dec). Additive, read-side phases can
start now.

| Phase | What | Touches live paths? | Done when | Role |
|---|---|---|---|---|
| **E0** | This page approved; owner decisions D1–D6 below; the capability matrix written for today's 2 models × 8 sports | No | Decisions logged | Decide |
| **E1** | **E1a done (PR #73)**; E1b market frames and E1c NASCAR frames open. L1 frame schemas (declared and checked in tests) + F1 and downhill adapters as read-only views; `[data]` in the sport schemas | No | Both sports produce every frame they claim; `tests/test_frames.py`; goldens unchanged | Implement (Sonnet); the schemas reviewed by the deciding seat |
| **E2** | L2 `DataView.asof` + generic leak guard; `Measurements` rebuilt on it; `market_quotes` through the same view | No (F1 feature values identical) | F1 golden `f1_measurements` byte-identical; a leakage test per frame | Own (Opus) |
| **E4a** | **Done (PR #76).** L4 Prediction records **written alongside** `race_predictions` (new table or Parquet, per D1); kinds merged into one registry | No (readers unchanged) | Every saved run also has long records; a round-trip test | Implement |
| **E5** | L5 `eval scores / compare / scorecard` on the records; F1 commands wrap them | No | `f1 compare` and `f1 scorecard` outputs identical through the new path | Implement |
| **E6** | L6 `report build` + model card template; the first model card for `position_sim` and `timed_runs` | No | Both model cards render to PDF; `mkdocs build --strict` | Implement |
| **E7** | **First cross-sport proof:** algorithm B (market-implied strengths, requires only `market_links` + `market_quotes`) as a model, and a Plackett-Luce base model (requires `classifications`); run on the NASCAR Kalshi tape and on F1 | No (new models, not live) | A NASCAR model card and scorecard from the recorded Chase tapes, **in time for the December NASCAR decision** | Own (Opus) |
| **E3** | L3 contract v2: stages in the contract, instance settings (variants as presets), `[models]` registry, combiners + `tilt`; F1 stage pricing moved behind the contract | **Yes:** the sweep, signals and forecast price through it | Full 2025 and 2026 F1 sweeps identical; signals identical on a replayed weekend. **⚠️ after 6 Dec** | Own (Opus), final review by the deciding seat |
| **E4b** | Readers (web, MCP, signals) move to the Prediction records; `race_predictions` retired later | **Yes** | Pages and the MCP answers identical on a snapshot | Implement, after E3 |
| **E8** | L7 consumers read the registry; generic job types | Web only | A tape-only sport with a model shows up with no code | Implement |
| **E9** | Kalshi and Polymarket classifiers → per-sport TOML rules; `laps` generalized, or a per-sport extension table (per D5) | **Yes** (links feed the signals) | Every existing link classifies identically; **⚠️ money-adjacent** | Own (Opus), 2027 |

**Order:** E0 → E1 → E2 → E4a → E5 → E6 → E7 now to December. E3 → E4b → E8 → E9 in January–February, before
2027's first race.

E7 is deliberately early. It's the test of the whole idea: a model that has never seen F1 code prices a sport we
have only a tape for, and the standard outputs and reports come out the same.

## Owner decisions

All six were taken as recommended on 2026-09-29 ("as recommended", the owner, in the implementation-plan
thread); D4 is split and D5 is deferred as the decision log records.

| # | Decision | Options | Recommendation (= decision) |
|---|---|---|---|
| D1 | Where Prediction records live | (a) a new `predictions` table (migration on the VM: backup first, sign-off) · (b) Parquet under `data/runs/` + the bucket · (c) both | **(c):** Parquet first (no migration, E4a can ship now); the table in E4b, when readers move |
| D2 | How frame schemas are declared and checked | (a) dataclasses / TypedDicts + tests (as PR 58 did) · (b) `pandera` (a new dependency) | **(a)** now; revisit if validation grows |
| D3 | Keep `OutcomeSims`? | No · every stage run · only backtests and forecasts | **Backtests and forecasts** (about 35 MB per F1 season) |
| D4 | Several models per sport | One `pricing_model` · a `[models]` table with default + challengers | **`[models]`.** The promotion rule sets `default`, logged in the decision log |
| D5 | Sport-specific lap data | Generalize `laps` (nullable sector columns) · a per-sport extension table (`laps_f1`, `laps_nascar`) | Decide at E9 with NASCAR's feed in hand |
| D6 | Report builder | A `racinglines report build` command · one script per report | **Command** (E6) |

## Decision log

Same format as the [F1 roadmap](f1-roadmap.md#decision-log). Never delete a row; add one that supersedes it.

| Date | Phase | Decision | Why | Supersedes |
| --- | --- | --- | --- | --- |
| 2026-09-29 | E0 | Roadmap approved (PR #66); phases E0–E9 stand, with E0→E1→E2→E4a→E5→E6→E7 before 6 Dec and E3→E4b→E8→E9 after | Profiles A and C are frozen and signals run live through Abu Dhabi; only read-side work before then | — |
| 2026-09-29 | E0 | D1 (c): prediction records as Parquet under `data/runs/<run>/` first (E4a), the `predictions` table when readers move (E4b, VM migration with backup and sign-off) | E4a can ship with no migration; the table waits for its readers | — |
| 2026-09-29 | E0 | D2 (a): frame schemas as dataclasses plus tests, no `pandera` | No new dependency; matches PR #58's data-contract types | — |
| 2026-09-29 | E0 | D3: keep `OutcomeSims` for backtests and forecasts only (about 35 MB per F1 season), not for every stage run | Lets a new kind be priced on an old run; live stage runs stay light | — |
| 2026-09-29 | E0 | D4: a `[models]` table (`default`, `challengers`) in the sport schema, landing in E3. Before that, E7 adds only a `challengers = [...]` list that the new `eval` and generic `backtest` commands read; live pricing keeps reading `pricing_model` until E3 | E7 needs two models side by side on NASCAR before 6 Dec; the full table changes the live path and waits | — |
| 2026-09-29 | E0 | D5 deferred to E9: generalize `laps` or add `laps_nascar`, decided with NASCAR's lap feed in hand | The shape of the NASCAR lap data is not ingested yet | — |
| 2026-09-29 | E0 | D6: one `racinglines report build <folder>` command (E6), templates over L4/L5, rendered with `markdown_html.render` | Closes the open question in `CLAUDE.md`; one pipeline for every report type | — |
| 2026-09-29 | E0 | Every new engine switch is an environment variable `RACINGLINES_*`, default off; a default flips only in a follow-up PR with byte-identical evidence and a row here | The F1 ground rules, applied to the engine | — |
| 2026-09-29 | E0 | The `market_quotes` frame (E1) reads through the ingest roadmap's phase 2 `canonical_yes` reader when it exists; until then it maps today's `price` per exchange (`last` for Polymarket, `mid` for Kalshi and OG.com) behind the same function | Phase 2 is queued in the onboarding thread behind the NASCAR VM steps and needs the owner's go-ahead; E1's sport frames need no price column at all | — |
| 2026-09-29 | E4a | Parquet needs `pyarrow`, which is not installed in the cloud sandbox; the Mac and VM are unchecked. If absent there too, the archive is compressed `.npz` and the records CSV; no new pinned dependency without the owner's word | Keep `racinglines check` and the suite runnable everywhere | — |
| 2026-09-29 | E4a | Built with Parquet: `pyarrow` is already pinned in requirements.txt (and present in the sandbox), so the fallback above is not needed; records at `data/runs/records/<run>/predictions.parquet` with a `sims.npz` archive (backtests and forecasts only), behind `RACINGLINES_PREDICTION_RECORDS` (default off); `standings` kinds joined `markets/kinds.py`, which `db/reads.PREDICTION_KINDS` now derives from | Supersedes the fallback: no new dependency; readers unchanged | the row above |
| 2026-09-29 | E1 | `[data] live`, default empty; session-keyed frames are released a whole session at a time (`check_release`) | No source is live: FastF1 publishes a session only after it ends. The owner's requirement | — |
| 2026-09-29 | E1 | `available_at` for session data is the session's end, with no lag, matching `Measurements.view` and `session_end`; `[stages] lag_minutes` moves stage cutoffs, not data | The frames must reproduce the model's own leak boundary exactly | — |
| 2026-09-29 | E1 | F1 `laps` is not built in E1a: `Measurements` keeps only lap-derived measures. E2 passes the raw laps to the adapter; until then `position_sim`'s laps requirement is met through `Measurements` | No lap-level frame can come from what the model holds today | — |

## What this doesn't cover

- **Trading strategies** (taker, maker, profiles) stay where they are. The engine standardizes prices and
  their evaluation, not strategies.
- **The live private book** (`pipelines/live.py`) already has a one-core, one-adapter-per-sport design. It
  becomes an L4 consumer in E4b, nothing more.
- **Order placement** is out of scope everywhere. Trading flags stay off.

## Related

- [Backtest core](backtest-core.md): the execution engine this builds on.
- [F1 roadmap](f1-roadmap.md): the ground rules and the promotion rule.
- [Exchanges as schemas](exchanges.md): the schema driver that L1's exchange half extends.
- Models research (2026-09-29, `reports/2026-09-29-prediction-models-research.md`, local only): algorithms A–D.
  A and B need market quotes as an input (E2); D needs only classifications (E7).
