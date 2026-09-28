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

- [x] Build: name aliases, the shared live core, the F1 adapter, the Live tab's F1
      body, the demo taker, operations, a rehearsal on Baku (items B0–B8, cloud build-out 29 Sep; the Mac rehearsal under the LaunchAgent is Thursday's).
- [ ] Checkpoints: Polymarket listing Wed 30 Sep; the scenario chosen Thu 1 Oct 18:00 PDT;
      the book opens Thu 20:30 PDT.
- [ ] After the race (Mon 5 Oct): settle and reconcile, report with a fair-price scorecard.

**P1 · Next two weeks: consolidate the live platform**

- [ ] Singapore (round 17, sprint, 11 Oct): run it the same way if Polymarket still hasn't listed it. Ready: `live/f1/2026-17.toml`; the sprint stages rehearsed on the Dutch GP (`live/f1/2026-12.toml`).
- [x] A repeatable report command for any live event: `racinglines live report` ([Live events](#live-events)).
- [x] Settle the Whistler private book in the database, into the demo maker's story (`live_events`; the owner runs the migration and `racinglines live settle` locally).
- [x] A per-market loss cap or two-sided long-shot quotes in the shared quoting core (both built, off by default: the owner decides; [decision log](f1-live-roadmap.md#11-decision-log)).
- [ ] Watch for Polymarket listings: F1-8 starts the first weekend with markets.

**P2 · When Polymarket lists F1 again: paper-trade validation** ([F1-8](#paper-trading))

- [ ] Profiles A and C live; compare fills and markouts with the replay, weekend by weekend.
- [ ] Sizing after 4–6 live weekends; walk-forward with the new rounds; bankroll-aware sizing.
- [ ] Real orders only with the owner's approval; CLOB V2 signing is done and dry-run tested
      ([Market making](#market-making)).

**P3 · Models and data**

- [ ] F1 ([F1 model](#f1-model)): promote `gridq+pretrain` (owner's OK), the
      `rookie` variant for profile A, the stage-aware taker on live
      weekends (2025 didn't confirm it), book-depth replay once enough books are recorded.
- [ ] **Downhill points validation**, the top downhill item ([Points validation](#points-validation)),
      then downhill data and model ([Data](#data), [Model](#model)).
- [ ] **High priority for the next cloud session: the downhill [Data](#data) items** (owner,
      2026-09-28): slug probing, canonical venue names, Elite/Junior Women, start order, weather,
      the 2021 PDFs. Most need ChronoRace (`prod.chronorace.be`), which the cloud network policy
      blocks: allow it in the environment first, or do them locally.

**P4 · Platform and business**

- [ ] A live timing feed (F1 SignalR or OpenF1) for in-session updates; in-race trading (F1-7) only
      if the owner decides to trade during races.
- [ ] Kalshi and other exchanges ([F1-9](#exchanges)); find a venue that lists downhill markets.
- [ ] **Move to Google Cloud:** the data bucket is up ([Data](data.md#data-bucket)) and the
      [proposal](google-cloud.md) is written (Cloud SQL, Cloud Run, Scheduler, service identities, about
      $28–35 a month at list prices). Next: the owner's choices (database tier, recorder shape, domain).
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
- [x] Store the tables in the `points_schemes` database table (per competition,
      era and round kind), and have the model read them from there: `racinglines mtb_dh points
      import`, and `--points db` on `forecast` and `backtest` (default: the schema's placeholders).
      The entry file `sports/points/uci_dhi_wc.toml` holds placeholders for every era until the
      official scales are in (2026-09-28, cloud build-out).
- [ ] Check the edge cases:
  - [ ] DNF/DSQ in the Final: zero points, or last-place points?
  - [ ] Ties
  - [ ] Protected or wildcard riders
  - [ ] Bonus or double-points rounds
- [ ] **Reconcile:** `racinglines mtb_dh points check --season 2026 --through-round 7
      --standings …` compares each rider's cumulative total with the official standings
      (built; needs the official tables and standings). Every rider should match exactly.
      Repeat for one past season.
- [x] A test that pins those totals (`tests/test_points.py`): it checks every standings file in
      `sports/points/standings/` and skips until the owner adds one.
- [ ] Re-run `season` and `backtest`, and refresh the tables in the docs and README.

## Data

- [x] **Use UCI rider IDs** (code, 2026-09-28, cloud build-out; synthetic tests, unverified against
      the live API): the downloader writes a `UCI ID` column, the parser reads it (older files parse
      as before), and ingest matches `athlete_identifiers(scheme="uci")` before names and reports
      a UCI ID shared by two athletes. `racinglines db merge-athletes KEEP DROP` merges them.
- [x] Re-download the downhill files (UCI IDs) and re-ingest (2026-09-28, locally; [Data changes](data-changes.md)):
      584 results moved onto the UCI-matched athlete, 1,090 UCI identifiers.
- [x] Merged 53 of the 58 reported pairs (2026-09-28). Five stay: both rows are in saved forecast run 1287
      ([Data changes](data-changes.md)).
- [x] **2021 PDFs** (Leogang, Les Gets) and PDF-only Timed Training rounds: read by
      `download --pdf-results` (backfill only) and ingested 2026-09-28 (775 results).
- [ ] 2019–2020 PDFs: the text layer is unreadable font codes, so they'd need OCR.
      Low priority.
- [x] **Slug probing** in the downloader (`--probe START END`, 2026-09-28): all of 2021 finds exactly its
      six DH rounds.
- [x] Canonical venue names (`mont-ste-anne` → `mont-sainte-anne`,
      `vallnord`/`vallnord-pal-arinsal` → `pal-arinsal`): the database already stores every venue
      under its canonical slug (`venue_aliases`, checked on the snapshot: no duplicates); `mtb_dh parse
      --canonical-venues` does the same for the CSV path (off by default) (2026-09-28, cloud).
- [ ] Elite Women and Junior Women: download (`mtb_dh download --category 'Elite Women'` already works;
      ChronoRace is blocked in the cloud, so locally), then forecast with `--unraced-format last`.
      Done (2026-09-28, cloud, synthetic data): unraced rounds can take the category's own format
      (`--unraced-format last`, off by default); the default simulates every category in the 2026 elite
      men's format (a 30-rider final), which put all 24 riders of a synthetic women's field in the final.
      Enter the official formats per category in `sports/mtb_dh.toml` `[rounds.category_format]` (owner).
- [ ] Start order: it's in ChronoRace's start-list PDFs and possibly the JSON.
      Needed for track-evolution and weather effects. Blocked in the cloud (ChronoRace).
- [ ] Weather and track conditions (the PDFs have weather; `--conditions-file`
      exists but is empty). Blocked in the cloud (ChronoRace).
- [x] **2025 Polymarket F1 markets** downloaded and synced (2026-09-27: 23 of 24 races have
      markets; minute prices and trades, no order books) and backtested in the cloud search.
- [ ] **F1 pre-season testing:** ingest FastF1's testing sessions, so the pre-season forecast
      sees what the market sees in a new-regulations year.
- [ ] Re-create event diagnostics and scenarios where needed after the 2026-09-27 database
      rebuild (optional; sweeps, runs and market links came back from the snapshot).

## Model

- [x] **Calibration check** (2026-09-28, cloud build-out): `mtb_dh backtest --reliability` over
      all 43 rounds. Win and podium are close; top 10 and make-Final are too flat. Cause: too much
      shrinkage (`prior_n`). A lower `INCIDENT_THRESHOLD` and heavier-tailed ε (`--eps-df`) don't
      help ([Calibration](model.md#calibration)).
- [x] **New downhill defaults** (owner's OK, 2026-09-28): `prior_n` 0.5, half-life 240 days,
      junior weight 0.25. Better in every market on the 43 rounds; picked in-sample.
- [ ] Check the new downhill defaults on 2026's next rounds (out of sample).
- [ ] Owner: make `--unraced-format last` the default? Juniors' unraced rounds are simulated in the elite
      men's 30-rider-final format today; with their own format, the 2026 MJ leader's make-Final odds for
      the next round go from 92% to 73% (committed snapshot, 2,000 sims). Changes junior and women's prices.
      Per-round-type incident rates tried too: no gain.
- [x] A tuning sweep over all 43 rounds (2026-09-28, cloud build-out): `prior_n` 0.5, half-life
      240 days, junior weight 0.25 is better in every market ([Calibration](model.md#calibration)).
      Practice weight: flat between 0 and 1, 0.5 kept.
- [x] Rider × venue effects: tried (2026-09-28, cloud build-out), no gain on the 43 rounds
      ([Calibration](model.md#calibration)); not built in.
- [x] Time trends within a season (2026-09-28, cloud build-out): a faster-improving-rookie drift
      is worse; none detected beyond what the half-life already tracks
      ([Calibration](model.md#calibration)).
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
- [x] **Monte Carlo seed setting**: sweep and profile setting `seed`, unset = today's fixed seed
      (42), so noise replicates in a search are independent draws (2026-09-28, cloud build-out).
- [x] **Driver layer in a new season (F1-2):** the `rookie` variant fades a finished rookie
      season's teammate comparisons to a quarter. Small gain on win odds before qualifying;
      teammate head-to-heads better in 2026, worse in 2021 ([F1 evaluation](f1-evaluation.md#model-variants-f1-roadmap-f1-2-f1-3)).
      Not promoted (2026-09-28, cloud build-out).
- [ ] Decide whether profile A's model takes `rookie` (`gridq+pretrain+reset+rookie`, run 1289), after
      live weekends.
- [ ] Teammate-battle uncertainty: a larger per-driver season drift, or a driver-form model.
- [x] Price fastest lap, safety car / red flag, rain (F1-3): `models/position_sim/props.py`,
      `racinglines f1 props`; opt-in kinds for a live book (2026-09-28, cloud). Per-circuit rates
      don't beat the field rate on 2022–2026 ([F1 roadmap](f1-roadmap.md#decision-log)).
- [ ] Props next: calibrate fastest lap on stored stage runs; map Polymarket's prop markets in the
      sync classifier (they're `unmodeled` today) and backtest against their prices; sprint markets.
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
- [x] Stage-aware taker out of sample on 2025: **not confirmed** (−$316 on 23 weekends, against +$1,874
      in-sample on 2026; [Market making](market-making.md#strategy-options-f1-roadmap-f1-4)).
- [ ] The stage-aware taker on the live weekends, before anyone uses it.
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
      instead of the touch/through bounds. The queue model is built (`--fill queue`,
      [queue rule](market-making.md#the-queue-rule), tested on synthetic books, 2026-09-28,
      cloud build-out); running it needs several weekends of `markets record` books.
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
- [x] **Bankroll-aware sizing** and a **deployed-capital cap** in the backtest: sweep settings
      `bankroll` and `max_deployed`, unset by default (2026-09-28, cloud build-out; synthetic tests).
- [ ] Use them live: the signal engine sizes from the account's balance and deployed capital, once
      4–6 live weekends pick a rule. Later, fractional sizing once recorded depth supports it.
- [x] Fix: an h2h-only market-kinds sweep crashed on 2025 (`KeyError: 'cond'` in the maker replay's
      summary on a weekend with no market of the chosen kinds; 2025 lists no h2h before round 8).
      An empty weekend now summarises to zero (2026-09-28, cloud build-out).

## Live events

How it works: [Live events](live-events.md). First run: the Whistler downhill final, 27 Sep 2026.

- [x] Live tab for both demo users; downhill finals from UCI timing, rank probabilities, maker quotes,
      a simulated private book (1,000 anonymous takers with event budgets), P&L by venue, replay logs.
- [x] Replay on the Live tab once an event is over (timeline, step, play), with the book rebuilt from the
      logged fills; P&L by venue on Positions (2026-09-27).
- [ ] **F1 live test, round 16 (Bahrain GP at Sepang, 2–4 Oct 2026):** a mock private book on all 100
      usual Polymarket race markets, updated at session ends, as a shared live core plus an F1 adapter.
      Build items B0–B8 and the runbook: [F1 live test](f1-live-roadmap.md).
- [ ] Singapore (round 17, sprint weekend, 11 Oct): the same run if Polymarket still hasn't listed it. Code-ready (2026-09-29): launch spec `live/f1/2026-17.toml`; the F1 adapter's sprint stages (after SQ, after Sprint) rehearsed on the Dutch GP, round 12 (`live/f1/2026-12.toml`: seven updates, 100 markets, settles). Waits for the owner's decision after round 16.
- [x] A **report command** for any live event (the Whistler report, made repeatable): P&L by update, the
      crowd, the demo taker, the fair-price scorecard (`racinglines live report <spec> --pdf`, 2026-09-29).
- [x] Re-run an event's pricing from its logged raw feed: `racinglines live reprice <spec>` (downhill; every
      raw response re-priced with today's code and the recorded inputs, scored against what was quoted live;
      2026-09-29). On 38 sampled Whistler updates the re-price (v2 throughout) scored a little worse than the
      live quotes (v1, then v2): Brier 0.0216 vs 0.0202 on win, 0.0430 vs 0.0365 on podium.
- [x] Two-sided long-shot quotes (or a per-market loss cap) so the maker doesn't pile up shorts in unlikely
      winners: `[live.quoting] max_loss` and `floor_bid` in `markets/quoting.py` (2026-09-29), both off by default.
      Measured on Baku's rehearsal in the [decision log](f1-live-roadmap.md#11-decision-log).
- [ ] Owner: switch the loss cap on for round 16 or not (`max_loss = 500` in `live/f1/2026-16.toml` `[live.quoting]`).
- [x] Settle the Whistler private book in the database and add it to the demo maker's story: the
      `live_events` table (migration `a3f5c8d1e7b2`) and `racinglines live settle <spec>`; the story dates
      private-book events from it (2026-09-29). Locally: `alembic upgrade head`, then
      `racinglines live settle live/mtb_dh/20260925_mtb.toml`. The final's results still come from the usual
      downhill download and ingest (the event is `in_progress` in the snapshot).
- [ ] A live timing feed (F1 SignalR or OpenF1) for in-session updates; compared in the
      [F1 live test](f1-live-roadmap.md#5-live-data-source) plan.

## Exchanges

Phase [F1-9](f1-roadmap.md#f1-9-more-exchanges-kalshi-others).

- [x] **Kalshi connector** (`racinglines/markets/kalshi/`): markets (with their resolution rules), prices,
      trade tape, price history, order books, and post-only orders behind `KALSHI_TRADING_ENABLED`
      (`racinglines markets --exchange kalshi …`). Built on mocked responses only (2026-09-28, cloud):
      the cloud network blocks Kalshi's API. `venue_replay.Kalshi` is its backtest venue; the Polymarket
      paths (sweep, maker replay, season strategy, head-to-head pairs, links export, fetches) now read
      `exchange = 'polymarket'` only, so synced Kalshi links can't leak into them.
- [x] Kalshi against the live read-only API (2026-09-28, locally): `sync --closed`, trades, history and
      books run into a copy of the database. Fixed: series found by ticker (`KXF1*`; "Qualify in Pole
      Position" doesn't say F1), sprints unmodeled (the sprint winner and sprint pole were read as the
      race's), top 10 → `race_top10`, head-to-heads ("Will A beat B in the racing matchup?") with the
      race from the ticker's code, `volume_fp`, `orderbook_fp` (books came back empty), dollar strings in
      historical candlesticks (read as cents), and Kalshi's `/historical` endpoints for markets settled
      before its cutoff (older events came back with no markets). 2026: 15 weekends, 1,847 modeled links.
- [x] **Whistler replay** (2026-09-28): `PrivateBook.from_run` now re-derives Whistler's recorded book fill for
      fill. Two causes, both recorded in the run folder's `replay.json` ([Live events](live-events.md#kept-for-replay)):
      the crowd's rate rule changed mid-event, and two overlapping loops logged polls in the same second.
      Polls now log their rate. The test had always skipped (its module fixture pointed `paths.DATA` at a
      temp folder).
- [ ] Downhill `live run`: take a lock in the run folder like F1's step, so a restart can't leave two loops
      polling (what happened at Whistler, 22:38–22:39).
- [x] Kalshi in the maker replay and the demo maker's record (`f1 demo-history --venue kalshi`, PR #10):
      per-ticker grouping, Kalshi's maker fee, `RACINGLINES_KALSHI_VENUE=1` for the board / race / Positions
      pages. Feed differences vs Polymarket: [Kalshi history](kalshi-history.md).
- [x] Kalshi: the first real pull (2025–26, owner's device) replayed and summarised: how many of the maker's
      quotes Kalshi's tape fills, by market kind ([Kalshi history](kalshi-history.md#first-real-run-2026-09-28));
      Kalshi at parity with Polymarket in the app, on by default (`RACINGLINES_KALSHI_VENUE=0` hides it): Positions tiles and
      curve, Strategy switch, `/markets/kalshi`, race-page column and chart, Lab replay
      ([Kalshi history](kalshi-history.md#in-the-app)).
- [ ] Kalshi: the sweep and taker paper signals reading Kalshi's markets (F1-9's "done when"). No order has
      been sent; `KALSHI_TRADING_ENABLED` stays unset.
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
- [x] Admin overview: the takers' P&L leaves out the `polymarket-takers` replay counterparty and shows it
      on its own line (2026-09-28, cloud build-out).
- [ ] Remove the `demo_context` bubbles before real users.
- [ ] Before anything goes beyond a private demo: check F1's data terms, OpenF1's non-commercial terms,
      and settlement rules for relocated or cancelled races.
- [x] JSON API endpoints next to the pages: read-only events and athletes, behind the login,
      off unless `RACINGLINES_JSON_API=1` ([JSON API](webapp.md#json-api), 2026-09-28, cloud).
- [ ] JSON API, owner: what's public (results only, or prices), who can use it (accounts, keys, no
      login), data terms, rate limits ([open questions](webapp.md#json-api)).
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
