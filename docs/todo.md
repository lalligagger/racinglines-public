# Roadmap

The one place for what's next, across every sport and track, in priority order.
Tick items off where they are listed in the detail sections below. The priorities
point at them rather than repeating them.

| Plan | What it's for |
|---|---|
| **This page** | The priorities, and every open item (detail sections below) |
| [F1 live test (round 16)](f1-live-roadmap.md) | The P0 working plan for 2–4 Oct: build items, runbook, backup plans, decision log |
| [F1 roadmap](f1-roadmap.md) | The F1 phases (F1-0 … F1-9), their ground rules and decision log |

## Priorities

<!-- readme: todo-summary -->

**P0 · This week: the first live F1 test** (round 16, the Bahrain GP at Sepang, Malaysia, 2–4 Oct 2026)

Polymarket has listed no F1 race markets since 28 Aug, none for rounds 16 or 17. So
the test is a mock private book like the Whistler downhill run. We price all 100 of
Polymarket's usual race markets (winner, podium, pole, head-to-head, constructor)
anyway, and update at session ends only. It's built as one shared live core plus an
F1 adapter, keeping the platform multi-sport. Plan: [F1 live test](f1-live-roadmap.md).

- [ ] Build: name aliases, the shared live core, the F1 adapter, the Live tab's F1
      body, the demo taker, operations, a rehearsal on Baku (items B0–B7).
- [ ] Checkpoints: Polymarket listing Wed 30 Sep; the scenario chosen Thu 1 Oct 18:00 PDT;
      the book opens Thu 20:30 PDT.
- [ ] After the race (Mon 5 Oct): settle and reconcile, report with a fair-price scorecard.

**P1 · Next two weeks: consolidate the live platform**

