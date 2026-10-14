# Sports and exchanges: status

Where every sport stands on every exchange: what data we hold, what prices it, what has been backtested and how far
the result can be trusted, and what runs live or on paper. **Reviewed in full on 2026-10-14** against the code on
`staging` at `ba839f3` (what production runs once [PR #180](https://github.com/lalligagger/racinglines-public/pull/180),
the staging-to-main promotion, merges; "promotion pending" marks the few cells where that matters) and against
production's database, read-only, through the MCP server (`overview()` and `sql`, 04:50 UTC). Every count below
carries its query date; a count with no date is from an earlier review and says so.

Nothing here trades real money: `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are unset, and OG.com has
no order code at all. The fantasy league trades F$ on recorded books ([Alpha layout](alpha-layout.md)). Venue prices
and tapes are shown to signed-in users with their source and fetch time, under the terms-pending (#aintcare) warning
(owner, 2026-10-14).

**The short version.** Only **F1 on Polymarket** has a real model, a backtest that held up in a held-out season, and
live paper trading wired up; Polymarket lists F1 race markets again, from Italy (6 Sep) through São Paulo (8 Nov).
Every other cell is one or more steps short: F1 on Kalshi has a tuned maker and a taker result that rests on two
weekends a season; NASCAR and MotoGP price from the one engine's results core with no calibration check yet
([C48](todo.md#models-the-one-engine)), so their prices are **unvalidated**; OG.com is recorded and replayable with no strategy
tested on it; downhill has a real model and no exchange; IndyCar, Le Mans and SailGP are tapes with no model; road
cycling has a first model, admin-only. The three recorders run every 5 minutes, every day, on all three venues (books
in Postgres to 04:49 UTC today on each).

**The 3 × 3 the soft launch was planned around** (F1, NASCAR, MotoGP × Polymarket, Kalshi, OG.com), counts from
production on 2026-10-14:

| | Polymarket | Kalshi | OG.com |
|---|---|---|---|
| **F1** | Real model, robust taker A; 8,602 links, 898 open; race markets for rounds 13 to 20 | Real model; maker K tuned; 4,272 links, 74 open (futures; the US GP lists 2 to 4 days out); books every 5 min since 30 Sep | Season futures plus per-GP race markets since Malaysia (22 links each for rounds 16 and 17); 808 trades since 9 Oct |
| **NASCAR** | 1,721 links, 927 with a race, 229 open; books and trades recorded; no backtest of its own | Results core, in-sample demo paper; 14,490 links, 7,994 with a race, 529 open; next race (18 Oct) linked | 17 champion contracts, 69 trades since 9 Oct; uncalibrated season sim, offline |
| **MotoGP** | 209 links, 131 with a race, 29 open; 49 trades since 7 Oct; no strategy tested | Results core, race win only, in-sample demo paper; 344 links, 289 with a race, 33 open; **no round after Austria (18 Sep) in production** until #134's calendar step runs (promotion pending) | **Empty:** not listed |

## How to read the status

| Word | Means |
|---|---|
| **Real model** | A model with its own features, walk-forward backtested on results and compared with a baseline and the market (F1: [F1 evaluation](f1-evaluation.md); downhill: [Evaluation](evaluation.md)) |
| **Results core** | The one engine (`GlobalModel`, [Backtest core](backtest-core.md#one-engine-schema-declared-inputs)) at the results level: a probit strength model on recent finishing positions and the schema's declared inputs, one price per race before the weekend. It runs in the replays and prices the board's columns. Its calibration by probability bucket has not been checked (C48), so read its prices as **unvalidated**, not as edge |
| **Quote only** | The market is synced and recorded; no model prices it |
| **Tape only** | The sport's schema has `model_family = "none"`: links are `unmodeled`, prices, trades and books are recorded, nothing is priced |
| **Robust** | Positive in the target season (2026) **and** the held-out season (2025), beyond the noise floor ([promotion rule](f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default)) |
| **In-sample** | The settings were chosen on the same races they are scored on |
| **Unvalidated** | Priced, but never scored by probability bucket against results or closing prices |

Counts of links, trades and books are what production's Postgres held on 2026-10-14; the recorder's hourly archive
pass moves cold rows to Parquet (`data/archive/markets/`), so a trade count is the hot window, not the whole tape.
`racinglines backtest coverage` ([CLI](cli.md#racinglines-backtest-coverage)) counts both stores per sport ×
exchange × kind × season; run it on the VM for the full picture.

## The status matrix

One row per sport and exchange that lists it (a venue that lists nothing for a sport is left out; see
[Not listed anywhere](#not-listed-anywhere)). Links: total / with a race / open, production 2026-10-14.

| Sport × exchange | Data we hold | Model | Backtest (caveats) | Live / paper | Main gap |
|---|---|---|---|---|---|
| **F1 × Polymarket** | 8,602 links / 5,070 / 898 (4,323 `unmodeled`: props and markets no kind covers); 2025–26 race weekends and championships; 2026 race markets for every round from Italy (138 links) to São Paulo (266), Singapore 272; books every minute since 3 Oct (919,164 snapshots in Postgres, last 04:49Z); 6,199 trades in the hot window since 4 Oct | **Real model** (the one engine's laps core, stored as `f1_sector_sim`) for race kinds; season forecast for champion, season-wins and standings head-to-head | **Robust.** Taker profile A (+$1,389 in 2026 / +$1,432 in 2025 at 16k sims, PR #85) and maker C; the overnight 106-job sweep kept A. Championship checkpoints **lost** in 2026 (−$566 to −$797, every variant). Five alpha styles (T1, T2, T5, T6, T8) carry their 2025 and 2026 backtests on the picker; T8 is in-sample ([Alpha layout](alpha-layout.md#picking-a-style-strategypick)) | Signal engine and paper positions for A and C, stage by stage; last stored signal Singapore after qualifying (2026-10-11 14:37Z). Paper positions 2,264 (2,182 settled, 41 weekends). Fantasy: every signed-in account trades F$ by hand on these recorded books (Trade tab) or follows a style | G1 evidence: CLV over 100 live bets ([Paper trading](todo.md#paper-trading)); #181's golden comparison against the Probalytics tape |
| **F1 × Kalshi** | 4,272 links / 4,165 / 74 (925 `unmodeled`); 2025–26 history, trades and hourly candles; **books every 5 minutes since 2026-09-30** (923,282 snapshots, last 04:48Z; `record_venues.sh`); 47,034 trades in the hot window since 9 Oct | **Real model** (same as above) | **Maker K** tuned (2026 +$490, 2025 +$659; tunable, each change logged). **Taker** fills at the touch since 2026-10-05 (book, else candle bid/ask): profile A at 16k +$2,332 / +$1,257, negative without its best two weekends in both seasons, so no edge shown ([Kalshi history](kalshi-history.md#profile-a-on-kalshi-at-16k-2026-10-05)). Demo maker's Kalshi record 2025 +$193.39, 2026 −$118.84 (backfill) | Paper signals wired (`venue = kalshi`, U1; sprints on by default since 2026-10-06). Paper positions 2,632, all settled, last written 2026-09-30 (the backfill): at Singapore profile A took no Kalshi trade after FP1 | Books before 30 Sep: the Probalytics backfill (Kalshi books from 9 May 2026, [PR #181](https://github.com/lalligagger/racinglines-public/pull/181)); a taker result that survives dropping its best weekends |
| **F1 × OG.com** | 108 links / 44 / 20: 20 open season futures and, new since the 3 Oct review, **per-Grand-Prix race markets** (22 links each for Malaysia and Singapore, both closed); 74,213 book snapshots since 8 Oct; 808 trades since 9 Oct; settlement feed read hourly (`markets --exchange og settle`) | **Real model** for the champion markets (season forecast) and race kinds | **None run.** OG.com is a replay venue (#88); no champion or race replay has been reported on it ([Championship markets](championship-markets.md)) | Fair-price indicator only (`RACINGLINES_OG_VENUE`; on on the VM per the [48-hour report](report-48h.md), not re-checked today). No trading: needs FCM onboarding | Thin books; fee $0.02 unverified; per-GP contract rules in `exchanges/og.toml` still to write from the two race weekends seen |
| **NASCAR × Kalshi** | 14,490 links / 7,994 / 529 (14,071 `unmodeled`); 2026 season 40 events, 36 completed (results through Charlotte, 11 Oct); books in the 5-minute recorder; 33,814 trades in the hot window since 9 Oct; Phoenix (18 Oct) already 200 links | **Results core** (`[model] inputs = ["results", "qualifying", "fastest_lap"]`, `NascarCupRace` a challenger) for race win, top 3/5/10/20 and h2h; champion: #93 season sim, **not calibrated**, offline only | **Not robust.** Taker grid 2026 +$4,226 to +$5,479, 2025 −$242 to −$390 in every setting (Kalshi last-trade prices, so indicative). Nothing tuned. Calibration unchecked (C48) | Demo paper rows, **in-sample** (#110): Pro 2025 −$278.31 / 2026 +$6,525.45; Basic −$357.23 / +$2,657.23. Next-race fair price from the latest stored forecast, run 9937 (2026-10-11, data through 4 Oct); the forecast-refresh timer runs every 30 minutes and fetches results on race weekends | A held-out-positive result; the calibration check; the pre-race field from NASCAR's entry list (C46) |
| **NASCAR × Polymarket** | 1,721 links / 927 / 229 (1,611 `unmodeled`); each Sep–Oct race 42 to 44 links; books and trades recorded by `pm_sync.sh` (243 trades since 7 Oct) | Race kinds: same results core; champion: #93, not calibrated | **None of its own.** The demo backfill reused Kalshi's selected settings (matched 1 race, 30 Sep) | None since the demo backfill | A replay on its own tape, now that it is recorded |
| **NASCAR × OG.com** | 17 Cup Champion contracts, all open; books since 8 Oct; 69 trades since 9 Oct | Champion: #93, **not calibrated**, offline (`nascar season --quotes`) | **None** | None | Calibration of the season sim; OG.com lists no NASCAR race markets |
| **MotoGP × Kalshi** | 344 links / 289 / 33; 408 trades since 17 Sep; books in the recorder; production holds 2026 rounds through Austria (18 Sep) only: 15 events, no scheduled round, so no next-race price. The `forecast-refresh` MotoGP step in #134 files the calendar and results on its first pass after #180 deploys (promotion pending) | **Results core** (`inputs = ["results", "qualifying"]`; `MotoGPRaceChallenger` a challenger) for race win. Sunday race only: sprints not ingested. Champion and teams: **quote only** | **No verdict.** No held-out season (2025 lists no MotoGP race market on Kalshi); race-win log loss 0.0796 with no baseline comparison; calibration unchecked (C48: on the Indonesia GP the model's top three summed to 42.5% against Kalshi mids of 83.5%) | Demo paper rows, **in-sample**, 2026 only (11 races): Pro +$31.25, Basic +$7.70. Visible to every signed-in user after #180 (`audience = "all"`, owner's data-terms decision 2026-10-14) | The calendar on production; the calibration check; sprint results; champion classifiers |
| **MotoGP × Polymarket** | 209 links / 131 / 29 (all `unmodeled`); 49 trades since 7 Oct; books by `pm_sync.sh` (`PM_SPORTS`) | Champion: **quote only**. Race winners: the results core prices them on the board; the links stay `unmodeled` | **None** | None | A first replay; the champion needs sprints, schedule, standings ([Championship markets](championship-markets.md#what-pricing-motogps-champion-would-take)) |
| **Downhill × private book** | Whistler 2026 live event (7,703 fills); results 2021–26 from ChronoRace; 2026 season complete (8 rounds) | **Real model** (the one engine's run-times core, stored as `timed_runs`), walk-forward on 43 rounds | Walk-forward on results (Final-qualification error 38% below a uniform guess). No exchange tape, so **no market backtest** | Private book only (318 paper positions, 4 events). Off the Markets board since #163 (`markets_board = false`) | No exchange lists downhill; next World Cup spring 2027 |
| **IndyCar × Kalshi** | 1,374 links, all closed, none with a race | **Tape only** | None | None | Results source's terms forbid automated use (#75); season over until March 2027 |
| **Road cycling × Kalshi** | **0 links and 0 events on production** (2026-10-14); schema `road_cycling` (`KXCYCLING*`) built, no VM sync run | **Results core**, admin-only on the board since #163 (`audience = "admin"`); a stage-race GC model for the Eneco Tour is a draft ([PR #177](https://github.com/lalligagger/racinglines-public/pull/177)); PCS results live on the owner's Mac only | None on production | None | A results source with usable terms; the GC model's decision-log entries; a first VM data step (backup first) |
| **Le Mans × Kalshi** | Schema built (`le_mans`), no links on production | **Tape only** | None | None | No results source or model |
| **SailGP × Kalshi, OG.com** | OG.com 13 Championship Winner links, all open; Kalshi schema built, no links | **Tape only** | None | None | No results source or model |

**Buy-all is never a result.** `buy-all` (and the replays' `--buy-all`) buys one YES and one NO of every market to
prove it is found, priced and settled; a pair loses exactly its fees. Per the owner it is never shown in reporting or
the web app, and none of the numbers above come from it.

### Not listed anywhere

- **MotoGP on OG.com**, **IndyCar, road cycling and Le Mans on OG.com**: OG.com lists none of them (probed 2026-09-29).
- **Downhill, XCO/XCC, track, cyclocross, BMX**: no exchange lists mountain biking or track cycling. XCO results are
  fetchable from ChronoRace on the same weekend slugs, nothing is ingested, and there is no mass-start model.
- **Alpine skiing**: Kalshi and Polymarket list the February 2026 Olympic events only, no World Cup (owner's probe,
  2026-10-14); re-probe in November. Horse racing (blocked by law on both US venues), Formula E and rally: out of scope.

## Model status by sport

One engine, by owner rule (2026-10-11, [One engine](backtest-core.md#one-engine-schema-declared-inputs)): every
modelled sport prices with `GlobalModel`, and the schema's `[model] inputs` picks the core (results, laps or
run times). The older classes stay as challengers. What is left to retire is tracked as Core C56: the first package
release ships a single engine, which means the laps core's qualifying and grid knowledge must reach the results core
first (F1 race-win Brier 0.1134 for the laps core against 0.1476 for the results core in the 2 Oct validation,
[Novig and the bake-off](novig-and-model-bakeoff.md)); the owner chose "compare first", and the F1 walk-forward
comparison on production is Lab jobs 1 to 4 (2026-10-11; jobs 1 and 3 done, 2 and 4 failed, not re-run).

| Sport | `[model] inputs` (core) | Results source | How it was checked | Honest status (2026-10-14) |
|---|---|---|---|---|
| **F1** | `results, qualifying, grid, practice, laps, sectors` (laps core, runs stored as `f1_sector_sim`) | FastF1 (cloud-blocked); the schedule-sync timer keeps upcoming sessions current (#169) | 129 races, 2021 to Azerbaijan 2026, three stages each; after qualifying top-10 Brier 0.149 vs 0.163 grid-only. Polymarket is as sharp on race winners (sharper after qualifying, and in 2025 at every stage) | Real model; its edge is where the gap to the market is large. Live forecast run 9929 (2026-10-11, data through Singapore); live prices for rounds 18 to 20 re-run on the VM 2026-10-13 (runs 9952 to 9954, `gridq+pretrain+reset`, 4,000 sims) |
| **Downhill** | `run_times, practice` (run-times core, `timed_runs`) | ChronoRace web feed (primary), PDFs opt-in | 43 World Cup rounds walk-forward ([Evaluation](evaluation.md)) | Real model, nothing to trade it against; forecast run 1287 (2026-09-27) |
| **NASCAR Cup** | `results, qualifying, fastest_lap` (results core; `NascarCupRace` a challenger) | `cf.nascar.com` feeds, fetched by the forecast-refresh timer on race weekends | Taker replay on Kalshi only (above); no calibration table beside a naive baseline | **Unvalidated.** Race-day pricing ignores practice and track type; the replay's race spread (2.0 places) is tighter than NASCAR's measured ~7, an open owner decision; the pre-race field is the last race's (C46) |
| **MotoGP** | `results, qualifying` (results core; `MotoGPRaceChallenger` a challenger) | `api.motogp.pulselive.com` (unofficial, public); calendar and results step in #134, promotion pending | Race-win log loss 0.0796, no baseline comparison; Kalshi replay has no ranked result | **Unvalidated**, race win only. No sprints, so no season or champion pricing; no next race on production yet |
| **Road cycling** | `results` (results core) | PCS, on the owner's Mac; terms not cleared | Eneco Tour 2026 GC paper picks (not in the ledger), settle 18 Oct; the GC model is draft #177 | Admin-only; first model, no backtest on production |
| **IndyCar, Le Mans, SailGP** | `none` | None cleared (IndyCar's forbids scraping) | – | Tape only |

A `market_implied` or Plackett-Luce baseline is planned (engine roadmap E7); Plackett-Luce was tested on 7 Oct and
lost to the probit engine in all four sports, so it is not the baseline. The generic leak guard (E2) is F1-only today:
the NASCAR and MotoGP replays avoid leakage by pricing each race from results strictly before its start, a convention
in `pipelines/position_replay.py`, not a checked guard.

## The venues

| Venue | What it is | Can we read it? | Can we trade it? | Take |
|---|---|---|---|---|
| **Polymarket** | Crypto exchange, CLOB, public Gamma + CLOB APIs, full trade and price history | Yes: `markets sync/record/archive` (F1 books every 60 s) and `pm_sync.sh` every 5 minutes for NASCAR and MotoGP links, books and trades | Paper and F$; V2 order path built, `POLYMARKET_TRADING_ENABLED` unset | Our first venue. The gap in F1 race listings (28 Aug to Italy) is over: production holds race links for rounds 13 to 20. Championships deep. The Bahrain GP (held in Malaysia) is a permanent hole in Probalytics' archive, not ours |
| **Kalshi** | CFTC exchange, public REST API with candlesticks and trades, per-market maker fee | Yes: `markets --exchange kalshi`, F1 2025–26 ([Kalshi history](kalshi-history.md)); NASCAR, MotoGP, IndyCar with `--sport`; books every 5 minutes since 30 Sep; trades every 15 minutes | Paper; `KALSHI_TRADING_ENABLED` unset | Listed every 2025–26 F1 weekend and every NASCAR Cup race, 2 to 4 days out. Hourly candles are last trades, which spike; the recorded books fix that from 30 Sep on |
| **OG.com** | Crypto.com's US prediction market (CFTC contracts via Crypto.com Derivatives North America). Sports-first, $0.02 flat fee per contract (from reviews) | **Yes, public market data with no key** (`api.crypto.com/fcm/v1/public/*`), read by a schema (`exchanges/og.toml`, #44); books every 5 minutes since 8 Oct, settlements hourly; a replay venue since #88. History is short: about a month | Not without **FCM onboarding** and HMAC-SHA256 signing (owner waiting on an API key) | Readable and replayable, not tradable. F1 season futures and, since Malaysia, per-GP race markets; NASCAR and SailGP season futures. See [OG.com](#ogcom) |
| **Probalytics** | A third-party recorder of Polymarket and Kalshi fills and books (fills from 2022; books from 2025-11-20 on Polymarket and 2026-05-09 on Kalshi, owner's probe 2026-10-13) | Download by exact key from our links (`scripts/probes/probalytics_pull.py`, [PR #181](https://github.com/lalligagger/racinglines-public/pull/181), open into staging); a backtest venue behind `RACINGLINES_TAPE_SOURCE=probalytics` | No (not a venue) | A reference tape, not a replacement: our recorder stays primary (owner, 2026-10-12). Pull order: F1 complete, then NASCAR; any other sport only on the owner's explicit go. Their terms allow in-app use, no redistribution |
| **Private book** | Our own simulated pool (`racinglines live`): the demo maker quoting to a simulated crowd and the demo taker | Yes, replayable to the fill | Yes (the T3 tier) | The fallback where no venue lists the event. Proves pricing, not an edge. Admin-only under the alpha layout |

Other venues seen and **not** tracked: Robinhood's prediction-market tab (Kalshi's contracts resold), FanDuel
Predicts (CME and OG contracts), PrizePicks (picks, not a book), Octagon, and Coinbase's F1 weekend markets (a
temporary fallback in `markets/exchange_driver.py` and `pipelines/live_f1.py`, no exchange schema, no links on
production). None
adds a market Kalshi or Polymarket doesn't already list.

## The gaps, ranked

Effort: **S** under a day, **M** one to three days, **L** a week or more. Ordered by what moves the G1 goal (CLV
above +2% over 100 live bets, Oct to early Nov) and then a cell of the matrix soonest. None starts without the
owner's go ([Roadmap](todo.md#priorities)).

1. **CLV on every live and replayed fill (C4) — M.** `racinglines backtest clv` reports it for stored paper bets;
   the sweep stats, `f1 reconcile`, `f1 scorecard` and the weekend report do not. G1 is judged on it.
2. **Calibration by probability bucket, every sport (C48) — M.** Favourites, mid-field and long shots, walk-forward
   against results and against closing prices where recorded; a schema-set temperature or shrink if it fails, with a
   decision-log row. Until then NASCAR and MotoGP prices are unvalidated and no pick rests on them alone.
3. **Golden sweep on the Probalytics tape (#181) — S once merged.** Same jobs, two tapes; pass marks: mid within 1¢
   on 95% of snapshots, weekend P&L within 10% or $5, trades within 5%. Runs on `racinglines_staging_demo`.
4. **MotoGP's calendar on production — promotion pending (#134 in #180).** The first `forecast-refresh` pass after
   the deploy files the scheduled rounds (it takes its own daily backup); then MotoGP gets a next-race price.
5. **Kalshi taker on real touch prices before 30 Sep — M.** Our books start 2026-09-30; Probalytics' Kalshi books
   start 2026-05-09, so Canada to Azerbaijan 2026 can be re-run at the touch once the pull lands.
6. **NASCAR's pre-race field and start lists (C46, C5) — S to M, Mac probe first.** The forecast copies the last
   race's field; part-time entries are missing until the weekend feed is ingested.
7. **Champion replays (#95, #96) on the VM — S.** Merged 30 Sep; no run is recorded in [Data changes](data-changes.md).
   They would be the first backtest of any OG.com cell.
8. **MotoGP sprints and champion — M.** Sprint classifications (a Mac probe first), then the champion classifiers
   and a season sim ([Championship markets](championship-markets.md#what-pricing-motogps-champion-would-take)).
9. **OG.com follow-ups — S each.** Per-Grand-Prix contract rules from the Malaysia and Singapore listings, confirm
   the $0.02 fee, join OG.com to the U7 disagreement log. Trading only after FCM onboarding.
10. **Road cycling — L, with the owner.** A results source whose terms allow it, the GC model's decision-log rows
    (#177), then a first VM data step. Le Mans and SailGP stay tape only; XCO / XCC only if a venue ever lists it.

Done since the 3 Oct review: the three recorders on every day (owner rule 2026-10-07; trades every 15 minutes,
Polymarket NASCAR and MotoGP books, `backfill_tape.sh`, PR #91); the Kalshi book recorder (30 Sep) and the OG.com
settlement feed (hourly); the forecast-refresh timer with NASCAR results and the F1 championship forecast after each
result; Polymarket MotoGP links (209); the one engine on every modelled sport (2026-10-11); road cycling on the board
for admins (#163); the coverage counter `backtest coverage` (C0, #81); the fantasy alpha on F1's recorded books
(#146, #160, #161); the data-terms decisions (2026-10-14).

## OG.com

**Corrected 2026-09-29.** An earlier draft of this page, written from 2026 reviews, said OG.com has no
public API. That is wrong. The owner found the docs and a probe from the owner's Mac confirmed them.

What it is: Crypto.com's US prediction market (CFTC contracts via Crypto.com Derivatives North America).
Its API is the "Crypto.com GEN4 FCM US B2C API" at `exchange-developer.crypto.com/fcm-b2c/v1/docs/`, which
og.com's footer links to. It is a different product from Crypto.com's crypto derivatives exchange.

**Public, no key** (100 requests per second per method per IP; a UAT sandbox at `uat-api.3ona.co` also
answers):

| Need | Endpoint under `https://api.crypto.com/fcm/v1/public/` | Note |
|---|---|---|
| Market listing | `get-events`, `get-instruments`, `get-instrument-lifecycle-states` | 12,359 events, 54,676 live instruments on 2026-09-29 |
| Prices | `get-tickers`, `get-book` | 50-level book; tick 0.01, contract size 1 |
| Trades | `get-trades` | Retained about one month |
| History | `get-ticker-histories` | 1-minute bid/ask/last; at most 31 days and 1,000 rows per call. **No candlestick endpoint for event contracts** |
| Settlements | `get-expired-settlement-price` | Probed from the Mac 2026-10-06; read hourly by `record_venues.sh` ([Exchanges](exchanges.md#outcomes-the-settlement-feed)) |
| Stream | `wss://stream.crypto.com/fcm/v1/market` | No auth. Channels `book`, `ticker`, `trade`, `instrument`, `instrumentall`, `settlement`, `tradingstatus` |

**Private** endpoints (orders, positions) need FCM onboarding and HMAC-SHA256 request signing. The owner is
waiting on an API key. No API terms page was found on the docs site; the legal pages are `og.com/legal` and
`og.com/document/legal_us.pdf` (the owner checked them on 2026-09-29: the terms allow this read-only use).

**What it lists** (live instruments, sports grouping, 2026-09-29): college football 23,938, soccer 9,706, NFL 4,400,
NHL 3,015, MLB 555, tennis 297, WNBA 152, golf 144, NBA 110, esports 52, **F1 20, NASCAR 17, sailing 13**,
chess 2; plus politics, culture, economics, crypto, companies and climate. **Not listed:** MotoGP, IndyCar,
any cycling or mountain bike, Le Mans.

**Where it matters to us.** F1 first: 20 season futures (Drivers' champion 9, Constructors' 11, expiring
2027-01-31), and per-Grand-Prix race markets that appear around a weekend: production holds 22 links each for the
Bahrain GP in Malaysia (round 16) and Singapore (round 17), both closed, and 808 F1 trades since 9 Oct (2026-10-14).
Liquidity is thin: on 29 Sep the Norris and Verstappen futures books were asks only at 1–4¢ (1–5k contracts), no
bids, about 4 trades a week. NASCAR is 17 Cup Champion contracts (69 trades since 9 Oct) and SailGP 13 Championship
Winner contracts. Nothing else on our list. The F1 futures are model-priced (the season forecast); the NASCAR champion
is priced only offline by the uncalibrated #93 season sim; SailGP is tape only.

**Connector built as a schema, not code (PR #44, 2026-09-29).** `exchanges/og.toml` describes the API and one
generic driver reads it, so OG.com needs no OG-specific code. It syncs the futures and race markets into market links,
records the tape, minute prices and books (every 5 minutes since 8 Oct, `record_venues.sh`), reads the settlement
feed hourly, and prints a fair-price indicator (model fair vs quote, net of the fee). It is read-only and off by
default (`RACINGLINES_OG_VENUE=1` shows the venue). Since #88 it is also a replay venue (`nascar replay --venue og`,
`--venue all`). What is left:

1. **Per-Grand-Prix contract rules** in `exchanges/og.toml`, now that two race weekends' instruments have been
   recorded (their names are unchecked). Effort S.
2. **The fee**: $0.02 per contract is from reviews; confirm it in OG.com's fee schedule.
3. **Cross-venue comparison (U7)**: OG.com joins the championship comparison once `markets/disagree.py`, which
   knows Polymarket and Kalshi only, is generalised. Effort S to M.
4. **A replay on its tape**: the champion replays (#95, #96) and a race replay on the Malaysia and Singapore
   markets; nothing has been run.
5. **Trading**: only after FCM onboarding, signed private endpoints and the validation rules. Not started.

## Spot-check, 2026-09-29 (VM database, read-only)

Historical: this is the state before the first VM syncs of the new sports. The matrix above supersedes it.

Run from the owner's Mac against the live APIs and the VM's database, before the deploy of the overnight batch.
Kalshi F1: 3,793 links, 37,416 trades, 16,083 price rows, archived. OG.com, NASCAR, MotoGP and IndyCar on Kalshi:
**0 links, no archive folder**, as expected until the VM runs the syncs. Polymarket NASCAR, MotoGP, IndyCar,
Kalshi cycling and Le Mans: no schema. Kalshi's cycling and Le Mans series are still listed. Trap: total Kalshi
trades by joining `market_trades` to `market_links` on `token_id` only. `condition_id` is the whole event ticker
there, and joining on it overcounts about 20 times ([Kalshi history](kalshi-history.md)).

## What to verify on a device

The counts in the matrix come from production's database (the MCP server's `sql`, admin-only, or
`racinglines backtest coverage` on the VM). The venues' own listings need a device that reaches them (the VM or the
owner's Mac; the cloud sandbox does not). Each is a read-only GET.

Kalshi: every sports series that touches our sports, then the open and settled counts for cycling.

```bash
curl -s 'https://api.elections.kalshi.com/trade-api/v2/series?category=Sports&limit=200' \
  | python3 -c 'import sys,json; [print(s["ticker"], "|", s["title"]) for s in json.load(sys.stdin)["series"]]' \
  | grep -iE 'cycl|tour|giro|vuelta|mtb|mountain|downhill|f1|nascar|motogp|indy|sail|mans|formula|rally|ski'
```

```bash
for s in KXCYCLING KXCYCLINGSTAGE KXCYCLINGTEAM KXNASCAR KXMOTOGP KXINDYCAR; do
  for st in open settled; do
    n=$(curl -s "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=$s&status=$st&limit=200" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["markets"]))')
    echo "$s $st $n"
  done
done
```

Polymarket: what it lists for each sport.

```bash
for q in cycling "tour de france" giro vuelta "mountain bike" nascar motogp indycar "formula 1" sailgp "le mans"; do
  echo "== $q"
  curl -s "https://gamma-api.polymarket.com/public-search?q=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$q")" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(" ", e.get("slug"), "active" if e.get("active") else "closed", e.get("volume")) for e in d.get("events", [])[:15]]'
done
```

OG.com: this was probed on 2026-09-29. To refresh its F1 and NASCAR counts:

```bash
curl -s 'https://api.crypto.com/fcm/v1/public/get-events' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps(d)[:1500])'
```

Write the answers into the matrix above, with the date.

## Calendar: what could be listed before year end

Production's scheduled events on 2026-10-14, with the links already stored for each.

| When | Event | Listed today | Our side |
|---|---|---|---|
| 18 Oct | NASCAR Phoenix (Freeway Insurance 500) | Kalshi 200 links, Polymarket 43 | Results core price on the board (unvalidated); recorded by the timers |
| 23–25 Oct | F1 round 18, United States GP | Polymarket 266 links; Kalshi none yet (lists 2 to 4 days out) | A, C and K paper; fantasy trading on the recorded books; forecast run 9929 |
| 25 Oct | NASCAR Talladega (YellaWood 500) | None yet | As Phoenix |
| 30 Oct – 1 Nov | F1 round 19, Mexico City; NASCAR Martinsville (Xfinity 500) | Polymarket 266 links for Mexico; nothing for Martinsville yet | As above |
| 6–8 Nov | F1 round 20, São Paulo; NASCAR Championship Race (Homestead) | Polymarket 266 links for São Paulo; nothing for Homestead yet | As above; NASCAR's champion priced only offline |
| ~12 Nov | Sizing review | | After the live weekends on real markets ([Roadmap](todo.md#paper-trading)) |
| 20–22 Nov | F1 round 21, Las Vegas (Saturday race) | Nothing yet | The CLV-gated milestone ([Roadmap](todo.md#priorities)); check the night-time stage cut-offs |
| 27–29 Nov, 4–6 Dec | F1 rounds 22 and 23, Qatar and Abu Dhabi | Abu Dhabi: 1 Kalshi link | Championships settle; U8 rules if a race is cancelled |
| Nov | MotoGP's last rounds (Qatar, Portugal, Valencia as listed on 28 Sep; not in production's calendar until #134 runs) | Kalshi 33 open MotoGP links, Polymarket 29 | Replay and board price only, unvalidated |
| from 23 Nov | UCI Cyclocross World Cup | Probably none | Nothing |
| Spring 2027 | Classics, Giro, UCI MTB World Cup opener | Kalshi cycling series, Polymarket | Decide over the winter from the 2026 tapes and #177 |
