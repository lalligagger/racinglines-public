# Data

## Data layout

Every path comes from `racinglines/paths.py`. Set `RACINGLINES_DATA` to move the
whole tree.

```
data/
  raw/<sport>/<source>/...                 immutable downloads: the record
    raw/f1/fastf1/<year>/<rnd>_<session>.{results,laps}.parquet + .meta.json
    raw/f1/fastf1/<year>/schedule.parquet   the season's FastF1 schedule (used when FastF1 can't be reached)
    raw/mtb_dh/chronorace/*.md              one file per event and category
    raw/mtb_dh/manual/...                   live-timing copy/pastes (not used by the pipeline)
    raw/nascar/cf/<year>/<series>/...       NASCAR content feeds as served: race list, standings, and per race
                                            <race_id>/{weekend-feed,lap-times,lap-notes,pit-data,loopstats}.json
  archive/markets/<exchange>/{prices,trades,books}/month=YYYY-MM/*.parquet
  archive/markets/polymarket/links/market_links.parquet   market links with stable keys (f1 pm-links-export)
  archive/markets/kalshi/links/market_links.parquet       Kalshi's market links, same format
  archive/db/<table>.parquet + manifest.json               database snapshot (db snapshot-export)
  archive/<sport>/...                       stale heavy race data moved out of Postgres (future)
  runs/<sport>/{backtests,sweeps,...}/      generated outputs
  runs/jobs/                                outputs of jobs launched from the web app
  runs/search/<name>/                       settings searches (f1 search): leaderboard, results, state, logs
  runs/alerts/new_markets.jsonl             new-market alerts, one JSON line per event
  runs/logs/                                logs: web, record (recorder), signals, postgres, long runs
  cache/<tool>/                             disposable (FastF1's HTTP cache, cleared after fetches)
  pg/                                       local Postgres cluster when not using Docker (see Database)
```

- **Downhill source files** are keyed in the database by their path relative to
  `data/` (e.g. `raw/mtb_dh/chronorace/20260925_mtb_dhi_elite-men.md`), so moving
  the tree doesn't cause a re-ingest.
