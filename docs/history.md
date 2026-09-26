# Project history

All of the work below happened in **one Claude Code session**, my first
(vibe-)coding session with Claude, within the session credit limit of a basic paid
plan. By the time the pitch deck and docs were finished, the session limit was at
96%:

![Claude Code session limit at 96% near the end of the session](img/session-limit.png)

What was built so far, in order, with the reasoning behind each step. The
`2026-09` dates are when the work was done. The race data covers 2019–2026.

## 0. Starting point

The repo started with two scaffolds written before any real data existed:

- `parser.py` handled HTML, CSV and JSON inputs, with guessed column names.
- `predictor.py` had the per-race model: Elo ratings, a gradient-boosted `pct_back`
  regressor, and Plackett–Luce win probabilities.

## 1. Copy/paste parser

**Input:** a select-all copy of the ChronoRace live-timing page for 2026 Les Gets
elite Qualification 2 (`uci:event:20260821_mtb:DHI:CG1:dh:91:res.md`).

**Built:** a `.md`/`.txt` path in `parser.py`. It splits the page into rider blocks
on `n°<bib>` lines and classifies each token by its shape (split with rank, finish
time, gap, status, team). That makes missing team lines and missing splits
harmless. Also: `normalize_event_id`, and `:` as a separator in the event-ID parser.

**Checked:** all 88 riders parse (66 finishers, 3 DNF, 6 DSQ, 13 DNS). Every rider
has S1–S4 and FINISH rows, and completed splits are kept for DNFs.

## 2. 2026 season model

**Input:** `data/*.md` files from `download_chronorace.py`: 2026 Men Elite, rounds 1–7.

**Built:**

- A parser path for the downloaded markdown tables (detected by content).
- Checking the data showed the weekend format: Q1 top 20 go to the Final, the rest
  ride Q2, and the Q2 top 10 fill the Final. That held in all 7 rounds.
- The **season model** (see [Season model](model.md)). The existing Elo/GBR model
  wasn't extended, because it doesn't model the qualifying format or points.
- The `predictor.py season` command: a holdout backtest of the last 2 rounds, and a
  forecast of the remaining 2 rounds plus final standings.
- Placeholder points tables. The user chose "Finals + qual points, marked as a
  guess", with official values to follow.

**Result (2026 data only):** holdout Spearman about 0.65–0.67. Make-Final Brier about
half the baseline. Williams at 82% for the title.

## 3. README and TODO

A README with a "What it does" demo section, and a points-validation checklist.

## 4. 2023–25 elite plus juniors as training data

**Goal:** still predict only 2026, but learn from older seasons and junior results.

**Downloads:** Men Elite 2023–25 and Men Junior 2023–26 into
`data/script-generated/`. Two downloader fixes:

1. Wikipedia season pages also link neighbouring seasons, so discovery keeps only
   the requested year.
2. The results endpoint can return bare `null`, which crashed a whole year. It now
   falls back to PDF links for that round.

**Parser:**

- New round labels `qual` and `semi`, for the 2023–24 elite format and juniors.
- The category is now part of `event_id`, because elite and junior share event slugs.
- Venue comes from the file's title.
- **Rider-ID normalization:** 159 riders had been split across IDs, from accents,
  ` *` markers, double spaces and apostrophes. None are left.

**Model:**

- Target and training are separated (`select_target`, `_training_rows`).
- Recency is now measured in days rather than events.
- Category weights were added.
- Noise and incident rates are pooled from the target category only.

**New:** `--walk-forward`. It showed that history improves 2026 Spearman from 0.643
to 0.668 on the same 6 rounds, and lets round 1 be predicted at all.

## 5. Docs site

These MkDocs pages, with the README cut down to a high-level summary.

## 6. 2019–2022 downloads and multi-season backtest

**Goal:** get the last 10 years of elite and junior results, and backtest every
season since 2020.

**What exists:**

- **2016–18:** no ChronoRace links on Wikipedia, which fits with ChronoRace not
  timing the World Cup then.
- **2019–20:** events exist on ChronoRace, but live timing returns `null`. Only PDFs
  exist, and the 2020 PDFs are unreadable without OCR.
- **2021:** Leogang and Les Gets are PDF-only. The PDFs are readable text, and the
  parser for them is still a TODO. Maribor and Lenzerheide are in JSON. The two
  Snowshoe rounds were missing from Wikipedia and found by probing dated slugs.
- **2022:** all 8 rounds.

Downloader fix: PDF links typed `Folder` (2019–20) are now captured.

**Model:** `event_format` detects each event's format (`q1q2`, `semi`, `single`)
and field sizes from the event's results, so older seasons are simulated in the
format actually raced. Qualifying points follow the format too.

**New:** `predictor.py backtest`, covering 2021–2026: 43 rounds, 6 standings holdouts.

