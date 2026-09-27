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

- `racinglines/sources/chronorace/parse.py` handled HTML, CSV and JSON inputs, with guessed column names.
- `racinglines/models/timed_runs/` had the per-race model: Elo ratings, a gradient-boosted `pct_back`
  regressor, and Plackett–Luce win probabilities.

## 1. Copy/paste parser

**Input:** a select-all copy of the ChronoRace live-timing page for 2026 Les Gets
elite Qualification 2 (`uci:event:20260821_mtb:DHI:CG1:dh:91:res.md`).

**Built:** a `.md`/`.txt` path in `racinglines/sources/chronorace/parse.py`. It splits the page into rider blocks
on `n°<bib>` lines and classifies each token by its shape (split with rank, finish
time, gap, status, team). That makes missing team lines and missing splits
harmless. Also: `normalize_event_id`, and `:` as a separator in the event-ID parser.

**Checked:** all 88 riders parse (66 finishers, 3 DNF, 6 DSQ, 13 DNS). Every rider
has S1–S4 and FINISH rows, and completed splits are kept for DNFs.

## 2. 2026 season model

**Input:** `data/*.md` files from `racinglines/sources/chronorace/download.py`: 2026 Men Elite, rounds 1–7.

**Built:**

- A parser path for the downloaded markdown tables (detected by content).
- Checking the data showed the weekend format: Q1 top 20 go to the Final, the rest
  ride Q2, and the Q2 top 10 fill the Final. That held in all 7 rounds.
- The **season model** (see [Season model](model.md)). The existing Elo/GBR model
  wasn't extended, because it doesn't model the qualifying format or points.
- The `racinglines mtb_dh forecast` command: a holdout backtest of the last 2 rounds, and a
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
`data/raw/mtb_dh/chronorace/`. Two downloader fixes:

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

