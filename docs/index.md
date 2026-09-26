# racinglines

racinglines builds databases and prediction engines for timed race disciplines.
The first target is the **UCI Mountain Bike World Series downhill (DHI), Men Elite,
2026 season**. The long-term goal is to be accurate enough to make markets on a
niche sport.

These docs cover everything built so far in detail. The top-level `README.md` is
the short version, and parts of it are generated from sections of these pages
(see [Docs & README](cli.md#build_readmepy)).

## What it does

<!-- readme: overview -->

- **Downloads** official split timing from ChronoRace. Men Elite and Men Junior
  2021–2026 have usable data; 2019–20 exist only as PDFs.
- **Parses** it into one tidy table.
- **Learns** each rider's pace, consistency and crash/DNF rate from every season
  and category.
- **Simulates** race weekends (qualifying → Final) thousands of times. The output
  is each rider's chance to win, podium, finish top 10 and make the Final, plus
  expected championship points and final standings.
- **Backtests** itself on every season since 2021, predicting each round only from
  what came before it.

<!-- /readme -->

## What exists today

| Piece | File | What it does |
|---|---|---|
| Downloader | `download_chronorace.py` | Finds World Cup events for a year and writes per-round split timing to one markdown file per event and category. |
| Parser | `parser.py` | Turns downloaded files, copy/pastes, HTML, CSV or JSON into one tidy long-format CSV. |
| Season model | `predictor.py season` | Estimates each rider's pace from all seasons and categories, simulates race weekends in each event's own format, and projects 2026 championship standings. Includes walk-forward and holdout backtests. |
| Multi-season backtest | `predictor.py backtest` | Runs the walk-forward and standings backtests for every season with data (2021–2026). |
| Per-race model | `predictor.py fit` / `predict` | Earlier, separate approach: Elo ratings, a gradient-boosted time-gap regressor, and Plackett–Luce win probabilities. |

## Pipeline

```
download_chronorace.py ──> data/script-generated/*.md ──> parser.py ──> splits.csv ──> predictor.py season
     (ChronoRace API)          (1 file / event / category)      (tidy rows)     (backtests, forecast)
```

## Quickstart

<!-- readme: quickstart -->

```
pip install -r requirements.txt

python parser.py --input-dir data/script-generated --out splits.csv
python predictor.py season   --data splits.csv --walk-forward   # 2026 forecast + backtests
python predictor.py backtest --data splits.csv                  # every season since 2021
```

<!-- /readme -->

To build these docs:

<!-- readme: docs-build -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python build_readme.py   # refresh README.md from sections tagged in docs/
```

<!-- /readme -->

On very new Pythons (e.g. 3.14) the `watchdog` dependency may have no prebuilt
package and fail to build. `watchdog` is only needed for `mkdocs serve`'s live
reload. Either use Python ≤3.13, or install with
`pip install --no-deps mkdocs mkdocs-get-deps` plus mkdocs's other dependencies,
then run `mkdocs build` and open `site/index.html`.

## Repo layout

<!-- readme: repo-layout -->

| Path | |
|---|---|
| `download_chronorace.py` | Event discovery and download from ChronoRace |
| `parser.py` | Raw files → tidy CSV |
| `predictor.py` | Season model: `season`, `backtest`. Older per-race model: `fit`, `predict` |
| `build_readme.py` | Regenerates README sections from tagged docs sections |
| `requirements.txt`, `requirements-docs.txt` | Pinned dependencies (pipeline / docs site) |
| `data/script-generated/` | Downloaded event files (one per event and category) |
| `data/copy-paste/` | Raw live-timing copy/pastes. Duplicates of 2026 data; don't train on them. |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /readme -->

## Page map

- [Data](data.md): where the data comes from, what was downloaded, file format,
  and the race formats by year.
- [Parser](parser.md): input formats, the tidy schema, round labels, and rider-ID
  normalization.
- [Season model](model.md): the statistical model, how it's fit, and how weekends
  and seasons are simulated.
- [Evaluation](evaluation.md): metrics, walk-forward and holdout results, and
  whether older and junior data helps.
- [Current forecast](forecast.md): the latest projection for the remaining 2026 rounds.
- [CLI reference](cli.md): every command and option.
- [Project history](history.md): what was built, in what order, and why.
- [TODO](todo.md): open work, starting with points validation.

<!-- readme: points-warning -->

!!! warning "Points are placeholders"
    Championship points use approximate tables, not the official UCI scale. Every
    number measured in points (expected points, standings, champion odds) is
    approximate until [points validation](todo.md#points-validation) is done.
    Win, podium, top-10 and make-Final probabilities don't depend on points.

<!-- /readme -->
