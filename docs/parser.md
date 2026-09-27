# Parser

`racinglines/sources/chronorace/parse.py` turns raw result files into one **tidy long-format CSV**. The predictor
reads only this CSV, so any new data source only needs a parser path.

```
racinglines mtb_dh parse --inspect <file>                              # print what was detected, write nothing
racinglines mtb_dh parse --input-dir data/raw/mtb_dh/chronorace --out splits.csv
racinglines mtb_dh parse --input-file a.md --input-file b.html --out splits.csv
```

## Input formats

The format is picked by file extension, and for `.md`/`.txt` by content:

| # | Input | Detection | Notes |
|---|---|---|---|
| 1 | Saved, fully rendered HTML page | `.html` / `.htm` | Reads `<table>` elements. Column names are matched fuzzily through `COLUMN_MAP`. |
| 2 | CSV export | `.csv` | Same column mapping as HTML. |
| 3 | Raw JSON (e.g. an XHR response saved from devtools) | `.json` | Handles a list of rider dicts with nested splits. |
| 4 | Copy/paste of the live-timing page | `.md` / `.txt` without a `| Pos |` table | See [copy/paste format](#copypaste-format). |
| 5 | Downloaded event file | `.md` containing a `| Pos |` table | The main path. See [Data](data.md#file-format). |

Formats 1–3 predate the real data and are best-effort. Formats 4 and 5 have been
tested on real files.

## Tidy schema

One row per **rider × sector × round**:

| Column | Type | Meaning |
|---|---|---|
| `event_id` | str | `<slug>_DHI_<category>`, e.g. `20260821_mtb_DHI_ME`. The category is included because juniors and elites race the same event. |
| `event_date` | str | ISO date, from the slug. |
| `discipline` | str | `DHI` |
| `category` | str | `ME`, `MJ`, `WE`, `WJ` (from the file's `Category:` line) |
| `round` | str | `practice`, `qual`, `qual1`, `qual2`, `semi`, `final` |
| `rider_id` | str | Normalized name key. See [rider IDs](#rider-ids). |
| `rider_name` | str | Display name, cleaned of `*` markers and doubled spaces. |
| `team`, `bib`, `nation` | str | As published. Bibs differ between Timed Training and racing, so don't join on them. |
| `start_order` | int | Always empty; start order isn't in the data yet. |
| `venue` | str | From the title, e.g. `les-gets`, `mont-sainte-anne`. |
| `series_round` | int | The `DHI #n` number from the title. |
| `sector_id` | str | `S1..Sn` for splits, `FINISH` for the whole run. |
| `split_time_s` | float | Time for this sector alone. On `FINISH` rows it's the last split to the line. |
| `cum_time_s` | float | Cumulative time at this split. On `FINISH` rows it's the run time. |
| `rank_at_split` | float | On `FINISH` rows: official `Pos`. On split rows: recomputed rank by cumulative time within the round. |
| `status` | str | `OK`, `DNF`, `DNS`, `DSQ`, or `START` (on a published start list, not raced yet: ChronoRace shows `NA`). For a DNF, completed splits are `OK` and later ones carry the status. |
| `track_condition` | str | `unknown`. Can be backfilled with `--conditions-file` (CSV of `event_id,round,track_condition`). |

## Round labels

Downloaded files use `## <round>` headings, mapped by `TABLE_ROUND_MAP` (the first
match wins):

| Heading | Label |
|---|---|
| Timed Training / Practice | `practice` |
| Qualification 1 | `qual1` |
| Qualification 2 | `qual2` |
| Semi-Final | `semi` |
| Qualification (single qualifier: 2023–24 elite, juniors) | `qual` |
| Final | `final` |

`semi` must be checked before `final`, because "Semi-Final" contains "final".

## Rider IDs

There's no UCI ID in the data, so riders are keyed by name. ChronoRace spells the
same rider differently across seasons:

- accents present or dropped: `ABELLA Léo` / `ABELLA Leo`;
- a trailing ` *` marker on some seasons' lists: `CAPPELLO Davide *`;
- doubled spaces: `KIEFER  Henri`;
- apostrophe or space: `O'CALLAGHAN Oisin` / `O CALLAGHAN Oisin`.

`normalize_rider_id` handles all four:

1. remove `*` and collapse whitespace (`clean_rider_name`);
2. convert accents to plain ASCII (Unicode NFKD);
3. lowercase, and turn apostrophes into spaces;
4. keep only `a-z` and spaces, then collapse spaces.

The result looks like `name:o callaghan oisin`. Before this fix, **159 riders were
split across two or more IDs**, which quietly threw away much of the history that
older seasons add. After the fix, there are none. Here's the check used, which is
worth re-running after new downloads:

```python
import pandas as pd, unicodedata, re
d = pd.read_csv("splits.csv"); f = d[d.sector_id == "FINISH"]
key = lambda n: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower())
g = f.drop_duplicates(["rider_id", "rider_name"]).assign(k=f.rider_name.map(key)).groupby("k").rider_id.nunique()
print(g[g > 1])   # should be empty
```

Name keys still fail in two ways:

- **Name changes:** the same rider published under a different name, e.g.
  `WILLIAMS Robert Jordan` (2023) and `WILLIAMS Jordan` (2026) look like one rider
  but get two IDs. That rider's history is split, and the model treats their 2026
  self as partly new.
- **Namesakes:** two riders sharing a name would be merged. None are known yet.

The real fix is ChronoRace's `UciRiderId`, which the results JSON has for every
rider but the downloader doesn't write out yet (see [TODO](todo.md#data)).

## Downloaded-file details

- **Splits:** the gap in brackets is removed from each split cell. If the last split
  equals `Time`, it's treated as the finish line rather than a real sector.
- **Missing times:** zero or blank times (`00.000`) become missing.
- **Status:** comes from the `Status` column. `NA` with no time means the round
  hasn't been raced yet, and becomes `START`, so start lists for a weekend in
  progress are kept. Any other row with no time and no status counts as `DNF`.
- **Venue:** the last `" - "` part of the title, up to the first comma, turned into
  a slug. So `"... - Les Gets, August 21-23, FRA"` becomes `les-gets`.

## Copy/paste format

This is a select-all copy of the live-timing page. Each rider is a block of lines:

```
1.	n°100                       <- rank + bib (no rank for DNF/DNS/DSQ)
                                <- flag image (lost in copy)
O CALLAGHAN Oisin               <- name
TREK - UNBROKEN DH	35.954 (31) <- optional team, then split 1 (split rank)
1:49.498 (5)
...
4:07.776                        <- finish time
+1.063                          <- gap (every rider except the winner)
```

After the name, each token is classified by its shape:

| Token looks like | Meaning |
|---|---|
| a time with a rank in brackets | a split |
| a bare time | the finish |
| starts with `+` or `-` | a gap (ignored) |
| `DNF` / `DNS` / `DSQ` | the status |
| any other text before the first time | the team |

Because tokens are classified by shape, a missing team line or missing splits don't
shift anything. The event ID comes from filenames like
`uci:event:20260821_mtb:DHI:CG1:dh:91:res.md`, which become `20260821_mtb_DHI_CG1_dh_91`.
The round comes from the "Live Timing - Qualification 2" header.

Test file: 2026 Les Gets elite Q2. All 88 riders parse (66 finishers, 3 DNF,
6 DSQ, 13 DNS), including riders with no team line.
