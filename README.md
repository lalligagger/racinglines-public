# racinglines
create databases and build prediction engines for timed race sport disciplines; become a market maker for some niche sport on prediction markets

Current focus: **UCI Mountain Bike World Series downhill, Men Elite**.

<!-- Sections between include markers are generated from docs/ by build_readme.py.
     Edit the tagged section in docs/, then run: python build_readme.py -->

## What it does

<!-- include: overview -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

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

<!-- /include -->

### Headline numbers

<!-- include: headline -->
<!-- generated from docs/evaluation.md by build_readme.py - edit it there -->

Walk-forward backtest over 43 rounds, 2021–2026. Each round is predicted only from
data before it.

| | Model | Uniform guess |
|---|---|---|
| Brier score, making the Final | **0.127** | 0.204 |
| Brier score, podium | **0.0224** | 0.0259 |
| Win probability given to the actual winner (average) | **7.1%** | ~1% |
| Rank correlation, predicted vs actual points | **0.62** | 0 |

Per-season and per-round tables: [Evaluation](docs/evaluation.md#results-every-season-with-data-20212026).

<!-- /include -->

<!-- include: forecast-summary -->
<!-- generated from docs/forecast.md by build_readme.py - edit it there -->

2026 title odds with 2 rounds left: **Williams 72.7%**, Vermette 18.5%, Pierron 4.2%,
Iles 2.8% ([full forecast](docs/forecast.md#projected-final-standings)).

<!-- /include -->

<!-- include: points-warning -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

> ⚠️ **Points are placeholders**
>
> Championship points use approximate tables, not the official UCI scale. Every
> number measured in points (expected points, standings, champion odds) is
> approximate until [points validation](docs/todo.md#points-validation) is done.
> Win, podium, top-10 and make-Final probabilities don't depend on points.

<!-- /include -->

## Quickstart

<!-- include: quickstart -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
pip install -r requirements.txt

python parser.py --input-dir data/script-generated --out splits.csv
python predictor.py season   --data splits.csv --walk-forward   # 2026 forecast + backtests
python predictor.py backtest --data splits.csv                  # every season since 2021
```

<!-- /include -->

## Docs

Full documentation covers the data sources and gaps, parser, model, evaluation,
the current forecast, CLI reference and project history. The source is in
[`docs/`](docs/).

<!-- include: docs-build -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python build_readme.py   # refresh README.md from sections tagged in docs/
```

<!-- /include -->

## Repo layout

<!-- include: repo-layout -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

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

<!-- /include -->

## TODO

Full list: [`docs/todo.md`](docs/todo.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**Points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      for past formats.
- [ ] Replace `FINAL_POINTS` / `QUAL_POINTS` / `QUAL_POINTS_ROUND`, per era if needed.
- [ ] Settle the edge cases: DNF/DSQ in the Final, ties, protected riders, bonus rounds.
- [ ] Check our 2026 totals after round 7 against the official standings, and add a
      test that pins them.
- [ ] Re-run and refresh the published numbers.

**Data**

- [ ] Key riders by UCI ID. It's in ChronoRace's JSON; names change across seasons.
- [ ] Parse the readable 2021 PDFs (Leogang, Les Gets). 2019–20 would need OCR.
- [ ] Build rounds missing from Wikipedia (probing) into the downloader. Clean up
      venue names.
- [ ] Add Women's categories, start order and weather.

**Model**

- [ ] Check calibration: win probabilities look too flat.
- [ ] Tune over all 43 backtest rounds. Add rider × venue effects.

**Engineering**

- [ ] Tests.

<!-- /include -->
