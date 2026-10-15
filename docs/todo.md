# Roadmap

The one place for what's next, across every sport and track, in priority order. Rebuilt on 2026-09-28 around the
[strategy to the end of 2026](strategy-2026.md) and re-ranked on **2026-10-14** around the three goals the owner set
(G1 to G3 below). Tick items off where they are listed. Finished items move to [Done](#done) at the bottom. Items
tagged **U1**…**U13** are the strategy session's app updates, **C-numbers** are the Core backlog's (the project
library, `library/core/2026-10-06-core-backlog.md`), **STG-n** the staging and CI items, and (F1-n) tags belong to
the [F1 roadmap](f1-roadmap.md).

| Plan | What it's for |
|---|---|
| **This page** | The priorities, the race-weekend calendar, owner decisions and every open item |
| [Sports and exchanges](coverage.md) | The sport × venue grid with production's counts (links, tapes, models, backtests, paper), the gaps ranked with effort |
| [Alpha layout](alpha-layout.md) | What the app shows today: Markets, Trade, History, Lab; styles, sizing, the leaderboard |
| [Strategy 2026](strategy-2026.md) | The reasoning of 28 Sep: where the demo record stood, how long each strategy takes to prove, event tiers |
| [Paper trading: validation plan](paper-trading.md#validation-plan) | The pre-registered rules every live weekend is judged by |
| [F1 roadmap](f1-roadmap.md) | The F1 phases (F1-0 … F1-9), their ground rules and decision log |
| [Engine roadmap](engine-roadmap.md) | Standard model inputs and outputs for every sport and exchange (E0 … E9), building on [Backtest core](backtest-core.md) |
| [Parity rebuild](parity-rebuild.md) | Every valid sport × exchange × kind brought to the F1-on-Polymarket bar; the coverage counter (C0, built) |
| [Market tape](market-tape.md) | What the recorders store, every 5 minutes, every day, and how to backfill a gap |

## Priorities

<!-- readme: todo-summary -->

**Where things stand (14 Oct 2026).** [racinglines.bet](https://racinglines.bet) runs the **fantasy league alpha**:
every signed-in account gets F$1,000 of fantasy money and four tabs, Markets, Trade, History and Lab
([Alpha layout](alpha-layout.md)). Hand trading is F1 only, on the recorded Polymarket and Kalshi books; Markets shows
F1, NASCAR and MotoGP. Polymarket lists F1 race markets again (rounds 13 to 20 are linked); no real order is placed
(the trading flags are unset, [Sports and exchanges](coverage.md)). The three recorders poll Polymarket, Kalshi and
OG.com every 5 minutes, every day. From the command line, `--remote`, `racinglines remote` and `racinglines data
pull SPORT` reach the hosted server, in testing, with a warning that the review of venue and data terms is still
pending ([MCP server](mcp.md#more-commands-on-the-hosted-server-remote-racinglines-remote-data-pull)).

The goals (owner): **G1, October to early November, prove the edge**, closing-line value above +2% over 100 live
bets; **G2, November to December**, real fills, venue capacity, more users; **G3, January to March 2027**, billing.
The real-money gate stays at six or more live weekends. What is in flight now, in order: the staging-to-production
promotion (PR #180: MotoGP for every signed-in user, `data pull`, `remote`, race-data triggers); CLV on every fill;
the calibration check of every sport's model (C48); the Probalytics tape comparison (PR #181); the one engine for the
first package release (C56).

<!-- /readme -->

### P0 · now (14 Oct to the United States GP, 25 Oct)

Each item names its PR or backlog number; "promotion pending" means it is on `staging` and reaches production with
the next staging → main promotion (a draft until the owner says "promote"; the owner merges).

- [x] **Promote staging to production (#180), 2026-10-14.** Merged 06:50Z, prod deploy green 06:55Z (806278c).
      Checked 17:00Z: live auto on, no per-event F1 timer, nothing paused; `record fastf1` disabled (no race this
      week). The internal book is in `data/internal-docs/` on both sites (`vm.sh internal-docs`, 410 files).
- [ ] **Next promotion: staging → main (draft until the owner says "promote").** Carries #188/#189:
      `record_fastf1.sh` executable (`vm.sh record fastf1 status` and the recorder's unit failed with "command not
      found" without it) and two data-change entries. Touches `scripts/vm/`, so it deploys production.
- [ ] **Stage cutoffs from a session's actual end, not its scheduled end (owner, 2026-10-14: P0, review after the
      day's fill-fidelity runs).** A stage's cutoff is the scheduled start + `[sessions.schedule]` minutes +
      `[stages] lag_minutes` 30 (`racinglines/core/stages.py` `build`), and the model's data gate uses the same scheduled
      end (`models/inputs/laps.py` `session_end`). A session that overran by more than 30 minutes (red flags, a delayed
      start) is then priced with results the market had not seen yet: a future leak in every backtest and sweep, worst
      at "after Quali". Same on both tapes, so the ours vs Probalytics A/B holds, but absolute P&L can be too high. First
      step: list every 2026 session whose actual end (FastF1 session status, VM) is after its cutoff; then cut from the
      actual end where it is known. The fill paths themselves read as of t (tested in `tests/test_book_fill.py`).
- [ ] **CLV on every live and replayed fill (C4).** `racinglines backtest clv` covers stored paper bets; the sweep
      stats, `f1 reconcile`, `f1 scorecard` and the weekend report still read P&L only. G1 is judged on CLV: the plain
      mean per decided bet against the fill price (owner, 2026-10-07). [Paper trading](#paper-trading).
- [ ] **Calibration by probability bucket, every sport (C48; owner, 2026-10-08: the next development once staging
      is confirmed).** Favourites, mid-field and long shots, walk-forward against results and against closing prices
      where recorded, for F1, NASCAR, MotoGP, downhill and road cycling. Evidence: Indonesia MotoGP, the model's top
      three summed to 42.5% against Kalshi mids of 83.5%. Until it is done NASCAR and MotoGP prices are labelled
      **unvalidated** and no pick rests on them alone. [Models](#models-the-one-engine).
      **F1 (2026-10-14):** the sweep setting `calib_power` (`walk_forward`: fitted on earlier races only), off by
      default, better log loss and P&L in 2025 and 2026 sweeps ([F1 calibration](f1-calibration.md)). Open: make it
      the default (owner), the 10–20% bin still under-priced, the other sports.
- [ ] **Probalytics tape: pull, compare, golden (#181, into staging).** Resumable F1 pull by exact key (owner,
      2026-10-14: F1 complete, unlinked F1 markets included as data only, then NASCAR; any other sport only on the
      owner's explicit go); `RACINGLINES_TAPE_SOURCE=probalytics` as a backtest venue; pass marks mid within 1¢ on 95%
      of snapshots, weekend P&L within 10% or $5, trades within 5%. The golden comparison runs on
      `racinglines_staging_demo`. The internal recorder stays primary (owner, 2026-10-12).
- [x] **Staging as a live mirror of production (#154), on since 2026-10-14 17:54Z** (scope `all`; 42 tables ready,
      0 bytes behind at 18:31Z; [data changes](data-changes.md)). Open: the production backup's exact file name from
      `vm.sh backup staging-mirror` is not yet in the data-change entry.
- [ ] **Staging mirror upkeep (#154; on since 2026-10-14 17:54Z, 42 tables, 0 bytes behind).** No more `staging
      reset` while it is on. After any production migration, run `vm.sh mirror status`; a table production adds joins
      only after `vm.sh mirror on` runs again (it refreshes the publication). Owner OK still needed to delete the
      pre-mirror leftovers on the VM: `racinglines_staging-before-mirror-*.sql.gz` under staging's `data/backups/db/`
      and `data/archive.pre-mirror` if it exists.
- [ ] **Which database staging serves.** Still the season demo (`racinglines_staging_demo`), which the Probalytics
      comparison (15 Oct) uses; the mirror fills `racinglines_staging`. `vm.sh staging db main` to show the mirrored
      copy, `staging db demo` to go back (owner's call).
- [ ] **Road cycling on production.** The Kalshi road cycling links (53 events, 9,421 links, 14 Oct) are only in
      `racinglines_staging_demo`. Next: `vm.sh backup road-cycling-kalshi`, then `racinglines markets --exchange kalshi
      --sport road_cycling sync --closed` on production; the mirror then carries them to `racinglines_staging`. Fair
      prices still need the PCS results ingested and a forecast ([Road cycling](road-cycling.md)); admin only.
- [ ] **`vm.sh internal-docs` has no staging-only mode.** It always copies to production and staging; a staging-only
      copy was done by hand on 14 Oct. Low priority.
- [ ] **United States GP weekend (23–25 Oct), the first live weekend of the alpha with Polymarket race markets
      (266 links stored) and Kalshi's (expected 2 to 4 days out).** A, C and K paper-trade; the fantasy accounts trade
      by hand or follow a style; no code merges in the book window; Monday: `f1 reconcile`, `f1 scorecard`, and the
      first DITL report for an F1 weekend.
- [ ] **Sign-up terms acceptance** (`TERMS_VERSION`, planned in [Fantasy accounts](fantasy-accounts.md), not in
      code). The data-terms review is done (owner, 2026-10-14: venue prices to signed-in users, MotoGP in the alpha and
      `data pull` all allowed; the #aintcare warning stays); the sign-up page still records no acceptance.

### P1 · to the sizing review (~12 Nov)

- [ ] **The one engine for the first package release (C56).** Every modelled sport already prices with
      `GlobalModel`; what remains is folding the laps core's qualifying, grid and practice knowledge into the results
      core (F1 race-win Brier 0.1134 vs 0.1476 in the 2 Oct validation) and retiring `position_sim` and `TimedRuns`
      as classes. Owner chose "compare first" (2026-10-11); open: the "works the same" tolerance and the timing
      against G1 and the Las Vegas GP. Scope: the library's `core/2026-10-11-retire-f1-model-scope.md`.
- [ ] **Recorder follow-ups:** read `backfill_tape.sh` results into the data-change log after each gap; alert when a
      recorder misses a pass (the 1 to 2 Oct Kalshi outages were found a week later by the Probalytics comparison).
- [ ] **NASCAR before the Chase finale (8 Nov):** the pre-race field from NASCAR's entry list (C46, Mac probe first),
      start lists in the replay (C5), the replay's race spread (owner decision), and a replay on Polymarket's own
      NASCAR tape, recorded since 7 Oct.
- [ ] **MotoGP after the calendar lands:** sprint classifications (Mac probe first), champion classifiers and a
      season sim ([Championship markets](championship-markets.md#what-pricing-motogps-champion-would-take)).
- [ ] **STG items still open** ([Staging and CI deploys](#staging-and-ci-deploys)): STG-5 off-VM copy of the VM's
      data (the disk is still the only copy), STG-7 fixtures for CI, STG-8 migration gate, STG-6, STG-9, STG-10,
      STG-11. STG-2 (tests in CI) is partly done: CI runs pytest on PRs (PR #180 reports it green) but
      `deploy-production` still does not need it (C17).
- [ ] **Per-user bet books in the app (C55)** and the F1 race-week demos (C54), after the alpha's first weekends.
- [ ] **Sizing review (~12 Nov)** after 4–6 live weekends on real markets ([Paper trading](#paper-trading)).
- [ ] **Web: race URLs by sport** (owner, 2026-10-14): race pages under their sport (`/f1/races/135` style) instead
      of `/races/{id}`, with the old URLs redirecting (the `legacy.py` MOVED pattern) and template links updated.
      Not started. The race page 500 behind the ask (an all-null Parquet column) is fixed in #184.
- [ ] **Web: docs icon in the top bar** (owner question, 2026-10-14, unanswered): the book icon beside GitHub links to
      `/docs/` today (#184). Open: switch it to the Jupyter Book logo and link the owner's Jupyter Book once it is
      hosted (it is only served locally so far).

### P2 · to the Las Vegas GP (21 Nov) and year end

- [ ] **Las Vegas GP (21 Nov):** the milestone the owner set for real stakes ($2k to $10k, CLV-gated); only if the
      [validation rules](paper-trading.md#validation-plan) and G1 are met, and never without the owner's explicit
      sign-off on the trading flags in the same turn.
- [ ] Qatar (29 Nov) and Abu Dhabi (6 Dec) may be cancelled: settle by each venue's rules (U8; the owner's two
      assumptions still to confirm).
- [ ] **Road cycling:** the stage-race GC model (draft #177, held by the owner), its calibrated settings' decision-log
      rows (road noise 1.25, ITT noise 1.15, `road_gap_scale` 0.1, `short_tt_noise_scale` 2.0), a results source
      whose terms allow it, then a first VM data step (backup first). Admin-only on the board until then.
- [ ] **PyPI release** (preview written 2026-10-11; no PR until the owner's go): ships the single engine (C56),
      Rich output by default, the kart demo offline, then our MCP by sign-in, then self-hosted.
- [ ] 2026 season report (December); walk-forward re-selection of the profiles for 2027; **U10** pre-season testing
      ingest; **U12** Google Cloud; **U11** downhill off-season ([Points validation](#points-validation), [Data](#data),
      [Model](#model)); decide whether NASCAR and road cycling are 2027 sports.

### Record: the sprint to the soft launch (28 Sep – 8 Oct 2026)

Kept as the record of that sprint; everything ticked below is in [Done](#done) with its PR.

- [x] **Finish CI and the staging environment:** STG-1 (staging host), STG-3 (staging deploys), STG-4 (owner checks
      staging, then promotes) built; the rest is in P1 above.
- [x] **Sign-up** built (#146, the alpha fantasy launch on production 2026-10-12, with the fantasy reset).
- [x] **Recorders on the VM:** Kalshi and OG.com books every 5 minutes (U2, 30 Sep; every day since 2026-10-07),
      trades every 15 minutes, Polymarket NASCAR and MotoGP books (U9, #91), the forecast-refresh timer, the
      schedule-sync timer (#169).
- [x] **Round 16 live paper** (Sepang, 2–4 Oct) and **round 17** (Singapore, 9–11 Oct) ran on Polymarket's and
      Kalshi's real markets; the Singapore /term parts are recorded (#157).
- [x] **Coverage gaps in the 3 × 3:** Polymarket MotoGP links (209 on production); MotoGP calendar ingest built
      (#134, promotion pending); the OG.com column on the VM.
- [ ] **Champion replays after deploy** (#95, #96): merged 30 Sep, no run recorded ([Data changes](data-changes.md)).
- [x] **Progress lines** on every long job (#99, #114).
- [ ] **Report reproducibility** (REP-1 to REP-7): `SOURCES.md` by hand on every report since; the rest open
      ([Reports](#reports-consistency-and-reproducibility)).
- [x] **Fantasy soft launch:** shipped as the alpha layout (#160, #161) on 2026-10-12, F$ only, F1 hand trading.

**Where things stood** on 30 Sep, 29 Sep and 28 Sep is in [Strategy 2026](strategy-2026.md#where-things-stand) and the
[48-hour report](report-48h.md).

## Race weekends to 31 December

One row per event, in date order, with what production already holds for it (2026-10-14). Every F1 weekend also
runs the championship sleeve after the race, and the [weekend routine](#weekend-routine).

- [ ] **18 Oct · NASCAR Phoenix (Freeway Insurance 500).** Kalshi 200 links, Polymarket 43. Results core price
      (unvalidated); the timers record and fetch results.
- [ ] **23–25 Oct · F1 R18, United States GP.** T1 on Polymarket (266 links) and Kalshi when it lists. A, C and K
      paper; the alpha's hand traders and styles. **25 Oct · NASCAR Talladega.**
- [ ] **30 Oct – 1 Nov · F1 R19, Mexico City.** T1 (Polymarket 266 links). **NASCAR Martinsville.**
- [ ] **6–8 Nov · F1 R20, São Paulo.** T1 (Polymarket 266 links). **NASCAR finale, Homestead (8 Nov).** MotoGP's
      November rounds are recorded as T2 once the calendar is on production.
- [ ] **~12 Nov · Sizing review** ([Paper trading](#paper-trading)).
- [ ] **20–22 Nov · F1 R21, Las Vegas (Saturday race).** T1; check the night-time stage cut-offs; the CLV-gated
      milestone.
- [ ] **27–29 Nov · F1 R22, Qatar.** T1 once U8 is confirmed; may be cancelled.
- [ ] **4–6 Dec · F1 R23, Abu Dhabi.** T1 (1 Kalshi link stored already); championships settle.

**If Polymarket stops listing again:** Kalshi carries the record. **If neither venue lists an F1 race:** that weekend
is T3 (the private book, admin-only) and proves the pricing, not an edge. There are no downhill events left in 2026.

### Weekend routine

For every F1 weekend, T1 or T3:

- [ ] Wed: check Kalshi and Polymarket for the race's markets; confirm they link to the event (not `unmodeled`);
      `vm.sh record status` and `vm.sh pm-sync status` show no WARN.
- [ ] Thu 18:00 PDT (or the equivalent before FP1): pick the tier and log it in the decision log.
- [ ] Race weekend: the signal engine (T1) or the live engine (T3) runs unattended; no code merges in the book window
      except logged fixes (staging deploys are allowed).
- [ ] After the race: the signals pass settles the paper positions and stops (C59, promotion pending); run the
      championship sleeve.
- [ ] Monday: the reconciliation (live vs replay, T1) and the pricing scorecard (T1 and T3); the DITL report; flag a
      weekend outside the [validation rules](paper-trading.md#validation-plan) and explain it before the next.

## Owner decisions

Open decisions first, then the ones on record (so a thread never re-asks one).

| Decision | When | Recommendation / status |
|---|---|---|
| Merge the promotion (#180) ⚠️ VM scripts and units | Now | Yes; then the post-deploy checks in P0 |
| C56: the "works the same" tolerance for the one engine, and whether the F1 switch waits for the Las Vegas GP | Before the first package release | Validate now, switch after Vegas (proposal, 2026-10-11) |
| Probalytics download beyond F1 and NASCAR | Per sport | Only on the owner's explicit go for that sport (2026-10-14) |
| Sizing rule | ~12 Nov | After 4–6 live weekends on real markets |
| Real stakes at the Las Vegas GP (21 Nov) | After G1 | Only if CLV > +2% over 100 live bets and the validation rules hold; the flags need the owner's word in the same turn |
| U8 rules for a cancelled race: Polymarket 50/50 on head-to-heads, Kalshi NO versus void | Before Qatar (29 Nov) | Confirm against each venue's rules text |
| Replay race spread for NASCAR (2.0 places vs a measured ~7) | Before any NASCAR result is read as edge | Owner's call, with a decision-log entry |
| Road cycling: hold or merge the GC model (#177); which results source | Any time | Held by the owner (2026-10-13); decision-log rows first |
| Add NASCAR (and road cycling) for 2027 | December | Only if the tapes, calibration and data terms hold up |
| Promote `gridq+pretrain` as the F1 default; keep `reset` for 2027 | December | Decide on the walk-forward; live prices already use `gridq+pretrain+reset` through the profiles |
| `--unraced-format last` as the downhill default | Any time | See [Model](#model) |
| STG-5 off-VM data copy (VM service account write access to the bucket), STG-7 fixtures in git or bucket, STG-8 migration gate | High | Yes; STG-5 first: today the VM's disk is the only copy |
| OG.com: confirm the $0.02 fee; per-GP contract rules | Before any OG.com result counts | From OG.com's fee schedule and the two recorded race weekends |
| History purge for data off GitHub (force-push) | Last stage | Needs the owner's spoken OK in the same turn |
| Open-Meteo's free API is non-commercial only ([Weather forecasts](weather.md)) | Before billing (G3, 2027) | Stay on the free tier while there is no revenue |
| Keep or retire the /term browser replay, now that the quickstart and demo pages show captured commands and outputs (`scripts/docs/capture_examples.py`) | Any time | Keep for now; retire once the docs pages cover its three parts (docs review, 2026-10-14) |
| The docs' mailbox addresses ([Email setup](email-setup.md)) and the cloud service-account name ([Data](data.md)) are also in the public `/llms-full.txt` | Any time | Already public in the repo; owner to confirm they may stay, or the llms hook redacts them |
| Odds presentation names in the sportsbook schema ([Sportsbook schema](sportsbook/index.md)) | Any time | Owner checks the names; a rename is one line in `racinglines/books/schema.py` plus the docs table |

**On record (don't re-ask):** no sport-specific models, only schemas that declare model inputs (2026-10-11, C56);
no freezing of strategy profiles, every change logged with its date (2026-10-05); live books never freeze
(2026-10-04); the real-money gate stays 6+ live weekends (2026-10-05); market prices polled every 5 minutes every day
(2026-10-07); the internal recorder stays primary, Probalytics is a reference tape (2026-10-12); venue prices, MotoGP
and `data pull` may reach signed-in users, the #aintcare warning stays (2026-10-14); MotoGP visible to the alpha
(2026-10-14, reversing the 11 Oct hide); loss cap and tier for round 16 (decided in the
[F1 live test decision log](f1-live-roadmap.md#11-decision-log)); Kalshi bid/ask candles re-pull automated on the VM
(2026-10-05); new VM timers one at a time, each with a backup (2026-09-30); the OG.com column on the VM (read-only,
2026-10-01); Fable only when the owner asks for a project-notes update (2026-09-30); close draft #97, superseded by
#110 (2026-09-30).

## Exchanges

Phase [F1-9](f1-roadmap.md#f1-9-more-exchanges-kalshi-others), pulled forward: Kalshi is the likeliest
venue with live F1 race markets this year.

- [x] **U2 · P0 · Kalshi recorder on the VM.** Done: `racinglines-record-venues.timer` (`scripts/vm/record_venues.sh`)
      snapshots every open Kalshi and OG.com market every 5 minutes, every day since 2026-10-07 (books since
      2026-09-30: 923,282 Kalshi snapshots in production's Postgres on 2026-10-14), syncs hourly, stores the last two
      hours of trades every 15 minutes, and reads OG.com's settlements hourly ([Market tape](market-tape.md)).
      Original plan: `markets --exchange kalshi` sync every 30 min on race weekends, plus trades, books and history.
- [x] **U1 · P0 · Kalshi in the signal engine** (PR #34, merged 2026-09-29) (F1-9's "done when"). `pipelines/signals.py`,
      `taker_weekend` and `maker_replay` read `exchange='kalshi'` markets for a profile whose new `venue`
      setting says so (default `polymarket`, optional, left out of `settings_key` while unset). Signals
      carry `detail.venue='kalshi'` and positions `venue='kalshi'`. Group by market ticker (`token_id`),
      never by `condition_id`; apply `KALSHI_MAKER_FEE`; the liquidity filter is per market. Polymarket
      profiles unchanged. The sweep reads Kalshi the same way.
      *Done when:* a replay of 2026 round 15 through the engine on Kalshi matches `f1 demo-history
      --venue kalshi` for C to the cent, and A's Kalshi taker replay matches the sweep's trades
      (`scripts/signals_parity.py --venue kalshi`). No order is sent; `KALSHI_TRADING_ENABLED` stays unset.
- [x] **U5 · P1 · Kalshi sprint markets** (PR #36, merged; on by default since 2026-10-06, `RACINGLINES_KALSHI_SPRINTS=0` turns it off). Map sprint winner and sprint pole (`KXF1*` sprint tickers,
      `unmodeled` today) to the sprint stages (after SQ, after Sprint). Check on the Dutch GP (round 12).
      *Done when:* Singapore's Kalshi sprint markets sync with a model price.
- [x] **U7 · P1 · Cross-venue disagreement log** (PR #35, merged, behind `RACINGLINES_DISAGREE`; Polymarket and Kalshi only, OG.com not joined yet). For each F1 outcome linked on both venues (race and
      championship), keep both mids, both fee-adjusted edges and the top of each book at every recorder
      pass (a table or a view over `market_price_history`), with a report
      (`racinglines markets disagree --event …`) and a panel on the Markets page.
      *Done when:* the report lists the gaps above fees for the championship markets, day by day.
- [ ] **OG.com follow-ups (new, from [Coverage](coverage.md#ogcom)):** (a) done: the 5-minute recorder covers OG.com's books, trades and settlements since 2026-10-08 ([Market tape](market-tape.md)); (b) confirm the $0.02 fee in OG.com's fee schedule (S); (c) per-Grand-Prix `[[rules]]` in `exchanges/og.toml` once a live race market is seen (S); (d) join OG.com to the U7 log (S–M). (e) done: a `/markets/og` page and a generic per-schema-exchange route, plus `/markets/tapes` (PR #49; found by the 2026-09-29 spot-check, [Coverage](coverage.md#the-gaps-ranked)). (f) outcomes: `markets --exchange og settle` reads the settlement feed (`get-expired-settlement-price`, probed from the Mac 2026-10-06), hourly in `record_venues.sh` since 2026-10-08 ([Exchanges](exchanges.md#outcomes-the-settlement-feed)); on 2026-10-14 production holds 108 OG.com F1 links, 44 of them per-GP race markets (Malaysia and Singapore, closed), so (g) per-GP contract rules can now be written from the recorded names. (h) a replay on the two recorded race weekends: not run.
- [ ] **Coinbase F1 weekend patch (temporary):** a public GraphQL fallback for this weekend's F1 race markets and
      event page, shown behind a schema switch and a short-term TODO. Future work: formal market mapping, driver/team
      resolution, stable persisted-query tracking, and a proper auth/key path if Coinbase exposes one for deeper history.
- [ ] Other exchanges, if they list motorsport or cycling markets with real depth, including one for
      downhill (none on Polymarket or Kalshi as of 2026-09).
- [x] **OG.com** (Crypto.com's CFTC prediction market): **connector built as a schema** (PR #44: `exchanges/og.toml`,
      one generic driver, `racinglines markets --exchange og sync|trades|history|books|fair`; off by default). Open: a
      recorder timer on the VM (the API keeps about a month), per-GP contract rules once a live race market is seen,
      confirm the $0.02 fee against OG.com's own fee schedule (today from reviews; the API terms were checked), join the U7 comparison. Trading needs FCM onboarding and the
      owner's API key ([Coverage](coverage.md#ogcom)).

## Paper trading

Phase [F1-8](f1-roadmap.md#f1-8-live-paper-trade-validation-polymarket), now on every venue that lists;
how it works: [Paper trading](paper-trading.md). Recommendations and paper fills only; no order is placed.

- [ ] **P0 · Pre-register the rules; profiles stay tunable (owner, 2026-10-05: no freezes).** A, C and K can
      be re-tuned at any time. Each change is recorded with its date in the
      [F1 roadmap](f1-roadmap.md#decision-log) and starts a new settings version with its own live count. Rules:
      [validation plan](paper-trading.md#validation-plan).
- [ ] Run A (demo taker) and C (demo maker) live on every weekend Polymarket or Kalshi lists, through 2026
      and into 2027. Built and scheduled on both venues (the signal engine, every 5 minutes in a race window); ran on
      rounds 16 and 17 (last stored signal: Singapore after qualifying, 2026-10-11 14:37Z). Under the alpha, every
      account's followed style is a paper profile of its own, sized to F$1,000 ([Alpha layout](alpha-layout.md)).
- [x] **U3 · P1 · Kalshi maker profile K** (sweep done; freezing is the owner's call). A sweep of the maker's settings on Kalshi's 2025–26 tape
      (spread, `max_disagree`, `size`, model `gbm` / `gridq+pretrain`, per-market `min_volume_24h`),
      judged on both seasons as `params-4h` was. Save the winner as the Lab candidate "K · Kalshi maker",
      assigned as the demo maker's Kalshi profile.
      *Done when:* K is frozen before round 18, with its 2025 and 2026 Kalshi replay P&L recorded in
      [Kalshi history](kalshi-history.md). **Result (PRs #38, #41, corrected 2026-09-29):** K = `gbm`, 2¢ quotes, 10-point
      disagreement filter, 25 shares, $400 24-hour volume floor: **+$490 (2026), +$659 (2025)**, at 16,000 simulations
      +$453 / +$741, against profile C's −$119 / +$510. The first 2025 figure (+$855) missed Imola 2025, which only
      Kalshi listed (−$195). Owner (2026-10-05): K's settings stay tunable; log each change in the decision log and keep its live record per settings version.
- [x] **P1 · Per-weekend reconciliation** (PR #37, merged). `racinglines strategy reconcile f1 --event 2026-NN --profile X --venue V`:
      live paper fills and markouts against the replay of the same weekend on the recorded tape (the
      conservative "through" fill rule), flagging a weekend outside the validation rules. Its output goes
      into the weekend's report.
- [x] **P1 · Pricing scorecard** (PR #28, merged: `f1 scorecard` for exchange weekends; run it on every weekend), traded or not: Brier and log loss of the fair values
      against the result and against each venue's mid at each stage. `racinglines live report` does this
      for private books; extend it to Kalshi and Polymarket weekends.
- [x] **P1 · `track_record(venue='all')` in the MCP server** (PR #30, merged; original problem: lists one row per weekend while its total sums
      every venue (the maker's weekends mix Polymarket and Kalshi rows). Return one row per weekend and
      venue, with a `venue` column and a total per venue.
- [ ] **P1 · Closing-line value (CLV) in backtests and live** (owner, 2026-10-05). For every replayed and live
      fill, record the venue's price when the market closes (lights out for race kinds, the session start for
      pole), and report CLV = close minus entry, signed for our side, in points and in percent. Report it per
      profile, venue, market kind and weekend, next to P&L in the sweep stats, `f1 reconcile` and
      `f1 scorecard`. Polymarket tapes first. Kalshi uses the recorder's bid/ask books from 2026-09-30 on;
      Kalshi history waits for the bid/ask re-pull, because its last-trade candles spike. Hand-placed
      sportsbook bets get the same field in the project's bet ledger, using an exchange's close as a proxy
      where the book publishes none.
      *Done when:* the 2025 and 2026 replays of A, C and K report mean CLV, and the weekend report shows it.
      **Paper bets done (C4):** `racinglines backtest clv` reports CLV for every stored paper bet, any sport and
      venue ([CLI](cli.md#racinglines-backtest-clv)). Still open: the sweep stats, `f1 reconcile`, `f1 scorecard` and
      the weekend report.
      **G1 definition (owner, 2026-10-07):** the go-live gate reads CLV as the plain mean per bet against the fill
      price, every decided bet counting once (the wider gate: more bets, even if the P&L reads less sharp). Storing
      sweep trades one row per trade, so sweeps get CLV too, is a nice-to-have (core backlog C41).
- [ ] **P1 · On-demand strategy previews** (owner, 2026-10-06). One command that prices the coming weekend
      from a stored stage run and shows what each strategy (T1–T10, TB) would enter now, at a chosen bankroll
      and caps (half- and quarter-Kelly). It writes two tables per strategy: the markets it would pick (side,
      shares, cost) and every other modelled market with its skip reason, such as no edge, the volume
      filter or a cap. It must be read-only, with no orders and no database writes, and it marks
      apparent-value trades that fail a filter as watchlist only. **First version (PR #64):**
      `scripts/strategy_preview.py`, with tests and `docs/strategy-preview.md`. It's standalone
      and read-only, works for any event and source run at 4k or 16k, and was first run on Singapore
      2026-10-05 at $1,000, $50 a market and $250 in total. Every trade there was blocked by zero recorded
      24-hour Polymarket volume, so the preview should also show the venue's own 24-hour volume next to ours.
      *Done when:* it's a `racinglines f1` subcommand documented in `docs/cli.md`, and it shows the venue's
      volume.
- [x] **P2 · Stale line in `docs/coverage.md`** (owner, 2026-10-05). Fixed 2026-10-14: production holds Polymarket
      race links for every 2026 round from Italy (13) to São Paulo (20); the page's counts are now dated.
- [ ] **P2 · Sizing review (~12 Nov),** after 4–6 live weekends on real markets (T3 weekends don't count):
      walk-forward re-run of A, A-lite, C, K, B (#06) and A′ (#08) with rounds 16–20 added, then a sizing
      rule from `bankroll` / `max_deployed` (owner's call, e.g. A-lite → A).
- [ ] Use it live: the signal engine sizes from the account's balance and deployed capital, once the review
      picks a rule. Later, fractional sizing once recorded depth supports it.

## Live events

How it works: [Live events](live-events.md). First run: the Whistler downhill final, 27 Sep 2026. Live
events are T3 unless a venue lists the event.

- [x] **F1 live test, round 16 (Bahrain GP at Sepang, 2–4 Oct 2026)** and **round 17 (Singapore, 9–11 Oct)**: both
      venues listed, so both ran as T1 paper weekends on the signal engine (Polymarket 183 and 272 links, Kalshi 165
      and 314, OG.com 22 each); the Singapore picks and their path through the sessions are the /term parts 2 and 3
      (#157). The private-book runbook stays ready for a weekend no venue lists: [F1 live test](f1-live-roadmap.md).
- [x] Live timers are calendar-driven: `vm.sh live <event>` turns on `live auto` instead of a per-event timer (#134,
      promotion pending), and the signals pass stops once the race result is in and the positions are settled (C59,
      #175, promotion pending).
- [x] **P1 · Launch specs for rounds 18–23** (PR #24, merged) (`live/f1/2026-18.toml` … `2026-23.toml`), used only on
      weekends no venue lists. Check Las Vegas's Saturday-night stage cut-offs.
- [x] **U6 · P0 · Championship sleeve, paper only** (PR #29, merged; first live rebalance is after round 16). `f1 season-strategy` run live after each race on both
      venues (Kalshi's `KXF1*` champion markets included), as a separate profile. Its positions stay out of
      A, C and K's track records. The 2026 replay was −$208 (the model lagged pre-season), so expect little.
      *Done when:* round 16's post-race rebalance is stored for both venues.
- [x] **U8 · P1 · Relocated and cancelled races** (PR #27, merged, behind `RACINGLINES_CANCELLED_RACE_RULES`; the Polymarket 50/50-on-cancel and Kalshi NO-vs-void rules are assumptions for the owner to confirm). Encode Kalshi's and Polymarket's rules for a cancelled or
      moved race (Polymarket's Bahrain 2026 "Other" resolution; the Abu Dhabi "take place" market) in
      settlement, with a test on Bahrain 2026.
      *Done when:* paper positions on a cancelled race settle as the venue's rules say.
- [ ] Owner: switch the loss cap on for round 16 or not (`max_loss = 500` in `live/f1/2026-16.toml` `[live.quoting]`).
- [ ] Optional, round 16: record SignalR during FP1 with FastF1's client, to learn whether it needs a login.
- [ ] A live timing feed (F1 SignalR or OpenF1) for in-session updates; compared in the
      [F1 live test](f1-live-roadmap.md#5-live-data-source) plan.
- [x] Downhill `live run`: take a lock in the run folder like F1's step, so a restart can't leave two loops
      polling (what happened at Whistler, 22:38–22:39). Before the 2027 downhill season.

## Market making

- [ ] The stage-aware taker on the live weekends, before anyone uses it (it lost $316 out of sample on 2025).
- [ ] **First real V2 order** (owner): post, list and cancel one small post-only order, unverified
      against the live CLOB so far. `POLYMARKET_TRADING_ENABLED` stays unset until then. Only after the
      [validation rules](paper-trading.md#validation-plan) are met.
- [ ] Replay with recorded book depth (F1-4): queue position and competing makers,
      instead of the touch/through bounds. The queue model is built (`--fill queue`,
      [queue rule](market-making.md#the-queue-rule), tested on synthetic books, 2026-09-28,
      cloud build-out); running it needs several weekends of recorded books (Polymarket and, with U2, Kalshi).
- [ ] Liquidity rewards as a replay P&L line; optional fractional-Kelly caps.
- [ ] Record venue liquidity rewards (owner asked 2026-10-13; on hold, not merged): branch
      `claude/project-thread-bg60pc` adds `racinglines markets --exchange polymarket|kalshi rewards`
      (markets/rewards.py), run hourly by pm_sync.sh and record_venues.sh: each venue's reward programs on our open
      markets, a row only when one starts, changes or ends, to `data/archive/markets/<exchange>/rewards/`; an empty
      venue response is never saved. No migration. Next: rebase on main, open the PR. Probe 2026-10-13: Polymarket set
      min size 50 / max spread 4.5¢ on 219 of 241 markets per race (Austin, Mexico, Brazil), but only one Austin market
      paid ($0.001/day); Kalshi had no F1 race markets or incentive programs yet (the last ones: Bahrain pole,
      target size 1,000, $100 per market). Re-check Kalshi `/incentive_programs?status=upcoming` from about 21 Oct.

## Models: the one engine

Owner rule (2026-10-11): no sport-specific models, only schemas that declare model inputs and compatibility. Every
modelled sport prices with `GlobalModel` and its schema's `[model] inputs` picks the core (F1 laps and sectors, downhill
run times, the rest results); the old classes are challengers ([Backtest core](backtest-core.md#one-engine-schema-declared-inputs),
[Sports and exchanges: model status](coverage.md#model-status-by-sport)).

- [ ] **C56 · retire the sport-specific classes for the first package release.** The results core must take
      qualifying, grid and practice as schema inputs before F1 can switch without losing accuracy (race-win Brier
      0.1134 laps core vs 0.1476 results core, 2 Oct validation); downhill's `TimedRuns` the same way (C56c). Owner:
      compare first; the F1 walk-forward comparison is production Lab jobs 1 to 4 (2026-10-11; two done, two failed).
      Live F1 and downhill pricing unchanged until the owner's go.
- [ ] **C48 · calibration by probability bucket, every sport** (the next development, owner 2026-10-08): favourites,
      mid-field and long shots, walk-forward against results and against recorded closing prices; a schema-set
      temperature or shrink toward the market if it fails, with a decision-log row. NASCAR and MotoGP prices are
      **unvalidated** until then.
- [ ] **NASCAR and MotoGP in the results core:** start lists instead of every driver ever seen (C5), fitted noise and
      retirements (C6; `GlobalModel` handles retirements, C26), a real challenger (C7), head-to-head and top-20 kinds
      live (C10), the pre-race field from the entry list (C46), `race_start_utc` for CLV (C42).
- [ ] **A naive baseline (engine E7):** `market_implied`; Plackett-Luce was tested on 7 Oct and lost to the probit
      engine in every sport, so it is not the baseline ([Novig and the bake-off](novig-and-model-bakeoff.md)); the extended model, one `rank_logit` challenger with ties, teams, `top_k` and a covariance, is F1-6, started narrowed on 2026-10-14 ([decision log](f1-roadmap.md#decision-log)).
- [ ] **F1-6 · the `walk_forward` job has no `settings` parameter.** MCP `run_job` and the Lab form take a challenger
      by name (`model`) but not its settings, so rank_logit's `top_k`, `tie_on`, `team_effects` and the rest reach only
      the CLI (`backtest walk-forward --model rank_logit --top-k 3`) and the search jobs. The Lab also lists every
      challenger for every sport and rejects a mismatch only at submit. Needed before the F1-6 comparison can be run
      from the Lab or `racinglines remote` (every-surface rule).
- [ ] **Prediction records, cross-engine pairing (found by the F1-6 comparison, 2026-10-14):** record `subject` keys differ between
      engines (the results core and `rank_logit` write `"1"`, the run-times core `"ath:1"`), so `eval compare` across engines
      pairs nothing; and `markets.kinds.settle` returns False, not None, for an entrant the result doesn't know, so such rows
      score as losses without warning. One key convention for every writer of records, and `settle` → None, with a test each.
- [ ] **F1-6 confirmation on NASCAR and MotoGP** (pre-registered in [F1-6](f1-roadmap.md#f1-6-optional-plackett-luce-challenger-reference-model-b)):
      after `racinglines data pull nascar|motogp --no-markets` into the pull database (owner sign-in), three `rank_logit` runs per
      sport against `global`, `race_pole` included; then a decision-log row for `top_k`/qualifying if they hold.
- [ ] **Decision-log rows still missing:** in-race `SIGMA = 3.0` and the live downhill constants (C12); the road
      cycling GC settings (#177).

## F1 model

Phased plan and ground rules: [F1 roadmap](f1-roadmap.md).

- [ ] **P1 · Grid penalties (branch `work/grid-penalties`).** Confirmed penalties in `sports/f1/grid_penalties.toml`
      move the race's or sprint's starting grid before it is simulated ([F1 model](f1.md#model-racinglinesmodelsinputslapspy),
      "Grid penalties"); first row: Russell to the back for Singapore (2026-17). Re-price Singapore once it ships.
- [ ] **P2 · Weather-aware position-model variant `gridq+pretrain+reset-WX`** (owner, 2026-10-06: "later branch", not
      the weather PR). The disruption mixture (more noise and retirements in disrupted races) weighted by the race's
      forecast rain probability (`weather/wet.p_wet_series`, lead 5 days) instead of history alone; then the strategies on it
      (`A-WX` against `A`) in their own sweep under the promotion rule. Until then a `-WX` strategy name would be
      byte-for-byte its baseline: nothing weather-aware feeds win, podium, h2h, constructor or pole. Decided after the
      5-day forecast backtest found the forecast beats the circuit history for rain, is neutral for red flags and adds
      nothing for safety car or DNF ([Weather forecasts](weather.md), [decision log](f1-roadmap.md#decision-log)).
- [ ] **U13 · P2 · Sprint-race pricing model. In progress (2026-10-06, branch `work/sprint-stage`).** Until U5
      (PR #36) Kalshi's sprint winner and sprint pole markets priced from the race's win and pole probabilities
      as a stand-in; the owner approved that for Singapore (2026-09-29).
      **Landed:**
      - **The sprint stage** ([F1 model](f1.md#model-racinglinesmodelsinputslapspy), step 6). It is
        schema-driven (`[sessions.sim]` in `sports/f1.toml`) and drawn on a side stream, so Grand Prix prices are
        byte-identical. It prices from the GP finishing model with the sprint points and `dnf_scale` 0.5
        (provisional, [decision log](f1-roadmap.md#decision-log)).
      - **Grid:** SQ's laps ranked by best valid lap once SQ has run, else simulated. After the sprint, its
        actual result. Per year (`grid_from_by_year`): the 2021 sprint takes its grid from `qual` (no SQ then).
      - **Outputs:** `extra.sprint_win_prob` / `sprint_pole_prob` on every run of a sprint weekend; sprint arrays
        in the sims and records.
      - **Kinds:** `race_sprint_podium` / `_top8` / `_h2h` / `_constructor_top` (`default=False`; out of every
        book per DEC-12), settled from `race_outcomes`' sprint columns.
      - **Polymarket:** `<GP>: Sprint Winner` and `<GP>: Sprint Qualifying Pole Winner` link as
        `race_sprint_win` / `race_sprint_pole`.
      - **Walk-forward:** `racinglines model sprint-check f1`, run on the owner's Mac (2026-10-06): the stage beats the
        GP-win stand-in once the SQ order is known ([decision log](f1-roadmap.md#decision-log)).
      **Open:**
      - **Sprint backfill on the VM:** `f1 fetch --sprints-from 2023` for the 12 missing 2023–25 weekends
        (a database write: backup first, data-changes entry). Then refit `dnf_scale` and decide whether a
        sprint-specific grid weight or noise earns a setting.
      - **SQ order:** segment-aware SQ1/SQ2/SQ3 ordering (best lap per segment, not over the whole session)
        and a TeamId fill for SQ rows (FastF1 leaves both empty). Also SQ positions in `ingest.py`, if FastF1
        ever gives them.
      - **Settlement timing:** `race_sprint_pole` settles from the sprint's starting grid (`extra.grid`, after
        penalties), so not before the sprint has run.
      - **Live stage runs** before SQ only see the sprint when the caller passes `stages=` (the weekend's rows
        don't exist yet): wire it from the schedule in `signals` / `weekend_sweep` if sprint kinds go live.
      - **Replay** against the Kalshi and Polymarket sprint tapes.
      *Done when:* sprint markets price from the sprint simulation and beat the race-odds stand-in on the
      walk-forward and the tape replay.
- [ ] **U10 · P3 · F1 pre-season testing:** ingest FastF1's testing sessions as a stage before round 1 for
      the forecast and the season strategy, so the pre-season forecast sees what the market sees.
      *Done when:* a 2026 re-run with testing moves the pre-season constructors' odds toward the market's
      (Mercedes 41%), measured with `f1 compare`.
- [ ] **Promote `gridq+pretrain` to the default** (owner's OK: it changes live prices; re-run the
      sweep and `UPDATE_GOLDEN` in the same change). Owner, 2026-09-27: keep iterating first; decide in
      December on the walk-forward. The paper-trading profiles pick their model through settings.
- [ ] `reset` for 2027, the second year of these regulations: keep it in profile A's model or not (December).
- [ ] Decide whether profile A's model takes `rookie` (`gridq+pretrain+reset+rookie`, run 1289), after
      live weekends. Not before 31 Dec: A is frozen.
- [ ] Teammate-battle uncertainty: a larger per-driver season drift, or a driver-form model.
- [ ] Props next: calibrate fastest lap on stored stage runs; map Polymarket's and Kalshi's prop markets
      in the sync classifiers (they're `unmodeled` today) and backtest against their prices.
- [ ] Fastest lap from the simulation (`fastlap` variant, off, 2026-10-04): price stage runs with it, score
      `extra.fl_prob` against Kalshi's resolved `race_fastest_lap` links on the VM, then the owner decides
      whether a profile takes it ([decision log](f1-roadmap.md#decision-log)). Score `flpos` (2026-10-07: the fastest
      lap from the simulated finishing order and pace) the same way, beside it.

## New sports

F1 (large audience, deep markets) and UCI downhill (niche, no exchange markets) are the two endpoints.
Candidates between them: NASCAR, MotoGP, WEC, IndyCar, Formula E, road-cycling classics and grand tours,
XC/enduro, alpine skiing. Rank by audience, data availability and exchange listings; no grassroots or
local-league plans. As of 2026-09 the ranking is led by exchange depth:
[Strategy 2026](strategy-2026.md#other-racing-sports-for-2027).

- [x] **U9 · P1 · Tape recording for other sports** (code, PR #26, merged). **First live run on the VM, 2026-09-29:** Kalshi NASCAR 13,599 links and 1.69M trades, MotoGP 322 links and 12k trades, IndyCar 1,374 links and 167k trades, all `unmodeled` ([Data changes](data-changes.md)). NASCAR and MotoGP tapes were pulled again for the replays in the overnight VM run (2026-09-30). The tapes timer is `record_venues.sh` (every 5 minutes, every day, since 2026-10-07). Generalise the Kalshi sync to named series: NASCAR
      Cup (`KXNASCAR*`, race and champion), MotoGP (`KXMOTOGP*`), IndyCar (`KXINDYCAR*`). Each under its own
      competition (a `sports/<code>.toml` entry with no model), links `unmodeled`, with prices, trades and
      books archived per exchange.
      *Done when:* the NASCAR finale (Homestead, 8 Nov) and MotoGP's Qatar–Valencia rounds are recorded
      from listing to settlement.
- [x] **Polymarket tapes for NASCAR, MotoGP and IndyCar** (PR #51). The Polymarket sync now takes a named tape-only
      sport (`[markets.polymarket] tags` in `sports/<code>.toml`, links `unmodeled`, additive: no reset or delete path).
      Running on the VM in `pm_sync.sh` (`PM_SPORTS`): production holds 1,721 NASCAR and 209 MotoGP Polymarket
      links on 2026-10-14 ([Coverage](coverage.md#the-status-matrix)).
- [x] **UCI road cycling, tape only** (schema, PR #50): `sports/road_cycling.toml` (competition `uci_road_wt`, Kalshi
      `KXCYCLING*`), plus `le_mans.toml` and `sailgp.toml` (Kalshi, and SailGP on OG.com). Not yet run on the VM:
      `markets --exchange kalshi --sport road_cycling sync --closed` pulls the 2026 grand tours Kalshi still serves. A
      model is a 2027 question ([Sports and exchanges](coverage.md#the-status-matrix)).
### MotoGP prediction model track

The database and API plumbing are in place and the source gate is complete: the public MotoGP results API is verified for season/event/standings/classification data, and the first pass stays within that contract. **Status 2026-09-30:** `sports/motogp.toml` now has `model_family = "position_sim"` and `pricing_model = MotoGPRaceChallenger` (a result-only form model, Sunday race only), the taker replay runs it (`racinglines strategy replay motogp`, #82), and the board's race-win column is on by default (owner, 2026-09-30). That happened **before M5's gate was met**: the model has not been compared with a naive baseline, the Kalshi replay has no held-out season (2025 lists no MotoGP race markets) and its ranking has not been read. Read its prices as a baseline, not an edge ([Sports and exchanges](coverage.md#model-status-by-sport)). **Since then:** `pricing_model = GlobalModel` (decision log 2026-10-07), and with the one engine (staging, 2026-10-11) `model_family = "global"` at the results level (`[model] inputs = ["results", "qualifying"]`); `MotoGPRaceChallenger` is kept as a challenger ([One engine](backtest-core.md#one-engine-schema-declared-inputs)).

- [x] **M0 · MotoGP source gate:** verify the public API and document the actual data that exists (`api.motogp.pulselive.com`, race classification and standings only; no JSON lap or sector splits). Record the limits in [Data](data.md#other-series-tapes-nascar-motogp-indycar-road-cycling-le-mans-sailgp) (the MotoGP limits paragraph itself is still to be written there).
- [x] **M1 · MotoGP model skeleton** (`models/motogp_model.py`; circuit history not used): create the sport-specific model settings + variant plumbing in the same schema as the F1 sweep (`sweep_settings.py` / `f1`-style run params), but without the F1-only assumptions. Base the first variant on rider form, team-level strength, and circuit history using the already-ingested results table.
- [ ] **M2 · Feature builder for race results only:** keep the first model conservative: only result-based priors (prior race form, rider/team recent pace, circuit-adjusted history), no lap-by-lap or sector splits because the public API does not expose them as JSON. Lock the feature set to what is available in the standard schema and document the exact leak-free cutoff rules.
- [x] **M3 · One-season backtest harness** (as the shared taker replay, `pipelines/position_replay.py`, one pre-race pricing per race rather than F1's stages; saved runs are `model_runs` kind `diagnostic`): wire a MotoGP backtest using the F1 walk-forward pattern (before qualifying / before race) but with the MotoGP event calendar and the same result-kind conventions. Save a small set of model runs to `data/runs/motogp/` and verify the model can price a handful of old races without crashing.
- [ ] **M4 · Sweep then compare:** run a narrow sweep over recent seasons (for example 2021–2026, or a 2–3 season window) and compare the baseline variant to a simple form-only challenger. Use the same search/backtest/reporting conventions as the F1 path, even if the first pass is intentionally small and not production-quality.
- [ ] **M5 · Promotion gate:** only if the backtest beats a naive baseline on a consistent set of races and there are no leakage issues should MotoGP move from `model_family = "none"` to a live pricing model. The first pass stays conservative and does not change any trading or live market plumbing.

- [ ] **Tape-sync follow-ups (2026-09-29 first live run):** ~~the sync should seed a sport's competition row from
      `sports/<code>.toml` instead of raising `NoResultFound`~~ done: every sync creates the rows of the sport it files
      links under (`db/ingest.ensure_competition`), and `vm.sh deploy` now runs `db seed` after the migrations; exchange
      schemas can state the exchange's own caps (`limits`), checked when the schema loads. Kalshi's
      `KXNASCARTRUCKSERIES` (35 links) and `KXNASCARAUTOPARTSSERIES` (40) match the `KXNASCAR` prefix and landed under
      `nascar_cup`; the owner chose to **tag** them (2026-09-29), not filter: done by the market-link pass (`params.nascar_series`,
      applied to the stored links by `racinglines data link nascar`). Still open: the Polymarket tag slugs above.
- [x] **NASCAR and MotoGP in the app** (#108–#112, deployed 2026-09-30): the Markets "Every sport: status" table
      (`RACINGLINES_SPORT_STATUS=1`), NASCAR and MotoGP sections with replay-save prices, next races and recent
      results, sport filters on the strategy pages, and the demo accounts' NASCAR and MotoGP paper rows labelled
      "demo replay, in-sample" (`RACINGLINES_SPORT_PAPER=1`, `nascar|motogp demo-history`, run on the VM by
      `vm.sh demo`). Kalshi: NASCAR Pro −$278.31 (2025) / +$6,525.45 (2026), Basic −$357.23 / +$2,657.23; MotoGP
      2026 Pro +$31.25, Basic +$7.70. In-sample: the settings were picked on the same seasons.
- [x] **Next-race forecasts** (#112): `racinglines model forecast nascar` stored run #9068 (South Point 400); the board and
      race pages show its fair price. Undo: `racinglines model forecast nascar --undo 9068`.
- [x] **Forecast refresh after each race:** `racinglines-forecast-refresh.timer` every 30 minutes fetches and ingests
      NASCAR results on race weekends and Mondays, refreshes the NASCAR and MotoGP forecasts, and re-runs the F1
      championship forecast once per new race result (#107; the daily backup it takes is logged in
      [Data changes](data-changes.md)). Still open: the NASCAR pre-race field from the entry list (C46).
- [ ] **MotoGP calendar ingest:** built in #134 (the forecast-refresh step fetches MotoGP's calendar and results
      daily, every pass on MotoGP weekends; the probe passed), **promotion pending**: production holds no MotoGP round
      after Austria (18 Sep) on 2026-10-14, so MotoGP has no next-race price until #180 deploys and the first pass runs.
- [x] **Polymarket MotoGP links:** 209 on production (131 with a race, 29 open, 2026-10-14), synced by `pm_sync.sh`;
      no replay or demo backfill on them yet.
- [x] **Champion replays** (#95 F1 on Kalshi and OG.com, #96 NASCAR and MotoGP `season-replay` behind
      `RACINGLINES_SEASON_REPLAY=1`; merged 2026-09-30). Left: deploy, then the VM steps in
      `handoffs/2026-10-01-season-replays.md`. MotoGP flags SPRINT POINTS MISSING until sprints are ingested.
- [ ] **Read the unread overnight outputs**: MotoGP's grid ranking (re-run after #102), the OG.com buy-all CSVs (a
      plumbing check, never a result), the NASCAR spike share.
- [ ] **Re-run the coverage probes and spot-check every combo** (handoff written 2026-09-29: `handoffs/2026-09-29-spot-check-exchange-coverage.md`) (Kalshi and Polymarket counts drift; the remaining ? cells) on the VM or the owner's device: the read-only
      commands in [Coverage](coverage.md#what-to-verify-on-a-device). Effort S.
- [x] **P2 · NASCAR data sources** (research, PR #25, merged): results, qualifying, practice and lap data
      (NASCAR's public feeds, community archives), their terms and history depth; written up in
      [Data](data.md).
- [x] **NASCAR results adapter** (`racinglines data fetch nascar | ingest`; the feeds probed 2026-09-29, findings in
      [Data](data.md#nascar-content-feeds-verified-2026-09-29)). **Done on the VM 2026-09-30** (backup first): 408 Cup events 2016–2026 ingested and 7,544 Kalshi links identified with a race ([Data changes](data-changes.md)). The original plan:
      database backup, then Cup 2017–2026 on the VM with a `data_changes` entry (three races were fetched on the Mac
      on 2026-09-29 and the pit feed read: real stops, `nascar_pit_data_2026_5628.json`). Built since: scheduled events for upcoming races and the driver/race resolver (`sources/nascar/identity.py`);
      **the market-link pass** (`sources/nascar/links.py`, `racinglines data link nascar`, and inside the Kalshi, Polymarket and OG.com syncs): race by name within its season,
      driver, contract kind, and a `cup | xfinity | trucks` tag, with `prediction` left `unmodeled` (tested on the real Kalshi and Polymarket listings).
      Next, in order (VM, owner): full pull and `ingest` after a backup; then `link` dry run, read the unresolved list, `link --apply --backup FILE`; then the
      readiness audit. OG.com's NASCAR contracts and Kalshi head-to-heads were sampled from the Mac (PR #68) and the pass handles both.
- [ ] **P3 · NASCAR for 2027?** Decide from the recorded Chase tapes (volume, spread, how often markets
      trade) and the data review. If yes: a first model in Jan–Feb, paper-traded from the 2027 Daytona 500.
- [ ] MotoGP: its qualifying / sprint / race weekend maps onto the F1 adapter; sprints are not ingested yet, so the
      model is Sunday-race only and the champion is quote only. Thin on Kalshi (champion ~$20k); revisit if the tapes show depth.
- [ ] Skip horse racing: the Interstate Horseracing Act keeps it off Kalshi and Polymarket.

## Points validation

The points tables in `racinglines/models/inputs/run_times/` (`FINAL_POINTS`, `QUAL_POINTS`,
`QUAL_POINTS_ROUND`) are **placeholders**, and the same tables are used for every
season. Until they're fixed, every number measured in points (expected points,
standings, champion odds, `spearman_points`) is approximate. Off-season work (U11).

- [ ] Get the official UCI DHI World Cup points scales, from the UCI MTB regulations
      (Part 4) or the standings PDFs on ChronoRace. Get the 2026 table first, then
      earlier eras for backtests (2021–22 single qualifier, 2023–24 semi-final,
      2025–26 Q1/Q2).
- [ ] Replace `FINAL_POINTS` with the official Final points for every scoring place.
      Check how many places score: currently 30, but the 2021–22 Finals had 60+ riders.
- [ ] Confirm which qualifying round pays points in each format, and how many places
      score. Also check whether riders who get through Q2 score. Update `QUAL_POINTS`
      and `QUAL_POINTS_ROUND`. If more than one round pays, extend
      `actual_event_points` and `simulate_weekend`.
- [ ] Check the edge cases:
  - [ ] DNF/DSQ in the Final: zero points, or last-place points?
  - [ ] Ties
  - [ ] Protected or wildcard riders
  - [ ] Bonus or double-points rounds
- [ ] **Reconcile:** `racinglines data points mtb_dh check --season 2026 --through-round 7
      --standings …` compares each rider's cumulative total with the official standings
      (built; needs the official tables and standings). Every rider should match exactly.
      Repeat for one past season.
- [ ] Re-run `season` and `backtest`, and refresh the tables in the docs and README.

## Data

Downhill data, mostly from ChronoRace (`prod.chronorace.be`), which the cloud network blocks: allow it in
the environment first, or run locally.

- [ ] Elite Women and Junior Women: download (`mtb_dh download --category 'Elite Women'` already works;
      ChronoRace is blocked in the cloud, so locally), then forecast with `--unraced-format last`.
      Done (2026-09-28, cloud, synthetic data): unraced rounds can take the category's own format
      (`--unraced-format last`, off by default); the default simulates every category in the 2026 elite
      men's format (a 30-rider final), which put all 24 riders of a synthetic women's field in the final.
      Enter the official formats per category in `sports/mtb_dh.toml` `[rounds.category_format]` (owner).
- [ ] Start order: it's in ChronoRace's start-list PDFs and possibly the JSON.
      Needed for track-evolution and weather effects. Blocked in the cloud (ChronoRace).
- [ ] Weather and track conditions (the PDFs have weather; `--conditions-file`
      exists but is empty). Blocked in the cloud (ChronoRace).
- [ ] Check the incomplete past seasons: UCI 2023 shows 7 of 8 events completed and 2025 shows 9 of 10
      (a cancelled round or a missing result each).
- [ ] 2019–2020 PDFs: the text layer is unreadable font codes, so they'd need OCR.
      Low priority.
- [ ] Re-create event diagnostics and scenarios where needed after the 2026-09-27 database
      rebuild (optional; sweeps, runs and market links came back from the snapshot).

## Model

Downhill model.

- [ ] Check the new downhill defaults on 2027's first rounds (out of sample; 2026 is over).
- [ ] Owner: make `--unraced-format last` the default? Juniors' unraced rounds are simulated in the elite
      men's 30-rider-final format today; with their own format, the 2026 MJ leader's make-Final odds for
      the next round go from 92% to 73% (committed snapshot, 2,000 sims). Changes junior and women's prices.
      Per-round-type incident rates tried too: no gain.
- [ ] Protected-rider rules in older formats.
- [ ] 2027 venues: once the calendar is announced, use venue history in the forecast.
- [ ] Decide whether to retire or rebuild the older `fit`/`predict` Elo/GBR model.
      It hasn't been checked against the multi-season data.

## Engineering

- [x] **Engine roadmap E0:** owner decisions D1–D6 taken as recommended 2026-09-29 ([decision log](engine-roadmap.md#decision-log)); capability matrix written.
- [ ] **Engine roadmap, window 1 (read-side, now to 6 Dec)**, one branch and PR per task, in order: ~~E1a sport frames for F1 and downhill~~ (done, PR #73: `racinglines/frames/`, `[data]` in the schemas) · ~~E4a long prediction records beside `race_predictions`~~ (done, PR #76, behind `RACINGLINES_PREDICTION_RECORDS`) · E1b market frames over the canonical price reader · E1c NASCAR frames (after the onboarding thread's `nascar ingest`) · E2 `DataView.asof` and the generic leak guard (switch off; ⚠️ `pricing.py`) · E5 `racinglines eval` · E6 `racinglines report build` and the model card (the plan: [Reports](#reports-consistency-and-reproducibility) REP-3 to REP-6) · E7 `market_implied` and `plackett_luce` on the NASCAR tape and F1, with a NASCAR model card for the 2027 decision. Details: the owner's Engine Implementation Plan page.
- [ ] **Engine roadmap, window 2 (after 6 Dec, before 2027's first race):** E3 contract v2 (⚠️ live sweep and signals path) · E4b readers onto the records plus the `predictions` table (⚠️ VM migration, backup, sign-off) · E8 consumers read the registry · E9 Kalshi and Polymarket classifiers to per-sport TOML rules, fees from the schema, D5 (⚠️ money-adjacent). The `exchanges/kalshi.toml` and `exchanges/polymarket.toml` drafts can be proved in a scratch database this year.
- [ ] **E2 prerequisite for downhill: an `events.end_date` column set at ingest.** The frames parse a weekend's end from the event name (`racinglines/frames/mtb_dh.py`) because `events` has only `start_date`, which is not always the weekend's first day. A DB migration: backup first (the standing practice in CLAUDE.md) and the owner's sign-off.
- [ ] **Data defect, F1 event 27:** its qualifying rows alias BEA to placeholder athlete 567 and miss Stroll, so the entry list (and the E1a `entrants` frame, which uses it) lacks him. Found in E1a; not fixed there.
- [ ] **U12 · P3 · Move to Google Cloud,** after Abu Dhabi so nothing changes under live weekends: the data
      bucket is up ([Data](data.md#data-bucket)) and the [proposal](google-cloud.md) is written (Cloud SQL,
      Cloud Run, Scheduler, service identities, about $28–35 a month at list prices). Next: the owner's
      choices (database tier, recorder shape, domain).
- [x] Forecast runs from committed code: both live forecasts (F1 run 3, downhill run 1287) were built from
      `1ab8934-dirty`. Checked (2026-09-29): the F1 forecast does not overwrite run 3; `f1 forecast --save`
      always inserts a new `model_runs` row (`save_model_run`, nothing updates or deletes forecast runs; Lab
      promotion only sets `params.promoted_at`) and the web app prices from the latest one. Run 3 is the
      only F1 forecast because the database was rebuilt on 2026-09-27 (ids 1–3 are its first rows, 18:37–18:42Z)
      and the forecast has been saved once since; the downhill one came later (1287). Still to do: re-save
      both from committed code.
- [x] **Web app N+1 in `model_prob`** (PR #43, merged 2026-09-29): Kalshi's `market_links` rows doubled the per-market
      lookups on the Markets page; fixed with one batched read.
- [x] **Same-second maker fills kept apart in stored signals** (PR #39, merged), the bug `f1 reconcile` found.
- [x] **CLAUDE.md** (PR #45, merged): the standing process note (environments, model tiers, dev cycle, pre-merge
      checks, report format, safety rails). Open: its Fable tiering versus the session-only no-Fable rule.
- [ ] Remove the `demo_context` bubbles before real users.
- [ ] Before anything goes beyond a private demo: check F1's data terms, OpenF1's non-commercial terms,
      and settlement rules for relocated or cancelled races (U8).
- [ ] JSON API, owner: what's public (results only, or prices), who can use it (accounts, keys, no
      login), data terms, rate limits ([open questions](webapp.md#json-api)).
- [ ] **Condition in-weekend forecasts on completed rounds** (downhill). Once Q1 has run, fix
      who has qualified and use the Q1 times. Also use split times from disrupted
      Timed Training sessions.
- [ ] Market-making loop (F1-5, deferred): re-quote linked markets automatically when the model or
      book moves, within per-market and total exposure limits.
- [ ] Have `forecast_season` read `scheduled` events (no start list yet) as named rounds instead of `remaining_round`.
- [ ] Ingest on a schedule: download, then `racinglines data ingest mtb_dh` for new rounds.
- [ ] Ingest the other input formats (copy/paste, HTML, JSON) into the database.
- [ ] Tests: parser fixtures (one file per format era), `event_format`,
      `actual_event_points`, the rider-ID normalization check.
- [x] **Faster searches** (2026-09-29). Every search job was one CPU-bound Python process with the database
      idle, and a full-season Kalshi maker job spent ~60% in the maker replays, ~20% reading the weekend's
      markets, ~15% loading Kalshi's tape, plus the rating history. Now: (1) `[search] grid = N` runs up to N
      sweeps of one season and model in one process (`f1 sweep --grid`), sharing the measurements, stage
      pricings, markets and maker tape, with saved runs identical to separate processes; (2) the rating
      history is built only when a stage has to be priced, and `[search] history_cache = true` keeps it on
      disk (`data/cache/history/`, keyed by model settings and data); (3) `parallel` defaults to every core.
      The 106-job `sweeps/kalshi-maker-k.toml` grid went from 59 to 21 minutes on 4 cores, same results.
      Left: the maker replay itself (`maker_replay.quote`/`PublicView`, about half of what remains).

### Web UI: open items (from the "Web UI Improvements" thread, closed 2026-10-14)

Interaction side of the web app (forms, auth and sessions, navigation, app-shell code). The full backlog with audit
citations lives in the project library (`library/audit/2026-10-06-web-ui-backlog.md`). Checked against `staging`
at `4905943` on 2026-10-14 where marked; the rest were last checked on 2026-10-06.

- [ ] **S1 · CSRF is one global token** (`CSRF_TOKEN`, `check_csrf` in `racinglines/web/app.py`), the same for every
      user and visible to the demo logins. It guards settings, MCP and admin writes and the order routes. Still true
      2026-10-14. Money-adjacent: its own `work/web-security` branch, staging first.
- [ ] **S2 · Login throttle trusts `cf-connecting-ip` / `x-forwarded-for`** from any client (`users.py`, `app.py`),
      per-IP only, in-process dicts that never evict, no test. Still true 2026-10-14.
- [ ] **S3 · `APP_SECRET` unset falls back to a random per-process secret** (`app.py`: sessions and CSRF break on
      restart). Fail fast instead. Still true 2026-10-14.
- [ ] **S4 · What sign-up's role may trigger** (DB-writing syncs, `diag_example`). Needs the owner's call; re-check
      against the alpha layout, which runs basic as pro.
- [ ] **S5 · Admin "create user" does not validate the role** (`admin.py` `admin_user_create`; the update path
      does). Still true 2026-10-14.
- [ ] **S6 · Demo guard redirects to the `Referer` header** (`demo.py:80`, off-site redirect possible). Still true
      2026-10-14.
- [ ] **S7 · Logout and password reset don't end other sessions** (stateless cookie). May need a per-user
      counter column: a migration, so backup and owner sign-off.
- [ ] **U1 · Self-serve strategy switching for pro users** (admin-only today). Needs an owner decision.
- [ ] **U2 · Password change and a light/dark toggle in Settings** (`settings.html` has neither, 2026-10-14).
- [ ] **U3 · Link the pro/basic comparison from the sign-in page.**
- [ ] **U4 · Open the sport with a race in the next 7 days on /markets** without overriding remembered state
      (shared with the Web View side).
- [ ] **C2 · Web app sport-specific literals** (Lab job types, `'f1_wdc'` in views and templates) to schema-driven,
      per the one-engine rule. C1 (split `app.py`) is mostly done: 883 lines on 2026-10-14, down from 1,550.
- [ ] **`/demo/book` and `/demo/live` pages for the F1 race-week demos** (Core C54; plan
      `library/engineering/2026-10-11-f1-race-week-demos/plan.md`, the Web UI side owns the replay behaviour). No such
      routes on `staging` 2026-10-14.
- [ ] **Maker `/positions` page speed:** the profiler `library/web/2026-10-11-positions-speed/profile_positions.py`
      (run on the VM from the Mac) has never been run or its output never returned.
- Standing limit (owner, 2026-10-11): further maker UI is drop-down entries and sub-setting inputs only, no new
  components. Alpha settings stay as they are until about mid-November (owner, 2026-10-12).

## Staging and CI deploys

**High priority** (owner, 2026-09-30; in [P1](#priorities)). Audited 2026-10-01 against the public repo, the
workflow, `scripts/deploy/`, `deploy/vm/` and the data bucket ([VM deploy: Code from GitHub, data on the
VM](vm-deploy.md#code-from-github-data-on-the-vm)).

**What works today (2026-10-01).** `main-merge-gate` (`.github/workflows/predeploy.yml`): `detect-docs-only` skips
everything when the change set is only `docs/` and `*.md`; otherwise `predeploy-staging` smoke-checks
`staging.racinglines.bet`, and on a push to `main` `deploy-production` runs `vm.sh deploy <sha>` (pause timers,
untrack, checkout, pip, `alembic upgrade head`, `db seed`, restart, resume timers) and smoke-checks
`racinglines.bet`. First green end to end: run 19, commit `4469100`.

**What it does not do yet, and what to watch until it does:**

| Gap | Effect now | Watch for | Fixed by |
|---|---|---|---|
| No tests in CI | A green PR has only passed a smoke check of staging | Run `racinglines check`, `pytest -m "not live"`, `mkdocs build --strict` locally before asking for a merge | STG-2 |
| Golden tests skip without `tests/fixtures/` | ~50 tests skip on a public checkout, all goldens included; pytest still looks green | Pricing / model / replay PRs: run the goldens on the owner's Mac | STG-7 |
| Staging smoke doesn't run the PR's code | `predeploy-staging` checks whatever staging serves | Merge the branch to `staging` first (PR 11) and look at it; `predeploy-staging` alone means "staging is up" | STG-4 |
| A merged migration runs on the VM at once, no backup step | The safety rail (owner sign-off for VM migrations) depends on who merges | PRs with `migrations/versions/*`: ⚠️ in the title, `vm.sh backup <purpose>` first, owner's word, then merge | STG-8 |
| No off-VM copy of the VM's data | VM disk loss = data since 2026-09-28 gone, incl. archived market history | Avoid anything risky on the VM's disk; `vm.sh backup` before every data step | STG-5 |
| Cloud sessions read the old bucket (last push 2026-09-28) | Cloud sweeps and analyses run on stale data | Say so in any cloud result; check `bucket.py ls` dates | STG-5 |
| No concurrency group | Two merges close together run two `vm.sh deploy`s at once (overlapping pause/resume) | Merge one PR, wait for its Actions run to finish, then the next | STG-6 |
| Every code merge deploys, also in a live window | The web app restarts; live timers pause and catch up | Don't merge code during a book (round 16: Fri 2 Oct 03:30Z to Sun 4 Oct 07:00Z) | STG-9 |
| `/docs` is built on the VM by deploys (since PR 7) but not by docs-only merges; `/pitch` images are only on the VM's disk | `/docs` lags docs-only merges; a rebuilt VM has no pitch images | After a docs-only merge: `vm.sh docs` | STG-10 |
| Re-tracking a file the VM keeps untracked | Checkout refuses after `untrack.sh`; timers stay paused until fixed | Before committing pitch images or fixtures, move the VM copies aside | STG-10, STG-7 |
| Claude GitHub App not on the public repo | PR and CI events never reach threads | Threads check PRs by hand; owner installs the app | STG-11 |
| Workflow edits | Cloud sessions can't push `.github/workflows/*` | Workflow changes come as a patch the owner applies (`git am`) | — |

Each item below needs the owner's go; the ones touching the VM, DNS, the bucket or secrets need sign-off.

- [x] **STG-1 · staging host.** Built 2026-10-01 (PR 11, [VM deploy: Staging](vm-deploy.md#staging)): a second app copy on the VM (port 8010, `racinglines_staging`, no timers, no trading flags), `vm.sh staging setup|deploy|status|reset|off`. Open: Cloudflare Access in front of it. Original plan: a second app instance with its own database
      (`racinglines_staging`, restored from the latest VM backup, trading flags off, `RACINGLINES_*` switches as on
      production), either a second compose project on the VM (cheapest; the n2-standard-2 has room) or a small
      separate VM; Cloudflare DNS and tunnel route; Cloudflare Access or basic-auth. Owner decisions pending: same
      VM or its own, keyless GCP auth (workload identity) or the JSON key, Cloudflare Access or a password.
- [ ] **STG-2 · tests in CI** (workflow patch). A `checks` job on every PR, required before `deploy-production`:
      Python 3.14 as on the VM, `pip install -r requirements.txt -e .`, a Postgres service container with
      `TEST_DATABASE_URL` pointing at `racinglines_test` (never `racinglines`: the fixture drops the DB it names),
      `racinglines check`, `pytest -m "not live"`, `pip install -r requirements-docs.txt && mkdocs build --strict`.
      It must not run on docs-only change sets' deploy path, but it should still run `mkdocs build` for them. Done
      when a PR that breaks a test is red on GitHub.
- [x] **STG-3 · deploy branches to staging.** Built 2026-10-01 (PR 11): a merge or push to the `staging` branch runs `deploy/ci/staging.yml` (`vm.sh staging deploy <sha>`, smoke with `SMOKE_EXPECT_ENV=staging`); the owner copies it into `.github/workflows/`. Original plan: on a push to a `track/*` branch (or a PR label), CI deploys it to
      staging with a `vm.sh deploy --staging` variant (alembic runs against the staging DB only), runs
      `smoke.sh` against staging and posts the result on the PR. Replaces today's staging smoke of whatever is live.
- [ ] **STG-4 · verify, then production.** The owner checks staging (a short checklist per track: pages load,
      Markets board counts, paper rows), then merges; the merge deploys.
- [ ] **STG-5 · an off-VM copy of the VM's data.** *(2026-10-14: built as `scripts/vm/offsite.sh` + `racinglines-offsite.timer`, `vm.sh offsite`; nightly prod dump, `data/backups` and `data/archive/markets` to the primary bucket. The VM can already write there. Restore drill and cloud-session read key still open.)* Today the VM's disk is the only copy of the newest database,
      `data/backups/`, and the market history the recorder's archive pass moved out of Postgres into
      `data/archive/markets/` (dumps alone no longer hold it). Steps: (1) `bucket.sh push` gets a VM mode: `pg_dump`
      through `docker compose exec -T db` instead of the Mac's `PG_BIN`; (2) the VM service account gets object
      write on `racinglines-data-384052502248` (owner, GCP; GCE's default scope is storage read-only, so the VM may
      need a scope change and a restart); (3) a `racinglines-offsite.timer` nightly (outside book windows): dump,
      trailer check, upload the dump + manifest and `gcloud storage rsync` `data/archive/markets`, `data/runs/live`,
      `data/raw`, the pitch images; progress line every 5 minutes; (4) `vm.sh offsite [status]` to enable it and
      read the last run; (5) a restore drill: `vm.sh restore` into a scratch database on the VM, row counts compared.
      Then decide whether cloud sessions get an HMAC key on the VM's bucket (read-only) or the VM also pushes to
      the old bucket. Never at the same time as a VM DB write step.
- [ ] **STG-6 · CI hardening** (workflow patch): `concurrency: { group: deploy-production, cancel-in-progress:
      false }` on `deploy-production`; the docs-only rule narrowed to `docs/`, `README.md`, `CLAUDE.md`,
      `mkdocs.yml` and `handoffs/` (today any `*.md` anywhere counts); a job summary naming the deployed sha and
      the timers resumed.
- [ ] **STG-7 · test fixtures for CI and cloud.** The public repo has `tests/golden/` but no `tests/fixtures/`.
      Owner decision: commit them (they come from public sources: FastF1, Polymarket, ChronoRace; check size and
      terms) or keep them in the bucket and pull them in CI with a read-only key. Before committing, move the
      VM's untracked copy aside (else the next deploy stops after `untrack.sh`). Done when a fresh clone runs the
      goldens instead of skipping them.
- [ ] **STG-8 · migration gate.** `update.sh` dumps the database (`data/backups/db/racinglines-before-migrate-<UTC>.sql.gz`,
      trailer checked) whenever `alembic current` differs from `alembic heads`, before `alembic upgrade head`; and
      the workflow refuses to deploy a commit that adds `migrations/versions/*` unless the PR carries an owner label
      (e.g. `migration-ok`). Keeps the "no VM migration without the owner's sign-off" rail true under auto-deploy.
- [ ] **STG-9 · deploy freeze for live windows.** A `/var/lib/racinglines/deploy-hold` file on the VM (set by
      `vm.sh hold on|off`, or automatically while a `racinglines-live-*` timer is active) that makes the CI deploy
      wait or fail cleanly with "held for a live event"; a manual `workflow_dispatch` re-runs it after.
- [ ] **STG-10 · built docs and pitch images on the VM.** Done for code deploys (2026-10-01): `vm.sh deploy` and
      `vm.sh docs` run `deploy/vm/build_docs.sh` (`/docs` was 404 "Docs not built" on the VM since cutover). Open:
      docs-only merges run a light workflow job that calls `vm.sh docs` (workflow patch). The 10 pitch images go to the bucket (STG-5) and, if the owner wants them in the repo, are committed
      under `racinglines/web/static/pitch/` with a `.gitignore` exception (VM copies moved aside first).
- [ ] **STG-11 · GitHub App.** Install the Claude GitHub App on `racinglines-public` (owner:
      https://github.com/apps/claude/installations/select_target) so PR, review and CI events reach the threads.

## Reports: consistency and reproducibility

Owner ask (2026-09-30): reports lean on ad-hoc Claude work; someone else (or a later session) can't rebuild one.
Recommendations, in order; the first two are cheap and can start with the next report.

- [ ] **REP-1 · a `SOURCES.md` per report folder** (now, by hand; in CLAUDE.md): the commit, every command or SQL
      query behind a number or plot, run ids, data files and their hashes, screenshot settings.
- [ ] **REP-2 · one report skeleton.** A template with the fixed sections both good reports share (scene-setter,
      top-line table, sections, timeline, winners/losers, "what this does and doesn't show", what's next) and the
      screenshot rule (1024 px, 150%). Reports keep their own voice inside the sections.
- [ ] **REP-3 · `racinglines report build <folder>`** (engine roadmap E6, with the model card). A folder holds
      `report.toml` (inputs: run ids, queries, date window, venue, sport; seeds; the settings file), the Markdown
      with placeholders for tables and plots, and `build.py` hooks. The command re-runs the queries, draws the plots
      with fixed styles, fills the tables, renders HTML and PDF through `markdown_html.render` (as `live report`
      does), and writes a `manifest.json`: commit, inputs, output hashes.
- [ ] **REP-4 · pinned inputs.** Reports read a data snapshot, not the live DB: `db export` of the tables they
      use (or the bucket's Parquet snapshot) named by date and hash in `report.toml`. Model runs by id, never
      "latest". Seeds for every simulation in the report.
- [ ] **REP-5 · versioned config and model cards.** Every tuned setting read from a committed settings file
      with its decision-log entry; a model card per model in use (inputs, training window, calibration, known
      gaps), linked from each report that uses it.
- [ ] **REP-6 · regenerate check.** A CI job (after STG-2) rebuilds one reference report from its pinned
      snapshot and fails if a number changes; `UPDATE_GOLDEN=1`-style promotion when a change is meant.
- [ ] **REP-7 · screenshots by script.** A Playwright script per report takes its screenshots at 1024 px and
      150% against staging (after STG-1), so they can be re-taken, not re-clicked.

### Internal onboarding book (2026-10-14)

The admin-only onboarding book (Jupyter Book) is served at `/docs/internal/` from `data/internal-docs` on the VM
(route in `racinglines/web/info_routes.py`, copied by `vm.sh internal-docs`, on prod since #180). Its source is
never in git: it lives in the project library (`library/onboarding/book`) and on the owner's Mac
(`~/Documents/racinglines/jb/book`); build steps are in its `README.md`.

- [ ] **BOOK-1 · put the first draft on the VM.** The Mac build is clean (14 Oct 07:03 UTC, with the DITL #1
      timeline fix). Run `bash scripts/deploy/vm.sh internal-docs ~/Documents/racinglines/jb/book/_build/html`
      from a checkout of `main` if it has not been run yet (not verified from the thread), then open
      `racinglines.bet/docs/internal/` as an admin; anyone else should get a 404.
- [ ] **BOOK-2 · owner review of the draft.** Every chapter carries a "Claude first draft (2026-10-14)" note; remove
      each note once the owner has read that chapter.
- [ ] **BOOK-3 · DITL #1 follow-ups.** (a) The owner decides whether the v4 joint prologue + GC paper slip goes
      into DITL #1. (b) Only the book's copy of `ditl/core.md` has the timeline fix (betting closed about 16:00 to
      16:02 UTC, window missed by about 56 minutes, not 24); the Mac source `core.md`, its timeline figure and the
      internal PDF still count to the 16:34 start. (c) Add the paper result once the Eneco GC settles (18 Oct).
- [ ] **BOOK-4 · missing sources.** The runs/f1 matrix artifact was not saved; `research/algo-abc` links
      `img/pl-vs-global-win.png`, which was not found (only its script exists); 5 of the 8 recovered 24-hour report
      figures are captures of the sign-in page; the Whistler, global-model sweep, Kalshi maker K and overnight sweep
      report texts are still missing (see `sources/index.md` in the book).

## Business and collaborators

- [ ] **2026 season report** (December): live weekends by venue and profile against their replays, the
      pricing scorecard for rounds 16–23, the championship sleeve, the disagreement log. Published under
      `reports/` like the Whistler report.
- [ ] **Beta testers and collaborators:** accounts and onboarding; contributor docs; a code-only
      public mirror or invited access to the private repo (it is private only because of the
      committed data set).
- [ ] **B2B:** selling the prediction models remains open.
- [ ] Trade on exchanges only after paper-trade validation (F1-8, the
      [validation rules](paper-trading.md#validation-plan)).

## Done

Finished items, moved here from the sections above, with the dates they were done.

### October 2026: the alpha, the recorders, the one engine (moved here 2026-10-14)

- [x] **Fantasy league alpha on production** (2026-10-12): sign-up and accounts (#146), the alpha layout with four tabs,
      five styles and F$1,000 sizing with Kelly (#160), settlement, leaderboard P&L and MCP trading tools (#161), the
      Lab tab opening on Follow a strategy (#166), the landing page and sign-in (#144, #167). Everything else is
      archived behind the layout switch ([Alpha layout](alpha-layout.md)).
- [x] **Recorders every 5 minutes, every day** (owner rule 2026-10-07; #90, #91): Kalshi and OG.com books, trades every
      15 minutes, Polymarket NASCAR and MotoGP books, `tape_check.sh` warnings, `backfill_tape.sh` for gaps
      ([Market tape](market-tape.md)). Forecast-refresh (#107) and schedule-sync (#169) timers.
- [x] **The one engine** (2026-10-11, #128): `GlobalModel` for every modelled sport with three cores, prices identical
      to the old classes, which stay as challengers.
- [x] **Rounds 16 and 17 paper-traded on real markets** on both venues; /term's Singapore parts (#152 to #157).
- [x] **Racinglines 101** in three parts and the kart quickstart replay under `/docs` (#139, #142).
- [x] **Sprint stage** (U13's core, PR #73) and **grid penalties** (PR #74), merged 2026-10-06.
- [x] **CLV for stored paper bets:** `racinglines backtest clv` (C4, #81); the coverage counter `backtest coverage`
      (C0, #81); `race_start_utc` for NASCAR (C42).
- [x] **Deploy guards:** production and staging never share a venv (C57, #147); a deploy stops a long signals pass
      instead of refusing (#149); the smoke check follows the alpha layout (#164).
- [x] **Data-terms review** (owner, 2026-10-14): venue prices, MotoGP and `data pull` may reach signed-in users; the
      #aintcare warning stays. **MotoGP back for the alpha, `data pull` (C51), `racinglines remote` (C53)** (#179,
      promotion pending).
- [x] **Season demo database for staging** (`racinglines_staging_demo`, #173, #174): built on the VM 2026-10-13, every
      player on a random style through 2026; `vm.sh staging db demo|main` switches staging to it.
- [x] **Staging mirror code** (#154, merged, not enabled); **MCP results as drawn tables** (#171).
- [x] **Live trading history report** (3 to 12 Oct, the project library) and the first DITL report (13 Oct).

### Strategy session (2026-09-28)

- [x] **U4 · Profile A's record vs the sweep, explained.** The demo taker's record (+$575 in 2025, +$323 in
      2026 on Polymarket) is about a third of profile A's (+$1,363 and +$1,243) because the demo taker
      follows about a third of A's calls (`profiles.DEMO_FOLLOW` 0.33, see
      [Following](paper-trading.md#following)); taking every call makes +$2,606, the sum of the two. No fix needed.
- [x] Maker record by venue checked: Polymarket +$285 (2025) and +$653 (2026), Kalshi +$193 and −$119,
      private book (Whistler) +$11,349.
- [x] Round 16's event name ("Bahrain Grand Prix in Malaysia") is correct: the race moved to Sepang.

### Priorities (September)

- [x] Round 16 build: name aliases, the shared live core, the F1 adapter, the Live tab's F1 body, the demo
      taker, operations, a rehearsal on Baku (items B0–B8, cloud build-out 29 Sep).
- [x] A repeatable report command for any live event: `racinglines live report`.
- [x] Settle the Whistler private book in the database, into the demo maker's story.
- [x] A per-market loss cap and two-sided long-shot quotes in the shared quoting core (both off by default).

### Done: Points validation

- [x] Store the tables in the `points_schemes` database table (per competition,
      era and round kind), and have the model read them from there: `racinglines data points mtb_dh
      import`, and `--points db` on `forecast` and `backtest` (default: the schema's placeholders).
      The entry file `sports/points/uci_dhi_wc.toml` holds placeholders for every era until the
      official scales are in (2026-09-28, cloud build-out).
- [x] A test that pins those totals (`tests/test_points.py`): it checks every standings file in
      `sports/points/standings/` and skips until the owner adds one.

### Done: Data

- [x] **Use UCI rider IDs** (code, 2026-09-28, cloud build-out; synthetic tests, unverified against
      the live API): the downloader writes a `UCI ID` column, the parser reads it (older files parse
      as before), and ingest matches `athlete_identifiers(scheme="uci")` before names and reports
      a UCI ID shared by two athletes. `racinglines db merge-athletes KEEP DROP` merges them.
- [x] Re-download the downhill files (UCI IDs) and re-ingest (2026-09-28, locally; [Data changes](data-changes.md)):
      584 results moved onto the UCI-matched athlete, 1,090 UCI identifiers.
- [x] Merged 53 of the 58 reported pairs (2026-09-28). Five stay: both rows are in saved forecast run 1287
      ([Data changes](data-changes.md)).
- [x] **2021 PDFs** (Leogang, Les Gets) and PDF-only Timed Training rounds: read by
      `download --pdf-results` (backfill only) and ingested 2026-09-28 (775 results).
- [x] **Slug probing** in the downloader (`--probe START END`, 2026-09-28): all of 2021 finds exactly its
      six DH rounds.
- [x] Canonical venue names (`mont-ste-anne` → `mont-sainte-anne`,
      `vallnord`/`vallnord-pal-arinsal` → `pal-arinsal`): the database already stores every venue
      under its canonical slug (`venue_aliases`, checked on the snapshot: no duplicates); `mtb_dh parse
      --canonical-venues` does the same for the CSV path (off by default) (2026-09-28, cloud).
- [x] **2025 Polymarket F1 markets** downloaded and synced (2026-09-27: 23 of 24 races have
      markets; minute prices and trades, no order books) and backtested in the cloud search.

### Done: Model

- [x] **Calibration check** (2026-09-28, cloud build-out): `mtb_dh backtest --reliability` over
      all 43 rounds. Win and podium are close; top 10 and make-Final are too flat. Cause: too much
      shrinkage (`prior_n`). A lower `INCIDENT_THRESHOLD` and heavier-tailed ε (`--eps-df`) don't
      help ([Calibration](model.md#calibration)).
- [x] **New downhill defaults** (owner's OK, 2026-09-28): `prior_n` 0.5, half-life 240 days,
      junior weight 0.25. Better in every market on the 43 rounds; picked in-sample.
- [x] A tuning sweep over all 43 rounds (2026-09-28, cloud build-out): `prior_n` 0.5, half-life
      240 days, junior weight 0.25 is better in every market ([Calibration](model.md#calibration)).
      Practice weight: flat between 0 and 1, 0.5 kept.
- [x] Rider × venue effects: tried (2026-09-28, cloud build-out), no gain on the 43 rounds
      ([Calibration](model.md#calibration)); not built in.
- [x] Time trends within a season (2026-09-28, cloud build-out): a faster-improving-rookie drift
      is worse; none detected beyond what the half-life already tracks
      ([Calibration](model.md#calibration)).

### Done: F1 model

- [x] **Evaluation (F1-1):** `racinglines model compare f1 RUN_A RUN_B` (paired ± 2 SE, log loss,
      reliability bins) and `racinglines model matrix f1`; model-vs-Polymarket Brier for every market kind.
- [x] **Front of the grid (F1-2):** `gridq` closes the gap to the grid-only baseline after qualifying.
- [x] **Pre-practice pricing (F1-2):** `pretrain` (a no-practice finishing model) closes the regression.
- [x] **Chaotic-race tail and correlated DNFs (F1-3):** `tail` is neutral at every stage; not promoted.
- [x] **Regulation reset:** `reset` down-weights earlier seasons' car pace in a new-regulations
      season; `gridq+pretrain+reset` is the most accurate combination and profile A's model.
- [x] Practice pace prior; car shared by teammates (2026-09-26).
- [x] **Monte Carlo seed setting**: sweep and profile setting `seed`, unset = today's fixed seed
      (42), so noise replicates in a search are independent draws (2026-09-28, cloud build-out).
- [x] **Driver layer in a new season (F1-2):** the `rookie` variant fades a finished rookie
      season's teammate comparisons to a quarter. Small gain on win odds before qualifying;
      teammate head-to-heads better in 2026, worse in 2021 ([F1 evaluation](f1-evaluation.md#model-variants-f1-roadmap-f1-2-f1-3)).
      Not promoted (2026-09-28, cloud build-out).
- [x] Price fastest lap, safety car / red flag, rain (F1-3): `models/props.py`,
      `racinglines model props f1`; opt-in kinds for a live book (2026-09-28, cloud). Per-circuit rates
      don't beat the field rate on 2022–2026 ([F1 roadmap](f1-roadmap.md#decision-log)).
- [x] Polymarket sync and repricing on a schedule during race weekends: the recorder re-syncs
      every 30 min; the signal engine prices each stage as its data arrives (every 5 min).

### Done: Market making

- [x] As-of diagnostics, Polymarket minute prices and trade tape, maker replay, tests (Baku).
- [x] Keep `markets record` running through every race weekend (LaunchAgent, F1-0).
- [x] Fetch trades after each session: the signal engine pulls prices and trades for the
      weekend's markets on every run.
- [x] **Maker options (F1-4):** flatten before qualifying, info-timed skew, markout-driven
      widening. None beats the default maker.
- [x] **Stage-aware taker (F1-4):** in the sweep (+$1,874 in-sample on 2026).
- [x] Stage-aware taker out of sample on 2025: **not confirmed** (−$316 on 23 weekends, against +$1,874
      in-sample on 2026; [Market making](market-making.md#strategy-options-f1-roadmap-f1-4)).
- [x] Replay across every race with a tape (2025 and 2026), then tune: the `params-4h` cloud
      search over 1,161 settings combos, judged on both seasons.
- [x] Live watch list: the Markets page lists every open Polymarket F1 market with the profile's
      call and heat; new markets raise alerts (macOS, ntfy, webhook, log).
- [x] **Migrate to CLOB V2** (found in F1-0): `markets/polymarket/trade.py` signs with
      `py-clob-client-v2==1.2.0`; dry runs sign locally (V2 struct, EIP-712 domain 2) and the
      tests recover the signer (2026-09-28, cloud build-out).

### Done: Paper trading

- [x] **Bankroll-aware sizing** and a **deployed-capital cap** in the backtest: sweep settings
      `bankroll` and `max_deployed`, unset by default (2026-09-28, cloud build-out; synthetic tests).
- [x] Fix: an h2h-only market-kinds sweep crashed on 2025 (`KeyError: 'cond'` in the maker replay's
      summary on a weekend with no market of the chosen kinds; 2025 lists no h2h before round 8).
      An empty weekend now summarises to zero (2026-09-28, cloud build-out).

### Done: Live events

- [x] Live tab for both demo users; downhill finals from UCI timing, rank probabilities, maker quotes,
      a simulated private book (1,000 anonymous takers with event budgets), P&L by venue, replay logs.
- [x] Replay on the Live tab once an event is over (timeline, step, play), with the book rebuilt from the
      logged fills; P&L by venue on Positions (2026-09-27).
- [x] A **report command** for any live event (the Whistler report, made repeatable): P&L by update, the
      crowd, the demo taker, the fair-price scorecard (`racinglines live report <spec> --pdf`, 2026-09-29).
- [x] Re-run an event's pricing from its logged raw feed: `racinglines live reprice <spec>` (downhill; every
      raw response re-priced with today's code and the recorded inputs, scored against what was quoted live;
      2026-09-29). On 38 sampled Whistler updates the re-price (v2 throughout) scored a little worse than the
      live quotes (v1, then v2): Brier 0.0216 vs 0.0202 on win, 0.0430 vs 0.0365 on podium.
- [x] Two-sided long-shot quotes (or a per-market loss cap) so the maker doesn't pile up shorts in unlikely
      winners: `[live.quoting] max_loss` and `floor_bid` in `markets/quoting.py` (2026-09-29), both off by default.
      Measured on Baku's rehearsal in the [decision log](f1-live-roadmap.md#11-decision-log).
- [x] Settle the Whistler private book in the database and add it to the demo maker's story: the
      `live_events` table (migration `a3f5c8d1e7b2`) and `racinglines live settle <spec>`; the story dates
      private-book events from it (2026-09-29). Locally: `alembic upgrade head`, then
      `racinglines live settle live/mtb_dh/20260925_mtb.toml`. The final's results still come from the usual
      downhill download and ingest (the event is `in_progress` in the snapshot).

### Done: Exchanges

- [x] **Kalshi connector** (`racinglines/markets/kalshi/`): markets (with their resolution rules), prices,
      trade tape, price history, order books, and post-only orders behind `KALSHI_TRADING_ENABLED`
      (`racinglines markets --exchange kalshi …`). Built on mocked responses only (2026-09-28, cloud):
      the cloud network blocks Kalshi's API. `venue_replay.Kalshi` is its backtest venue; the Polymarket
      paths (sweep, maker replay, season strategy, head-to-head pairs, links export, fetches) now read
      `exchange = 'polymarket'` only, so synced Kalshi links can't leak into them.
- [x] Kalshi against the live read-only API (2026-09-28, locally): `sync --closed`, trades, history and
      books run into a copy of the database. Fixed: series found by ticker (`KXF1*`; "Qualify in Pole
      Position" doesn't say F1), sprints unmodeled (the sprint winner and sprint pole were read as the
      race's), top 10 → `race_top10`, head-to-heads ("Will A beat B in the racing matchup?") with the
      race from the ticker's code, `volume_fp`, `orderbook_fp` (books came back empty), dollar strings in
      historical candlesticks (read as cents), and Kalshi's `/historical` endpoints for markets settled
      before its cutoff (older events came back with no markets). 2026: 15 weekends, 1,847 modeled links.
- [x] **Whistler replay** (2026-09-28): `PrivateBook.from_run` now re-derives Whistler's recorded book fill for
      fill. Two causes, both recorded in the run folder's `replay.json` ([Live events](live-events.md#kept-for-replay)):
      the crowd's rate rule changed mid-event, and two overlapping loops logged polls in the same second.
      Polls now log their rate. The test had always skipped (its module fixture pointed `paths.DATA` at a
      temp folder).
- [x] Kalshi in the maker replay and the demo maker's record (`f1 demo-history --venue kalshi`, PR #10):
      per-ticker grouping, Kalshi's maker fee, `RACINGLINES_KALSHI_VENUE=1` for the board / race / Positions
      pages. Feed differences vs Polymarket: [Kalshi history](kalshi-history.md).
- [x] Kalshi: the first real pull (2025–26, owner's device) replayed and summarised: how many of the maker's
      quotes Kalshi's tape fills, by market kind ([Kalshi history](kalshi-history.md#first-real-run-2026-09-28));
      Kalshi at parity with Polymarket in the app, on by default (`RACINGLINES_KALSHI_VENUE=0` hides it): Positions tiles and
      curve, Strategy switch, `/markets/kalshi`, race-page column and chart, Lab replay
      ([Kalshi history](kalshi-history.md#in-the-app)).

### Done: Engineering

- [x] Web app (`racinglines/web/`): predictions, histories, backtests, Polymarket maker orders.
- [x] Pages and routes that match their names (Markets, Strategy, Positions, My Book, Lab); old
      URLs redirect.
- [x] Demo accounts with a backtest-replay track record, disposable demo sessions, interaction
      logging.
- [x] One settings schema for sweeps, the Lab and cloud searches; cloud searches from a database
      snapshot (an exact replica).
- [x] Pinned `requirements.txt` (pipeline) and `requirements-docs.txt` (mkdocs).
- [x] `pyproject.toml`: `pip install -e .` installs the `racinglines` command.
- [x] `scripts/build_readme.py --check` runs in the pre-push hook, with `mkdocs build --strict`.
- [x] PostgreSQL database instead of re-parsing files every run.
- [x] `.gitignore`: `data/` stays ignored except the allow-listed minimal set for cloud runs.
- [x] Admin overview: the takers' P&L leaves out the `polymarket-takers` replay counterparty and shows it
      on its own line (2026-09-28, cloud build-out).
- [x] JSON API endpoints next to the pages: read-only events and athletes, behind the login,
      off unless `RACINGLINES_JSON_API=1` ([JSON API](webapp.md#json-api), 2026-09-28, cloud).

