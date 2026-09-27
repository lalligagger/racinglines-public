# TODO

## Summary

<!-- readme: todo-summary -->

**F1 model and trading** (phased in the [F1 roadmap](f1-roadmap.md))

- [x] F1-0: CLOB V2 check (it's V1: fix below); market recorder persistent (LaunchAgent).
- [ ] **Migrate order signing to Polymarket CLOB V2** (`py-clob-client-v2`). V1 orders are rejected
      on production since 2026-04-28. Required before enabling trading.
- [x] F1-1: `racinglines f1 compare` (paired ± 2 SE tables), log loss, reliability curves.
- [x] F1-2: fix the front-of-grid weighting: after qualifying, the model loses to a
      grid-only guess on the win market (`gridq`: 0.0306 vs 0.0309).
- [ ] **Promote `gridq+pretrain` to the default** (owner's OK: it changes live prices;
      re-run the sweep and `UPDATE_GOLDEN` in the same change).
- [x] F1-2: pre-practice pricing: train the finishing model for the no-practice case too.
- [x] F1-4: stage-aware taker strategy (stop re-trading after FP3 and qualifying): +$1,874, in-sample.
- [ ] F1-4: confirm the stage-aware taker on events after Baku.
- [x] F1-4: inventory skew that grows before each session, flatten before quali, widen on bad markouts.
- [ ] F1-4: replay with recorded book depth and a queue model (needs recorded books: from 2026-09-26).
- [ ] **Download and backtest 2025 on Polymarket** (~150 events over 25 GPs, $441M traded; minute
      prices and trades are still served for closed markets, order books are not). Run the weekend
      sweep, the season strategy and the checkpoints on 2025: an out-of-sample test for the
      stage-aware taker and `reset` (both came from 2026), and a normal season to contrast with
      2026's regulation reset. Maker replays run on prices and trades only (no 2025 books).
- [ ] F1-2: driver layer in a new season: the teammate offset carries last season (2026: Russell
      priced far above Antonelli after 3 GPs). Candidate: faster forgetting for second-year drivers,
      judged on every season, not 2026 alone.
- [ ] Data: ingest pre-season testing (FastF1 testing sessions), so the pre-season forecast sees
      what the market sees in a new-regulations year.
- [x] F1-3: chaotic-race tail, correlated DNFs (`tail`: neutral, not promoted).
- [ ] F1-3: safety-car / red-flag / rain props (deferred: no strategy trades them yet).

**Downhill: points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      past formats, and settle the edge cases.
- [ ] Check our 2026 totals against the official standings, and pin them in a test.
- [ ] Re-run and refresh the published numbers.

**Downhill: data and model**

- [ ] Key riders by UCI ID; parse the 2021 PDFs; add Women's categories, start order
      and weather.
- [ ] Check calibration (win probabilities look too flat); tune over all 43 rounds.
- [ ] Find a venue that lists downhill markets (none on Polymarket as of 2026-09).

**Platform**

- [x] Sport schemas (`sports/*.toml`), read by the existing code, so the differences
      between sports are configuration. Additive only (see the [F1 roadmap](f1-roadmap.md) decision log).
- [x] F1 roadmap: F1-0 to F1-4 done (see the [matrix](market-making.md#model-strategy-matrix)); F1-5 deferred.
- [ ] Kalshi as a second exchange.
- [ ] Per-maker exposure limits, per-taker limits and ledgers.
- [ ] Condition in-weekend forecasts on completed rounds (Q1 results, split times).

<!-- /readme -->

Details for each item are in the sections below.

## Points validation

The points tables in `racinglines/models/timed_runs/` (`FINAL_POINTS`, `QUAL_POINTS`,
`QUAL_POINTS_ROUND`) are **placeholders**, and the same tables are used for every
season. Until they're fixed, every number measured in points (expected points,
standings, champion odds, `spearman_points`) is approximate.

- [ ] Get the official UCI DHI World Cup points scales, from the UCI MTB regulations
      (Part 4) or the standings PDFs on ChronoRace. Get the 2026 table first, then
      earlier eras for backtests (2021–22 single qualifier, 2023–24 semi-final,
      2025–26 Q1/Q2).
- [ ] Replace `FINAL_POINTS` with the official Final points for every scoring place.
      Check how many places score: currently 30, but the 2021–22 Finals had 60+ riders.
- [ ] Confirm which qualifying round pays points in each format, and how many places
      score. Also check whether riders who get through Q2 score. Update `QUAL_POINTS`
      and `QUAL_POINTS_ROUND`. If more than one round pays, extend
      `actual_event_points` and `simulate_weekend`.
- [ ] Store the tables in the `points_schemes` database table (per competition,
      era and round kind), and have the model read them from there instead of the
      constants.
- [ ] Check the edge cases:
  - [ ] DNF/DSQ in the Final: zero points, or last-place points?
  - [ ] Ties
  - [ ] Protected or wildcard riders
  - [ ] Bonus or double-points rounds
- [ ] **Reconcile:** run `actual_event_points(select_target(raw, 2026, "ME"))` and
      compare each rider's cumulative total after round 7 with the official
      standings. Every rider should match exactly. Repeat for one past season.
- [ ] Add a test that pins those totals, so a points change or bad data file is
      caught right away.
- [ ] Re-run `season` and `backtest`, and refresh the tables in the docs and README.

## Data

- [ ] **Use UCI rider IDs.** The results JSON has `UciRiderId` for every rider.
      Write it as a column in the downloaded markdown, re-download, and add
      `athlete_identifiers(scheme="uci")` at ingest, matched before names. This
      merges name changes such as `WILLIAMS Robert Jordan` / `WILLIAMS Jordan`
      (existing athletes need a one-off merge).
- [ ] **Parse the 2021 PDFs** (Leogang, Les Gets). The text layer is readable but has
      repeated letters from bold text (`BBBBRRRROOOO`), and each rider spans two
      lines. The PDFs also have UCI ID, year of birth, weather, temperature and
      track length.
- [ ] 2019–2020 PDFs: the text layer is unreadable font codes, so they'd need OCR.
      Low priority.
- [ ] Build **slug probing** into the downloader (`--probe START END`) for rounds
      missing from Wikipedia, like 2021 Snowshoe.
- [ ] Canonical venue names (`mont-ste-anne` → `mont-sainte-anne`,
      `vallnord`/`vallnord-pal-arinsal` → `pal-arinsal`).
- [ ] Elite Women and Junior Women: download, and check the model works for
      smaller fields.
- [ ] Start order: it's in ChronoRace's start-list PDFs and possibly the JSON.
      Needed for track-evolution and weather effects.
- [ ] Weather and track conditions (the PDFs have weather; `--conditions-file`
      exists but is empty).

## Model

- [ ] **Calibration check:** reliability curves for win, podium, top-10 and
      make-Final across all 43 backtest rounds. Win probabilities look too flat. Try
      a lower `INCIDENT_THRESHOLD`, per-round-type incident rates (Finals vs
      qualifying), or a heavier-tailed ε.
- [ ] A tuning sweep over all 43 rounds, not just 2026 rounds 2–7: half-life,
      junior weight, `prior_n`, practice weight.
- [ ] Rider × venue effects: shrink a rider's past residuals at the venue into the
      simulation instead of a fresh `u` every time.
- [ ] Time trends within a season, e.g. rider form or rookies improving fast.
- [ ] Protected-rider rules in older formats.
- [ ] Remaining 2026 venues: once rounds 8–9 are announced, use venue history in the
      forecast.
- [ ] Decide whether to retire or rebuild the older `fit`/`predict` Elo/GBR model.
      It hasn't been checked against the multi-season data.

## F1 model

Phased plan and ground rules: [F1 roadmap](f1-roadmap.md). Items tagged
(F1-n) belong to that roadmap phase.

- [ ] **Evaluation (F1-1):** `racinglines f1 compare RUN_A RUN_B` with paired
      ± 2 SE tables; log loss and reliability curves per market type and stage;
      model-vs-Polymarket Brier per stage for every market type.
- [ ] **Chaotic-race tail (F1-3):** a mixture with rain, safety-car and multi-DNF races
      (inflated noise, more DNFs), so backmarkers get realistic points chances.
      The Sainz–Alonso market showed the gap.
- [x] **Practice pace prior** (2026-09-26): large gain before qualifying (backtest in [Formula 1](f1.md#results)).
- [ ] **Pre-practice pricing got slightly worse (F1-2)** with the practice prior: train the finishing model on
      no-practice paces for pre-FP1 pricing (or on both).
- [x] Re-price the 2026 sweep stages with the practice prior and re-run the sweep (run 191: update −$1,313 → −$479, hold −$2 → +$214).
- [ ] **Front of the grid is underweighted (F1-2).** After qualifying, the model loses to a
      grid-only baseline on win and ties it on podium (backtest run 115, 129 races). Check the finishing
      model's noise and grid terms. Consider a grid-position prior that the
      model adjusts.
- [x] Car shared by teammates: car pace from both drivers, teammate-correlated noise
      (2026-09-26). Teammate head-to-heads improved.
- [ ] **Top-scoring constructor got slightly worse (F1-3)** with shared noise (+0.0008 Brier).
      Check team points variance vs reality, and correlated DNFs (teammate DNF
      correlation +0.11 isn't simulated).
- [ ] Teammate-battle uncertainty: a larger per-driver season drift, or a
      driver-form model.
- [ ] Price fastest lap, safety car / red flag, rain (F1-3: per-circuit rates from track status
      and weather), and sprint markets.
- [ ] Refresh the Polymarket sync and repricing on a schedule during race
      weekends.

## Market making

- [x] As-of diagnostics, Polymarket minute prices and trade tape, maker replay, tests (Baku).
- [ ] **Migrate to CLOB V2** (found in F1-0): `markets/polymarket/trade.py` signs with the V1
      `py-clob-client==0.34.6`, and V1-signed orders stopped working on 2026-04-28. Move to
      `py-clob-client-v2` (the order struct and EIP-712 domain version changed), re-test the
      dry run, and only then enable trading.
- [x] Keep `markets record` running through every race weekend (LaunchAgent, F1-0).
- [ ] Fetch `markets trades` after each race.
- [ ] Replay with recorded book depth (F1-4): queue position and competing makers,
      instead of the touch/through bounds.
- [ ] **Stage-aware taker (F1-4):** in the 2026 sweep, trades after FP3 and qualifying lost
      −$2,353 while FP1/FP2/sprint trades made +$1,944. Test a strategy that stops
      re-trading late in the weekend, on events after Baku (not tuned on these).
- [ ] **Maker options (F1-4):** time-to-next-session inventory skew (Avellaneda-Stoikov style);
      pull windows for every session type; markout-driven widening; liquidity
      rewards as a replay P&L line; optional fractional-Kelly caps.
- [ ] Flatten or hedge inventory before qualifying (F1-4) (Baku's biggest losses were
      pre-qualifying shorts).
- [ ] Replay across every backtest race once their Polymarket tapes are
      fetched; only then tune half-spread, limits and the disagreement filter.
- [ ] Live maker watch list: fair vs book depth and recent flow for upcoming
      markets, flagging where a quote is +EV.

## Engineering

- [x] Web app (`racinglines/web/`): predictions, histories, backtests, Polymarket maker orders.
- [ ] Public/JSON API endpoints next to the admin pages.
- [ ] **Condition in-weekend forecasts on completed rounds.** Once Q1 has run, fix
      who has qualified and use the Q1 times. Also use split times from disrupted
      Timed Training sessions.
- [ ] Market-making loop (F1-5): re-quote linked markets automatically when the model or
      book moves, within per-market and total exposure limits.
- [ ] Find a venue that lists downhill markets. Polymarket has none as of 2026-09.
- [x] In-progress events are forecast with their real start lists and saved against their race.
- [ ] Have `forecast_season` read `scheduled` events (no start list yet) as named rounds instead of `remaining_round`.
- [ ] Ingest on a schedule: download, then `racinglines mtb_dh ingest` for new rounds.
- [ ] Ingest the other input formats (copy/paste, HTML, JSON) into the database.

- [x] Pinned `requirements.txt` (pipeline) and `requirements-docs.txt` (mkdocs).
- [x] `pyproject.toml`: `pip install -e .` installs the `racinglines` command.
- [ ] Run `python scripts/build_readme.py --check` in CI or a pre-commit hook, so the README
      can't drift from the docs.
- [ ] Tests: parser fixtures (one file per format era), `event_format`,
      `actual_event_points`, the rider-ID normalization check.
- [x] PostgreSQL database instead of re-parsing files every run.
- [x] `.gitignore` (ignores `data/`, generated outputs, `site/`, Python and editor files).
