# Data

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
  content-tree endpoint. Probing isn't built into the downloader yet (see [TODO](todo.md)).
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

116 files in `data/script-generated/`, one per event and category.

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

`data/copy-paste/` holds raw copy/pastes of 2026 Les Gets live-timing pages. They
duplicate data in `script-generated/` under different event IDs, so **don't include
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
