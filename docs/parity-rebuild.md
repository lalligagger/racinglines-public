# Parity rebuild: every valid combo on par with F1 on Polymarket

The plan for rebuilding every backtest and the paper-trading P&L with the F1-on-Polymarket pipeline, for every
sport and exchange we cover. Staging first; prod only after the owner reviews staging. It also specifies **C0**, the
read-only coverage counter that comes first. The owner's go, 2026-10-07: C0 only for now.

**Status:** plan and C0 spec. Nothing built. Counts below come from a read-only query of the VM database on
2026-10-07 at 04:10 UTC, made against `main` `c1b7277`. C0 replaces them with a command anyone can re-run.

## Sprint goal (owner, 2026-10-07)

When this sprint ends, F1, NASCAR and MotoGP should each support two uses:

1. **Our model against the prediction markets.** Polymarket, Kalshi and OG.com wherever they list the sport: fair
   prices on the board, backtests and paper P&L for every valid combo. That is the parity work below.
2. **Expected value (EV) of a sportsbook slip.** Price each leg of a generic sportsbook's slip with our model, and
   show the prediction-market price beside it wherever a linked market exists. Report the EV against both. That is
   package C9 below.

For C9, how the model and the market price are combined is a decision for the owner. It gets a decision-log entry
before any blend is treated as final. Until then, both prices and both EVs are shown side by side.

Road cycling (C6) is outside this sprint.

## What "on par" means

The F1/Polymarket pipeline has eight stages. A sport × exchange × market kind ("combo") is on par when it passes
all eight:

| # | Stage | F1 · Polymarket | Where it lives |
|---|---|---|---|
| 1 | **Link:** the exchange market is linked to race, athlete and kind by exact keys | yes | `market_links` (`prediction` = kind) |
| 2 | **Tape:** prices, trades and books are recorded and archived | yes, 2025 and 2026 | `market_price_history`, `market_trades`, `market_book_snapshots`, `data/archive/markets/<exchange>/` (`markets/store.py`) |
| 3 | **Price as of:** each weekend stage is priced with no leakage | yes | `pipelines/weekend_sweep.py`, `position_sim` |
| 4 | **Settle:** from results and from the exchange outcome | yes | `markets/kinds.py`, `private_book.py` |
| 5 | **Sweep:** 4 taker modes and 5 maker variants, tuned on one season and held out on the other | yes | `f1 search`, `pipelines/search.py`, `sweeps/*.toml` |
| 6 | **Report:** a leaderboard and a verdict for each strategy | yes | `search_report.py`, Lab Edge Finder, MCP `edge_finder` |
| 7 | **Paper:** profile → live paper signals every 5 minutes | yes | `pipelines/signals.py`, `profiles.py` |
| 8 | **Track record:** shown on the web and MCP | yes | `pipelines/story.py`, MCP `track_record` |

**Valid-combo bar** (proposed; owner to confirm):

- **parity-2:** at least 8 settled races with tape in each of two seasons.
- **parity-1:** at least 8 settled races with tape in one season. It gets P&L but no held-out verdict.
- **thin:** 1 to 7 races. Reported only.
- **missing:** no linked markets.

## Combos on 2026-10-07 (linked races, 2025 / 2026)

The counts are races that have at least one linked market of the kind. The season comes from the market's
`end_date`. **Tape was not counted** (it lives mostly in Parquet), so a combo can drop a tier once C0 counts its tape.

| Sport · exchange | parity-2 | parity-1 | thin | missing |
|---|---|---|---|---|
| F1 · Polymarket | win 22/20, h2h 15/19, pole 17/19, team top 21/20 | podium 3/18 | fastest lap 0/4, sprint 0/1, rain/red flag/safety car ≤ 5 | |
| F1 · Kalshi | win 24/16, podium 22/16 | pole 3/15, top 10 0/16, fastest lap 3/16, team top 0/13 | h2h 0/2, top 5 0/1, mover 0/1 | |
| F1 · OG.com | | | win 0/1 (season futures otherwise) | |
| NASCAR · Kalshi | win 8/33 | podium, top 5, top 10, top 20 0/29; fastest lap 0/21; pole 0/12; team win 0/17 | h2h 0/6, mover 0/2 | |
| NASCAR · Polymarket | | win 7/12 | | |
| NASCAR · OG.com | | | | race markets (champion only, 17 open) |
| MotoGP · Kalshi | | win 0/13 | | |
| MotoGP · Polymarket | | | win 4/0 | |
| MotoGP · OG.com | | | | everything |
| Road cycling · any | | | | everything: no links, events or results in the database |

