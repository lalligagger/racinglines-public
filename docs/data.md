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
| `data/archive/db/` | Database snapshot |
| `data/runs/search/` | Search results brought back from cloud sessions |
| `data/runs/live/<slug>_<key>/` | A live event, kept permanently for replay: raw timing-feed responses, snapshots, quotes, model inputs, the private book and every crowd fill (see [Live events](live-events.md#kept-for-replay)) |

- **Everything else in `data/` stays ignored:** downhill downloads, order books,
  other run outputs, logs, alerts, caches, `data/pg/`, plus `tests/fixtures/` and
  `tests/golden/`.
- **Enforced:** `tests/test_no_data_in_git.py` fails if data outside the allow-list is
  tracked or about to be added (it also runs in the [pre-push hook](testing.md#pre-push-hook)).
- **If the repo ever goes public,** this data must be removed from the git history
  first, not just deleted.

## Data bucket

Everything a cloud session needs that isn't in git lives in a private Google Cloud Storage
bucket: the first piece of an eventual move to Google Cloud.

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
| `archive/markets/` | `data/archive/markets/` | The Polymarket archive, including what git doesn't carry |
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

## Respecting the sources' limits

Every download goes through one of two guards, so a long unattended run (e.g. a
[cloud sweep](cloud-sweep.md)) never hammers a source:

| Source | Guard |
|---|---|
| Polymarket (Gamma, CLOB, Data API), ChronoRace, Wikipedia | `racinglines/sources/http.py`: a minimum interval between requests to the same host, shared by every thread (CLOB 0.15 s, Gamma and Data API 0.25 s, ChronoRace 0.5 s, Wikipedia 1 s, others 0.25 s), and up to 5 tries with exponential backoff and jitter (2, 4, 8, 16 s …, capped at 120 s) on timeouts, dropped connections, 429 and 5xx, honouring `Retry-After`; other 4xx return at once |
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
  **probing**: trying `YYYYMMDD_{dh,dhi,mtb}` for every date in a window against the
  content-tree endpoint. Probing isn't built into the downloader yet (see [Roadmap](todo.md)).
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
| 2021 | 6 / 6 | 4 / 4 | Leogang and Les Gets are PDF-only (the PDFs are readable text). Maribor, Lenzerheide, and Snowshoe ×2 have timing. |
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

PDF-only rounds are written as a list of links, and the parser skips them.

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
