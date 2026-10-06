# Roadmap

The one place for what's next, across every sport and track, in priority order. It was rebuilt on
2026-09-28 around the [strategy to the end of 2026](strategy-2026.md): **prove the demo maker and taker
on real markets wherever they are listed**, and fall back to a simulated pool (a private book like
Whistler's) only where no venue lists the event.

Tick items off where they are listed. Finished items move to [Done](#done) at the bottom. Items tagged
**U1**…**U12** are the strategy session's app updates; (F1-n) tags belong to the [F1 roadmap](f1-roadmap.md).

| Plan | What it's for |
|---|---|
| **This page** | The priorities, the race-weekend calendar, owner decisions and every open item |
| [Strategy 2026](strategy-2026.md) | The reasoning: where the demo record stands, how long each strategy takes to prove, event tiers, other sports for 2027 |
| [Paper trading: validation plan](paper-trading.md#validation-plan) | The pre-registered rules every live weekend is judged by |
| [F1 live test (round 16)](f1-live-roadmap.md) | The working plan for 2–4 Oct: build items, runbook, backup plans, decision log |
| [F1 roadmap](f1-roadmap.md) | The F1 phases (F1-0 … F1-9), their ground rules and decision log |
| [Engine roadmap](engine-roadmap.md) | Standard model inputs and outputs for every sport and exchange (E0 … E9), building on [Backtest core](backtest-core.md) |
| [Coverage](coverage.md) | The sport × venue grid (history, backtested strategy, live strategy per cell), the gaps ranked with effort, and the device checks that settle the unverified cells |

## Priorities

<!-- readme: todo-summary -->

**The rule:** real markets first. Events are tiered ([Strategy 2026](strategy-2026.md#event-tiers)):
**T1** a real market is listed, so paper-trade it with frozen profiles; **T2** a real market we don't
model yet, so record its tape; **T3** no market anywhere, so run a simulated pool (private book). T3
proves the pricing, not an edge.

### Demo completion path (2026-10-01)

The live repo is the public `lalligagger/racinglines-public` since 2026-10-01, and **merging to `main` deploys to the
VM** through GitHub Actions (`main-merge-gate`: staging smoke, `vm.sh deploy`, prod smoke; docs-only merges deploy
nothing; CI runs no tests). Deploys carry code only; data and the database change on the VM through scripts and the
admin views. The flow and what lives where: [VM deploy](vm-deploy.md#the-flow).

- **Before asking for a merge (local, CI doesn't run them):** `racinglines check`, `python -m pytest -m "not live"`,
  `mkdocs build --strict`. Golden tests skip without `tests/fixtures/` (not in the public repo).
- **Commit policy:** never leave a commit in an editor; use `git commit -m "..."` or `git commit --amend --no-edit`.
- **Branch/merge flow:** one feature-track branch per sprint, PRs from it, the owner squash-merges with
  `--delete-branch`. A merge is a deploy: batch them, keep them out of live race windows, and back up first for a
  migration.
- **Smoke gate:** valid sign-ins only. If an old wrong-password probe warmed the throttle, wait 15 minutes.

**Where things stand (30 Sep 2026, evening; VM on `306a147`, #95 and #96 merged after it):** NASCAR and MotoGP went
from tape-only listings to sports the production app shows end to end: results, Kalshi markets identified with their
race, a simple-baseline price for NASCAR's next race, and an in-sample demo paper record on Strategy and Positions
(`RACINGLINES_SPORT_STATUS=1` and `RACINGLINES_SPORT_PAPER=1`, both on on the VM). The owner's 3 × 3 soft-launch grid
(F1, NASCAR, MotoGP × Polymarket, Kalshi, OG.com) has 7 of 9 cells filled; MotoGP × Polymarket (no linked markets) and
MotoGP × OG.com (not listed) are empty. **The only held-out-robust strategy is still F1 profile A on Polymarket**, which
has listed no F1 race since 28 Aug. Status per cell: [Sports and exchanges](coverage.md). The full day:
[48-hour report](report-48h.md) (backfills into the web app, then the public repo and CI deploys).

**Where things stood (29 Sep 2026, after the overnight roadmap batch, PRs #23–#45 merged):** U1, U5, U6, U7, U8, U9,
reconcile, the scorecard and the K sweep are built and merged (new behaviour behind switches, off by default). What
is left before round 16 is on the VM and with the owner: the Kalshi recorder (U2), the VM cutover, freezing K, the
loss cap and the tier call. Coverage of every sport × venue is in [Coverage](coverage.md).

**Where things stood (28 Sep 2026):** no F1 race markets are open on either venue. Polymarket has
listed no race since 28 Aug; Kalshi listed 2025 races only 2–4 days out, so it may still list round 16.
The F1 championships are open and deep on both (drivers' ~$38M on Polymarket, ~$9M on Kalshi). Profile
C makes money on Polymarket's tape and loses on Kalshi's.

**P0 · Sprint to the fantasy soft launch (to Thu 8 Oct), in this order.** Work is grouped into feature-track
branches, one PR per track (owner, 2026-09-30); the track is named on each item.

- [ ] **HIGH · Finish CI and the staging environment** (STG-1 to STG-11 in [Staging and CI deploys](#staging-and-ci-deploys)).
      CI deploys merges to `main` since 2026-10-01, but runs no tests, smoke-checks staging rather than the PR, and
      the VM's data has no off-VM copy. First: STG-5 (off-VM data copy), STG-2 (tests in CI), STG-8 (migration gate).
      The fantasy staging rehearsal (STAGE-1, Wed 7 Oct) needs STG-1.
- [ ] **Sign-up** (track `signup`; SEC-1, MAIL-1, ACC-1, ACC-3 from [Fantasy accounts](fantasy-accounts.md)): not
      built. Copilot builds it locally Fri 2 – Sat 3 Oct behind `RACINGLINES_SIGNUP=off`; the `fantasy_schema_v1`
      migration goes to the VM Tue 6 Oct (OWNER-8, backup and sign-off). Then the trading batch, STAGE-1, the go/no-go
      Thu 8 Oct 12:00 PDT and invite-only sign-up at 18:00 PDT ([Fantasy soft launch](fantasy-launch.md)).
- [ ] **Recorders on the VM** (track `recorders`): the Kalshi recorder (U2), a tapes timer for NASCAR's Chase and
      MotoGP's last rounds (U9), an OG.com weekly `trades`/`history`/`books` timer (its API forgets after a month), and
      a forecast refresh after each NASCAR race. New VM units, so each needs a backup and the owner's sign-off.
- [ ] **Round 16 live paper** (2–4 Oct, Sepang): the F1 book opens about 01:30Z Fri 2 Oct; the demo taker (profile
      A) paper-trades from round 16. No deploys around it. Owner calls: loss cap and tier.
- [ ] **Coverage gaps in the 3 × 3** (track `sports-coverage`): MotoGP calendar ingest (upcoming events, so MotoGP gets
      a next-race price; a Mac probe of the calendar endpoint first); Polymarket MotoGP links (tag slug unverified;
      Mac probe first); `RACINGLINES_OG_VENUE=1` on the VM so the OG.com column shows (owner). MotoGP × OG.com stays
      empty: OG.com lists no MotoGP.
- [ ] **Champion replays after deploy** (#95, #96, merged 2026-09-30): deploy, then VM steps 5–7 of
      `handoffs/2026-10-01-season-replays.md` (backup first; not during the round 16 book). They are the first backtest
      of any OG.com cell.
- [ ] **Progress lines** (owner rule, 2026-09-30): every long job, cloud, Mac or VM, prints a flushed progress line
      at least every 5 minutes. The overnight run has per-step lines and a heartbeat since #99; the shared helper for
      searches, replays and demo-history is PR #114 (open).
- [ ] **Report reproducibility** (owner ask, 2026-09-30): REP-1 to REP-7 in PR #114 (a `SOURCES.md` per report,
      one skeleton, `racinglines report build`, pinned inputs, scripted screenshots at 1024 px and 150% zoom).

**P0 · This week (to Thu 1 Oct): be ready to trade round 16 on whichever venue lists it**

- [ ] **U2** Kalshi recorder on the VM ([Exchanges](#exchanges)). Books every 5 minutes (plus OG.com) via `vm.sh record` (`scripts/vm/record_venues.sh`); open: a trades/tape pass and a continuous `markets record` mode.
- [x] **U1** Kalshi in the signal engine, so A and C can paper-trade Kalshi's race markets (PR #34, merged 2026-09-29; [Exchanges](#exchanges)).
- [x] **U6** Championship sleeve, paper only (PR #29, merged; `f1 season-strategy --paper`). Its first live rebalance is round 16's result ([Live events](#live-events)).
- [ ] Freeze A and C and pre-register the rules in [Paper trading](paper-trading.md#validation-plan).
- [ ] Round 16 checkpoints: both venues checked Wed 30 Sep; the tier chosen Thu 1 Oct 18:00 PDT
      (T1 on Kalshi if it lists, otherwise T3, the private book); the book opens Thu 20:30 PDT.
      Plan: [F1 live test](f1-live-roadmap.md).

- [ ] **Fantasy soft launch (owner, 2026-09-29):** invite-gated F1 fantasy trading (F$ paper money only) from
      Thu 8 Oct, Singapore (R17), with the VM reliability work before R16. Plan and owner dates:
      [Fantasy soft launch](fantasy-launch.md); tasks and blocks in the [runbook](fantasy-runbook.md).

**P1 · October (rounds 16–19): first live weekends on real markets**

- [ ] **STG · high priority (owner, 2026-09-30): finish CI and a staging environment.** CI deploys `main` since
      2026-10-01; tests in CI, a real staging deploy, an off-VM data copy, a migration gate and a live-window freeze
      are open: STG-1 to STG-11 in [Staging and CI deploys](#staging-and-ci-deploys).
- [x] **U5** Kalshi sprint markets before Singapore (11 Oct); built in PR #36 behind `RACINGLINES_KALSHI_SPRINTS`, merged. Priced from the race's pole and win odds
      until **U13**, a real sprint model, lands ([F1 model](#f1-model)).
- [ ] **U3** Kalshi maker profile K: swept (PRs #38, #41, merged; K = `gbm`, 2¢, 10-pt filter, 25 shares, $400 volume floor); **freezing it is the owner's call** before the United States GP (25 Oct).
- [x] **U7** Cross-venue disagreement log (PR #35, behind `RACINGLINES_DISAGREE`); **U8** settlement rules for relocated or cancelled races (PR #27, behind `RACINGLINES_CANCELLED_RACE_RULES`). Both merged; the owner's two assumptions for U8 are still to confirm.
- [x] Per-weekend reconciliation (`f1 reconcile`, PR #37) and the pricing scorecard (`f1 scorecard`, PR #28), both merged; run them after every weekend ([Paper trading](#paper-trading)).
- [ ] **U9** Record Kalshi's NASCAR (Chase, finale 8 Nov), MotoGP and IndyCar tapes: code merged (PR #26); first live run on the VM 2026-09-29 and NASCAR/MotoGP tapes pulled in the overnight run (2026-09-30). **Still open: a timer**, so each race is recorded without a hand run ([New sports](#new-sports)); in the soft-launch sprint's `recorders` track.
- [ ] **Parallel track, owner (2026-09-28): the downhill [Data](#data) items are high priority for the next
      cloud session** (Elite/Junior Women, start order, weather). They don't touch the F1 weekends. Most
      need ChronoRace (`prod.chronorace.be`), which the cloud network blocks: allow it first, or run locally.

**P2 · November (rounds 20–22): the sizing review**

- [ ] About 12 Nov, after 4–6 live weekends: sizing decision and a walk-forward with rounds 16–20 added.
- [ ] Qatar (29 Nov) and Abu Dhabi (6 Dec) may be cancelled: settle by each venue's rules (U8).

**P3 · December: close 2026, set up 2027**

- [ ] 2026 season report; walk-forward re-selection of A′, C′ and K′ for 2027, frozen before Australia.
- [ ] **U10** F1 pre-season testing ingest; the `reset` and `gridq+pretrain` decisions for 2027.
- [ ] Decide whether NASCAR joins in 2027, from the recorded tapes and the data-source review.
- [ ] **U12** Move to Google Cloud; the first real V2 order only if the validation rules are met.
- [ ] **U11** Downhill off-season: points validation (the top downhill item), then the rest of data and
      model ([Points validation](#points-validation), [Data](#data), [Model](#model)).

<!-- /readme -->

## Race weekends to 31 December

One row per event, in date order. The full table with contingencies is in
[Strategy 2026](strategy-2026.md#week-by-week). Every F1 weekend also runs the championship sleeve after
the race, and the [weekend routine](#weekend-routine).

- [ ] **2–4 Oct · F1 R16, Bahrain GP at Sepang.** T1 on Kalshi if listed (A, and C as a control);
      otherwise T3 (`live/f1/2026-16.toml`). Optional: record SignalR during FP1. Mon 5 Oct: settle and
      reconcile, and report with a fair-price scorecard ([F1 live test](f1-live-roadmap.md#9-after-the-weekend-mon-5-oct)).
- [ ] **9–11 Oct · F1 R17, Singapore (sprint).** T1 on Kalshi if listed (needs U5); otherwise T3
      (`live/f1/2026-17.toml`).
- [ ] **October weekends · NASCAR Chase** (Las Vegas, Charlotte Roval, Phoenix, Talladega, Martinsville).
      T2: record every Kalshi tape (U9).
- [ ] **23–25 Oct · F1 R18, United States GP.** T1: A, C and K on Kalshi, and Polymarket if it's back.
- [ ] **30 Oct – 1 Nov · F1 R19, Mexico City.** T1.
- [ ] **6–8 Nov · F1 R20, São Paulo.** T1. **NASCAR finale, Homestead (8 Nov)** and **MotoGP Qatar**: T2.
- [ ] **~12 Nov · Sizing review** ([Paper trading](#paper-trading)).
- [ ] **20–22 Nov · F1 R21, Las Vegas (Saturday race).** T1; check the night-time stage cut-offs.
      **MotoGP Portugal**: T2.
- [ ] **27–29 Nov · F1 R22, Qatar.** T1 once U8 is in; may be cancelled. **MotoGP Valencia (finale)**: T2.
- [ ] **4–6 Dec · F1 R23, Abu Dhabi.** T1; championships settle. About 53% on Polymarket that it takes place.

**If Polymarket lists again:** A and C go live there at once, and it becomes the main record; Kalshi
carries on alongside. **If neither venue lists F1 races:** every F1 weekend is T3 and the goal for 2026
becomes proving the pricing (the scorecard), plus the championship sleeve and the disagreement log on
the markets that are open. There are no downhill events left in 2026.

### Weekend routine

For every F1 weekend, T1 or T3:

- [ ] Wed: check Kalshi and Polymarket for the race's markets; confirm they link to the event (not `unmodeled`).
- [ ] Thu 18:00 PDT (or the equivalent before FP1): pick the tier and log it in the decision log.
- [ ] Race weekend: the signal engine (T1) or the live engine (T3) runs unattended; no code changes except logged fixes.
- [ ] After the race: settle; run the championship sleeve.
- [ ] Monday: the reconciliation (live vs replay, T1) and the pricing scorecard (T1 and T3); flag a
      weekend outside the [validation rules](paper-trading.md#validation-plan) and explain it before the next.

## Owner decisions

| Decision | When | Recommendation |
|---|---|---|
| Loss cap for round 16 (`max_loss = 500` in `live/f1/2026-16.toml`) | Before 1 Oct | Owner's call ([decision log](f1-live-roadmap.md#11-decision-log)) |
| Freeze A and C as they are until 31 Dec | Now | Yes |
| Profile A takes `rookie` | Now | No: keep A frozen |
| Round 16: T1 on Kalshi or T3 | Thu 1 Oct 18:00 PDT | T1 if Kalshi lists |
| Sizing rule | ~12 Nov | After 4–6 live weekends on real markets |
| Add NASCAR for 2027 | December | Only if the tapes and data hold up |
| Promote `gridq+pretrain`; keep `reset` for 2027 | December | Decide on the walk-forward |
| `--unraced-format last` as the downhill default | Any time | See [Model](#model) |
| Freeze Kalshi maker profile K (+$490 / +$659, [Kalshi history](kalshi-history.md#profile-k)) | Before 25 Oct | Yes, then no more tuning on Kalshi's 2025–26 tape |
| U8 rules for a cancelled race: Polymarket 50/50 on head-to-heads, Kalshi NO versus void | Before Qatar (29 Nov) | Confirm against each venue's rules text |
| Greenlight the coverage backlog: tape-only UCI road cycling schema (S), Polymarket tapes for NASCAR, MotoGP and IndyCar (M) | Any time | Cycling first: cheapest, and Kalshi holds the history |
| Fable for High-tier work in CLAUDE.md, against the no-Fable rule | Settled 2026-09-30 | No Fable anywhere until the owner asks for a project-notes update |
| Go on **STG-1 to STG-11**; first STG-5 (off-VM data copy: VM service account write access to the bucket), STG-2 (tests in CI), STG-8 (migration gate). Also: fixtures in git or bucket (STG-7), staging on the same VM or its own, keyless GCP auth or key, Cloudflare Access or password (STG-1) | Now: HIGH | Yes; STG-5 first: today the VM's disk is the only copy |
| Next engine plan task after T5 | Any time | T2 |
| Turn on `RACINGLINES_OG_VENUE=1` on the VM (the OG.com column) | Before the soft launch | Yes: read-only, fair-price indicator only |
| Kalshi bid/ask candles re-pull (backup first) | Before any Kalshi taker result counts | Approved 2026-10-05: automate it on the VM |
| Sign-off for new VM timers: Kalshi recorder (U2), tapes (U9), OG.com recorder, NASCAR forecast refresh | Before round 17 | Yes, one at a time, each with a backup |
| Price-column migration and the audit scorecard (engine plan) | After round 16 | Owner's call; migration needs a backup and sign-off |
| Replay race spread for NASCAR (2.0 places vs a measured ~7) | Before any NASCAR result is read as edge | Owner's call, with a decision-log entry |
| Close draft #97 (superseded by #110) | Any time | Yes |
| History purge for data off GitHub (force-push) | Last stage | Needs the owner's spoken OK in the same turn |
| Open-Meteo's free API is non-commercial only ([Weather forecasts](weather.md)): paid plan, or MET Norway (free for commercial use, not built) | Before billing goes live (G3, 2027) | Stay on the free tier while there is no revenue; decide with the first paid tier |
| Odds presentation names in the sportsbook schema: `decimal`, `american`, `fractional`, `cents` (Kalshi), `dollars` (Polymarket, OG.com), `prob` ([Sportsbook schema](sportsbook/index.md)) | After PR #69 merges | Owner checks the names; a rename is one line in `racinglines/books/schema.py` plus the docs table |
| Fantasy soft launch decisions DEC-1 to DEC-23 ([Fantasy soft launch](fantasy-launch.md#decisions)) | Batch A Wed 30 Sep 18:00 PDT; B Mon 5 Oct; C Wed 7 Oct; go/no-go Thu 8 Oct 12:00 PDT | Per the [runbook's decision table](fantasy-runbook.md#decisions) |

## Exchanges

Phase [F1-9](f1-roadmap.md#f1-9-more-exchanges-kalshi-others), pulled forward: Kalshi is the likeliest
venue with live F1 race markets this year.

- [ ] **U2 · P0 · Kalshi recorder on the VM.** Schedule `markets --exchange kalshi` sync (every 30 min on
      race weekends, every 6 h otherwise), plus trades, books and history for the open F1 race and
      championship markets, next to the Polymarket recorder (`deploy/` systemd units,
      [VM deploy](vm-deploy.md)). First confirm the GCE VM can reach Kalshi's API (the cloud sandbox can't).
      *Done when:* a race weekend's Kalshi books and trades land in the database and
      `data/archive/markets/kalshi/` with nobody running a command.
- [x] **U1 · P0 · Kalshi in the signal engine** (PR #34, merged 2026-09-29) (F1-9's "done when"). `pipelines/signals.py`,
      `taker_weekend` and `maker_replay` read `exchange='kalshi'` markets for a profile whose new `venue`
      setting says so (default `polymarket`, optional, left out of `settings_key` while unset). Signals
      carry `detail.venue='kalshi'` and positions `venue='kalshi'`. Group by market ticker (`token_id`),
      never by `condition_id`; apply `KALSHI_MAKER_FEE`; the liquidity filter is per market. Polymarket
      profiles unchanged. The sweep reads Kalshi the same way.
      *Done when:* a replay of 2026 round 15 through the engine on Kalshi matches `f1 demo-history
      --venue kalshi` for C to the cent, and A's Kalshi taker replay matches the sweep's trades
      (`scripts/signals_parity.py --venue kalshi`). No order is sent; `KALSHI_TRADING_ENABLED` stays unset.
- [x] **U5 · P1 · Kalshi sprint markets** (PR #36, merged, behind `RACINGLINES_KALSHI_SPRINTS`). Map sprint winner and sprint pole (`KXF1*` sprint tickers,
      `unmodeled` today) to the sprint stages (after SQ, after Sprint). Check on the Dutch GP (round 12).
      *Done when:* Singapore's Kalshi sprint markets sync with a model price.
- [x] **U7 · P1 · Cross-venue disagreement log** (PR #35, merged, behind `RACINGLINES_DISAGREE`; Polymarket and Kalshi only, OG.com not joined yet). For each F1 outcome linked on both venues (race and
      championship), keep both mids, both fee-adjusted edges and the top of each book at every recorder
      pass (a table or a view over `market_price_history`), with a report
      (`racinglines markets disagree --event …`) and a panel on the Markets page.
      *Done when:* the report lists the gaps above fees for the championship markets, day by day.
- [ ] **OG.com follow-ups (new, from [Coverage](coverage.md#ogcom)):** (a) a VM recorder timer running `trades`, `history` and `books` at least weekly (S, the API forgets after about a month); (b) confirm the $0.02 fee in OG.com's fee schedule (S); (c) per-Grand-Prix `[[rules]]` in `exchanges/og.toml` once a live race market is seen (S); (d) join OG.com to the U7 log (S–M). (e) done: a `/markets/og` page and a generic per-schema-exchange route, plus `/markets/tapes` (PR #49; found by the 2026-09-29 spot-check, [Coverage](coverage.md#the-gaps-ranked)).
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
      and into 2027. Built and scheduled for Polymarket (the signal engine); Kalshi needs U1.
- [x] **U3 · P1 · Kalshi maker profile K** (sweep done; freezing is the owner's call). A sweep of the maker's settings on Kalshi's 2025–26 tape
      (spread, `max_disagree`, `size`, model `gbm` / `gridq+pretrain`, per-market `min_volume_24h`),
      judged on both seasons as `params-4h` was. Save the winner as the Lab candidate "K · Kalshi maker",
      assigned as the demo maker's Kalshi profile.
      *Done when:* K is frozen before round 18, with its 2025 and 2026 Kalshi replay P&L recorded in
      [Kalshi history](kalshi-history.md). **Result (PRs #38, #41, corrected 2026-09-29):** K = `gbm`, 2¢ quotes, 10-point
      disagreement filter, 25 shares, $400 24-hour volume floor: **+$490 (2026), +$659 (2025)**, at 16,000 simulations
      +$453 / +$741, against profile C's −$119 / +$510. The first 2025 figure (+$855) missed Imola 2025, which only
      Kalshi listed (−$195). Owner (2026-10-05): K's settings stay tunable; log each change in the decision log and keep its live record per settings version.
- [x] **P1 · Per-weekend reconciliation** (PR #37, merged). `racinglines f1 reconcile --event 2026-NN --profile X --venue V`:
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
- [ ] **P2 · Stale line in `docs/coverage.md`** (owner, 2026-10-05). Its summary says Polymarket has listed no F1
      race since 28 Aug 2026, but the Malaysia audit (round 16, 2026-10-04) linked 139 Polymarket tokens, titled
      "Bahrain Grand Prix". Check which recent rounds Polymarket listed and correct the summary and the grid.
- [ ] **P2 · Sizing review (~12 Nov),** after 4–6 live weekends on real markets (T3 weekends don't count):
      walk-forward re-run of A, A-lite, C, K, B (#06) and A′ (#08) with rounds 16–20 added, then a sizing
      rule from `bankroll` / `max_deployed` (owner's call, e.g. A-lite → A).
- [ ] Use it live: the signal engine sizes from the account's balance and deployed capital, once the review
      picks a rule. Later, fractional sizing once recorded depth supports it.

## Live events

How it works: [Live events](live-events.md). First run: the Whistler downhill final, 27 Sep 2026. Live
events are T3 unless a venue lists the event.

- [ ] **F1 live test, round 16 (Bahrain GP at Sepang, 2–4 Oct 2026):** a mock private book on all of
      Polymarket's usual race markets, updated at session ends. Runs as T3 unless Kalshi lists (then it's a
      side demo next to the Kalshi paper trading). Build items B0–B8 and the runbook:
      [F1 live test](f1-live-roadmap.md).
- [ ] Singapore (round 17, sprint weekend, 11 Oct): the same run if no venue lists it. Code-ready: launch
      spec `live/f1/2026-17.toml`; the sprint stages rehearsed on the Dutch GP (`live/f1/2026-12.toml`).
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

## F1 model

Phased plan and ground rules: [F1 roadmap](f1-roadmap.md).

- [ ] **P2 · Weather-aware position-model variant `gridq+pretrain+reset-WX`** (owner, 2026-10-06: "later branch", not
      the weather PR). The disruption mixture (more noise and retirements in disrupted races) weighted by the race's
      forecast rain probability (`weather/wet.p_wet_series`, lead 5 days) instead of history alone; then the strategies on it
      (`A-WX` against `A`) in their own sweep under the promotion rule. Until then a `-WX` strategy name would be
      byte-for-byte its baseline: nothing weather-aware feeds win, podium, h2h, constructor or pole. Decided after the
      5-day forecast backtest found the forecast beats the circuit history for rain, is neutral for red flags and adds
      nothing for safety car or DNF ([Weather forecasts](weather.md), [decision log](f1-roadmap.md#decision-log)).
- [ ] **U13 · P2 · Sprint-race pricing model.** For now (U5, PR #36) Kalshi's sprint winner and sprint pole
      markets price from the race's win and pole probabilities as a stand-in; the owner approved that for
      Singapore (2026-09-29). Simulate the sprint itself: sprint qualifying as its own stage, a shorter race
      (about a third of the distance: less tyre and pit variance, fewer retirements), and write
      `extra.sprint_pole_prob` / `extra.sprint_win_prob` on the stage runs, which the pricing already reads
      first. Backtest on the 2025–26 sprint weekends against Kalshi's and Polymarket's sprint prices.
      *Done when:* sprint markets price from the sprint simulation and beat the race-odds stand-in on the
      backtest.
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
      whether a profile takes it ([decision log](f1-roadmap.md#decision-log)).

## New sports

F1 (large audience, deep markets) and UCI downhill (niche, no exchange markets) are the two endpoints.
Candidates between them: NASCAR, MotoGP, WEC, IndyCar, Formula E, road-cycling classics and grand tours,
XC/enduro, alpine skiing. Rank by audience, data availability and exchange listings; no grassroots or
local-league plans. As of 2026-09 the ranking is led by exchange depth:
[Strategy 2026](strategy-2026.md#other-racing-sports-for-2027).

- [x] **U9 · P1 · Tape recording for other sports** (code, PR #26, merged). **First live run on the VM, 2026-09-29:** Kalshi NASCAR 13,599 links and 1.69M trades, MotoGP 322 links and 12k trades, IndyCar 1,374 links and 167k trades, all `unmodeled` ([Data changes](data-changes.md)). NASCAR and MotoGP tapes were pulled again for the replays in the overnight VM run (2026-09-30). A tapes timer is still open. Generalise the Kalshi sync to named series: NASCAR
      Cup (`KXNASCAR*`, race and champion), MotoGP (`KXMOTOGP*`), IndyCar (`KXINDYCAR*`). Each under its own
      competition (a `sports/<code>.toml` entry with no model), links `unmodeled`, with prices, trades and
      books archived per exchange.
      *Done when:* the NASCAR finale (Homestead, 8 Nov) and MotoGP's Qatar–Valencia rounds are recorded
      from listing to settlement.
- [x] **Polymarket tapes for NASCAR, MotoGP and IndyCar** (PR #51). The Polymarket sync now takes a named tape-only
      sport (`[markets.polymarket] tags` in `sports/<code>.toml`, links `unmodeled`, additive: no reset or delete path).
      **The tag slugs are unverified against the live Gamma API**; `sync --tags SLUG …` overrides them, so the first VM
      run can correct one without a code change. Not yet run on the VM ([Coverage](coverage.md#the-gaps-ranked)).
- [x] **UCI road cycling, tape only** (schema, PR #50): `sports/road_cycling.toml` (competition `uci_road_wt`, Kalshi
      `KXCYCLING*`), plus `le_mans.toml` and `sailgp.toml` (Kalshi, and SailGP on OG.com). Not yet run on the VM:
      `markets --exchange kalshi --sport road_cycling sync --closed` pulls the 2026 grand tours Kalshi still serves. A
      model is a 2027 question ([Sports and exchanges](coverage.md#the-status-matrix)).
### MotoGP prediction model track

The database and API plumbing are in place and the source gate is complete: the public MotoGP results API is verified for season/event/standings/classification data, and the first pass stays within that contract. **Status 2026-09-30:** `sports/motogp.toml` now has `model_family = "position_sim"` and `pricing_model = MotoGPRaceChallenger` (a result-only form model, Sunday race only), the taker replay runs it (`racinglines motogp replay`, #82), and the board's race-win column is on by default (owner, 2026-09-30). That happened **before M5's gate was met**: the model has not been compared with a naive baseline, the Kalshi replay has no held-out season (2025 lists no MotoGP race markets) and its ranking has not been read. Read its prices as a baseline, not an edge ([Sports and exchanges](coverage.md#model-status-by-sport)).

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
      applied to the stored links by `racinglines nascar link`). Still open: the Polymarket tag slugs above.
- [x] **NASCAR and MotoGP in the app** (#108–#112, deployed 2026-09-30): the Markets "Every sport: status" table
      (`RACINGLINES_SPORT_STATUS=1`), NASCAR and MotoGP sections with replay-save prices, next races and recent
      results, sport filters on the strategy pages, and the demo accounts' NASCAR and MotoGP paper rows labelled
      "demo replay, in-sample" (`RACINGLINES_SPORT_PAPER=1`, `nascar|motogp demo-history`, run on the VM by
      `vm.sh demo`). Kalshi: NASCAR Pro −$278.31 (2025) / +$6,525.45 (2026), Basic −$357.23 / +$2,657.23; MotoGP
      2026 Pro +$31.25, Basic +$7.70. In-sample: the settings were picked on the same seasons.
- [x] **Next-race forecasts** (#112): `racinglines nascar forecast` stored run #9068 (South Point 400); the board and
      race pages show its fair price. Undo: `racinglines nascar forecast --undo 9068`.
- [ ] **Forecast refresh after each race** (track `recorders`): today a forecast is stored once, by hand, so NASCAR's
      price goes stale after each Chase race. A VM timer after results land; sign-off needed.
- [ ] **MotoGP calendar ingest** (track `sports-coverage`): upcoming events from the MotoGP API, so MotoGP gets a
      next-race forecast and a status row with a next race. A Mac probe of the calendar endpoint first (standing
      practice in CLAUDE.md). Effort S–M.
- [ ] **Polymarket MotoGP links** (track `sports-coverage`): the demo backfill stored nothing for MotoGP on Polymarket,
      probably because no market is linked (unconfirmed). Probe the tag slug from the Mac, then sync with
      `--tags SLUG` and link. Read back the Polymarket NASCAR demo totals (`vm.sh demo status`) at the same time.
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
- [x] **NASCAR results adapter** (`racinglines nascar fetch | ingest`; the feeds probed 2026-09-29, findings in
      [Data](data.md#nascar-content-feeds-verified-2026-09-29)). **Done on the VM 2026-09-30** (backup first): 408 Cup events 2016–2026 ingested and 7,544 Kalshi links identified with a race ([Data changes](data-changes.md)). The original plan:
      database backup, then Cup 2017–2026 on the VM with a `data_changes` entry (three races were fetched on the Mac
      on 2026-09-29 and the pit feed read: real stops, `nascar_pit_data_2026_5628.json`). Built since: scheduled events for upcoming races and the driver/race resolver (`sources/nascar/identity.py`);
      **the market-link pass** (`sources/nascar/links.py`, `racinglines nascar link`, and inside the Kalshi, Polymarket and OG.com syncs): race by name within its season,
      driver, contract kind, and a `cup | xfinity | trucks` tag, with `prediction` left `unmodeled` (tested on the real Kalshi and Polymarket listings).
      Next, in order (VM, owner): full pull and `ingest` after a backup; then `link` dry run, read the unresolved list, `link --apply --backup FILE`; then the
      readiness audit. OG.com's NASCAR contracts and Kalshi head-to-heads were sampled from the Mac (PR #68) and the pass handles both.
- [ ] **P3 · NASCAR for 2027?** Decide from the recorded Chase tapes (volume, spread, how often markets
      trade) and the data review. If yes: a first model in Jan–Feb, paper-traded from the 2027 Daytona 500.
- [ ] MotoGP: its qualifying / sprint / race weekend maps onto the F1 adapter; sprints are not ingested yet, so the
      model is Sunday-race only and the champion is quote only. Thin on Kalshi (champion ~$20k); revisit if the tapes show depth.
- [ ] Skip horse racing: the Interstate Horseracing Act keeps it off Kalshi and Polymarket.

## Points validation

The points tables in `racinglines/models/timed_runs/` (`FINAL_POINTS`, `QUAL_POINTS`,
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
- [ ] **Reconcile:** `racinglines mtb_dh points check --season 2026 --through-round 7
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
- [ ] Ingest on a schedule: download, then `racinglines mtb_dh ingest` for new rounds.
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
- [ ] **STG-5 · an off-VM copy of the VM's data.** Today the VM's disk is the only copy of the newest database,
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

Finished items, moved here from the sections above on 2026-09-28, with the dates they were done.

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
      era and round kind), and have the model read them from there: `racinglines mtb_dh points
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

- [x] **Evaluation (F1-1):** `racinglines f1 compare RUN_A RUN_B` (paired ± 2 SE, log loss,
      reliability bins) and `racinglines f1 matrix`; model-vs-Polymarket Brier for every market kind.
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
- [x] Price fastest lap, safety car / red flag, rain (F1-3): `models/position_sim/props.py`,
      `racinglines f1 props`; opt-in kinds for a live book (2026-09-28, cloud). Per-circuit rates
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

