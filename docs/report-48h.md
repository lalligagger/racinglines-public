# Sports and exchanges, 48 hours: backfills into the web app, then a public repo with CI (29 Sep – 1 Oct 2026)

From 2026-09-29 16:00Z to the morning of 1 Oct (UTC), most of the work went into one problem: getting the backfills
for every sport and exchange to reach the production web app. NASCAR and MotoGP went from tape-only listings to sports
the app shows end to end: results, identified Kalshi markets, a simple model price for NASCAR's next race, and a demo
paper P&L history on the Strategy and Positions pages. The owner's 3 × 3 soft-launch grid (F1, NASCAR, MotoGP ×
Polymarket, Kalshi, OG.com) has 7 of 9 cells with something in them; MotoGP on Polymarket (no linked markets) and
MotoGP on OG.com (not listed) are the two empty ones. The last stretch moved the code to the public repo
`lalligagger/racinglines-public`, where **merging to `main` now deploys to the VM** and deploys carry code only, so
data and the database stay on the VM. The honest bottom line has not moved: **the only held-out-robust strategy is
still F1 profile A on Polymarket**, which has listed no F1 race since 28 Aug. Every NASCAR and MotoGP dollar below is
in-sample paper, and almost all of it is NASCAR 2026.

This replaces the 24-hour report of 30 Sep (kept in the old private repo, first version PR #104, final #113). PR numbers
with a `#` (#85, #110 …) are the old private repo's; "PR 2" to "PR 9" are the public repo's, where numbering restarted.

| Piece | Result on the morning of 1 Oct | Label |
| --- | --- | --- |
| Production app | Markets shows every sport's status, NASCAR and MotoGP sections with model prices, next races and recent results; Strategy splits the record by sport and maker/taker; the OG.com column is on | Live, behind `RACINGLINES_SPORT_STATUS=1`, `RACINGLINES_SPORT_PAPER=1` and `RACINGLINES_OG_VENUE=1` (all on on the VM) |
| NASCAR paper record (Kalshi) | Pro demo 2025 **−$278.31** (8 races), 2026 **+$6,525.45** (32); Basic demo **−$357.23** and **+$2,657.23** | In-sample, demo only |
| MotoGP paper record (Kalshi) | 2026 only, 11 races: Pro **+$31.25**, Basic **+$7.70**; no 2025 markets | In-sample, no held-out season |
| NASCAR next-race price | Forecast run #9068 stored; the board and race pages show a fair price | Simple baseline, uncalibrated |
| MotoGP next-race price | None: no MotoGP calendar is ingested, so there is no next race to price | Gap |
| F1 | Profile A stays (106-job sweep); demo taker paper 2025 **+$450.46**, 2026 **+$353.01** | Robust on Polymarket; paper |
| Champion replays (#95, #96) | Merged 30 Sep 22:41Z; the VM runs (handoff steps 5 to 7) not done yet | Gap |
| Kalshi and OG.com books | Recorded every 5 minutes on the VM since 30 Sep 23:39Z | Live; books only, no trade tape |
| Code delivery | Public repo; merge to `main` = staging smoke, VM deploy, production smoke. First full green run 08:14Z; PRs 2 to 9 merged | Live; tests in CI since PR 9 |
| Data safety | The VM's disk is the only copy of the newest database dumps, backups and archived market history | Open: STG-5 |
| Beta sign-up | Built (PR 7) behind `RACINGLINES_SIGNUP`, off by default; switched on by `vm.sh accounts` | Built; switch-on not verified here |

**Screenshots.** The 24-hour report's screenshots were placeholders, and this version has none: the cloud session that
wrote it can't reach the site. Retaking them (1024 px wide, 150% zoom, with `browser_smoke.py`) is an open item.

## 1. Backfills into the web app: what a visitor sees now

The backfills became visible through #105-#112 (deployed on 30 Sep, VM on `306a147`) and then through the public
repo's CI deploys on 1 Oct. The /markets timeout that failed the 16:05 smoke check on 30 Sep (#101 counted the Parquet
archive inside the request) is fixed by #103.

| Page | What changed | PR | Switch (VM) |
| --- | --- | --- | --- |
| Markets | "Every sport: status" table: one row per sport schema with race data, exchange markets, model, backtests and (Pro) the demo paper record; missing pieces say so | #110 | `RACINGLINES_SPORT_STATUS=1` (on) |
| Markets | NASCAR and MotoGP sections: the model's replay-save prices, next scheduled races, recent results (MotoGP counts the RDR category) | #111 | same |
| Markets, race pages | NASCAR next-race fair price from the stored forecast run | #112 | — (data) |
| Strategy (Pro) | "Where the P&L came from": the record split by sport and by maker/taker | #110 | — |
| Positions, Signals, nav P&L | NASCAR and MotoGP demo positions with race names, dates and a "demo replay, in-sample" pill; buy-all rows never shown | #110 | `RACINGLINES_SPORT_PAPER=1` (on) |
| Strategy pages | NASCAR and MotoGP sport filters; the sport catalog dropdown lists every modeled sport | #108, #109 | — |
| Docs | `docs/coverage.md` is the status page (sport × exchange matrix, honest model status) | #105, #106 | — |
| Markets | Per-venue "Order books recorded" line (live / stale since / no data yet); the OG.com column | #119 | `RACINGLINES_OG_VENUE=1` (on) |
| Every page | Maintenance popup on sign-in and app pages, dismissed once per browser session (`MAINTENANCE_NOTICE` in `racinglines/web/app.py`; `""` turns it off; changing it is a deploy) | PR 2 | — |
| Sign-up, sign-in, admin | `/signup`: scrypt-hashed account plus 1,000 fantasy bucks in `accounts.fantasy_ledger` in one transaction; every sign-up starts as pro; no email collected; `/admin/users` one-time password reset with a ready-to-send email, Remove and balances; "Forgot password" opens a prefilled email to hello@racinglines.bet. The `accounts` schema is created by `vm.sh accounts` (backup first), never by a deploy | PR 7 | `RACINGLINES_SIGNUP=1` (off by default) |
| /docs | Built on the VM at every deploy (was answering "Docs not built"); `vm.sh docs` after a docs-only merge | PR 7 | — |
| README | CI, Python, license and Tests badges; contributor guide and an invite to collaborators | PRs 7, 9 | — |

`browser_smoke.py` (PR 7) signs in with the demo buttons as pro and basic, follows same-site links two levels deep,
reports 4xx/5xx and JavaScript errors, and saves 1024 px screenshots. It is read-only and hasn't been run against
racinglines.bet yet.

## 2. Data status per sport and exchange

What the production database held on the evening of 30 Sep, and how far each cell can be trusted. "Paper" means the
demo accounts' backfilled record, never real orders: both trading flags are unset and OG.com has no order code.

| Sport × exchange | Data on the VM | Model price | Backtest | Paper record | Verdict |
| --- | --- | --- | --- | --- | --- |
| **F1 × Polymarket** | 2025-26, 7,285 links, prices and trades | Real model | **Robust** (A: +$1,389 / +$1,432 at 16k, #85) | Taker 2025 +$450.46, 2026 +$353.01 | Only tradeable cell; nothing listed since 28 Aug |
| **F1 × Kalshi** | 2025-26, 3,793 links, trades, last-trade candles; no books | Real model | Maker K +$490 / +$659 (frozen); taker not usable | Maker 2025 +$193.39, 2026 −$118.84 | Needs bid/ask candles |
| **F1 × OG.com** | 20 season futures since 29 Sep | Real model (season) | None | None | Column on since #119 (`RACINGLINES_OG_VENUE=1`); books recorded every 5 min |
| **NASCAR × Kalshi** | 408 events 2016-26, 7,544 links with a race, tape | Simple baseline; next race priced (#9068) | **Not robust**: every setting loses 2025 | Pro −$278 / +$6,525; Basic −$357 / +$2,657 | Demo only |
| **NASCAR × Polymarket** | Backfilled on the VM with Kalshi's selection (`vm.sh demo extra`) | Same baseline | No own grid | **+$4.82 paper history, 2 positions** (26 Jul 2026) | Demo only |
| **NASCAR × OG.com** | 17 Cup Champion contracts since 29 Sep | Champion sim (#93), uncalibrated, offline | None (buy-all is a plumbing check) | None | Mechanical only |
| **MotoGP × Kalshi** | 202 events, 289 race-winner links, tape | Simple baseline, race win only; **no next race** (no calendar) | No held-out season (no 2025 markets) | 2026 Pro +$31.25, Basic +$7.70 | Demo only |
| **MotoGP × Polymarket** | No linked markets | — | — | — | Empty |
| **MotoGP × OG.com** | Not listed by OG.com | — | — | — | Empty |

How to read it: the paper record picks each market kind's best setting from the same seasons it then replays
(`--book best`, `docs/paper-trading.md`), so it shows what the demo would have done, not an edge. 2026 is 32 of NASCAR's 40
races and all 11 of MotoGP's. The one test that separates settings from seasons, the NASCAR taker grid, is below:
the same model loses 2025 at every setting.

**Realistic model status.** F1 has a real model and one robust strategy. NASCAR and MotoGP run a result-only
baseline (recent finishes, a team prior; no qualifying, practice, track type or sprints) that has not been compared
with the market or a naive baseline; the replay's race spread (2.0 places) is tighter than NASCAR's measured ~7.
Treat every NASCAR and MotoGP number as a working demo of the pipeline, not a trading signal.

**What is still missing.** A MotoGP calendar ingest (so MotoGP gets a next-race price); Polymarket MotoGP links;
runs of the champion replays (#95 F1 on Kalshi and OG.com, #96 NASCAR and MotoGP; code merged 30 Sep 22:41Z); forecasts refreshed
after each race (today a forecast run is stored once, by hand; the timer is a later step); Kalshi bid/ask candles
before any Kalshi taker result counts.

## 3. Getting it to production: the public repo, CI and code-only deploys

Once the backfills showed on the app, the question became how changes reach production without risking the data
behind them.

**The public repo.** The owner rewrote history on 1 Oct (~06:10Z) and made `lalligagger/racinglines-public` the live
repo. Raw data, archives, run outputs, reports and `tests/fixtures/` are not in it (`.gitignore` keeps it code-only);
the ten `/pitch` images and the fixture bundle live only on the VM's disk and the owner's Mac, and the fixtures are
offered to contributors on request. Doc links point at the public repo (PR 5). 62 old branches were deleted at 08:08Z;
since then one feature-track branch per night or sprint, head branch deleted at merge, the owner squash-merges.

**How a merge reaches production** (`main-merge-gate`, [VM deploy: The flow](vm-deploy.md#the-flow)):

1. `detect-docs-only` skips everything when a change set is only `docs/` and `*.md` files.
2. `predeploy-staging` smoke-checks `staging.racinglines.bet` (whatever staging serves, not the PR's code).
3. On a push to `main`, `deploy-production` runs `vm.sh deploy <sha>`: pause the live timers, untrack what the new
   commit doesn't track (backed up to `data/backups/files/`), checkout, pip, `alembic upgrade head`, `db seed`, build
   `/docs`, restart, resume the timers, print each timer's state.
4. A production smoke check of racinglines.bet.

New `vm.sh` subcommands: `repoint` (point the VM checkout at the public repo and fetch; no file touched), `backup
<purpose>` (a database dump on the VM), `docs` (rebuild `/docs`), `accounts [off]` (backup, accounts schema, sign-up
switch). A deploy that fails before the checkout moves resumes the paused timers; one that fails after leaves them
paused on purpose.

It took four failed CI deploys to get there. Each deployed nothing and left or put the timers back:

| PR | Commit | Why its deploy failed | Fix |
| --- | --- | --- | --- |
| PR 2 (maintenance popup) | `cd7bf32` | `fatal: Needed a single revision`: the VM still fetched the private repo | PR 3: `vm.sh repoint`; deploy refuses until repointed |
| PR 3 (code-only deploys) | `a449e18` | Refused until repointed; deployed by hand at 07:19Z | — |
| PR 4 (repoint as app user) | `59a66af` | `scp` Permission denied on a `/tmp` file left by another ssh user; a fresh runner's ssh-keygen output on stdout fooled the origin check | PR 4 reads only the last line; PR 6 pipes `untrack.sh` over ssh |
| PR 6 | `4469100` | First full green run (run 19, 08:14Z) | — |

**Code only, and where the data lives** (owner rule, 07:00Z; audit in [VM deploy: Code from GitHub, data on the
VM](vm-deploy.md#code-from-github-data-on-the-vm)). A deploy never restores, overwrites or deletes `data/`, the pitch
images or database rows; those change only by ssh and scripts (backup first) or the site's admin views. The audit found:

- **The VM's disk is the only copy** of the newest database dumps, `data/backups/` and `data/archive/markets/`. No
  script or timer pushes them off the VM. A nightly off-VM backup is STG-5, waiting on the owner.
- **Database dumps are no longer a full backup on their own.** The recorder's hourly archive pass moves cold market
  rows from Postgres to Parquet under `data/archive/markets/` (dumps went from 118 MB to 56 MB at 01:56Z on 1 Oct, row
  counts checked).
- **Cloud sessions read stale data.** Their bucket access reaches only the old bucket, last pushed on 28 Sep.
- Re-committing a path the VM keeps untracked (pitch images, `tests/fixtures/`) makes the deploy's checkout fail
  after the untrack step, and the timers stay paused.

**What CI still doesn't do** (full table and STG-1 to STG-11 in [todo: Staging and CI
deploys](todo.md#staging-and-ci-deploys)): about 50 tests, all goldens included, skip on a public checkout because
`tests/fixtures/` is absent (STG-7); the staging smoke doesn't run the PR's code (STG-1, STG-3); a merged migration
runs on the VM at once with no backup step (STG-8); there is no concurrency group (STG-6); nothing stops a code merge
during a live window (STG-9); the Claude GitHub App isn't installed on the public repo, so PR and CI events don't reach
Claude threads (STG-11); cloud sessions can't push `.github/workflows/*`, so workflow changes ship as patches. Tests in
CI (STG-2) arrived with PR 9.

## 4. Recorders and round 16

- The Kalshi and OG.com book recorder (`vm.sh record`, timer `racinglines-record-venues`, every 5 minutes) has run
  since 30 Sep 23:39Z (first pass backed up the database first); the owner confirmed rows landing at 04:04Z on 1 Oct.
  It has no end date; `vm.sh record off` stops it.
- Round 16 (Sepang): the book opens Fri 2 Oct 03:30Z and closes Sun 4 Oct 07:00Z. At 08:14Z on 1 Oct the Polymarket
  recorder, the signals timer, `racinglines-live-f1@2026-16.timer` and the record-venues timer were active. Because
  merging deploys, **no code merges in that window** unless the owner says so. Still owed by the owner: the tier call
  (Thu 18:00 PDT), the loss cap, hype picks and crowd pace.

## 5. Lessons learned

| # | What happened | Cost | Lesson (now a rule where noted) |
| --- | --- | --- | --- |
| 1 | The overnight run stopped at the NASCAR Kalshi tape pull: 13,599 links, **0 with a race**, because NASCAR results and linking had only ever run on the Mac | ~3.5 h and a manual fix | **A dry run checks per-sport readiness** (events, races, links with a race), not row counts. #98 added the preflight |
| 2 | #101 counted the Parquet archive inside the /markets request (~30 s); the deploy smoke check read `000` | A failed smoke, a second deploy | Anything that scans the archive runs in the background; **read the deploy smoke before calling a deploy done** (#103) |
| 3 | Overnight jobs under `systemd-run` printed nothing for long stretches: Python buffered stdout, and some steps had no progress line | "Is it stuck?" questions, relay steps for the owner | **Every long-running job prints flushed progress at least every 5 minutes** (owner rule, 2026-09-30 22:36Z) |
| 4 | The deploy from the Mac Remote Control session was blocked by its permission rules: ssh to the VM needs an exact-command allow rule, and only the progress tail had one | Deploy steps fell back to the owner pasting | Give the owner one command that does everything; add the exact allow rule before a planned remote step |
| 5 | About 30 PRs in 24 hours, several stacked; after a squash-merge of the base, the stacked ones conflicted, and a local squash left GitHub PRs open | Merge-order churn, stale drafts (#97) | **Group work into feature-track branches** (owner, 22:36Z); check PR state before giving merge commands |
| 6 | The overnight "Profile A" row was A's settings with the `early` taker, not A's `update` taker (inferred from the candidate id) | A false gap (+$2,607 vs +$1,389) | Label every row with its strategy family and candidate id; never compare across families |
| 7 | MotoGP's grid ranking crashed on a season with no markets (`KeyError 'net'`) | A re-run | Code for a new sport must handle an empty season; tests should include one (#102) |
| 8 | Report numbers were copied by hand from logs and PR bodies | Each number traced by an agent; the paper totals for Polymarket NASCAR are still unread | See recommendations below: reports should be built from saved run outputs |
| 9 | Merging became a deploy on 1 Oct; the first CI deploys of PRs 2, 3 and 4 all failed on the VM side (wrong origin, refusal, `/tmp` permission, ssh-keygen noise on stdout) | Three failed deploys; the round 16 timers paused once | Before telling the owner to merge, say what the merge deploys; read the deploy run, not just the PR check |
| 10 | Check and smoke results were read from an earlier commit or run | "Green" claims that didn't hold for the latest push | Read the check run on the PR's current head, and whether a run is still going after the last push |
| 11 | The workflow has no concurrency group | Two merges close together would run two deploys over each other | Merge one PR, wait for its Actions run, then the next (STG-6) |
| 12 | Two versions of the same command, and stub or duplicate messages, reached the owner | Re-pasted commands; a command already run was pasted again | One command that does everything, sent once; check what already ran before advising |
| 13 | `as_app "a && b"` ran only `a` as the app user | A repoint that half worked (PR 4) | Wrap chains in `bash -c` when switching users over ssh |
| 14 | Deploys didn't build mkdocs, so `/docs` said "Docs not built" | A broken docs link on the live site | The deploy builds `/docs`; `vm.sh docs` after a docs-only merge, which deploys nothing |
| 15 | Golden tests skip silently on the public checkout | `pytest -m "not live"` looks green with ~50 skips | Run goldens on the Mac for any pricing or model change (STG-7) |

## 6. Report consistency and reproducibility: recommendations

Today a report is a Markdown file an agent writes from logs, PR bodies and memory; nothing re-runs it. The 24-hour report's
figures were the first step: its `make_figures.py` (old private repo) rebuilds every chart from numbers typed in with their source,
without a database. The recommendations, in order of value (the owner asked for these as roadmap and todo items):

1. **Every run writes a machine-readable summary.** Replays, grids, demo-history and forecasts write a
   `summary.json` (inputs, settings, git commit, seasons, net P&L per season, counts) beside their Markdown output, and
   `data_changes` rows point at it. Reports read those files instead of copying numbers.
2. **A `racinglines report build <folder>` command.** Reads a `report.toml` (which run summaries, which queries, which
   figures), renders tables and charts with the same code every time, then the existing `markdown_html.render` to HTML
   and PDF. The prose stays human- or agent-written; every number and chart is generated.
3. **Screenshots by script.** A Playwright script with the fixed viewport (1024 px wide, device scale 1.5 for the 150%
   zoom) and a page list per report, run against staging or production with a demo login.
4. **One template for large-update reports:** scene-setter, top-line table, a section per workstream, what-shows and
   what-doesn't, opens with owners. The two existing templates in `CLAUDE.md` stay; this adds the third kind.
5. **A consistency check in CI:** `report build --check` fails if a report's numbers differ from the summaries it cites.

## 7. Open items

| Open | Who | Blocker |
| --- | --- | --- |
| Champion replays (#95, #96): VM steps 5 to 7 of `handoffs/2026-10-01-season-replays.md` | Owner | Backup first; not during the round 16 book |
| Off-VM copy of the VM's data (STG-5) | Owner decision | Yes or later, unanswered |
| Migration gate (STG-8), staging host (STG-1: same VM or its own, keyless auth or key, Cloudflare Access or password) | Owner decisions | — |
| Sign-up switched on (`vm.sh accounts`) and checked on the live site | Owner | Unverified from here |
| Fantasy tiers (everyone starts as pro) | Owner decision | — |
| MotoGP calendar ingest, so MotoGP gets a next-race price | Next thread | Needs a Mac probe of the calendar endpoint first |
| Polymarket MotoGP links | Next thread | Tag slug unverified; Mac probe first |
| Forecast refresh after each race (timer) | Next thread | VM sign-off |
| Kalshi bid/ask candles re-pull | Owner decision | Needed before any Kalshi taker result counts |
| MotoGP grid ranking re-run, OG.com buy-all output, NASCAR spike share | Owner or Copilot | Written on the VM, not yet read |
| Report screenshots | Owner or a Mac session | Retake at 1024 px, 150% zoom (`browser_smoke.py`) |
| Round 16 calls: tier, loss cap, hype picks, crowd pace | Owner | Book opens Fri 2 Oct 03:30Z |

## What this does and doesn't show

It shows what the repo history (old #85-#121, public PRs 2 to 9), `docs/todo.md`, `docs/vm-deploy.md` and the project's
notes record. No number from the 24-hour report was recomputed; they are as of the evening of 30 Sep. It doesn't
verify the VM after 08:14Z on 1 Oct: PR 7's and PR 9's deploy results, whether `vm.sh accounts` has run, and the
timer states come from notes or the owner's word, not from output read here. Every NASCAR and MotoGP P&L is in-sample
demo paper, not an edge.

---

*Appendix: the morning report of 30 Sep (as of 16:00Z), kept as the record of the overnight run.*

## The owner's 3 × 3 grid (morning)

F1 is the only full row, and only F1 on Polymarket has a held-out-robust backtest. Every other filled cell is data plus either a backtest that failed its held-out season, a mechanical check (buy-all), or an uncalibrated champion price.

| Sport | Polymarket | Kalshi | OG.com |
| --- | --- | --- | --- |
| **F1** | **Backtested, robust.** Profile A (taker) and C (maker), 2025-26 races; overnight 16k re-confirmed A. No F1 race listed since 28 Aug 2026 | **Backtested, not usable as a taker.** Maker K tuned (2026 +$490, 2025 +$659, frozen pending review). Taker replay reads last-trade prints, which spike (1.67% of points >15 pts off median) | **Priced, not backtested.** 20 season futures, model fair via the fair-price indicator (`RACINGLINES_OG_VENUE=1`, off on the VM). Buy-all ran overnight, output not yet read. #95 champion replay drafted |
| **NASCAR** | **Gap.** 1,101 links on the Mac, champion priced offline by #93; no race markets we can trade, no backtest | **Backtested, not robust.** 40 races with markets; 2026 +$4.2k to +5.5k, 2025 −$242 to −$390 | **Mechanical only.** 17 Cup Champion contracts; buy-all ran, output not yet read; champion priced offline by #93 (uncalibrated) |
| **MotoGP** | **Gap.** Champion market (25 outcomes) is quote-only; per-race winners seen 29 Sep but not synced or backtested | **Replayed, no verdict.** 289 race-winner links; tape pulled; 16 grid runs done; ranking re-run pending the #102 deploy | **Not listed** by OG.com |

Wider coverage outside the 3 × 3 (from `docs/coverage.md`, unchanged in this window): IndyCar has 1,374 closed Kalshi links but its results source's terms forbid automated use; road cycling, Le Mans and SailGP have tape-only schemas (#50) and no results source; downhill has no venue.

## What each exchange offers historically

Kalshi is the only venue with deep, uncapped history for the new sports; OG.com keeps about a month, so its history starts on 2026-09-29, when we began pulling. PR #101 fixed the board's Exchange data counts, which had read only the Postgres buffer (Polymarket showed 0 trades, Kalshi 37,416).

| Exchange | Trades | Price history | Order books | New-sport listings |
| --- | --- | --- | --- | --- |
| Polymarket | Taker trades only, newest ~100,000 per market | `/prices-history`, hourly by default | No history API; only what we recorded live | NASCAR race winners + champion, MotoGP champion and some Grands Prix |
| Kalshi | Every trade, no cap (older than ~2 months via `/historical/trades`) | Hourly candles: last trade, else bid/ask mid. An empty side is now no price, not 0.50 (#89, #90) | No history API; no Kalshi book recorder yet | NASCAR 13,599 links (race, top-N, h2h, pole, fastest lap, champion), MotoGP 322, IndyCar 1,374 |
| OG.com | About one month | 1-minute bid/ask/last, 31 days per call | One snapshot per `books` run | F1 20 futures, NASCAR 17 Cup Champion, SailGP 13; no MotoGP, IndyCar, cycling or Le Mans |

Counts on the cloud archive copy (mostly F1, from #101): Kalshi 1,065,605 trades and 520,969 hourly price points; Polymarket 447,274 trades and 3,983,682 price points. The VM's counts, which include the overnight NASCAR and MotoGP pulls, have not been read yet. NASCAR Kalshi hourly prices on the VM went from 152,257 before the dead-book cleanup to 295,553 during the overnight pull (`docs/data-changes.md`).

## What was built

About 30 PRs landed in the window, and three more are open drafts. Grouped by what they unlocked:

| Area | PRs | What it does | State |
| --- | --- | --- | --- |
| Ingest plumbing | #57, #58 | Syncs seed their own sport rows; `vm.sh deploy` runs `db seed`; exchange schemas state API caps and fail to load if exceeded; one exchange data contract for charts | Merged |
| NASCAR results and identity | #60, #62, #63, #64, #67, #69 | `cf.nascar.com` feed adapter (probed read-only from the Mac first), scheduled events, driver and race resolver, links carry driver, race, kind and h2h pairs for Kalshi, Polymarket and OG.com | Merged |
| MotoGP results and model | #75, #77, direct commits 72f16c0, 6e50e57, adac98d | Results API probe (MotoGP allowed, IndyCar terms forbid scraping), result-only race model (race-win log loss 0.0796), pricing and board parity | Merged |
| Taker replay for new sports | #82, #84 | `nascar replay` / `motogp replay`: taker P&L on Kalshi and Polymarket tapes, per-race tape probe and pull, NO TAPE flags, `--save` with undo. New sports' defaults switched on (owner, 03:07Z) | Merged |
| Price hygiene | #89, #90, #91 | Empty Kalshi book side is no price (was a 0.50 mid); dead-book quotes rejected; MotoGP UUID athlete ids kept; 27,024 bad Mac rows deleted and re-pulled, 157,049 on the VM | Merged |
| OG.com as a venue | #88 | OG.com is a replay venue; debug `buy-all` buys one YES and one NO of every listed market to prove each is found, priced and settled | Merged |
| F1 taker | #81, #85, #87 | Thin-market exception, Kalshi taker fee, re-sweep (A stays, blend TB offered to Pro), demo taker walk-forward story | Merged |
| Champion markets | #93; #95, #96 drafts | NASCAR Cup season sim through the 2026 Chase (read-only, uncalibrated); F1 champion replay on Kalshi and OG.com; NASCAR and MotoGP champion replays | #93 merged; #95, #96 wait on a Mac spot check |
| Overnight VM run | #86, #92, #94, #98, #99, #100, #102 | Runner, 3 × 3 plan, n2-standard-2 sizing, per-sport preflight that loads results and links, progress log, MotoGP ingest newest first, grid ranking with an empty season; report, decision log, data-changes entry | Merged |
| Exchange data counts | #101, #103 | Board counts span the Parquet archive plus buffer, n/a for zero, per-exchange source notes; archive counted in the background after #101 timed out the deploy smoke check | Merged; #103 not yet deployed |
| Sport paper portfolio | #97 draft, then #110 | NASCAR and MotoGP replay trades stored as the demo accounts' Kalshi paper positions (`RACINGLINES_SPORT_PAPER=1`, labelled in-sample); buy-all never shown | Shipped in #110 and run on the VM that evening; #97 draft left open |

**Copilot's intermediate reports.** The NASCAR parity write-up (NASCAR wrap-up (`reports/2026-09-29-nascar-wrap-up/report.md`, old private repo), #79) and the new-sport template (MotoGP first model (`reports/2026-09-29-motogp-first-model/report.md`, old private repo)) are Copilot's part, confirmed by the owner. Their figures agree with this report's where they overlap: NASCAR 14,700 links on the Mac (Kalshi 13,599, Polymarket 1,101), 7,044 fully identified outcomes, 33 NASCAR tests passing; MotoGP race-win log loss 0.0796; IndyCar blocked on its terms. Their 129 NASCAR events are the Mac database; the VM's 408 (2016-2026) came from the overnight fix, so the two counts describe different databases, not a conflict. Copilot's reports stop before any backtest, so every P&L figure here comes from the overnight run and PR #85.

## The overnight VM run: what failed and why

The run took four starts, and every stop was a data-readiness gap, not a model bug. The root cause of the first and biggest one: the dry run checked row counts, not whether each sport had results and identified links on the VM, and NASCAR's ingest and linking had only ever been run on the Mac.

| Time (UTC, 30 Sep) | Event | Cause or result | Fix |
| --- | --- | --- | --- |
| ~07:00 | Dry run passed; F1 golden gate +1,242.88 (target +1,243 ±400) | VM on n2-standard-2 (e2-standard-4 unavailable) | #94 |
| to 09:25 | `rl-overnight` (all): F1 broad 104/106, top 10 at 16k 24/24 | Done | — |
| **09:25** | **Failed at NASCAR Kalshi tape pull** | 13,599 NASCAR links, 0 with a race: no NASCAR results on the VM | Owner's manual fetch, ingest, sync, link (backup first); #98 preflight |
| 12:59 | `rl-overnight-sports` starts (backup 115 MB) | NASCAR 7,544 links with a race; MotoGP 202 events, 0 links with a race | — |
| 12:59-14:45 | NASCAR links, tape, replay (106 min), saves (1 min), Kalshi grid 16/16 (3 min) | Done | — |
| **15:02** | **Failed at MotoGP results and link load** (11 min in) | The ingest stopped the run; traceback in the VM log, not read | #100: newest seasons first, a failed load no longer stops the run |
| 15:23 | `rl-overnight-rest`: demo taker story (backup 118 MB), gate passed, record rebuilt; MotoGP tape and saves | Done | — |
| **after 15:23** | **MotoGP grid ranking crashed**, `KeyError 'net'` | 2025 has no MotoGP race with Kalshi markets | #102 |
| to ~16:00 | `rl-finish`: MotoGP rank, OG.com buy-all (F1, NASCAR), NASCAR champion forecast; FINISH-DONE | `replay-grid/motogp/grid.md` not seen yet | Re-run ranking after deploy |
| ~16:05 | Deploy of #99, #101, #102: smoke **FAIL 000 on /markets** as maker; site up | #101 scanned the Parquet archive inside the request (~30 s) | #103, merged, not yet deployed |

Nothing touched trading flags, migrations or `vm.sh public on`. Backups: `racinglines-before-overnight-replay-20260930T092216Z` (97 MB), `…T125934Z` (115 MB), `racinglines-before-demo-taker-story-20260930T152320Z` (118 MB), `racinglines-before-nascar-ingest-link-*`, all in `data/backups/db/` on the VM.

## Backtests: results and labels

One backtest passed its held-out season (F1 on Polymarket, where the incumbent held); one failed it (NASCAR on Kalshi); MotoGP has no ranking yet. All P&L is simulated at the default stake ($250 per unit of edge, $50 a market) unless stated.

### F1 × Polymarket: 106-job sweep, top 10 at 16k (VM)

Target 2026, held out 2025, noise floor ±352. A setting replaces A only if it beats A by more than the floor in both seasons; none did.

| Setting (on A's settings) | 2026 | vs A | 2025 | vs A |
| --- | --- | --- | --- | --- |
| A's settings (row labelled "Profile A") | +2,607 | — | +503 | — |
| `reset_weight=0.5` | +3,007 | **+400** | +525 | +22 |
| gbm, half-life 90, min edge 0.08 | +3,012 | **+405** | +16 | −487 |
| half-life 90, min edge 0.08 | +2,983 | +376 | +284 | −219 |
| 24 h volume floor $25 | +2,840 | +233 | +725 | +222 |

Every top row leans on the British Grand Prix: without it each 2026 total drops by 1,000 to 1,500. Decision-log entry 2026-09-30: profile A stays, no default changes.

### NASCAR × Kalshi: taker settings grid (VM)

Ranked by the worse season. 2026 has 32 races with Kalshi markets, 2025 only 8.

| Min edge | 24 h floor | Sims | 2026 (races up) | 2025 (races up) |
| --- | --- | --- | --- | --- |
| 0.15 | $50 | 16,000 | +4,226 (19/32) | −242 (2/8) |
| **0.10** | **$50** | **16,000** | **+5,419 (21/32)** | **−249 (2/8)** |
| 0.10 | $50 | 4,000 | +5,479 (21/32) | −278 (2/8) |
| 0.08 | $50 | 4,000 | +5,203 (21/32) | −317 (1/8) |
| 0.05 (default) | $50 | 4,000 | +5,091 (21/32) | −360 (1/8) |
| 0.10 | $200 | 4,000 | +2,721 (17/32) | −381 (1/8) |

Label: **2026-specific, not robust**. Prices are Kalshi last trades, which the F1 check found spiky, and the NASCAR spike-share line was not in the pasted output. Nothing is tuned; defaults stay (min edge 0.05, $50 floor).

### MotoGP × Kalshi (VM)

Tape pulled, replay saves stored, 16 of 16 grid runs finished. No ranking: it crashed on 2025, which has no MotoGP races with Kalshi markets, so there is **no held-out season at all**. A Mac spot check before the run (2026, $0 volume floor, so not tradeable) made +413.62 on 93 trades.

### Demo taker paper record, F1 (VM)

Walk-forward: defaults for 2025 rounds 1-8, then the maker's rule picks A's core settings (TW2). The gate passed, and `f1 demo-history --reset --user taker` rebuilt the record: **2025 +450.46** over 23 weekends, **2026 +353.01** over 15. Last five 2026 weekends: Hungary −5.44, Netherlands −29.54, Italy +22.21, Spain −5.57, Azerbaijan −93.55. Label: paper, and the rule saw 2025 before choosing, so only 2026 is out of sample.

### What is not a backtest

- **Buy-all** (OG.com F1 and NASCAR): proves every market is found, priced and settled. A pair loses exactly its fees by design. Per the owner, it never appears in reporting or the web app, and its output has not been read.
- **NASCAR champion forecast** (#93): Larson 94.6% on the first Mac run vs 40-55% on the market, before rev 2's fixes; labelled NOT CALIBRATED.
- **Champion replays** (#95, #96): built, not run.

## The profile A gap: likely a strategy mix-up, not a data problem

The overnight report's "Profile A" row (+2,607 in 2026, +503 in 2025) is most likely A's settings run with the stage-aware `early` taker, not A's `update` taker, so it should not be compared with PR #85's +1,389 and +1,432. This is inferred from the files, not re-run.

The evidence:

- The row's candidate id is `early-e726f828b96a`. Search candidates are named by strategy (`update-`, `hold-`, `last-`, `early-`), and every sweep job runs all four.
- PR #85 measured the same thing at 16k as T8, "early, A's settings": **+2,707 and +546**. The VM's row is −100 and −43 from that, inside the ±700 noise floor #85 set for `early`.
- A's `update` taker reproduced on the VM: the dry run's golden gate read +1,242.88 against the published +1,243 at 4k.

| Run | Strategy | 2026 | 2025 |
| --- | --- | --- | --- |
| PR #85, T1 = profile A, 16k | update | +1,389 | +1,432 |
| PR #85, T8, 16k | early | +2,707 | +546 |
| Overnight VM, "Profile A" row, 16k | early (inferred from the id) | +2,607 | +503 |
| Overnight VM dry run, 4k | update | +1,242.88 | not run |

To close it: read the `update-` rows for A's settings in `data/runs/search/overnight-vm/report.md` on the VM. If they sit near +1,389 and +1,432, the overnight report's F1 table and decision-log entry should be relabelled as the `early` family. The verdict (A stays) does not change either way.

Still unexplained: the demo taker's paper record (+450.46 and +353.01) is well below #85's walk-forward story (−129 + 870 = +741 in 2025, +1,099 in 2026). The paper record goes through the signal engine's paper sizing and settlement, not the search replay, so the two may not be comparable. That has not been checked.

## What this does and doesn't show (morning)

**Shows:** the new-sport path works end to end on production (probe, results, identity, links, tape, replay, saves) for NASCAR and MotoGP; F1's taker choice survived a 106-job sweep; the demo taker has a full paper record in the app; the board's data counts now reflect the exchanges' real stored history.

**Doesn't show:**

- A tradeable edge anywhere outside F1 on Polymarket. NASCAR's profit rests on 2026 alone (2025's 8 races lose in every setting), on last-trade prices a taker may not have been able to pay.
- Anything about Kalshi takers at real prices: that needs Kalshi's bid/ask candles, which today's sync does not store (re-pull from a machine with Kalshi access).
- MotoGP's grid verdict, OG.com buy-all output, and the NASCAR spike share: all were written on the VM and not yet read.
- The VM's exchange data counts after the overnight pulls (#101 numbers are from the cloud copy).

**Gaps, and why they stay gaps:**

| Sport or cell | Blocker |
| --- | --- |
| MotoGP × OG.com | OG.com lists no MotoGP (probed 29 Sep) |
| NASCAR, MotoGP × Polymarket | Polymarket tag slugs unverified (#51 not run live); MotoGP champion needs sprint points, schedule, standings and classifiers (`docs/championship-markets.md`), which need a Mac probe first |
| IndyCar | Results source's terms forbid automated scraping (#75); season over until March 2027 |
| Road cycling, SailGP, Le Mans | Tape-only schemas built (#50), not run on the VM; no results source or model |
| Downhill | No venue lists it; private book only |

## Open owner decisions and next steps (morning; section 7 has the current list)

The first three steps are the owner's and unblock everything else; none needs a trading flag or a migration.

1. Redeploy main so #103 clears the /markets smoke failure, then check `vm.sh status`.
2. Re-run the MotoGP ranking and read the three unread outputs (MotoGP `grid.md`, OG.com buy-all CSVs, NASCAR spike line), plus the `update-` rows that settle the profile A gap.
3. Look at the taker's record in the app (Signals page, nav P&L).
4. Mac spot check, then merge #95 and #96 in that order (handoff `handoffs/2026-10-01-season-replays.md` in the project files), before round 16's book opens Thu 1 Oct 20:30 PDT.
5. #97 paper portfolio for NASCAR and MotoGP: Mac spot check and backup first (handoff `handoffs/2026-09-30-sport-paper-portfolio.md`).

Decisions waiting on the owner:

- [ ] Turn on `RACINGLINES_OG_VENUE=1` on the VM so the OG.com column shows in the app.
- [ ] Replay race-spread setting (2.0 is tighter than NASCAR's measured ~7 places).
- [ ] Kalshi bid/ask re-pull, needed before any Kalshi taker result counts.
- [ ] Polymarket schema migration; freeze Kalshi maker K.
- [ ] Recording timer and price-column migration on the VM (each needs a backup and sign-off).
- [ ] MotoGP champion classifiers (`KXMOTOGP` to `champion`): changes stored links, needs a backup and `link --apply`.
- [ ] NASCAR 2027 timing (recommended: decide in November, after the 8 Nov finale is recorded).
- [ ] Close #58 on GitHub; empty the Mac Trash of the old MotoGP Parquet folder.