**New:** `racinglines mtb_dh backtest`, covering 2021–2026: 43 rounds, 6 standings holdouts.

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
  [CLI reference](cli.md#scriptsbuild_readmepy).

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
  idempotent ingest keyed on file hashes, and `racinglines db` commands.
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

## 12. Roles: admin, maker, taker

- **Accounts:** the web app now has real accounts (`users`, scrypt hashes) and three
  roles.
  - Takers bet on a board of every maker's markets, without seeing fair values.
  - Makers quote and manage their own markets.
  - The admin sees and settles everything, and has an activity log, user
    management, a per-user trading view, a database explorer (row edit and delete)
    and a SQL console (read-only by default).
- **Checked end to end:**
  - the access matrix for all three roles;
  - maker quoting;
  - a taker bet;
  - a stale-price bet refused;
  - the stake cap;
  - cross-maker edits and maker settlement blocked;
  - activity logged;
  - password hashes hidden;
  - read-only SQL rejecting `DELETE` and data-modifying `WITH`;
  - a row edit logged with before and after values.

## 13. Aligning with real Polymarket F1 markets

- **Model:** the F1 forecast now also produces constructors' championship
  odds, per-race top-scoring constructor, race and championship head-to-heads,
  season win counts, and a season pace drift.
- **Sync:** `racinglines/markets/polymarket/sync.py` maps Polymarket's F1 events onto those
  predictions. The first sync covered 21 events and 336 outcome tokens, 234 of
  them priced by the model.
- **Makers** get a Polymarket board with live prices vs fair values, and can
  mirror a market into their own book in one click.
- **Takers** see the Polymarket price next to every mirrored quote.
- **Settlement:** mirrored markets settle from Polymarket's resolution.
- **Found:** the model's biggest gap to the market (Sainz ahead of Alonso) is a
  blind spot for chaotic races, not an edge.

## 14. Leakage review and as-of pricing

- **Clean separation:** backtests (`kind='backtest'`), single-event diagnostics
  (`'diagnostic'`) and live forecasts (`'forecast'`) all price through one
  function with a hard session-time cutoff, checked by `assert_no_leak`.
- **Old runs:** runs 5–8 predate this and shouldn't be used.
- **Season drift:** its size is now estimated as of the cutoff, and it applies
  only to season totals.
- **Baku test case:** the Azerbaijan GP priced as of the evening before. Model
  vs Polymarket at the cutoff, scored on the result, on a maker-side diagnostic
  page.

## 15. Maker replay on the real Polymarket tape

- **Recording:** Polymarket minute prices and the full trade tape for Baku,
  plus a book-snapshot recorder for future events.
- **Replay:** a maker quoting through three as-of stages (pre-qualifying,
  post-qualifying, overnight) and filled only by real taker trades. At ±2¢ it
  lost $303: it was adversely selected, and pre-qualifying inventory was the
  biggest loss.
- **Sample taker:** the `taker` account's bets are the replay's fills.
- **Tests:** 53 pytest tests. See [Market making](market-making.md).

## 16. One product: board, race pages, book, lab

- **Standard shape.** Every view reads one structure: event → outcome → our fair,
  venue quotes (Polymarket, Kalshi coming soon, private book) and result.
  Upcoming races use the live forecast; past races use the last as-of price,
  compared with the exchange at the same moment.
- **Board.** Every sport's next races, season markets and recent results, plus
  headline numbers.
- **Race page.** Replaces Predictions, Market board and the event view: price
  chart, every market kind across venues, quoting actions, classification.
- **My book.** Replaces My markets: positions across venues.
- **Lab.** Replaces Diagnostics, Model runs and Backtests. Backtests, scenario
  forecasts and diagnostics are launched with knobs as background jobs; a
  scenario is promoted to live explicitly.
- **Event diagnostic.** The maker replay exposes every strategy knob.
- **Fixes:**
    - a phantom "nan" constructor, from two F1 results with no team id;
    - constructors named by their latest team name.
- **Tests:** 66.

## 17. Shared car, season sweep, Parquet market store

- **Shared car.** Car pace now comes from both drivers, and teammates share
  part of the race noise. Teammate head-to-heads improved significantly.
- **2026 season sweep.** Every weekend priced before any running and after each
  session, and traded against Polymarket at that moment:
    - maker replay +$852;
    - taking −$1,313 (update), −$2 (hold), −$512 (after qualifying only).
- **Parquet market store.** Heavy exchange history moves to Parquet under an
  event-aware retention rule:
    - Postgres went from 975 MB to 228 MB;
    - 1.9M market rows take 15 MB;
    - the FastF1 cache (1.2 GB) was cleared, since raw sessions are kept as
      Parquet;
    - `data/` went from 1.2 GB to 37 MB.

## 18. Data layout and one package

- **Data layout:** `data/` is organized by lifecycle, then sport:
  `raw/<sport>/<source>`, `archive/markets/<exchange>`, `runs/<sport>`, `cache/`.
  Every path comes from `racinglines/paths.py`. Downhill source files are keyed
  by their path relative to `data/`, so moving the tree doesn't cause a
  re-ingest.
- **One package:** the code moved into `racinglines/`:
    - `sources/`, `models/`, `markets/`, `pipelines/`, `db/`, `web/`;
    - one `racinglines` command with `f1`, `mtb_dh`, `markets`, `db` and `web`
      groups, replacing `python -m f1`, `python -m racedb`, `python -m webapp`,
      `predictor.py`, `parser.py` and `download_chronorace.py`;
    - the old Elo per-race downhill model (`predictor.py fit`/`predict`) was
      removed.
- **No behaviour change:** the pinned regression suite passed with identical
  golden outputs.

## 19. Cleanup, no data in git

- **Shared helpers:** duplicated helpers were consolidated (`core/stats.py`,
  `markets/strategies/sizing.py`), and dead code and stale references were
  removed.
- **No data in git:** fixtures, raw downloads and golden baselines are ignored,
  and a guard test enforces it. The downhill files committed earlier are
  untracked.
- **Fixtures from public sources:** `scripts/fetch_test_fixtures.py` builds the
  test fixtures from FastF1, ChronoRace and Polymarket, replacing the extractor
  that read our own database.

## 20. Refreshed results and layered docs

- **2026 sweep re-priced with the practice prior** (run 191). Every taker
  strategy improved: update & rebuy went from −$1,313 to −$479, and enter &
  hold from −$2 to +$214. The maker replay stayed profitable (+$751). Trades
  after FP2 swung from −$11 to +$1,130, and the model now beats Polymarket's
  race-winner price mid-weekend.
- **Downhill backtest re-run** (run 192) reproduced the published numbers to
  within simulation noise.
- **Docs reorganized:**
    - a headline page first;
    - then one layer at a time: data, models, accuracy, markets, operations,
      background;
    - the README is generated from the same tagged sections.
- **F1 roadmap and reference** added to the docs: a phased plan (F1-0 …
  F1-7) with ground rules (the baseline stays the default, new behavior behind
  switches, golden files unchanged, a promotion rule), and the model and
  market-making ideas behind it. The sport-schema phase is now additive only.
- **Pre-push hook** (`scripts/hooks/pre-push`): the docs must build with
  `--strict`, the README must match them, and no data may be tracked.

## 21. F1 roadmap F1-1 to F1-4: variants, evaluation, strategy options

- **Sport schemas** (`sports/f1.toml`, `sports/mtb_dh.toml`): points, sessions,
  rounds and market kinds now live in one file per sport. The code reads them;
  every constant is unchanged.
- **Model variants behind switches** (`--variant`): a front-of-grid term
  (`grid`, `gridq`), a no-practice finishing model (`pretrain`), a
  gradient-boosted finishing model (`gbm`) and a disrupted-race tail with
  correlated retirements (`tail`). The baseline stays the default and the golden
  files are unchanged.
- **Evaluation:** `racinglines f1 compare` (paired ± 2 SE, reliability bins) and
  `racinglines f1 matrix`, every variant against every strategy.
- **Strategy options:** a stage-aware taker (in-sample +$1,874), and three maker
  options (flatten before quali, info-timed skew, widen on bad markouts).
- **Championship checkpoints** (`f1 season-checkpoints`): books entered
  pre-season, after 3 and after 6 GPs, held, and scored on how far the market
  came to our number. Early 2026 the market knew more (new regulations, winter
  testing); the new `reset` variant fixes the car ranking but not the driver
  split.
- **Docs in the app:** the built docs are served at `/docs/`, linked in the nav.
- **Result:** `gridq+pretrain` is better than baseline at every stage it touches
  and lifts every maker strategy (default +$751 → +$874); adding `reset` makes
  every weekend strategy profitable. The default stays the baseline for now.

## Reproducing the tuning sweep

The scope, half-life and junior-weight table in [Evaluation](evaluation.md#tuning)
came from a short script that calls the library functions directly:

```python
import numpy as np
from racinglines.db.config import get_engine
from racinglines.db.queries import load_tidy
from racinglines.models import timed_runs as P
raw = load_tidy(get_engine())
target = P.select_target(raw, 2026, "ME")
for scope, hl, jw in [("season", 75, .5), ("all", 120, 0), ("all", 120, .5), ("all", 240, .5)]:
    wf = P.walk_forward_season(raw, target, min_prior_events=1, n_sims=4000,
                               rng=np.random.default_rng(0), train_scope=scope,
                               half_life_days=hl, category_weights={"MJ": jw})
    print(scope, hl, jw, wf[["spearman_points", "brier_podium", "brier_final", "top10_hits"]].mean().round(4).to_dict())
```
