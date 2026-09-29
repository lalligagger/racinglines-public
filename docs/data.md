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

### Other series' tapes: NASCAR, MotoGP, IndyCar

Kalshi also lists NASCAR Cup (race winners and the champion), MotoGP and IndyCar. Each is a **tape-only
sport** ([Roadmap](todo.md#new-sports), U9): a schema with no model (`sports/nascar.toml`, `motogp.toml`,
`indycar.toml`; `[sport] model_family = "none"`, no `pricing_model`, no `[live]`), its own league and competition
(`nascar_cup`, `motogp_wc`, `indycar_series`, seeded by `db seed` like the others), and a `[markets.kalshi]
series` list of ticker prefixes (`KXNASCAR`, `KXMOTOGP`, `KXINDYCAR`) that the sync matches against Kalshi's
Sports series. Nothing is priced: the board and the Lab don't list them (they only show competitions with
model runs), `racinglines check` doesn't run them, and no pipeline reads them.

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
Research only, no build. Written from a cloud session where `cf.nascar.com`, `nascar.com`, `racing-reference.info`
and CRAN were blocked by the network, so the feeds themselves were not opened: what's below comes from the
packages and projects that wrap them, and every claim that could not be checked is marked **(unverified)**.
Verify the feed shapes from the owner's machine before relying on any of it.

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
