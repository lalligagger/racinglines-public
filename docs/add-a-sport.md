# Adding a sport (the real steps)

What adding NASCAR Cup and MotoGP (results-backed, modeled) and IndyCar, road cycling, Le Mans and SailGP (tape only)
actually took, in the order it has to happen. Each step links to the section that holds the detail; this page is the
checklist, not a second copy. Written 2026-09-30 from the code on `main`.

The short version: a sport is mostly **data**: a schema file, plus exchange schemas for any new venue. Code is needed for
two things only, a **results adapter** and a **model wrapper**, and neither is needed for a tape-only sport. A few
places still name the sports in code (listed in [step 9](#9-the-places-that-still-name-the-sports)).

## 1. Decide: tape only, or results-backed

| | Tape only | Results-backed |
|---|---|---|
| `[sport] model_family` | `"none"` | the model family (`position_sim` for NASCAR and MotoGP) |
| What you get | exchange links (all `unmodeled`) and the recorded tape: prices, trades, books | the same, plus results, a model, replays, forecasts, the demo paper record |
| Needs | a sport schema with `[markets.*]` | a cleared results source, a results adapter, a model wrapper |
| Examples | IndyCar, road cycling, Le Mans, SailGP | NASCAR Cup, MotoGP |

A sport starts tape only and moves to results-backed only when a results source is **cleared**: its terms of use allow
the use, and it has been probed from the owner's Mac (CLAUDE.md, "Probe a data source from the owner's machine before
any full run"). IndyCar is the counter-example: www.indycar.com's terms forbid automated scraping, and its live timing
feed is INDYCAR's content too, so `sports/indycar.toml` deliberately has no `[results]` table (adding one would read as
"cleared"). MotoGP's API terms are restrictive; the owner reviewed them on 2026-09-29 for the private,
non-commercial use, to be reviewed again before any soft launch (the `terms` string in `sports/motogp.toml`).

## 2. Write the sport schema (`sports/<code>.toml`)

Every section the code reads, as data ([Database](database.md#multi-sport-design): adding a sport or league is data,
not schema):

- `[sport]`: `code`, `name`, `result_kind`, `model_family`, `display_order`, and for a modeled sport
  `pricing_model = "module:Class"`. `[league]` and `[competition]` (`code`, `name`, `display_name`, `categories`).
  `tests/test_sports.py` checks the required keys for every schema.
- `[markets]`: `venues` and `standard_kinds` (the board's columns; `[]` for a tape-only sport).
- `[markets.kalshi] series`: the Kalshi series ticker **prefixes** to sync (e.g. `KXNASCAR`, `KXMOTOGP`).
- `[markets.polymarket] tags`: the Gamma `tag_slug` values to page. **These slugs are unverified** until checked
  against the live API from the Mac (every schema says so); `sync --tags SLUG …` overrides them.
- `[identity] resolver`: the package under `racinglines/sources/` whose `links.py` says which driver and race a market
  is about (step 4).
- `[results]`: the source's host, `terms` and `limits` from the probe (step 3), and the fallback rule.
- `[replay]`: the taker replay's `source` (the `events.source` its model reads), `linker`, `kinds`,
  `race_day_offset`, `stages` and `group_target` ([CLI](cli.md#racinglines-nascar)). All a priori; tuning any of them
  needs a decision-log entry.
- `[data] frames` and `[live]` only when the sport has input frames or a live simulation
  ([Input frames](frames.md#add-a-sport), [Live events](live-events.md#adding-a-sport)); NASCAR and MotoGP have neither.

Then add the code to `SPORT_CODES` in `racinglines/sports.py` (**at the end**: the order is the seeding order and keeps
database ids stable) and run `racinglines db seed` (syncs and ingests also create a sport's reference rows).

A **new exchange** is `exchanges/<code>.toml` read by the one generic driver, not new code
([Exchanges](exchanges.md#what-a-schema-holds)); its `[sports.<code>]` blocks say which sports it lists
(`exchanges/og.toml` lists F1, NASCAR and SailGP). The exchange's caps go in `limits` and fail at load, not on the
first live call. Polymarket and Kalshi predate schemas and keep their own packages.

## 3. Probe the results source from the Mac, then write the adapter

A Remote Control session on the Mac makes a small read-only probe: the endpoint answers, the shape matches, paging,
caps and history depth, the terms of use. The responses become test fixtures (`tests/fixtures/market/<sport>_*`, with
a `<sport>_README.txt`), the findings go into the schema (`limits`, `terms`), and only then does a full run happen on
the VM. Never guess at a live API from the cloud. Worked examples: [Data](data.md#nascar-content-feeds-verified-2026-09-29)
(NASCAR) and [Data](data.md#motogp-public-results-source-verified-2026-09-29) (MotoGP).

The adapter is `racinglines/sources/<sport>/` with `fetch.py` (raw files to `data/raw/<sport>/`, byte for byte, polite
rate) and `ingest.py` (events, races, rounds, results, athletes), plus a CLI group `racinglines/cli/<sport>.py`
registered in `GROUPS` (`racinglines/cli/__init__.py`). Lessons from the two sports:

- **Ingest scheduled events too.** A forecast needs upcoming races. NASCAR's ingest stores races still to run as
  `scheduled`; MotoGP's stores finished events only, so `motogp forecast` has nothing to price until its calendar is
  ingested (step 7).
- **Newest seasons first, and don't let old seasons block new ones.** MotoGP's ingest commits per event and stops at
  the first error; the overnight run now ingests 2025-2026 before 2016-2024 (#100).
- **Run ingest where the replays run.** The first overnight run lost its NASCAR phase because `nascar ingest` and
  `nascar link --apply` had only ever run on the Mac: the VM had 13,599 NASCAR Kalshi links and no results.

## 4. Link identity: which driver and race each market is about

A market link is only usable for a replay, a forecast or the board when it carries a **race** (`market_links.race_id`)
and, for a driver contract, an athlete. The replay groups markets by `race_id`; a link without one is recorded tape and
nothing more.

- **The resolver** is `racinglines/sources/<name>/links.py` with a `Linker(conn)` whose `fill(rows)` sets
  `athlete_id`, `race_id` and `params` (`kind`, season, …) and never raises (`racinglines/markets/identity.py` loads it
  from `[identity] resolver`). The Kalshi, Polymarket and OG.com syncs call it on every new link of the sport, so the
  same outcome gets the same identity on every exchange. `prediction` stays `unmodeled` outside F1.
- **Links stored before the resolver existed** are fixed by a database pass (`racinglines nascar link [--apply
  --backup FILE] [--undo FILE]`, a dry run by default) or identified in memory by the replay (MotoGP).
- **How races are matched differs by sport.** NASCAR matches the race's *name* within the season (a date alone would
  pick the O'Reilly race the day before at the same track); MotoGP maps the Kalshi series (`KXMOTOGPRACE` is the Grand
  Prix winner) and picks the event whose Sunday falls just before the market's close. `KXMOTOGP` (the championship) gets
  no race kind; `motogp season-replay` classifies it in memory only
  ([Championship markets](championship-markets.md#championship-replays-backtests)).
- Kalshi discovers a sport's series by the schema's ticker prefixes; `sync --series TICKER …` names exact tickers when
  discovery finds the wrong ones ([CLI](cli.md#kalshi-exchange-kalshi)).

## 5. Preflight: is the sport ready, before any run

Counts are not readiness. Before any long run, check per sport: **events stored, races stored, and Kalshi links with a
race** (not just links). The overnight run's preflight (`scripts/vm/overnight.sh`, `sport_ready`) prints
`preflight <sport>: N events, M Kalshi links with a race` for every sport in every mode; `dry` flags a sport with 0 of
either as `NOT READY`; `replay` loads the sport's results and identifies its links after its backup, and skips the sport
with a `STOP` line only if it is still not ready. A failed load is logged, not fatal, so one sport's data problem never
stops the rest ([Overnight VM run](overnight-vm-run.md#what-runs-on-the-vm)). Adding a sport there means adding it to
`SPORTS` and to `code_of` (sport code to competition code) in that script.

The replay checks readiness per race too: it counts races with markets, markets priced and markets tradeable, flags a
race with no stored price as `NO TAPE`, and prints `NOT TRADED` with the reason for a venue with nothing tradeable
(`--require-tradeable` exits 1). `--tape probe` asks each exchange about 3 markets before any pull.

## 6. Model wrapper, replay and backtest

- **The wrapper** is a class with the pricing-model contract, named by `[sport] pricing_model`
  ([Backtest core](backtest-core.md#adding-a-sport)). Then `racinglines backtest walk-forward <code>` and the search
  work without engine changes.
- **The taker replay** (`racinglines <sport> replay`, [CLI](cli.md#racinglines-nascar)) needs only the `[replay]`
  section. `--tape pull --backup FILE` pulls the selected races' tape; `--save --backup FILE` stores one as-of model run
  per race, which the board's recent results and the status table read.
- **The settings grid** is the overnight run's read-only grid (`scripts/vm/replay_grid.py`, runs
  `data/runs/replay-grid/<sport>/<year>-e<edge>-v<volume>/`), ranked by the worse season. A season with no markets at
  all (MotoGP 2025 on Kalshi) must not crash the ranking or count as a $0 season (#102, `sport_paper.pick`).
- **Champion markets** (optional): `season-replay` behind `RACINGLINES_SEASON_REPLAY=1`, read-only
  ([Championship markets](championship-markets.md#championship-replays-backtests)).

## 7. Put it in the app: status row, demo paper record, forecast

- **Status row.** With `RACINGLINES_SPORT_STATUS=1` (off by default) Markets opens with one row per sport schema,
  modeled or tape only: race data, exchange markets (links, with a race, open), model, backtests and the demo paper
  record, each green, amber, red or grey (`racinglines/web/sport_status.py`, [Web app](webapp.md#accounts-demo-users-vs-polymarkets-takers)).
  A new schema gets its row with no code. It is the quickest check that the steps above landed.
- **Board section.** A modeled sport with replay saves but no live forecast gets a board section (recent results with
  the model's pre-race price; next races with the exchanges' prices). The race-card queries in `racinglines/web/board.py`
  filter on the category codes `DRV`, `ME` and `RDR`, so a sport with another category code needs adding there.
- **Demo paper record.** `racinglines <sport> demo-history --grid data/runs/replay-grid/<sport> --backup FILE` stores
  the replay's trades as the demo accounts' paper positions (in-sample, labelled so; on the VM, `vm.sh demo`)
  ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)). The sport has to be in
  `sport_paper.SPORTS` and in the loops of `scripts/vm/demo_setup.sh`.
- **Forecast.** `racinglines <sport> forecast --save --backup FILE` prices the next scheduled races and stores a
  `forecast` run, which the board, race pages and exchange markets read as live prices; `--undo RUN_ID` removes it.
  **It needs an upcoming calendar**: with no scheduled race stored (MotoGP today) it says so and stores nothing.

## 8. Standing rules for every step that writes or runs long

- **Back up before any database write.** Every writing command refuses without `--backup FILE`, a dump under 24
  hours old (`link --apply`, `replay --save` and `--tape pull`, `demo-history`, `forecast --save`), and records a
  `data_changes` row naming it. Add the matching line to [Data changes](data-changes.md) in the same change. The VM
  scripts back up first and check the dump's trailer.
- **Progress lines.** Owner rule (2026-09-30): any long job, on the cloud, the Mac or the VM, prints a flushed progress
  line at least every 5 minutes (run Python with `PYTHONUNBUFFERED=1` or print with `flush=True`: the overnight run's
  12:59Z-13:44Z silence was partly Python buffering its output). The overnight runner has per-step lines and a heartbeat
  ([Overnight VM run](overnight-vm-run.md#progress-updates)); a shared helper for searches, replays and demo-history is
  still open ([Roadmap](todo.md)).
- **Label honestly.** Say which numbers are **in-sample** (a setting picked on the seasons it is then replayed on: the
  demo paper record, the settings grid) and which are **held out**; say whether a price comes from a **simple
  baseline** (NASCAR's and MotoGP's result-only models, uncalibrated season sims) or a **validated model**; and never
  report the debug `buy_all` mode as a result. The app shows *demo replay, in-sample* on every such row, and the status
  table marks non-F1 grids "indicative, in-sample". [Sports and exchanges](coverage.md#model-status-by-sport) keeps
  the per-sport model status.
- **Tuned settings need a decision-log entry** before they are treated as final ([F1 roadmap](f1-roadmap.md) format).

## 9. The places that still name the sports

Schemas carry most of it, but these still list sports in code or scripts, checked on `main` 2026-09-30. A new sport
that should reach them needs an edit there:

| Where | What |
|---|---|
| `racinglines/sports.py` `SPORT_CODES` | every sport with a schema (append at the end) |
| `racinglines/cli/__init__.py` `GROUPS`, `racinglines/cli/<sport>.py` | the sport's CLI group (fetch, ingest, and the shared `replay`, `season-replay`, `demo-history`, `forecast` from `cli/replay_cmd.py`) |
| `racinglines/pipelines/sport_paper.py` `SPORTS`, `pipelines/season_replay.py` `SPORTS` | `("nascar", "motogp")` |
| `scripts/vm/overnight.sh` `SPORTS`, `code_of`, `prep` | the overnight run's sports, their competition codes and how their results load |
| `scripts/vm/demo_setup.sh` | `for S in nascar motogp` |
| `racinglines/web/board.py` `recent_results`, `next_races` | category codes `DRV`, `ME`, `RDR` |
| `racinglines/markets/kalshi/sync.py` | only F1 is classified into model kinds (`modeled = sport == "f1"`); every other sport's links are `unmodeled` and get their identity from the resolver |

## Related

- [Database](database.md#multi-sport-design): the multi-sport tables.
- [Input frames](frames.md#add-a-sport): a sport's L1 frames.
- [Live events](live-events.md#adding-a-sport): a sport's live simulation.
- [Backtest core](backtest-core.md#adding-a-sport): a sport in the walk-forward and search.
- [Cloud build-out](cloud-buildout.md#design-schemas-first): the schemas-first design.
- [Sports and exchanges (status)](coverage.md): where each sport stands today.