- **F1 events** are keyed by season and round (`f1:2026-15`).
- **Snapshot and links file:** see [Database](database.md#snapshot-an-exact-replica)
  and [CLI](cli.md#racinglines-markets). The snapshot rebuilds an exact replica; the
  links file loads Polymarket's market links where the API can't be reached.
- **Local Postgres:** `data/pg/` exists only with the Docker-free setup
  ([Database](database.md#setup)); its log is `data/runs/logs/postgres.log`.

## What's in git

The repo is private (since 2026-09-27). `.gitignore` ignores `data/*` and data file
types (`*.parquet`, `*.csv`, …) everywhere, then allow-lists the minimal set a
[cloud sweep](cloud-sweep.md) needs to rebuild the database without the sources:

| Path | Holds |
|---|---|
| `data/raw/f1/` | FastF1 sessions and schedules |
| `data/archive/markets/polymarket/prices/`, `trades/` | Polymarket price and trade archive |
| `data/archive/markets/polymarket/links/` | Market links file |
| `data/archive/markets/kalshi/prices/`, `trades/`, `links/` | Kalshi price and trade archive and its links file (F1, 2025 to 2026-09-28) |
| `data/archive/db/` | Database snapshot |
| `data/runs/search/` | Search results brought back from cloud sessions |
| `data/runs/live/<slug>_<key>/` | A live event, kept permanently for replay: raw timing-feed responses, snapshots, quotes, model inputs, the private book and every crowd fill (see [Live events](live-events.md#kept-for-replay)) |

- **Everything else in `data/` stays ignored:** downhill downloads, order books,
  other run outputs, logs, alerts, caches, `data/pg/`. The test fixtures and golden
  baselines are tracked (since 2026-09-28, [Testing](testing.md)); their raw downloads
  (`tests/fixtures/_work/`) aren't.
- **Enforced:** `tests/test_no_data_in_git.py` fails if data outside the allow-list is
  tracked or about to be added (it also runs in the [pre-push hook](testing.md#pre-push-hook)).
- **If the repo ever goes public,** this data must be removed from the git history
  first, not just deleted.

## Data bucket

Everything a cloud session needs that isn't in git lives in a private Google Cloud Storage
bucket: the first piece of an eventual move to Google Cloud ([proposal](google-cloud.md)).

| | |
|---|---|
| Bucket | `gs://racinglines-data-650570086451` (project `project-977bffa3-5f15-47d7-be1`, `us-west1`) |
| Access | Private: public access prevented, uniform bucket-level access, object versioning on |
| Cloud sessions | Service account `racinglines-cloud`, **objects in this bucket only** (`roles/storage.objectUser`), through an HMAC key (S3-compatible API) |
| Key | `~/.config/racinglines/gcs-hmac.env` on the owner's machine (mode 600, never in git) |
| Org policy | Service-account keys are blocked across the organization (Google's default); **allowed for this project only** (2026-09-28), for the cloud sessions' key |

**Layout** (the same in `scripts/cloud/bucket.sh` and `bucket.py`):

| Prefix | Local path | Holds |
|---|---|---|
| `db/racinglines.sql.gz`, `db/manifest.json` | `data/archive/bucket-db/` (cloud) | A full dump of the owner's database (plain SQL, gzipped): model runs, signals, positions, private-book markets, recorded books. The manifest records the time and the Alembic head |
| `live/` | `data/runs/live/` | Live-event run folders (Whistler's, and every one after) |
| `runs/f1/` | `data/runs/f1/` | F1 backtest and sweep outputs |
| `raw/mtb_dh/` | `data/raw/mtb_dh/` | Downhill downloads (ChronoRace) |
| `archive/markets/` | `data/archive/markets/` | The Polymarket and Kalshi archives, including what git doesn't carry |
| `results/<session>/` | – | What a cloud session sends back (reports, run folders) |

**Commands:**

```bash
bash scripts/cloud/bucket.sh push      # owner: dump the database + sync the folders up (gcloud)
bash scripts/cloud/bucket.sh pull      # owner: sync the folders down
bash scripts/cloud/bucket.sh ls
python scripts/cloud/bucket.py pull    # cloud session: folders + the dump (boto3, HMAC key)
python scripts/cloud/bucket.py push results/<session> data/runs/live/<event>
```

`scripts/cloud/start.sh` pulls the bucket and restores the full dump in place of the committed
snapshot, whenever the environment has the key (`SKIP_BUCKET=1` skips it). **Refresh the bucket**
(`bucket.sh push`) before launching a cloud session that needs current data.

**Cloud environment settings.** At claude.ai/code, click the cloud icon with the environment's name
in the row above the message box, hover over `racinglines`, and click its settings icon:
- **Environment variables:** add `RACINGLINES_GCS_BUCKET`, `RACINGLINES_GCS_HMAC_ID` and
  `RACINGLINES_GCS_HMAC_SECRET`, from the key file. To copy them without printing them:
  `pbcopy < ~/.config/racinglines/gcs-hmac.env`. Anyone using the environment can read them.
- **Network access:** **Trusted** is enough: its default list includes `storage.googleapis.com`.
- **CLI:** `/remote-env` in a local Claude Code session sets the default environment for `claude --cloud`.

## MotoGP public results source verified (2026-09-29)

The public MotoGP results API at `api.motogp.pulselive.com` is the source gate for the first data-backed MotoGP model work:

- **Verified scope:** season metadata, event lists, standings and race classification payloads are available and match the project schema.
- **Confirmed limits:** no JSON field exposes lap-by-lap or sector-level splits for a session; the guessed lap/sector endpoints return 400s or remain unsupported by the public API contract.
- **Implication:** the first model pass stays conservative and uses only result-derived features until a separate source or API contract is cleared.

## Exchange history: Kalshi and Polymarket

Both exchanges' F1 history lands in the same tables (`market_links`, `market_price_history`, `market_trades`,
`market_book_snapshots`; `market_links.exchange` tells them apart) and is archived in the same Parquet layout,
one tree per exchange: `data/archive/markets/<exchange>/{prices,trades,books}/month=YYYY-MM/*.parquet`.
What each feed gives differs:

| | Polymarket | Kalshi |
|---|---|---|
| API, auth | Gamma (markets), CLOB (prices, books), Data API (trades); public | One REST API (`api.elections.kalshi.com/trade-api/v2`); public for market data, a signed key only for orders |
| Contract in `market_links` | One row **per outcome token** (YES and NO are separate tokens with their own prices) | One row **per market**: its YES contract (`token_id` = market ticker, `condition_id` = event ticker). NO is the mirror image (NO at p = YES at 1 − p) |
| Grouping | Event slug (`f1-azerbaijan-grand-prix-…`) | Series (`KXF1RACE`) → event (`KXF1RACE-AZEGP26`) → market (`KXF1RACE-AZEGP26-OPIA`) |
| Resolution rules | Market description | `rules_primary`, stored in `params.rules`; markets on two venues are only compared when their rules agree |
| Trades | Data API, taker trades only, paged by offset (newest first, capped at offset 100,000 per market) | Every trade, cursor-paged with no cap. Trades settled before Kalshi's historical cutoff (about two months) come from `/historical/trades`; the connector reads both |
| Trade fields | Token, side of that token, price, size in shares, time, transaction hash, **wallet** | Market, **taker side** (YES bought = `BUY`, NO bought = `SELL` YES), YES price, size in contracts, time, trade id (`tx_hash`). **No wallets** (`wallet` = ""), so takers can't be told apart |
| Price history | `/prices-history` per token at `--fidelity` minutes (1 = minute-level): traded price | Candlesticks at 1, 60 or 1440 minutes: the candle's close, else the YES bid/ask mid. Markets past the cutoff read from `/historical/markets/<ticker>/candlesticks` |
| Order books | Live only (no historical API): `markets record` snapshots them | Live only too: `markets --exchange kalshi books` takes one snapshot; nothing records them continuously yet |
| Fees | None modelled (the `Polymarket` venue in `venue_replay.py` charges nothing) | Takers pay ⌈0.07 × contracts × P × (1 − P)⌉ cents per order (`venue_replay.Kalshi.taker_fee`); makers ⌈0.0175 × contracts × P × (1 − P)⌉ per fill on most markets (`maker_replay.KALSHI_MAKER_FEE`) |
| Tick | Per market (`tick_size`, mostly 1¢) | 1¢ |
| F1 coverage | 2025–2026 races and season markets; the last race listed was Baku 2026, nothing new since 28 August 2026 ([F1 live roadmap](f1-live-roadmap.md#polymarket-has-stopped-listing-f1-races)) | Every 2026 weekend (win, podium, top 10, pole, fastest lap, top constructor, head-to-heads), every 2025 weekend (win, podium; pole and fastest lap for the last three), and both championships of both years ([F1](f1.md#kalshi-alignment)) |

**Filling a simulated maker against Kalshi's tape.** Each Kalshi trade has the taker's side, price, size and
time, which is what a maker replay needs: a resting quote fills when a taker trade prints at or through it.
Wallets are missing, so the tape can't say who traded (no per-taker P&L, and one large order split into
several prints looks like several takers). The tape is thick on winner, pole, podium and championship markets and
thin on fastest lap and top constructor (median 10–12 trades per market over a weekend in 2026). 2025's race
markets opened only 2–4 days before each race and are thinner ([Data changes](data-changes.md)).

**Grouping.** A Kalshi `condition_id` is the event ticker, shared by every driver's market of the event, so Kalshi
code reads and groups the tape by `token_id` (the market ticker), never by `condition_id`; the 24 h volume filter is
per market.

**One store, a tree per exchange.** `markets archive` and the recorder's hourly pass write each row to its
market's exchange tree (`market_links.exchange`; a token without a link counts as Polymarket), and
`markets/store.py` reads every exchange's tree unless given a `root`, so Kalshi rows are read like Polymarket's.
The Kalshi replays pass `root=store.root_for("kalshi")` to read only Kalshi's tree. Before 2026-09-28 the archive
pass wrote everything to the Polymarket tree ([Data changes](data-changes.md)); the Kalshi-only files it left under
`polymarket/{prices,trades}/` on the owner's machine were deleted the same day (every row is in the Kalshi archive).

### Other series' tapes: NASCAR, MotoGP, IndyCar, road cycling, Le Mans, SailGP

Kalshi also lists NASCAR Cup (race winners and the champion), MotoGP and IndyCar. Each is a **tape-only
sport** ([Roadmap](todo.md#new-sports), U9): a schema with no model (`sports/nascar.toml`, `motogp.toml`,
`indycar.toml`; `[sport] model_family = "none"`, no `pricing_model`, no `[live]`), its own league and competition
(`nascar_cup`, `motogp_wc`, `indycar_series`, seeded by `db seed` like the others), and a `[markets.kalshi]
series` list of ticker prefixes (`KXNASCAR`, `KXMOTOGP`, `KXINDYCAR`) that the sync matches against Kalshi's
Sports series. Nothing is priced: the board and the Lab don't list them (they only show competitions with
model runs), `racinglines check` doesn't run them, and no pipeline reads them.

**Also built (PRs #50, #51):** the same kind of schema for UCI road cycling (`road_cycling`, competition `uci_road_wt`), Le Mans (`le_mans`, `le_mans_24h`) and SailGP (`sailgp`, `sailgp_champ`, Kalshi and OG.com), and a Polymarket path for NASCAR, MotoGP and IndyCar through `[markets.polymarket] tags` (slugs unverified, `--tags` overrides; additive). **First live run (VM, 2026-09-29):** Kalshi NASCAR 13,599 links, MotoGP 322, IndyCar 1,374; road cycling, Le Mans, SailGP and Polymarket not yet run.

**Off by default.** `racinglines markets --exchange kalshi sync` still syncs F1 and nothing else. A tape-only
sport is synced only when named, `--sport nascar` (or `motogp`, `indycar`); its links land in `market_links`
with `exchange = 'kalshi'` under its own competition, every one `prediction = 'unmodeled'` (no classifier, no
driver or race lookup), with the same fields as F1's (bid/ask/last, volume, `params.series`, `params.rules`,
close time, result). `trades`, `history` and `books` then work as for F1, and without `--events` take every
Kalshi event of the sport's competition (books: its open markets), so one recording pass is three commands.
Prices, trades and books are archived per exchange by `market_links.exchange`, so they go to
`data/archive/markets/kalshi/` with F1's rows; nothing separates the sports in the Parquet tree (the links do).

The Kalshi API is blocked from the cloud, so the series tickers are matched by prefix and were not checked
against the live listing; `sync --series TICKER …` syncs exact tickers when the discovery finds the wrong ones
(or none). The whole path is tested on fixtures in the client's shape (`tests/fixtures/market/kalshi_other_series.json`).

### What the "Exchange data" counts show

The Markets board's per-sport **Exchange data** table (and `/markets/tapes`) counts, per sport and exchange,
the rows stored for that sport's linked markets (`market_links`): **Trades** from `market_trades`, **Price
points** from `market_price_history`, **Books** from `market_book_snapshots`. Since 2026-09-30 each count spans
the Parquet archive and the Postgres buffer (`store.counts`; a buffered row counts when it is newer than the token's last archived row). The archive is scanned in a background thread, at most every 5 minutes and only the months that changed, so a page never waits on it: right after a restart the counts show the buffer alone until the first scan finishes; before that only the
buffer counted, which after `markets archive` holds just the last few hours and the hot races, so Polymarket read
0 trades and 0 price points and Kalshi a small slice of its tape. Only the exchange syncs and the recorder write
these tables, so the counts never include paper, demo-history or simulated trades (those live in the house book
tables). A zero shows as **n/a**: nothing stored. Each exchange's feed sets what can be stored at all:

| Exchange | Trades | Price points | Books |
|---|---|---|---|
| Polymarket | Taker trades only, the newest ~100,000 per market (Data API offset cap) | `/prices-history` at the fidelity pulled (hourly by default) | No history API: only what `markets record` snapshotted live |
| Kalshi | Every trade, no cap (older than about two months via `/historical/trades`) | Hourly candles: the close, else the YES bid/ask mid | No history API, and no Kalshi book recorder runs yet, so n/a |
| OG.com | Only about the last month is served, so the tape starts when we began pulling (2026-09-29) | Minute quotes, same one-month window | One snapshot per `books` run |

The same line per exchange shows under the table on the board (`venues.COVERAGE`; a schema exchange says it in its
own file, `[exchange] coverage`). Tape-only sports (NASCAR, MotoGP, IndyCar and the rest) are counted the same way
as F1: their rows share the tables and the per-exchange Parquet trees, and the links decide which sport a row belongs to.

## Respecting the sources' limits

Every download goes through one of two guards, so a long unattended run (e.g. a
[cloud sweep](cloud-sweep.md)) never hammers a source:

| Source | Guard |
|---|---|
| Polymarket (Gamma, CLOB, Data API), Kalshi, ChronoRace, Wikipedia | `racinglines/sources/http.py`: a minimum interval between requests to the same host, shared by every thread (CLOB 0.15 s, Gamma and Data API 0.25 s, Kalshi 0.25 s, ChronoRace 0.5 s, Wikipedia 1 s, others 0.25 s), and up to 5 tries with exponential backoff and jitter (2, 4, 8, 16 s …, capped at 120 s) on timeouts, dropped connections, 429 and 5xx, honouring `Retry-After`; other 4xx return at once |
| FastF1 (F1 live-timing archive) | FastF1's own limiter (500 calls an hour); on its rate-limit error the fetcher waits 5 minutes and tries again |

And nothing is downloaded twice:

- **FastF1:** sessions already on disk are skipped; each season's schedule is saved
  (`data/raw/f1/fastf1/<year>/schedule.parquet`) and used when FastF1 can't be reached.
- **Polymarket race weekends:** a weekend whose prices are stored is skipped
  (`racinglines f1 sweep --fetch-only`); championship history is fetched in 7-day windows, and
  windows already stored are skipped.
- **Sweeps** with `--no-fetch` (and every search job) never download; stage prices are cached by model settings and data.

## Source: ChronoRace

All timing comes from **ChronoRace** (`prod.chronorace.be`), the timing provider for
the UCI Mountain Bike World Cup / World Series. Their results site is an Angular
single-page app, so plain HTML fetches return an empty shell. The downloader calls
the JSON APIs behind the site instead.

| Endpoint | Used for |
|---|---|
| `https://prod.chronorace.be/api/results/uci/dh/cms/{slug}` | The event's content tree: disciplines → categories → rounds, each round with a "Live Timing" key and PDF links. |
| `https://prod.chronorace.be/api/results/generic/uci/{slug}/dh?key={key}` | One round's results: riders (including `UciRiderId`), per-split cumulative times and gaps, status. |

`{slug}` is ChronoRace's internal event ID: the first date of the event plus a
suffix. The suffix is `_mtb` for combined XC+DH weekends (2023+), `_dh`/`_dhi` for
DH-only or older events, and once `_xco`.

### Finding events for a season

ChronoRace has no "list events for a year" endpoint. The downloader reads the
Wikipedia page `"{year} UCI Mountain Bike World Cup"` instead. That page cites a
ChronoRace result PDF for most rounds, and the slugs are pulled out of those
citation URLs (`chronorace.blob.core.windows.net/webresources/<slug>/...pdf`).
There are three caveats:

- **Neighbouring seasons:** season pages also cite them (the 2026 page links the
  2025 finals), so discovery keeps only slugs dated in the requested year.
- **Incomplete pages:** some pages miss rounds. The 2021 page lists 4 of the 6 DH
  rounds. The two Snowshoe rounds (`20210914_dh`, `20210918_dh`) were found by
  **probing**: trying `YYYYMMDD_{dh,dhi,mtb,xco}` for every date in a window against the
  content-tree endpoint, which answers `null` for a slug that doesn't exist (`mtb_dh download --probe
  START END`). Probing all of 2021 finds exactly the six DH rounds.
- **Before 2019:** the 2016–2018 pages have no ChronoRace links, which fits with
  ChronoRace not timing the World Cup before 2019.

Use `--events` to download specific slugs.

### Categories

| Friendly name | Code | Used here |
|---|---|---|
| Elite Men / Men Elite | `ME` | Target and training |
| Junior Men / Men Junior | `MJ` | Training only |
| Elite Women / Junior Women | `WE` / `WJ` | Not yet |

## What's downloaded

116 files in `data/raw/mtb_dh/chronorace/`, one per event and category.

| Season | Events on file (ME / MJ) | With usable timing (ME / MJ) | Notes |
|---|---|---|---|
| 2019 | 8 / 8 | 0 / 0 | PDF links only. Live timing returns `null`. |
| 2020 | 4 / 4 | 0 / 0 | PDF links only. The PDFs' text layer is unreadable font codes, so they'd need OCR. |
| 2021 | 6 / 6 | 6 / 6 | Leogang and Les Gets are PDF-only in the feed; their files come from `download --pdf-results` (backfilled 2026-09-28, [Data changes](data-changes.md); Leogang's elite Qualifying PDF is missing on ChronoRace's server). Maribor, Lenzerheide, and Snowshoe ×2 have timing. |
| 2022 | 8 / 8 | 8 / 8 | Complete. |
| 2023 | 8 / 8 | 8 / 8 | Complete. |
| 2024 | 7 / 7 | 7 / 7 | Complete. |
| 2025 | 10 / 10 | 10 / 10 | Complete. |
| 2026 | 7 / 7 | 7 / 7 | Through round 7 (Les Gets). Rounds 8–9 not raced yet. |

Parsing everything gives about 93.5k tidy rows and 1,126 distinct riders.

- 180 of the 204 riders who raced 2026 Men Elite have earlier history.
- 177 riders have raced both junior and elite.

File naming:

- The 2026 elite files were renamed by hand: `2026-08_les-gets_men-elite.md`.
- Everything else uses the downloader's naming: `<slug>_dhi_<category>.md`.

The parser doesn't rely on file names. It reads the title, `Category:` line and
slug from inside the file.

`data/raw/mtb_dh/manual/` holds raw copy/pastes of 2026 Les Gets live-timing pages. They
duplicate data in `chronorace/` under different event IDs, so **don't include
them in a training run**.

### Known gaps and quirks

| Where | Gap |
|---|---|
| 2019, 2020, 2021 Leogang and Les Gets | PDF only (see above). |
| 2025 Pal Arinsal, juniors | The Final is PDF-only. |
| 2025 Val di Sole juniors; 2021 Maribor and Lenzerheide (one round each) | PDF-only Timed Training. |
| 2022 Snowshoe, juniors | One PDF-only round. |
| 2023 Vallnord, 2024 Loudenvielle (elite) | No Semi-Final (weather). The weekend ran qualifier → Final. |
| Venue names | The same venue appears under different names: `mont-ste-anne` / `mont-sainte-anne`; `vallnord` / `pal-arinsal` / `vallnord-pal-arinsal`. Nothing uses venue yet. |
| Rider names | The same rider can appear under different names across seasons, e.g. `WILLIAMS Robert Jordan` (2023) and `WILLIAMS Jordan` (2026). See [rider IDs](parser.md#rider-ids). |
| Round numbers (`events.series_round`) | Expected and supported, not a gap: nothing is renumbered. The number comes from ChronoRace's event title (`DHI #n`), so every season reuses 1, 2, 3..., and a season can even number two weekends the same: 2022 Leogang and Lenzerheide are both `#3`, 2025 Lake Placid and Mont-Sainte-Anne both `#9`. Events are identified by their id and ordered by date; a round number is only read together with its season. F1 code keys on (year, round); the downhill `points check --through-round N` takes the season's last event numbered N, so "after round 3" of 2022 counts both `#3` weekends (`points.through_event`). Counting distinct round numbers therefore shows 2022 and 2025 one short; count events with `status = 'completed'` instead. That is also the likely source of the "UCI 2023 shows 7 of 8 events completed and 2025 shows 9 of 10" note in the 2026 strategy review: in the 2026-09-28 database every 2023 (8) and 2025 (10) event is `completed`, with an elite Final of 30–61 results each. |

PDF-only rounds are written as a list of links, and the parser skips them, unless the file was
downloaded with `--pdf-results`: then the result PDF is read into the same table (`pdftotext -layout`,
racinglines/sources/chronorace/pdf.py), with a `(From the result PDF ...)` note and the PDF's weather,
temperature and track length under the heading. The 2021 PDFs also carry UCI IDs (Timed Training PDFs
don't). On 2021 Snowshoe, where both exist, every PDF finish time and first split equals the live
timing.

## File format

Each file starts with:

```
# UCI MOUNTAIN BIKE WORLD SERIES - XCO #7+XCC #7+DHI #7 - Les Gets, August 21-23, FRA

Category: Men Elite

Source: ChronoRace (prod.chronorace.be), event slug `20260821_mtb`
```

Then there's one `## <round>` section per round, each with a table:

```
| Pos | Bib | Rider | Team | Nation | Split 1 | ... | Split 5 | Time | Gap | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1020 | ALRAN Max | COMMENCAL/MUC-OFF ... | FRA | 32.255 (+00.431) | ... | 3:22.585 | 3:22.585 |  |  |
|  | 83 | MASTERS Wyn |  | NZL | | | | | |  |  | DNS |
```

Notes on the cells:

- **Split cells** are cumulative times, with the gap to the fastest at that split in
  brackets.
- **The last split** usually equals `Time`; it's the finish line.
- **`Pos`** is blank for DNF, DNS and DSQ, and `Status` says which.
- **Junk rows:** a few rows have obviously broken times (e.g. `63:45.985` with
  `00.000` splits). The parser treats zero times as missing, and the model's
  outlier handling keeps the rest from mattering.

## Race formats by year

| Seasons / category | Rounds (parser labels) | Final size |
|---|---|---|
| Elite 2021–22 | Timed Training (`practice`) → Qualification (`qual`) → Final (`final`) | 60–64 (top 60 plus protected riders) |
| Elite 2023–24 | Timed Training → Qualification (`qual`) → Semi-Final (`semi`, about 60) → Final | 30–34 |
| Elite 2025–26 | Timed Training → Qualification 1 (`qual1`) → Qualification 2 (`qual2`) → Final | 30 (20 + 10) |
| Juniors, all years | Timed Training → Qualification (`qual`) → Final | varies |

The model detects each event's format and field sizes from that event's own
results, so backtests of older seasons simulate the format actually raced (see
[Season model](model.md#weekend-formats)).

### The 2025–26 elite qualifying rule (checked against the data)

In every 2025 and 2026 round:

- the **top 20 in Q1** go straight to the Final and don't ride Q2;
- **everyone else** rides Q2;
- the **top 10 in Q2** fill the Final.

That's exactly 30 riders every time, with no protected or wildcard entries.
Unraced 2026 rounds are simulated with this format.

## NASCAR data sources (research, 2026-09-28)

For the December "NASCAR for 2027?" decision ([Roadmap](todo.md#new-sports), [Strategy 2026](strategy-2026.md)).
Written from a cloud session where `cf.nascar.com`, `nascar.com`, `racing-reference.info` and CRAN were blocked by
the network, so the feeds themselves were not opened: what's below comes from the packages and projects that wrap
them, and every claim that could not be checked is marked **(unverified)**. **The content feeds have since been
probed from the owner's machine (2026-09-29): [what the probe verified](#nascar-content-feeds-verified-2026-09-29)
supersedes the unverified marks for that row, and the adapter is built.**

### The sources

| Source | What it holds | History | Terms | Notes |
|---|---|---|---|---|
| **NASCAR content feeds** (`cf.nascar.com/cacher/…`, no auth) | Per season: `{year}/{series}/race_list_basic.json` and `schedule-combined-feed.json` (series 1 = Cup, 2 = Xfinity, 3 = Trucks). Per race id: results and stage results, weekend feed (results, cautions, leaders, stages, pit reports), `lap-times.json` (every lap: time, speed, position, flag), lap notes, pit stops (time, tyres), loop stats (driver rating, fastest laps, quality passes), practice lap averages (`lapAvg_*_practice_1.json`), qualifying | Feeds exist for at least 2019 (a 2019 practice endpoint is documented); the wrappers say "any year" **(unverified: my recollection is that lap-by-lap and loop data go back to about 2016 and results further; test one season per year backwards)** | **Undocumented and unlicensed.** nascar.com's terms of use are the only terms; they were not readable here **(unverified: they are believed to forbid automated access and commercial reuse of the site)**. The feeds are what nascar.com's own pages read | Live during a race (updated every ~20 s), plus `racing-insights/raw-feed/{id}-NCS.json` (official gaps, pit events) and `live-ops/live-ops.json` (which race is live). This is real live timing, unlike FastF1's post-session archive |
| **`feed.nascar.com`** (Swagger UI) | Results, standings, schedules, drivers, teams, lap data | ? | Same terms | Documented by api-evangelist/nascar as NASCAR's feed API; not opened here **(unverified)** |
| **`nascar-api`** (PyPI 0.1.3, 23 Sep 2026, MIT) | Typed client for the content feeds: `HistoricNascarRepo` (schedule, results, laps, lap notes, pit stops, weekend feed, loop stats, standings) and `LiveNascarFeedRepo` (positions, speeds, pits, telemetry); Cup, Xfinity, Trucks; retries built in | As the feeds | MIT for the code; the data's terms are NASCAR's | Python 3.11+, Pydantic. The obvious fetch layer if the feeds are used |
| **`pynascar`** (GitHub ab5525, MIT) | Same feeds: laps, pit stops, flags and race-control messages, results and stage results, practice and qualifying, cautions | As the feeds | MIT / NASCAR's | Less typed; 42 commits, active in 2025 |
| **`nascaR.data`** (R package, CRAN, GPL-3) | Race results per driver: finish, start, laps, laps led, points, driver and team; Cup **1949–present**, Xfinity 1982–, Trucks 1995– | Complete | GPL-3; data "scraped with permission from DriverAverages.com" | Updated every Monday in season. No laps, no practice; the cleanest long history of results and grids. Readable from Python as its CSV/RDS files |
| **Racing-Reference** (`racing-reference.info`) | Every Cup, Xfinity, Truck and ARCA race since 1949: results, starts, laps, led, status, points, plus loop data pages for recent years; driver, owner and crew-chief stats | Complete | Site terms not readable here **(unverified)**; no bulk export, third-party scrapers only | The reference archive; scrape only with permission and slowly (`sources/http.py` guards) |
| **Kaggle** | "NASCAR Champion History (1949–present)" and similar; the JSE 1975–2003 race-level set (drivers, purse, cautions, lead changes) | Partial | Per dataset | Nothing lap-level found; not needed given the above |
| **Commercial** (Sportradar NASCAR, SportsDataIO, OddsMatrix) | Live timing, results, standings, per-lap | Deep | Paid licences | Only if the free feeds' terms are unusable |

### What an ingest would need, next to the F1 adapter

The F1 path is `sources/fastf1/fetch.py` (session files to `data/raw/f1/fastf1/<year>/`) → `sources/fastf1/ingest.py`
(event, race, rounds, results, laps, track profiles) with the sport described in `sports/f1.toml`. NASCAR would follow
it with these differences:

| | F1 (`sports/f1.toml`, FastF1) | NASCAR (content feeds) |
|---|---|---|
| Season | 22–24 rounds, 20–22 cars, one race each | 36 points races + 2 exhibitions, 36–40 cars; Xfinity and Trucks are separate series (competitions) |
| Weekend | FP1–FP3 (or SQ + Sprint), Q, Race, each a `round` | Practice (one or two short sessions, sometimes none), qualifying (single laps, groups on road courses; **rained-out qualifying sets the grid by formula**), race in **three stages** with points at each; `[sessions]` and `[stages]` need `stage_1`, `stage_2` cut-offs |
| Results | Position, status, time, grid, points, Q1–Q3 | Position, status (running/accident/engine…), laps, **laps led, stage finishes, playoff points**; qualifying speed not sector times |
| Laps | Lap and sector times, speed traps, tyre, pit, track status | Lap time, speed, position, flag; pit stops and tyres from a separate feed; **cautions and restarts** matter more than pace |
| Identity | Ergast driver id (`AthleteIdentifier` scheme `f1`) | NASCAR driver id from the feeds (scheme `nascar`); car number is per team, not per driver |
| Track | Street/permanent, 2026 regulation reset | Oval (short, intermediate, superspeedway), road course; **pack racing at Daytona and Talladega is a different sport** for a position model |
| Championship | Points table | **Playoffs:** 16 drivers, three elimination rounds, winner-takes-all finale; the champion market prices the format, not the season's points |
| Live | Stage runs after each session (30-minute lag) | The feeds are live: an in-race book is possible, which the Chase tapes (U9) will show is where Kalshi's volume is |
| Model | `position_sim` | A first model can reuse `position_sim`'s shape (grid, pace, DNF) with a caution/restart layer; the Chase tapes decide whether in-race pricing is needed |

### Recommendation for December

- **Data is not the blocker.** Results and grids back to 1949 (`nascaR.data`) and per-lap, loop and stage data for at least
  the last several seasons (the content feeds) are enough for a first model in January; FastF1 gave F1 only 2020–.
- **Terms are.** The content feeds are undocumented and carry no licence. Before the decision, read nascar.com's terms of
  use and `feed.nascar.com`'s Swagger page from the owner's machine, and ask DriverAverages/Racing-Reference for
  permission if their pages are wanted. A polite, cached, once-a-week fetch through `sources/http.py` is the most that
  should be assumed; live polling every 20 s during a race is a bigger ask.
- **Do in October** (the two-week gap after Singapore): from the owner's machine, pull one Cup season with `nascar-api`
  (schedule, results, laps, loop stats for 2025) into `data/raw/nascar/cf/`, check how far back each feed goes, and
  keep the sample with the recorded Chase tapes. That turns every **(unverified)** above into a fact before December.
- **Decide on the tapes,** as the roadmap says: if Kalshi's per-race markets trade mostly in-race, the model needed is a
  live one and the feeds' live terms matter most; if pre-race, a grid-and-pace model on the archived feeds is the
  cheaper start and NASCAR is a good 2027 sport.

## NASCAR content feeds, verified (2026-09-29)

A read-only probe from the owner's Mac (Remote Control, 1 request/s, ~100 requests, no 429), the first use of the
"probe a data source before a full run" practice in `CLAUDE.md`.
The responses are the test fixtures (`tests/fixtures/market/nascar_*.json`, described in `nascar_README.txt`); the
owner reviewed nascar.com's terms and approved the probe. Base URL `https://cf.nascar.com/`, series 1 Cup, 2 Xfinity,
3 Trucks. The feeds are static objects behind CloudFront (no auth, no cookies). **A missing object is HTTP 403**
(S3 AccessDenied), not 404: 403 means "no such file", so nothing is retried.

| Feed | Path | Cup history | Stored as |
|---|---|---|---|
| Race list | `cacher/{y}/{s}/race_list_basic.json` | 2015– | `raw/nascar/cf/{y}/{s}/race_list_basic.json` |
| Standings | `cacher/{y}/{s}/points-feed.json` | 2016– | `.../points-feed.json` |
| Weekend feed: results, stage results, cautions, leaders, practice and qualifying | `cacher/{y}/{s}/{race}/weekend-feed.json` | 2017– | `.../{race}/weekend-feed.json` |
| Pit stops | `cacher/live/series_{s}/{race}/live-pit-data.json` | 2018– | `.../{race}/pit-data.json` |
| Loop stats: driver rating, passes, fast laps | `loopstats/prod/{y}/{s}/{race}.json` | 2019– | `.../{race}/loopstats.json` |
| Lap by lap: every car's lap time, running position, per-lap flag | `cacher/{y}/{s}/{race}/lap-times.json` | 2020– | `.../{race}/lap-times.json` |
| Race-control notes per lap | `cacher/{y}/{s}/{race}/lap-notes.json` | 2020– | `.../{race}/lap-notes.json` |

**Identity.** `driver_id` is a stable integer across teams and seasons (Larson 4030 at Ganassi in 2017 and Hendrick in
2026) and equals `NASCARDriverID` in the lap file. Names are clean in results but decorated in the lap and pit feeds
(`"Kyle Larson (C)"`, `"Austin Hill(i)"`), and a car number belongs to the team: **join on `driver_id`, never on a name or a
number.** The pit feed has no driver id; the ingest joins it to results on the car number where that is unambiguous.

**Data-quality findings the ingest handles** (each has a test):

- *Rained-out qualifying* (Darlington and Bristol 2026): the qualifying run exists with every time 0, `qualifying_speed` is 0 on every
  result and the grid was set by formula. No qualifying round is written and `races.format.qualifying_ran` is false.
- *Cars that never started* (Daytona 500 2026): results rows with `finishing_position` 0 and no status. Stored as `DNS`, position null.
- *Lap file with holes and a short end* (Darlington 2026): laps 330–335 absent for every car and nothing after lap 355 of 367.
  The laps that exist are stored; the race round's `extra` records `laps_complete`, `laps_max` and `laps_missing`, so a
  lap-based feature can drop races like this one. This is a source property, seen on one race so far; the first full pull says how common it is.
- *Older shape* (2017): result rows without `team_id`, `crew_chief_id`, `official_car_number`, `disqualified`, `diff_*`, and
  `bonus_points_earned` in place of `playoff_points_earned`; no `stage_results`. Missing fields stay absent, never zero.
- `diff_time` on a result is the gap to the winner in **milliseconds** (P2 at Darlington: 1038 = `margin_of_victory` "1.038");
  the winner's clock time is `total_race_time` (`h:mm:ss`).
- *Pit feed*: the first probe fixture held only the 15 pre-race entries (`lap_count` 0). A full race (Kansas 2026,
  `nascar_pit_data_2026_5628.json`) shows real stops: 267 records, 231 in-race, 36 cars with 3 to 10 stops each (median 6),
  `pit_stop_type` `FOUR_WHEEL_CHANGE` (185), `OTHER` (80, 44 of them in-race), two `TWO_WHEEL_CHANGE_*`, and
  `pit_in_flag_status` 2 for stops under caution. The ingest keeps each stop under the source's own field names in
  `results.extra.pit_stops`. That `lap_count` is the lap of the stop is **inferred, not proven** (the first five stops are all
  lap 36 under caution, in pit-in order), so `laps.pit_in` is still not set.
- *Overtime* (Daytona 500 2026): `lap-times` runs to lap 201 while `actual_laps` is 200. The completeness check is "every lap up to
  `actual_laps` is present", not "the last lap equals `actual_laps`"; `laps_max` can exceed `actual_laps`.

### The adapter

`racinglines nascar fetch` (`sources/nascar/fetch.py`) → `racinglines nascar ingest` (`sources/nascar/ingest.py`),
the F1 pattern ([Formula 1](f1.md)) with NASCAR's own shape:

| Table | NASCAR |
|---|---|
| `events` | one race weekend: `source = "nascar_cf"`, `source_key = "<year>-<race_id>"`, `series_round` = points-race number (exhibitions have none), venue = track name. Races still to run are filed as `scheduled` events with no rounds (from the season's race list), so a market on an upcoming race has a race to point at; the weekend feed turns the same event into a `completed` one |
| `races` | competition `nascar_cup`, category `DRV`; `format` = laps, stage laps, cautions and their segments (start, end, reason, free-pass car), race leaders, `qualifying_ran`, margin |
| `rounds` | only sessions that were run: `fp1`…, `qual1`… / `qual`, `race` |
| `results` | position (null if never classified), status `OK`/`DNF`/`DNS`/`DSQ`, `bib` = car number, team; `extra` = grid, points, playoff points, laps led, stage finishes and points, loop stats, pit stops, crew chief and owner ids |
| `laps` | race laps: lap time, running position, flag state in `track_status` (`"1"` green, `"2"` yellow, `"4"` checkered); lap speed is not stored (it follows from lap time and track length) |
| `athletes` | one per `driver_id`: `AthleteIdentifier(scheme="nascar", value=<driver_id>)` |

**Identity** (`sources/nascar/identity.py`): one resolver for the sport, whichever exchange listed the market. `Resolver(conn, year).driver(subject)`
returns the athlete for a name as a venue writes it and `.race(date, name)` the race held within a day of a date (which date a venue's market carries, and how far its close
runs past the race, is read from real listings, not assumed). Names match exactly first (accents, case, punctuation and suffixes ignored), then on first plus last
name, a nickname group, a short first name with a surname only one driver in the pool has ("Chris Bell"), and a bare surname only if unique.
**A name that fits two drivers ("Busch") is never guessed**: it resolves to nothing and `.unresolved` says why, so a rule is added on
purpose. The pool is the drivers who raced that season or the one before.

**Market links** (`sources/nascar/links.py`, `[identity] resolver = "nascar"` in `sports/nascar.toml`): which driver, race and contract each
exchange's market is about, so the same outcome on Kalshi, Polymarket and OG.com gets the same athlete and race and therefore one outcome
key (`links.outcome_key`: kind, athlete, race or season). It is built from the real listings of 2026-09-29
(`kalshi_nascar_events.json`, `polymarket_nascar_events.json`), and what it fills is small on purpose:

| Field | What it holds |
|---|---|
| `athlete_id` | The driver, for a Cup contract on one driver (through the resolver above). A head-to-head (Kalshi lists two markets per matchup, "Will A beat B at the …", yes = A finishes ahead) gets A here and B as `params.opponent_id`, both or neither, so the two sides are two outcomes. Not for a team or a manufacturer. |
| `race_id` | The Cup race, for a contract on one race. Found **by the race's name inside the market's season**, as a whole phrase against the season's Cup schedule (sponsor tails like "presented by Jiffy Lube" are optional): Kalshi's rules text and Polymarket's question both spell it out. A name two races share (Cook Out 400 is Martinsville and Richmond in 2026) is settled by the date the listing states (Kalshi: "originally scheduled for Oct 4, 2026"; Polymarket's slug), then by the close time, else left unset and reported. A date alone is never enough: the O'Reilly race runs the day before the Cup race on the same track. |
| `params.kind` | What the contract is: `race_win`, `race_podium`, `race_top5`, `race_top10`, `race_top20`, `race_pole`, `race_fastest_lap`, `race_biggest_mover`, `race_h2h`, `race_team_win`, `champion`, `regular_season_champion`, `in_season_challenge`. From the Kalshi series ticker, else the wording of the question ("win", "championship"). |
| `params.nascar_series` | `cup`, `xfinity` or `trucks`, when the listing says so or a Cup race matched. Trucks and O'Reilly (Auto Parts) links are **tagged, not filtered** (owner, 2026-09-29): they keep their competition and their tapes and get no driver or race, because the results adapter files Cup only. "Xfinity 500" is a Cup race; only "Xfinity Series" / "Auto Parts Series" tag the second series. |
| `params.season` | The market's year (from the rules date, a year in the text, the ticker's last two digits, or the close time). |

`prediction` is **not** touched: every NASCAR link stays `unmodeled`, so nothing on the board, the calendar or the strategies changes; `params.kind`
is what a later step promotes when there is a model. A listing it cannot place keeps whatever it had and is reported with the reason
("no race of that season named", "2 races share the name and the date does not pick one", "driver: unknown").

*Where it runs.* Inside the syncs (Kalshi, Polymarket and OG.com, for a sport whose schema names a resolver), so a re-sync never undoes it, and as a
pass over the links already stored: `racinglines nascar link` (dry run by default: totals, then one line per exchange, Kalshi series, class and kind
with how many got a driver and a race, then the unresolved names). `--apply` needs `--backup FILE` (a database dump under 24 hours old), writes only
`athlete_id`, `race_id` and `params` of the links that change, records a `data_changes` entry, and writes the previous values of every changed
link to `data/backups/db/nascar-links-undo-<UTC>.json`; `--undo FILE` puts them back one link at a time, so undoing does not mean restoring a dump
and losing the tapes recorded since. Run it after the full NASCAR pull (`fetch`, `ingest`): with no drivers or races in the database it can only
fill kinds and series.

*Side effects of a race id on a tape-only link.* `markets/store.hot_tokens` keeps the whole history in Postgres for links whose race is
upcoming or the latest completed (a link with no race keeps only its last days), so markets on an upcoming race, and on the latest race
once it has run, stay in Postgres in full until the next race replaces them; older races archive to Parquet as before. Everything that prices or
trades selects on `prediction`, which stays `unmodeled` (checked in the disagreement recorder, the replays, the weekend sweep, the scorecard, the calendar and the MCP tools).

*Sampled, 2026-09-29 (PR #68).* OG.com lists 17 NASCAR contracts, all Cup champion, one binary option per driver
(`og_instruments_nascar.json`, `og_tickers_nascar.json`): the contract type is "Moneyline", the event name says "NASCAR Cup Series
Champion", the season is the last part of the event symbol `NSCAR-00002-2026`; 15 of the 17 drivers resolve in the test database. A Kalshi
head-to-head is only listed around a race (none was open; `kalshi_nascar_h2h.json` holds settled events and their historical markets).
Not sampled: an open Polymarket race market for a race Kalshi also lists (the pass is tested on Polymarket's Coca-Cola 600, Cracker
Barrel 400, Cup champion and an Xfinity race, and on a synthetic South Point 400 row), and Kalshi's `KXNASCARCUPCHAMP`, `RACEOLD` and `TOPMANU`
series (no events came back for them). The first real dry run lists whatever does not resolve; read it before `--apply`.

Cup only for now: Xfinity and Trucks need their own competition rows before `--series 2|3` ingests. Lap-notes and standings are
fetched and kept (the raw record is cheap to keep and expensive to re-crawl) but not ingested yet. Nothing runs by default;
tests: `tests/test_nascar.py`, `tests/test_nascar_links.py`.

**A full pull is a VM job, after a backup.** Cup 2017–2026 is about 380 races and one to five feeds each depending on the year
(see the history column), ≈ 1,600 requests at 1/s (under half an hour; `--dry-run` counts them exactly); the lap table adds
8,000 to 18,000 rows per race from 2020 (roughly 3 million rows for 2020–2026; `--no-laps` skips it). Steps, in order: a small fetch on the Mac to read what comes back (done 2026-09-29 for Darlington, Kansas and the Daytona 500:
the fetch layer worked, 17 requests, no errors); a database dump (`data/backups/db/racinglines-before-nascar-<UTC time>.sql.gz`);
then `fetch` and `ingest` for the seasons wanted, with a `data_changes` entry and a line in [Data changes](data-changes.md)
naming the backup.
