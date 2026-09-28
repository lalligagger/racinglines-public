# Cloud build-out

A long, unattended build session in a [Claude Code cloud session](https://code.claude.com/docs/en/claude-code-on-the-web),
working through the [Roadmap](todo.md) in priority order until nothing more can be done
without a live event, the owner, or data the cloud machine can't reach. This page is the
session's brief, protocol and progress log.

**Launch** (from a local terminal, with the branch pushed):

```sh
claude --cloud "Run the cloud build-out in docs/cloud-buildout.md. Follow its Agent protocol exactly."
```

Use the `racinglines` environment ([Cloud sweeps](cloud-sweep.md#one-time-setup)):
Trusted network, `BASH_MAX_TIMEOUT_MS=1800000`. The session works on its own
`claude/…` branch, cut from `live-event`; it's merged back through `live-event` into
`main` after a local review.

---

## Goal

1. **P0 first: the first live F1 test**, round 16 (the Bahrain GP at Sepang, 2–4 Oct 2026),
   exactly as planned in [F1 live test](f1-live-roadmap.md), code-complete and pushed by
   **Wed 30 Sep 2026, 12:00 PDT (19:00 UTC)**. The owner merges it and rehearses locally
   on Thursday.
2. **One seamless way to launch a live simulation for any sport**: F1 (session-end
   updates) and downhill (a timing feed polled every few seconds) today, more sports
   later. It's defined by schemas, not code, wherever possible.
3. **Then every other open item on the [Roadmap](todo.md)**, in priority order, as far as
   the cloud machine allows.

**Context.** Polymarket has listed no F1 race markets since 28 Aug 2026 (the venue change;
see the business context in [F1 live test](f1-live-roadmap.md#1-business-context)), and
no venue lists downhill markets. So every live event for now is a **mock private book**:
the demo maker quotes, 1,000 simulated takers and the demo taker trade, play money. The
code must still take Polymarket (or another venue) prices the moment they exist.

---

## Design: schemas first

The [multi-sport design](f1-live-roadmap.md#multi-sport-design-one-live-core-one-adapter-per-sport)
is the plan: one shared live core, one adapter per sport. The owner's requirement is that
everything that can be data **is** data. Sports already differ as data
(`sports/<code>.toml`, read through `racinglines/sports.py`); extend that.

### A `[live]` section per sport (`sports/<code>.toml`)

What a sport's live simulation *is*:

| Key (suggested) | Downhill (`mtb_dh`) | F1 (`f1`) |
|---|---|---|
| `sources.historical` | ChronoRace results (kind, URL template) | FastF1 archive |
| `sources.live` | ChronoRace live JSON (`prod.chronorace.be/api/results/generic/uci/{slug}/dh?key={key}`) | The model's stage runs (FastF1 archive, per session) |
| `poll.mode` | `interval` | `session_end` |
| `poll.interval_s`, `poll.late_interval_s`, `poll.late_when_left` | 5, 2, 3 (as at Whistler) | – |
| `poll.lag_min` | – | 30 (session end + data lag; as `weekend_sweep.DATA_LAG`) |
| `markets.kinds` | `race_win`, `race_podium` | `race_win`, `race_podium`, `race_pole`, `race_h2h`, `race_constructor_top` |
| `quoting` | half-spread 3¢, +2¢ on course, +1¢ next to start, `max_pos` 2,500, skew 1.0 | half-spread by stage (3 / 2.5 / 2¢), `max_pos` 2,500, skew 1.0 |
| `crowd` | 1,000 takers, $10–200 budgets, per-poll rate, late window 50×, $100 caps | the same crowd; one batch per update, per-hour rate; pre-race window |
| `freeze` / `close` | pull a market after a rider's last split; close when the final is over | freeze after qualifying's update; close at lights out |

Today's values live as constants in `pipelines/live_dh.py`. Move them into the schema, with
the constants reading from it, exactly as `sports.py` did for the models.

### A launch spec per event (committed config, not data)

Suggested: `live/<sport>/<event>.toml`. It holds:
- the sport, the event key, and the feed arguments (downhill: slug, final key, qualifying keys, conditions; F1: event key);
- the time window, and any overrides of the sport's `[live]` values;
- the market-set source (for F1's head-to-heads: the last listing Polymarket published).

### One CLI for every sport

Suggested; keep the names consistent with the existing CLI:

| Command | What it does |
|---|---|
| `racinglines live new <sport> <event>` | Write a launch spec from the schedule, with the sport's defaults |
| `racinglines live step <spec>` | One idempotent update (F1: act only if a stage run or a close/settle time is new; downhill: one poll) |
| `racinglines live run <spec>` | Loop `step` at the sport's cadence until the event is settled |
| `racinglines live agent <spec> [--install/--remove]` | Write (and load) a macOS LaunchAgent for the spec: a lock, restart, logs |
| `racinglines live status` | Every event: live / replay / settled, last update, lateness |
| `racinglines live report <spec>` | The event report (Markdown + charts + PDF), generalised from the Whistler report |

`racinglines mtb_dh live …` keeps working (delegating to the new path), and the Whistler
run folder keeps rendering and replaying exactly as it does today.

**Adding a sport** should mean: a `[live]` section, a launch spec, an adapter module
implementing the four-function interface (`markets`, `step`, `outcomes`, `view`), and a
page body partial. Prove it with a **synthetic third sport in the tests** (a toy adapter
and schema), and document the steps in [Live events](live-events.md).

---

## Tracks: one session or two in parallel

The owner has credits to use, so the queue splits into two tracks that don't touch the same
files. Launch one session per track, or one session for both (it works Track A first).

| Track | Items | Owns |
|---|---|---|
| **A: live platform** (critical path) | Queue items 1–3: P0, the unified launcher, P1 | `pipelines/live*.py`, `markets/crowd.py`, `markets/quoting.py`, `markets/private_book.py`, `sports/*.toml` `[live]`, `live/`, the Live tab templates, `racinglines live` CLI |
| **B: everything else** | Queue item 4, except anything in Track A's files | Models (`models/`), downhill data and parsers (`sources/`), exchanges (`markets/polymarket/trade.py`, a new `markets/kalshi/`), web pages other than the Live tab, tests for those |

**Launch commands** (one session each):

```sh
claude --cloud "Run the cloud build-out in docs/cloud-buildout.md, Track A only. Follow its Agent protocol exactly."
claude --cloud "Run the cloud build-out in docs/cloud-buildout.md, Track B only. Follow its Agent protocol exactly."
```

**In two sessions:**
- each keeps its own lines in the progress log, prefixed `A:` or `B:`;
- Track B doesn't edit Track A's files; if it needs a change there, it adds a Roadmap item;
- shared docs (the Roadmap, the README) get small, separate edits;
- merges happen locally, A first.

## Work queue, in order

Work top to bottom. An item that can't be finished in the cloud gets its code and
synthetic tests done, then goes on the blocked list in the [log](#progress-log) with what's
missing.

**1. P0: the F1 live test.** Build items B0–B8 in [F1 live test](f1-live-roadmap.md#build-items-scenario-b),
as the shared core + adapter + schemas above:
- the name aliases;
- the shared core (`markets/crowd.py`, `markets/quoting.py`, `pipelines/live.py` with the registry);
- the F1 adapter with the 100-market set, priced from stage runs;
- the Live tab's shell with a downhill body and an F1 body;
- the demo taker's hype picks;
- operations (LaunchAgent, lock, lateness alert, frozen settings);
- a rehearsal on Baku (`2026-15`) on a simulated clock.

Defaults for the plan's open questions: no informed takers, hype picks only, the usual
five kinds (no top-10), no live feed.

**2. The unified launcher.** The `[live]` schemas, launch specs and the `racinglines live`
CLI above:
- a launch spec for round 16 (F1) and one for the next downhill event, if one is known in the data;
- the synthetic third sport.

**3. P1 on the Roadmap:**
- the report command;
- a per-market loss cap or two-sided long-shot quotes in `quoting.py`;
- Singapore (round 17, a **sprint** weekend: add the sprint stages to the F1 adapter);
- settling the Whistler book in the database (code and a migration; the owner runs it locally);
- re-pricing an event from its logged raw feed.

**4. P2–P4, and every other open item on the Roadmap**, in its priority order. Also: a
**Google Cloud architecture proposal** (a docs page; the owner plans to move there):
- the database on Cloud SQL, and the web app on Cloud Run;
- the pollers and signal engine on Cloud Scheduler with Cloud Run jobs;
- the bucket as the data layer, service identities (no keys), and a cost estimate. Notes for
items with limits in the cloud:

| Item | In the cloud |
|---|---|
| CLOB V2 order signing | Implement with `py-clob-client-v2` and dry-run tests; **never** set `POLYMARKET_TRADING_ENABLED` or send an order |
| Kalshi connector (F1-9) | Build against Kalshi's documented API with mocked responses; mark it unverified against the live API |
| Promote `gridq+pretrain` | **Owner's decision: don't.** Prepare the change (sweep + `UPDATE_GOLDEN`) on a separate commit only if asked |
| Sizing, walk-forward, bankroll-aware sizing | Code and synthetic tests; decisions need live weekends |
| Book-depth replay / queue model | Build the model and tests on synthetic books; recorded books are local-only |
| F1 props (safety car, red flag, rain, fastest lap) | Price them from the committed FastF1 track-status and weather data, as optional private-book market kinds in the schema |
| Downhill points validation | The official UCI scales can't be fetched here: build the `points_schemes` loading, the reconciliation harness and the pinning test, with placeholders marked; the owner enters the official numbers |
| Downhill data (UCI rider IDs, start order, weather, Women's categories, slug probing, other input formats) | Code paths and parser tests on synthetic inputs; re-downloads run locally |
| Downhill model (calibration, 43-round tuning, rider × venue, trends) | Only if the downhill results are in the snapshot; otherwise code and tests |
| Web: admin P&L filter, a public JSON API, a setting that hides the `demo_context` bubbles | Do them; keep the bubbles on by default (the demo needs them) |

---

## Rules

- **The [F1 roadmap's ground rules](f1-roadmap.md#ground-rules) apply:**
  - the baseline stays the default; every new behaviour sits behind a switch that defaults to today's;
  - golden files pass untouched;
  - no renames or moves visible from outside (moved functions are imported back under their old names);
  - no refactors that aren't needed.
- **Downhill must not change.** Whistler's book re-derived from its fills, its replay pages
  and the downhill tests must match today. The run folder isn't in git, so write that
  regression test to skip when the folder is missing, and add it to the local checks in the log.
- **Database changes** are additive Alembic migrations (`migrations/versions/`), never destructive.
- **The data bucket** ([Data](data.md#data-bucket)) holds what git doesn't:
  - a full dump of the owner's database (model runs, signals, positions, books);
  - the Whistler run folder and every live run after it;
  - the F1 run outputs, the downhill downloads, and the Polymarket archive.

  `start.sh` pulls it when the environment has the key. Use it: Whistler's regression
  check can then run in the cloud too. Send reports and run folders back with
  `python scripts/cloud/bucket.py push results/<session> <path>`, never through git.
  If the key isn't set, note that in the log and carry on with the committed snapshot.
- **No data in git** beyond the allow-listed set: run `tests/test_no_data_in_git.py` before
  every push. Configs (schemas, launch specs) are fine; run outputs aren't.
- **No real trading, no secrets, no fabricated numbers.** Results measured on synthetic
  data say so. Anything not verified against a live service says so.
- **Docs are the source of truth.** Update the page that documents each feature, in the house
  style (short sentences, tables). Then run `python scripts/build_readme.py` and
  `python -m mkdocs build --strict`. The pre-push hook doesn't run in the cloud, so run it by hand.
- **Roadmap bookkeeping:**
  - tick items on the [Roadmap](todo.md) and in [F1 live test](f1-live-roadmap.md) when done;
  - add new items you discover;
  - add a decision-log line for every design decision (in [F1 live test](f1-live-roadmap.md#11-decision-log) or the [F1 roadmap](f1-roadmap.md)).

---

## Agent protocol

1. **Bring up the machine:** `bash scripts/cloud/start.sh` (Python 3.14 venv, Postgres, the
   database: the bucket's full dump if the key is set, else the committed snapshot).
   - Without the bucket, the snapshot has no `model_runs`: compute any stage runs you need (e.g. Baku's) offline from `data/raw/f1` (`--no-fetch`).
   - Try `python scripts/fetch_test_fixtures.py` once. If the network blocks it, note that in the log, and use `python -m pytest -m quick` plus your new tests; the full suite runs locally.
2. **Read** this page, the [Roadmap](todo.md), [F1 live test](f1-live-roadmap.md),
   [Live events](live-events.md), and the code named in them (`pipelines/live_dh.py`,
   `pipelines/signals.py`, `markets/private_book.py`, `sports.py`, `web/views.py` `live_page`).
3. **Work the queue in order.** For each item:
   - make the change, with tests;
   - run the tests and the docs checks;
   - commit with a message that names the item;
   - **push to your branch after every item** (never to `main`, never force-push);
   - add a line to the [log](#progress-log).
4. **P0 checkpoint:** when B0–B7 are done and the Baku rehearsal passes (or by Wed 30 Sep
   12:00 PDT, whichever is first), write a **P0 handoff** entry in the log. It says what's
   done, what's missing, and the exact local steps to merge and rehearse. Push it. Then
   carry on with the queue.
5. **Keep going** until every remaining item is blocked (a live event, the owner, local-only
   data or services). Then write the **final handoff**:
   - what was done, with the commits;
   - the blocked list: each item, what it needs, and who;
   - the local checks the owner must run after merging (below).

   Push, and stop.
6. If the owner sends a message, their instructions override this page.

**Local checks after merging** (the session copies this list into its handoff, adding to it):

- The full regression suite (`python -m pytest -m "not live"`) on the local fixtures.
- Whistler: its book re-derived from `crowd.jsonl`, `/live` and replay unchanged.
- Migrations applied to the local database (`alembic upgrade head`).
- `racinglines live agent <round-16 spec> --install`, then a dry run of one `step`.
- The pre-push hook passes.

---

## Progress log

The session appends here: date and time (UTC), item, commit, status, notes.

| When (UTC) | Item | Commit | Status | Notes |
|---|---|---|---|---|
| 2026-09-28 | Brief written | – | – | Ready to launch |
| 2026-09-29 02:45 | A: bring-up | 9010faf | done | Bucket key set: pulled the full database dump and the Whistler run folder. `bucket.py` now installs boto3 with uv (the venv has no pip); `start.sh` upgrades uv so the venv gets Python 3.14.7, not 3.14.0rc2 (pydantic fails under pytest on rc2). |
| 2026-09-29 03:00 | A: fixtures | – | blocked | `fetch_test_fixtures.py`: the proxy refuses FastF1, Polymarket and ChronoRace (403). Using `-m quick` plus new tests; the full suite runs locally. |
| 2026-09-29 03:05 | A: B0 name aliases | B0 | done | `GP_ALIASES`: Malaysian, Sepang, Kuala Lumpur, "Bahrain … in Malaysia" → `2026-16`. |
| 2026-09-28 02:56 | A: B1 shared live core | cdd9a37 | done | crowd / quoting / live core + registry; `[live]` in both schemas; Live tab shell + `live_mtb_dh.html`. Whistler: book re-derived, all 82 replay + Positions pages byte-identical, downhill digest pinned. |
| 2026-09-28 03:04 | A: B2 F1 markets | 767f103 | done | 99 markets from the stored stage runs; sums exact at every Baku stage. Baku's Lindblad–Tsunoda pair dropped (Tsunoda not in the field). Sepang: unknown venue, neutral track features. |
| 2026-09-28 03:04 | A: B3 F1 engine step | 767f103 | done | `live_f1.step` + `racinglines live` CLI; Baku on a simulated clock: 7 updates, pole after Quali, the rest at results, book reconciles, positions sum to maker P&L. |