**Result:** walk-forward Spearman 0.617 overall (0.58–0.67 by season). Make-Final
Brier 0.127 vs 0.204. The actual winner averaged a 7.1% win probability (uniform
is about 1%). The 2026 forecast barely changed: Williams at 72.7%.

**Found:** a rider published under two names (`WILLIAMS Robert Jordan` in 2023,
`WILLIAMS Jordan` later). Name keys can't fix this; UCI IDs would.

## 7. requirements.txt and README generation

- `requirements.txt` pins the pipeline's dependencies at the versions everything
  was run with. `requirements-docs.txt` covers mkdocs.
- `build_readme.py` generates parts of the README from sections tagged in
  `docs/`, so the README summary and the docs can't disagree. See
  [CLI reference](cli.md#build_readmepy).

## 8. PostgreSQL

**Goal:** move to a proper database ahead of a web API, with room for many sports
and leagues.

**Built:** the `racedb/` package.

- **SQLAlchemy 2 models** organized sport → league → competition → season → event
  → race → round → result → split.
- **Athletes** are shared across sports and matched through `(scheme, value)`
  identifiers. That's ready for UCI IDs.
- **Venue aliases**, and tables for **points schemes**, **model runs** and
  **predictions**.
- Alembic migrations, `docker-compose.yml` (Postgres 17 on port 5433), an
  idempotent ingest keyed on file hashes, and `python -m racedb` commands.
- `predictor.py --db` loads the same tidy layout from the database, and `--save`
  stores runs.

**Checked:**

- Ingest: all 88 files with timing data load in about 8 seconds (18,761 results,
  69,472 splits, 1,126 athletes). Re-ingesting is a no-op, and forced re-ingests
  don't duplicate anything.
- Forecasts and backtests from the database match the CSV pipeline within
  simulation noise.
- The full flow was run against the Docker Postgres: `docker compose up`, `init`,
  `ingest`, `season --db --save`.

## 9. Admin web app, Polymarket, and Whistler

**Built:**

- **`webapp/`:** an admin-only FastAPI app with predictions, events, athletes, model
  runs/backtests, market linking and maker-only Polymarket orders (preview →
  confirm, post-only, size cap, dry run unless enabled). New `market_links` and
  `orders` tables.
- **Forecasting a weekend in progress:** if an event has a start list but no Final
  yet, it's forecast with its real field. The model is fit on data before the
  weekend, and the weekend effect is conditioned on Timed Training, with a sanity
  check. The parser now keeps not-yet-raced start lists (`NA` → `START`).

**Whistler 2026 (DHI #8, `20260925_mtb`):**

- Downloaded on race weekend: Timed Training done, Q1 start list of 109 riders.
- The first forecast adjusted everyone about −15% from Timed Training, because
  riders were held on track and times jumped by minutes. That run was deleted, and
  the IQR check added so a disrupted session is ignored.
- The corrected forecast (run 3) has Williams at 6.9% to win, Vermette 5.8%,
  Max Alran 5.4% and Bruni 4.9%.
- Polymarket has no downhill markets as of 2026-09-26.

## 10. House book for Whistler

Polymarket has no downhill markets, so the app now quotes its own YES/NO markets
for private bets: win, podium, make the Final, and championship rank up/down.

- Prices are fair value ± half the spread.
- Bets are recorded with their exposure and EV, and markets settle automatically
  from results (rank markets by hand from official standings).
- The forecast now includes rank-movement probabilities for the next weekend
  (`rank_moves`).
- A 75-market Whistler book (top 15 riders per market type, 6-point spread) was
  generated from model run 4.

## 11. Sign-in, throttling and the Cloudflare tunnel

- **Sign-in:** the app now has a sign-in page and a signed 12-hour session cookie,
  because embedded browsers don't show HTTP Basic prompts. Basic auth still works
  for scripts.
- **Before going public:** failed-login throttling (8 per IP per 15 minutes, using
  `CF-Connecting-IP`) and `Secure` cookies over HTTPS were added before exposing
  the app through a quick `cloudflared` tunnel.
- **New routes:** `/events/by-key/{source_key}` (stable event links) and `/pitch`
  (serves a static page from the repo root).

## Reproducing the tuning sweep

The scope, half-life and junior-weight table in [Evaluation](evaluation.md#tuning)
came from a short script that calls the library functions directly:

```python
import numpy as np, pandas as pd, predictor as P
raw = P.load_splits("splits.csv")
target = P.select_target(raw, 2026, "ME")
for scope, hl, jw in [("season", 75, .5), ("all", 120, 0), ("all", 120, .5), ("all", 240, .5)]:
    wf = P.walk_forward_season(raw, target, min_prior_events=1, n_sims=4000,
                               rng=np.random.default_rng(0), train_scope=scope,
                               half_life_days=hl, category_weights={"MJ": jw})
    print(scope, hl, jw, wf[["spearman_points", "brier_podium", "brier_final", "top10_hits"]].mean().round(4).to_dict())
```