- [ ] Singapore (round 17, sprint, 11 Oct): run it the same way if Polymarket still hasn't listed it.
- [ ] A repeatable report command for any live event ([Live events](#live-events)).
- [ ] Settle the Whistler private book in the database, into the demo maker's story.
- [ ] A per-market loss cap or two-sided long-shot quotes in the shared quoting core.
- [ ] Watch for Polymarket listings: F1-8 starts the first weekend with markets.

**P2 · When Polymarket lists F1 again: paper-trade validation** ([F1-8](#paper-trading))

- [ ] Profiles A and C live; compare fills and markouts with the replay, weekend by weekend.
- [ ] Sizing after 4–6 live weekends; walk-forward with the new rounds; bankroll-aware sizing.
- [ ] Real orders only with the owner's approval; CLOB V2 signing is done and dry-run tested
      ([Market making](#market-making)).

**P3 · Models and data**

- [ ] F1 ([F1 model](#f1-model)): promote `gridq+pretrain` (owner's OK), a seed setting, the
      driver layer in a new season, fix the h2h-only sweep crash, the stage-aware taker out of
      sample, book-depth replay once enough books are recorded.
- [ ] **Downhill points validation**, the top downhill item ([Points validation](#points-validation)),
      then downhill data and model ([Data](#data), [Model](#model)).

**P4 · Platform and business**

- [ ] A live timing feed (F1 SignalR or OpenF1) for in-session updates; in-race trading (F1-7) only
      if the owner decides to trade during races.
- [ ] Kalshi and other exchanges ([F1-9](#exchanges)); find a venue that lists downhill markets.
- [ ] **Move to Google Cloud:** the data bucket is up ([Data](data.md#data-bucket)); next, a proposal
      for Cloud SQL, Cloud Run (web app, pollers, signal engine), Cloud Scheduler and service identities.
- [ ] New sports, beta testers and collaborators, B2B ([Business](#business-and-collaborators)).
- [ ] Before real users: remove the `demo_context` bubbles, fix the admin P&L, check data and settlement terms.

<!-- /readme -->

Everything open, by area, is in the sections below.

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
- [x] **2025 Polymarket F1 markets** downloaded and synced (2026-09-27: 23 of 24 races have
      markets; minute prices and trades, no order books) and backtested in the cloud search.
- [ ] **F1 pre-season testing:** ingest FastF1's testing sessions, so the pre-season forecast
      sees what the market sees in a new-regulations year.
- [ ] Re-create event diagnostics and scenarios where needed after the 2026-09-27 database
      rebuild (optional; sweeps, runs and market links came back from the snapshot).

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

- [x] **Evaluation (F1-1):** `racinglines f1 compare RUN_A RUN_B` (paired ± 2 SE, log loss,
      reliability bins) and `racinglines f1 matrix`; model-vs-Polymarket Brier for every market kind.
- [x] **Front of the grid (F1-2):** `gridq` closes the gap to the grid-only baseline after qualifying.
- [x] **Pre-practice pricing (F1-2):** `pretrain` (a no-practice finishing model) closes the regression.
- [x] **Chaotic-race tail and correlated DNFs (F1-3):** `tail` is neutral at every stage; not promoted.
- [x] **Regulation reset:** `reset` down-weights earlier seasons' car pace in a new-regulations
      season; `gridq+pretrain+reset` is the most accurate combination and profile A's model.
- [x] Practice pace prior; car shared by teammates (2026-09-26).
- [ ] **Promote `gridq+pretrain` to the default** (owner's OK: it changes live prices; re-run the
      sweep and `UPDATE_GOLDEN` in the same change). Owner, 2026-09-27: keep iterating first. The
      paper-trading profiles pick their model through settings, so they don't wait on this.
- [ ] **Monte Carlo seed setting** (default: today's fixed seed), so noise replicates in a search
      are independent draws rather than re-runs of the same one.
- [ ] **Driver layer in a new season (F1-2):** the teammate offset carries last season (2026:
      Russell priced far above Antonelli after 3 GPs). Candidate: faster forgetting for
      second-year drivers, judged on every season, not 2026 alone.
- [ ] Teammate-battle uncertainty: a larger per-driver season drift, or a driver-form model.
- [ ] Price fastest lap, safety car / red flag, rain (F1-3: per-circuit rates from track status
      and weather, `race_disruption`), and sprint markets.
- [x] Polymarket sync and repricing on a schedule during race weekends: the recorder re-syncs
      every 30 min; the signal engine prices each stage as its data arrives (every 5 min).

## Market making

- [x] As-of diagnostics, Polymarket minute prices and trade tape, maker replay, tests (Baku).
- [x] Keep `markets record` running through every race weekend (LaunchAgent, F1-0).
- [x] Fetch trades after each session: the signal engine pulls prices and trades for the
      weekend's markets on every run.
- [x] **Maker options (F1-4):** flatten before qualifying, info-timed skew, markout-driven
      widening. None beats the default maker.
- [x] **Stage-aware taker (F1-4):** in the sweep (+$1,874 in-sample on 2026).
- [ ] Confirm the stage-aware taker out of sample (2025, and the live weekends).
- [x] Replay across every race with a tape (2025 and 2026), then tune: the `params-4h` cloud
      search over 1,161 settings combos, judged on both seasons.
- [x] Live watch list: the Markets page lists every open Polymarket F1 market with the profile's
      call and heat; new markets raise alerts (macOS, ntfy, webhook, log).
- [x] **Migrate to CLOB V2** (found in F1-0): `markets/polymarket/trade.py` signs with
      `py-clob-client-v2==1.2.0`; dry runs sign locally (V2 struct, EIP-712 domain 2) and the
      tests recover the signer (2026-09-28, cloud build-out).
- [ ] **First real V2 order** (owner): post, list and cancel one small post-only order, unverified
      against the live CLOB so far. `POLYMARKET_TRADING_ENABLED` stays unset until then.
- [ ] Replay with recorded book depth (F1-4): queue position and competing makers,
      instead of the touch/through bounds. Needs several weekends of `markets record` books.
- [ ] Liquidity rewards as a replay P&L line; optional fractional-Kelly caps.

## Paper trading

Phase [F1-8](f1-roadmap.md#f1-8-live-paper-trade-validation-polymarket); how it works:
[Paper trading](paper-trading.md). Recommendations and paper fills only; no order is placed.

- [ ] Run profiles A (demo taker) and C (demo maker) live on every weekend Polymarket lists, through
      2026 and into 2027. Built and scheduled (the signal engine); Polymarket has listed no race since
      round 15 (28 Aug), so nothing to trade yet at rounds 16–17.
- [ ] After each weekend: compare live fills and markouts with the backtest's replay of the same
      weekend (conservative "through" fill rule) and log the markouts.
- [ ] After 4–6 live weekends: decide on sizing (e.g. A-lite → A).
- [ ] Walk-forward re-run of A, A-lite, C, B (#06) and A′ (#08) with rounds 16–17 added.
- [ ] **Bankroll-aware sizing** and a **deployed-capital cap** per account (bankrolls are recorded;
      sizing is fixed today). Later, fractional sizing once recorded depth supports it.
- [ ] Fix: an h2h-only market-kinds sweep crashes on 2025 (`KeyError: 'cond'` in the
      position-market step when a season has no position markets).

## Live events

How it works: [Live events](live-events.md). First run: the Whistler downhill final, 27 Sep 2026.

- [x] Live tab for both demo users; downhill finals from UCI timing, rank probabilities, maker quotes,
      a simulated private book (1,000 anonymous takers with event budgets), P&L by venue, replay logs.
- [x] Replay on the Live tab once an event is over (timeline, step, play), with the book rebuilt from the
      logged fills; P&L by venue on Positions (2026-09-27).
- [ ] **F1 live test, round 16 (Bahrain GP at Sepang, 2–4 Oct 2026):** a mock private book on all 100
      usual Polymarket race markets, updated at session ends, as a shared live core plus an F1 adapter.
      Build items B0–B8 and the runbook: [F1 live test](f1-live-roadmap.md).
- [ ] Singapore (round 17, sprint weekend, 11 Oct): the same run if Polymarket still hasn't listed it.
- [ ] A **report command** for any live event (the Whistler report, made repeatable): P&L by update, the
      crowd, the demo taker, the fair-price scorecard.
- [ ] Re-run an event's pricing from its logged raw feed (replay today shows what was seen live; this
      would re-price it with a new model).
- [ ] Two-sided long-shot quotes (or a per-market loss cap) so the maker doesn't pile up shorts in unlikely
      winners.
- [ ] Settle the Whistler private book in the database and add it to the demo maker's story.
- [ ] A live timing feed (F1 SignalR or OpenF1) for in-session updates; compared in the
      [F1 live test](f1-live-roadmap.md#5-live-data-source) plan.

## Exchanges

Phase [F1-9](f1-roadmap.md#f1-9-more-exchanges-kalshi-others).

- [ ] **Kalshi connector** (`racinglines/markets/kalshi/`): markets, prices, trade tape, and
      order placement behind a flag. Registered in `markets/venues`.
- [ ] Other exchanges, if they list motorsport or cycling markets with real depth, including one for
      downhill (none on Polymarket as of 2026-09).
- [ ] Before any real order: one small V2 order checked against the live CLOB ([Market making](#market-making)).

## Engineering

- [x] Web app (`racinglines/web/`): predictions, histories, backtests, Polymarket maker orders.
- [x] Pages and routes that match their names (Markets, Strategy, Positions, My Book, Lab); old
      URLs redirect.
- [x] Demo accounts with a backtest-replay track record, disposable demo sessions, interaction
      logging.
- [x] One settings schema for sweeps, the Lab and cloud searches; cloud searches from a database
      snapshot (an exact replica).
- [x] Pinned `requirements.txt` (pipeline) and `requirements-docs.txt` (mkdocs).
- [x] `pyproject.toml`: `pip install -e .` installs the `racinglines` command.
- [x] `scripts/build_readme.py --check` runs in the pre-push hook, with `mkdocs build --strict`.
- [x] PostgreSQL database instead of re-parsing files every run.
- [x] `.gitignore`: `data/` stays ignored except the allow-listed minimal set for cloud runs.
- [ ] Admin overview: the takers' P&L includes the `polymarket-takers` system account; filter it out.
- [ ] Remove the `demo_context` bubbles before real users.
- [ ] Before anything goes beyond a private demo: check F1's data terms, OpenF1's non-commercial terms,
      and settlement rules for relocated or cancelled races.
- [ ] Public/JSON API endpoints next to the admin pages.
- [ ] **Condition in-weekend forecasts on completed rounds** (downhill). Once Q1 has run, fix
      who has qualified and use the Q1 times. Also use split times from disrupted
      Timed Training sessions.
- [ ] Market-making loop (F1-5, deferred): re-quote linked markets automatically when the model or
      book moves, within per-market and total exposure limits.
- [ ] Have `forecast_season` read `scheduled` events (no start list yet) as named rounds instead of `remaining_round`.
- [ ] Ingest on a schedule: download, then `racinglines mtb_dh ingest` for new rounds.
- [ ] Ingest the other input formats (copy/paste, HTML, JSON) into the database.
- [ ] Tests: parser fixtures (one file per format era), `event_format`,
      `actual_event_points`, the rider-ID normalization check.

## Business and collaborators

- [ ] **New sports.** F1 (large audience, deep markets) and UCI downhill (niche, no exchange
      markets) are the two endpoints. Candidates between them: MotoGP, WEC, IndyCar, Formula E,
      road-cycling classics and grand tours, XC/enduro, alpine skiing. Rank by audience, data
      availability and exchange listings. No grassroots or local-league plans.
- [ ] **Beta testers and collaborators:** accounts and onboarding; contributor docs; a code-only
      public mirror or invited access to the private repo (it is private only because of the
      committed data set).
- [ ] **B2B:** selling the prediction models remains open.
- [ ] Trade on exchanges only after paper-trade validation (F1-8).
