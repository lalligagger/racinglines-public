# Championship markets

Season-long markets for the soft-launch sports (F1, NASCAR Cup, MotoGP) on Polymarket, Kalshi and OG.com, what the
syncs call them, and which of them a model prices. Taken from the code, the schemas and the captured listings in
`tests/fixtures/market` (2026-09-29). Live listings were not checked from the cloud. Last reviewed 2026-09-30.

**Model-priced** means a model run writes a fair value that `db.reads.model_prob` or a command reads. **Quote only**
means the market is synced and recorded, but no model prices it.

| Sport | Exchange | Market | Listing | Kind (where) | Priced |
|---|---|---|---|---|---|
| F1 | Kalshi | Drivers' champion | `KXF1` | `champion` (kalshi/sync.py) | **Model**: `pricing.forecast` standings, on the board |
| F1 | Kalshi | Constructors' champion | `KXF1CONSTRUCTORS` | `constructors_champion` | **Model**: forecast `constructors` |
| F1 | Polymarket | Drivers' / Constructors' champion | "F1 Drivers' Champion", "F1 Constructors' Champion" | `champion` / `constructors_champion` (polymarket/sync.py) | **Model** |
| F1 | Polymarket | Season wins ("win N+ Grands Prix") | question wording | `season_wins_ge` | **Model**: forecast `extra.wins_ge` |
| F1 | Polymarket | Standings head-to-head | question wording | `standings_h2h` | **Model**: forecast `extra.ahead_of` |
| F1 | OG.com | Drivers' / Constructors' champion | `F1-00001-2026`, `F1-00002-2026` (20 contracts) | `champion` / `constructors_champion` (exchanges/og.toml) | **Model** (venue shown with `RACINGLINES_OG_VENUE=1`) |
| NASCAR | Kalshi | Cup champion | `KXNASCARCUPSERIES`, `KXNASCARCUPCHAMP` | `params.kind = champion`, link `unmodeled` (sources/nascar/links.py) | **Model, offline**: `racinglines nascar season --quotes` (off by default, read-only) |
| NASCAR | Polymarket | Cup champion | `nascar-cup-series-2026-champion-…` | `champion` from the wording | **Model, offline**: the same |
| NASCAR | OG.com | Cup champion | `NSCAR-00002-2026` (17 contracts) | `champion`; og.toml `modeled = false` | **Model, offline**: the same |
| NASCAR | Kalshi | Regular-season champion | `KXNASCARCUPSEASON` | `regular_season_champion` | Quote only (settled for 2026: the regular season ended 29 Aug) |
| NASCAR | Kalshi | In-Season Challenge | `KXNASCARCHALLENGE` | `in_season_challenge` | Quote only (a bracket tournament, not the points table) |
| NASCAR | Kalshi | O'Reilly (Xfinity) / Truck champion | `KXNASCARAUTOPARTSSERIES`, `KXNASCARTRUCKSERIES` | `champion`, `nascar_series` xfinity / trucks | Quote only (only Cup results are ingested) |
| MotoGP | Kalshi | World champion | `KXMOTOGP` (22 markets) | none: `unmodeled` (sources/motogp/links.py knows only `KXMOTOGPRACE`) | **Model, offline**: `motogp season-replay` reads it as `champion` in memory |
| MotoGP | Kalshi | Teams' championship | `KXMOTOGPTEAMS` (11 markets) | none: `unmodeled` | Quote only |
| MotoGP | Polymarket | World champion (25 outcomes) | tag `motogp` | none: `unmodeled` | **Model, offline**: the same (from the wording) |
| MotoGP | OG.com | none listed | | | |

No exchange lists a NASCAR standings top 3, a standings head-to-head or season wins, although the season simulation
could price them (`markets.kinds.season_fair`). No NASCAR manufacturers' or owners' championship was found either.

## What pricing MotoGP's champion would take

The MotoGP race model (`MotoGPRaceChallenger`) prices one race at a time, so it could feed a season simulation the way
the NASCAR model does. What is missing:

1. **Sprint points.** `MotoGPRace.load` reads the Sunday race only, and sprint classifications are not ingested yet
   (`sources/motogp/ingest.py`). The sprint pays 12-9-7-6-5-4-3-2-1 every weekend, so the season total is wrong without it.
2. **The remaining schedule.** The MotoGP ingest files completed events only. The events endpoint that `fetch.py` already
   reads has the dates.
3. **Today's standings.** Summed race and sprint points, or the world-standing classification in
   `tests/fixtures/market/motogp_standings_2026_motogp.json`, which nothing ingests yet.
4. **Classifiers.** `KXMOTOGP` should map to `champion` (and `KXMOTOGPTEAMS` to a team kind), and Polymarket's wording
   to `champion`. That changes stored link params, so it needs the owner's go and `link --apply` with a backup.
5. **A points format.** A `ChaseFormat`-like table with no playoff (25-20-16-13-11-10-9-8-7-6-5-4-3-2-1 for the race).

Steps 1-3 need a probe from the Mac first (standing rule), so none of this is built.

**Update (2026-09-30): a replay-only version is built** (`racinglines motogp season-replay`, off by default with
`RACINGLINES_SEASON_REPLAY=1`, read-only). It covers the steps above without changing any stored link.
- `models/motogp_season.py` supplies the points format (5).
- The remaining schedule is the stored events plus the fetched `events.json` (2).
- The standings are summed from the stored Grand Prix and sprint points (3). With no sprint results stored, both sides
  are Grand Prix only and the report prints SPRINT POINTS MISSING (1).
- The classifier runs in memory only: `KXMOTOGP`, or a listing naming the championship, is read as `champion`, and the
  rider comes from the name resolver (4). Nothing is written.

## Championship replays (backtests)

`racinglines nascar season-replay` and `racinglines motogp season-replay` (`pipelines/season_replay.py`) trade the F1
championship sleeve's default strategy (`markets/strategies/season.py`) against each exchange's recorded champion
prices.
- **Decisions:** one at 12:00 UTC the day after each points race.
- **Fairs:** an as-of season forecast from only the results before the decision. For NASCAR this is
  `models/nascar_season.py` summed from race results, because the points feed is today's only.
- **Costs:** Kalshi's taker fee, OG.com's flat fee, or Polymarket's half-spread, each plus slippage.

Both commands are read-only and off by default (`RACINGLINES_SEASON_REPLAY=1`). They write only CSVs under
`data/runs/season-replay/`. The F1 replay takes `--venue kalshi|og` too (`f1 season-strategy`).

These are first backtest cells, not validated strategies. Both season forecasts simulate races independently from the
form at the decision, and NASCAR's was more favourite-heavy than every exchange on 2026-09-30.