Totals: 7 parity-2, 14 parity-1, 13 thin. Only the F1 combos have a sweep (244 `sweep` runs, 40 on Kalshi) and
live paper signals today.

**Data problems to fix before trusting non-F1 results:**

- **Unmodeled links.** Every NASCAR and MotoGP link has `prediction = 'unmodeled'` and keeps its kind in
  `params.kind`, because `markets/kalshi/sync.py` sets `modeled = sport == "f1"`.
- **Other series under NASCAR Cup.** Kalshi NASCAR has 3,101 race-win links over 33 races in 2026, about 94 per
  race. One champion link asks about the Truck Series champion. *Inferred:* markets from other series are filed
  under `nascar_cup`.
- **F1 links left unmodeled.** 831 F1 Kalshi links from 2026 are unmodeled, among them "to finish top 5" titles.
- **MotoGP champion links have no kind.** On both Kalshi and Polymarket, `params.kind` is empty.

## Every session, every supportable kind (owner, 2026-10-07: "close this gap")

The tables above count only the kinds we already link. This section lists everything the exchanges list for F1,
NASCAR and MotoGP that we don't price yet. It comes from the unmodeled links in a read-only query on 2026-10-07,
grouped by Kalshi series or Polymarket event title. Each row is marked **supportable** (the position sim can price
it once the kind exists as a `kinds.toml` row), **needs data or model** (named), or **not supportable** (out of
scope).

**Sessions to price at.** F1 already reprices after every session. NASCAR and MotoGP reprice only at fixed hours
before the race (`[replay] stages`). Every sport gets its session schedule in `sports/<sport>.toml`:

- **F1:** FP1–3, sprint qualifying, sprint, qualifying, race.
- **NASCAR:** practice, qualifying, stage 1, stage 2, race.
- **MotoGP:** FP1, Practice, Q1/Q2, sprint, race.

Each sport then reprices after each of its sessions, through the same stage engine.

### F1

| Listed, not priced | Exchange | Links (races) | Status |
|---|---|---|---|
| Top 5 finish (`KXF1TOP5`) | Kalshi | 330 (15) | **supportable now.** The `race_top5` kind exists; the classifier misses this series |
| Sprint winner, sprint top 5 and top 10, sprint fastest lap, sprint top constructor, sprint pole (`KXF1RACESPRINT`, `KXF1SPRINT*`) | Kalshi | 130 / 88 / 88 / 66 / 33 / 66 | **supportable.** The sprint stage exists since PR #73; the sprint kinds are off by default |
| Sprint winner, sprint qualifying pole | Polymarket | 199 + 69 / 159 | **supportable.** Same as above |
| Exact position (2nd, 3rd, 4th, 5th place) | Polymarket | about 230 | **supportable.** A new kind: finishing position = n |
| Constructor pole, constructor fastest lap | Polymarket | 284 / 284 | **supportable.** Team aggregate over the pole and fastest-lap kinds |
| Constructor score rank 1st to 5th, constructor head-to-head | Polymarket | about 220 / 36 | **supportable.** Team points rank and team h2h from the sim |
| Driver head-to-head and podium families with no race link ("finish ahead of", "who will finish higher") | Polymarket | 56 + 46 + 21 | **linking gap.** The kind exists; the link has no `race_id` |
| Practice 1, 2, 3 fastest lap | Polymarket | 526 / 344 / 368 | **needs a model:** practice pace from laps. FastF1 laps are in the database |
| Biggest mover | Kalshi | 44 (2) | **needs the starting grid** (core backlog C11; per-event grid penalties since PR #74) |
| Championship 2nd to 5th place (drivers, constructors) | Polymarket | 84 / 44 | **supportable.** Standings position from the season sim |
| Winning margin | Polymarket | 7 | **not supportable now.** The sim has no time gaps |
| Awards, transfers, retirements, calendar, attendance, winter testing | both | about 100 | **not supportable** (not race outcomes) |
| IndyCar races filed under F1 ("Honda Indy 200 at Mid-Ohio") | Polymarket | 78 | **data fix.** Refile them to IndyCar |

### NASCAR

Kalshi lists, all as `params.kind` with `prediction = 'unmodeled'`: win, podium, top 5, top 10, top 20, fastest lap,
pole, team win, head-to-head, biggest mover, champion and regular-season champion. Kalshi also has "win the
playoffs" (16 links) and Polymarket an In-Season Challenge winner (17 links).

| Kind | Status |
|---|---|
| Win, podium, top 5, top 10, top 20, head-to-head, team win | **supportable** once start lists and the global model are in (C3) and the kinds are rows |
| Pole | **needs a qualifying model.** 270 qualifying rounds are in the database |
| Fastest lap | **needs a lap model.** Laps exist for 279 races |
| Biggest mover | **needs the starting grid.** It's in the weekend feed |
| Champion, playoffs | **needs a playoff-format season sim** (16 drivers, eliminations, one-race final) |
| Regular-season champion, In-Season Challenge | **supportable** from the season sim once the formats are in the schema |
| Stage winners | not seen in the listings; **not checked** |

Other NASCAR series (Truck, possibly Xfinity) are filed under Cup; **data fix** first (C1).

### MotoGP

The exchanges list race win (Kalshi 289 links, Polymarket 131), the riders' champion (Kalshi 22, Polymarket 78) and
the teams' champion (Kalshi 11). Race win is supportable now. The champion and teams' champion are **supportable**
from a season sim with a team aggregate.

**Sportsbook slips** (C9) list more than the exchanges do: podium, top N, head-to-head, sprint winner and pole. Those
are **supportable** for slip EV with the model price alone. They **need data:** qualifying is not ingested (0
qualifying rounds in the database), so there is no grid, and sprints are only in from 2025 although they began in
2023. Both come from the MotoGP source we already use.

## Engine gaps

These line numbers come from grep and are approximate.

- **The sweep is F1-only.** `weekend_sweep.py` loads `sports.load("f1")` at import and branches `venue ==
  "polymarket"` else Kalshi, with no OG.com. `search.py` `KINDS` maps only `f1` and `mtb_dh`, and it branches on
  `sport == "f1"` in four places.
- **Paper signals are F1-only.** That covers `racinglines f1 signals` and the polymarket-or-other branches in
  `signals.py`. NASCAR and MotoGP have only the in-sample, update-mode backfill (`sport_paper.py`).
- **Sweep runs don't record the sport.** No `sweep` run has a `sport` key in `params`.
- **The NASCAR and MotoGP pricing model is overconfident.** In the 2026-10-07 A/B/C study, the form model priced
  NASCAR head-to-heads worse than uniform (log loss 1.4958 vs 0.6931). The sport-agnostic `GlobalModel` was best on
  the win in both NASCAR and MotoGP. See [todo](todo.md) and the core backlog items C5 to C7 and C26.
- **Per-sport and per-exchange branches** in `season_replay.py`, `season_strategy.py` and `exchange_driver.py`
  should become fields in `sports/<sport>.toml` and `exchanges/<venue>.toml`.

## Work packages

Every code package is a PR into `staging`. A data step means a write on the VM: take a backup first, run it on the
staging database first, and add a `data_changes` row.

| Thread | Packages |
|---|---|
| Core (leads) | **C0** coverage counter (below). **C1** link cleanup: kinds from `params.kind` for every sport, other NASCAR series refiled, MotoGP champion links classified (data step). **C2** sport-agnostic sweep: stages, kinds and venues come from the schemas, OG.com goes through `venue_replay`, and sweep params gain `sport` and `venue`; F1 goldens stay byte-identical. **C3** NASCAR/MotoGP pricing: start lists, `GlobalModel` as the pricing model, and top 20, h2h, team win, fastest lap and pole as kinds. **C4** CLV per bet. **C5** settlement parity: one top-N rule, OG.com settle verified, mover settles. **C6** cycling, gated on a Mac probe (deferred: outside this sprint). **C7** live paper signals for every sport and venue. **C8** the rebuild run (data step): 9 sport-venue-seasons × 9 strategies = 81 sweep jobs per model variant, then the paper backfill. **C9** sportsbook slip EV for F1, NASCAR and MotoGP. This is the `book map/price/settle` CLI (core backlog step 8; today only `racinglines/books/schema.py`, the validator, exists), extended to multi-leg slips. Each leg gets the model's fair price, the linked prediction-market price where one exists, and EV against both. Kinds come from `kinds.toml`, so no per-sport branches. **C10** linking and classifier gaps from "Every session, every supportable kind": Kalshi `KXF1TOP5` and the sprint series, Polymarket families with no race link, and IndyCar links filed under F1 (a data step). **C11** the supportable kinds above as `kinds.toml` rows and payoffs, with settlement. **C12** session-aware repricing for NASCAR and MotoGP from a session schedule in each sport's schema; MotoGP qualifying and the 2023–24 sprints ingested; an F1 practice-pace model; NASCAR qualifying and lap models for pole and fastest lap |
| MCP | Sports read from the database (M6). `sport` and `venue` (including `og`) on `edge_finder`, `track_record`, `replay_maker` and `run_job`. `list_kinds` reads C0. `map_book`, `price_book` and `settle_book` (M9) wrap C9. The SQL guard (M1/M2) comes first |
| Web View | A coverage page drawn from C0. Sport and venue filters on Edge Finder, Strategy and Positions. Track record per venue, including OG.com |
| Web UI | Split `web/app.py`, then a Lab launcher for any sport × venue. `og` in the profile venue selector |

Order:

1. C0.
2. C2 and C3 in parallel, then C4, C5 and C7, with MCP and web work alongside.
3. Staging data steps C1 and C8, then the owner's review.
4. Prod only on the owner's decision: `vm.sh backup`, merge `staging` → `main`, then C1 and C8 on prod.

No migration is planned. No existing F1 paper rows are deleted: the rebuild writes new runs and rows.

## C0: the coverage counter (spec)

`racinglines backtest coverage` is read-only. It prints, and with `--out DIR` writes as CSV, the matrix above from
the database **and** the Parquet archive, so that every tier rests on counted tape. It writes nothing to the
database.

**1. Markets.** One row for each sport × exchange × kind × season:

| Column | From |
|---|---|
| `links`, `races` | `market_links`. Kind = `prediction`, or `params->>'kind'` when it is `unmodeled`. `races` = distinct `race_id` |
| `settled_races` | races with at least one link where `resolved_yes is not null` |
| `price_races`, `trade_races`, `book_races` | races with at least one row for a linked token in `market_price_history` / `market_trades` / `market_book_snapshots` **or** in `data/archive/markets/<exchange>/{prices,trades,books}/`, read through `markets/store.py` `read()` |
| `tier` | the bar above, applied to `min(settled_races, price_races)`. The maker counts only `book_races` |
| `modeled` | yes when the kind is in `markets/kinds.py` or `markets/kinds.toml`, **and** the sport's `pricing_model` prices it |
| `unmodeled_links` | links still `prediction = 'unmodeled'` |

Season comes from the race's event date where `race_id` is set, else from `end_date`. Season futures (`race_id`
null) get their own table, with links, open, settled and tape days.

**2. Results depth and backfill sources** (added at the owner's request on 2026-10-07): one row per sport:

| Column | From |
|---|---|
| `first_season`, `last_season`, `events`, `events_with_results` | `seasons` → `events` → `races` → `rounds` → `results` |
| `results_source`, `fallbacks` | `sports/<sport>.toml` `[results]` / `[replay]` source and `fallbacks` |
| `source_modules` | packages under `racinglines/sources/` that fetch results for the sport |
| `cleared` | `yes` only when the schema has a `[results]` table. A sport whose schema omits it on purpose (IndyCar: the official site's terms forbid scraping without permission) shows `no` |

The answer to "can the Wikipedia sources backfill race data?" comes from this table. From the 2026-10-07 query:

| Sport | Results in the database | Wikipedia source |
|---|---|---|
| F1 | 2020–2026, 147 events with results | none. The official sources are already used |
| MotoGP | 2016–2026, 202 events | none |
| NASCAR | 2016–2026, 402 events | `fallbacks` allows Wikipedia **summary-only**, for missing seasons only, and never for full field rows |
| IndyCar | 0 events | `racinglines/sources/indycar` reads Wikipedia race pages (PR #67). `sports/indycar.toml` has no `[results]` table on purpose, so the owner has to decide whether it may be ingested |
| SailGP | 0 events | `racinglines/sources/sailgp` reads Wikipedia championship pages (PR #67) |
| Le Mans | 0 events | motorsport.com (PR #67), not Wikipedia |
| Road cycling | 0 events | none. Its source is procyclingstats, which is only on the owner's Mac |

More results deepen model training, which is the walk-forward burn-in. They don't add P&L backtests: those need
market tape, which starts when recording began.

**Done when:**

- It runs on the VM and on staging. It also says whether staging's database and archive hold the tapes; that is
  not known today.
- Its numbers match the counts above wherever tape is not the question.
- A test pins its output on the market fixtures.
- It needs no migration and writes nothing.
