# Overnight VM run: plan

Status: **plan** (2026-09-30). Nothing here has run. It folds the F1 taker re-sweep (PR #85), the replay tape work and
Mac Stage 1 (PR #84), the data-off-GitHub stages (PR #83, [plan](data-off-github.md)) and the standing backup and probe
rules into one run on the VM. The command sequence is in the Copilot handoff
`handoffs/2026-09-30-overnight-vm-run.md` in the project files (local only, never committed).

**The owner's asks (2026-09-30):** a broad settings sweep, then a 16,000-simulation deep run on the top combos; F1 is
the golden baseline; downhill and any sport without active markets since 2024 are out; NASCAR goes now and MotoGP once
its diagnostic lands. **The soft launch and fantasy test need a 3 sports × 3 exchanges matrix with no all-zero row or
column.** Long runs happen on the VM, for the record, after a small Mac/Copilot spot check; cloud sessions only write
code, plans and handoffs.

## The 3 × 3 matrix

Sports F1, NASCAR, MotoGP; exchanges Polymarket, Kalshi, OG.com. The other sports with markets (IndyCar on Kalshi,
SailGP on OG.com, Le Mans) have no pricing model, and downhill has no exchange, so they are out.

A cell counts at one of three levels:
- **Replayed prices:** the exchange's recorded prices replayed with a P&L, without our model (PR #88's buy-all, a
  debug check that the tape is real and settles).
- **Priced:** our model prices at least one listed market on that exchange against a stored exchange price. This is
  what a fantasy pick needs.
- **Backtested:** a replay or sweep over past races found tradeable markets and reports P&L.

| | Polymarket | Kalshi | OG.com |
|---|---|---|---|
| **F1** | **Backtested.** Taker profile A, +$1,389 (2026) and +$1,432 (2025) at 16k (PR #85) | **Backtested (maker).** Profile K. The taker replay is not usable until Kalshi candles carry bid/ask (PR #85, section 3) | **Priced.** Drivers' and constructors' champion: `og fair` printed 20 F1 rows on the VM (2026-09-29). Shown in the app only with `RACINGLINES_OG_VENUE=1`, still off on the VM. No backtest yet. **Replayed prices tonight** with PR #88's buy-all on the VM's recorded OG.com prices |
| **NASCAR** | **0.** 36 markets priced, 0 tradeable at a $0 floor (Mac Stage 1). Diagnostic 1d pending; likely a partial listing failing the coherence check | **Backtested, one race.** 178 tradeable at $0, 56 at $50 (Mac Stage 1, **before PR #89**, so some of those prices may be dead-book 0.50 midpoints). Needs the full tape pulled after #89 and the candle fix (tonight), and the spike check | **Replayed prices tonight** (PR #88's buy-all on the 17 Cup Champion contracts). Not priced by our model: there is no season-champion model for NASCAR |
| **MotoGP** | **0.** Never synced | **Priced, tradeable with PR #89.** 22 priced and 0 tradeable before it. With #89 (dead-book 0.50 midpoints rejected, UUID rider ids kept), the Mac's replay shows 13 races, 288 priced, 186 tradeable. The 3 races still untradeable (USA, RSM, AUT) fail real liquidity or coherence gates | **0.** OG.com lists no MotoGP that we know of (not in `exchanges/og.toml`, never probed) |

**Where it stands:** the MotoGP row is zero on the VM until PR #89 is merged and deployed. With it, MotoGP × Kalshi is tradeable on the Mac. After tonight, OG.com has two cells with replayed prices (F1 and NASCAR) and one priced by our model (F1). The OG.com column is zero for backtests, but F1 is priced there, so
at the priced level the column is not zero once the venue switch is on.

**The cheapest path to no zero row or column (the critical path):**

| # | Cell | Level | What it takes | Where |
|---|---|---|---|---|
| M1 | F1 × Polymarket | backtested | done; tonight's golden check re-confirms it on the VM's data | VM, tonight |
| M2 | NASCAR × Kalshi | backtested | full tape pull, replay, spike check, settings grid | VM, tonight |
| M3 | F1 × OG.com | priced | turn on `RACINGLINES_OG_VENUE=1` on the VM (display switch, not a trading flag), restart, smoke | VM, owner's word |
| M4 | MotoGP × Kalshi | backtested | PR #89 and the candle fix merged and deployed, then tonight's `replay` with `SPORTS="nascar motogp"` (conditional: the dry run must show `motogp_wc` races and a Kalshi probe above 0) | VM, tonight if #89 is in |

M1 to M4 give every row and every column at least one cell. After that, in order of cost:

| # | Cell | What it takes |
|---|---|---|
| N1 | NASCAR × Polymarket | the 1d diagnostic's NASCAR Polymarket line; if it is a partial listing, no coherence check for partial groups on that exchange (a schema line), then a re-run of the replay |
| N2 | MotoGP × Polymarket | the `replay` mode syncs MotoGP's Polymarket links when MotoGP is in `SPORTS`; then the same checks |
| N3 | F1 × OG.com, backtested | a Mac/Copilot probe of how far back OG.com's `get-ticker-histories` goes for the F1 champion contracts. If it covers months, the championship replay (`f1 season-strategy`) needs OG.com as a venue (code PR) |
| N4 | F1 × Kalshi taker | re-pull Kalshi F1 candles with bid/ask on the Mac and fill the taker at the ask (PR #85, what's next) |
| N5 | NASCAR × OG.com | a Cup Champion model (playoff format): the largest item, not needed for the minimum |

## What runs on the VM

`scripts/vm/overnight.sh`, as a transient systemd unit (`rl-overnight`), in one of five modes. It replaces the
`rl-backfill` script of the backfill handoff (revision 3) and drops its downhill walk-forward.

| Mode | Writes | What |
|---|---|---|
| `dry` | nothing | cores, memory, disk; table counts; each sport's tape probe and last-race replay; **the F1 golden check** (profile A on 2026 at 4k, not saved) |
| `f1` | sweep runs, walk-forward | backup; the broad sweep (`sweeps/overnight-vm.toml`); `search-report`; `scripts/vm/promote_16k.py` appends the top 10 plus profile A and the default settings at 16k; the 16k confirmations; `search-report` again; the F1 walk-forward and the default F1 sweeps saved (as the backfill's `full` did) |
| `replay` | links, tape, replay runs | backup; for each of `SPORTS` (default NASCAR and MotoGP together): Kalshi and Polymarket link syncs for 2025 and 2026 (closed included); tape pull and replay (Kalshi must be tradeable or it stops); the spike check; the replay saves; a read-only settings grid and its top 3 at 16k; then OG.com's read-only buy-all for F1 and NASCAR (PR #88) |
| `story` | 16 sweep runs, the taker's demo backfill | backup; evidence sweeps; a gate that stops on a different pick; the taker's backfill rebuilt ([below](#demo-taker-walk-forward-story)) |
| `all` | all three | `f1`, then `replay`, then `story`. Each starts only if the one before finished |

Every writing mode backs up first and checks the dump's trailer, logs to `data/runs/logs/overnight-<mode>-<UTC>.log`,
leaves an `overnight-<mode>.done` or `.failed` marker, adds a `data_changes` note naming the backup, and refuses to start
while a `racinglines-live-*` unit is active. Round 16's book opens Thu 1 Oct 20:30 PDT: the run must start early enough
to end before then.

### F1: broad sweep, then 16k

F1 is the golden baseline, so it goes first and is checked before anything else is read. The sweep numbers on the VM
won't match the cloud sweep to the cent, because the VM's database ids differ from the Mac snapshot's
([data off GitHub](data-off-github.md#target)). The pass is **profile A's 2026 update P&L within ±$400 of +$1,243**
(the measured noise floor for the update taker, PR #85 section 2). If it misses, stop and compare the VM's F1 market
links with the Mac's before trusting anything else.

The queue is **106 jobs at 4,000 simulations**, Polymarket only, 2026 the target and 2025 held out. The size is
48 settings × 2 seasons, plus profile A's 2 extra seeds × 2 seasons, plus 6 default-settings runs (3 seeds × 2 seasons).
Jobs run in this order:

| Group | Settings | What it asks |
|---|---:|---|
| golden | 1 (3 seeds) | Does A reproduce on the VM, and what is the noise floor on this data? |
| model | 20 | A with one model setting changed: half-life 60/90/180/240 days, reset weight 0/0.1/0.5, driver shrinkage 1/6, team shrinkage 1/4, slope shrinkage 3/12, teammate finish correlation 0.5/1.5, practice prior off, track features off, teammate noise off, plus the `tail` and `rookie` variants on A |
| taker | 12 | A with one taker setting changed: min edge 0.07/0.09/0.12/0.15, head-to-head edge 0.03/0.08/none, volume floor $25/$100/$400, stage-aware stop points (after FP2 and qualifying; after qualifying only) |
| cross | 15 | model (`gridq+pretrain`, `gbm`, A's) × half-life 90/180 × edge 0.08/0.12, and A's taker settings on `baseline`, `gbm`, `gridq+pretrain` |

What is left out on purpose: a volume floor of 0 (untradeable, PR #85), stake changes (sizing, not edge), Kalshi takers
(invalid until bid/ask), and PR #81's switches (inert on history or inside the noise). The queue stops starting jobs
after 3 hours, so a slow night cuts the cross group first. `promote_16k.py` then takes the 10 best distinct settings
from `candidates.toml`, keeps only Polymarket with a volume floor of at least $25, and queues each for both seasons at
16,000 simulations with profile A and the default settings: at most 24 jobs.

**Decision rule for the morning:** a setting replaces profile A only if it is ahead in both seasons at 16k by more than
the noise floor measured tonight. Otherwise A stays, and the top 10 feed the Pro list as PR #85 set up. Either way the
change gets a decision-log entry in `docs/f1-roadmap.md` before it is treated as final.

### NASCAR: tape, replay, grid

The replay settings in `sports/nascar.toml` are a priori, none tuned. The grid is **16 read-only runs** on Kalshi:
min edge 0.05/0.08/0.10/0.15 × volume floor $50/$200 × seasons 2026 and 2025. It is ranked by the worse season's update
P&L after Kalshi's taker fee (`scripts/vm/replay_grid.py rank`). The top 3 re-run at 16,000 simulations (the NASCAR
model's default is 2,000): **6 more runs**. The grid stops starting runs after 3 hours (`GRID_HOURS`).

**Read NASCAR's P&L only after the spike check.** Kalshi's stored price is the candle's last trade, and that is what
ruled out Kalshi's F1 taker replay (1.67% of points more than 15 points off their rolling median, against 0.06% on
Polymarket). `replay_grid.py spikes nascar kalshi` prints the same share for NASCAR, and the share of prices at exactly 0.50 (the
dead-book midpoint PR #89 stops storing; a pull before #89 may have left some), with a verdict. It runs after tonight's
pull, so on #89's prices:
- **clean:** the P&L can be read;
- **in between:** read the per-race table, not the total;
- **spiky:** the P&L is indicative only, and NASCAR waits for the bid/ask re-pull (N4's method) before any Pro pick
  uses it.

### Demo taker walk-forward story

The owner asked (2026-09-30) for the demo taker's history to follow the walk-forward story of the taker re-sweep
(PR #85, section 6) instead of running profile A with hindsight from the first race of 2025. The decision rule and
decision points are the demo maker's (`pipelines/story.py`), on the round-1 pool fixed before any result, so each phase
is out of sample for the decision that picked it:

| Phase | Weekends | Profile | Why it was picked | Sweep P&L then (out of sample) | A over the same weekends (in sample) |
|---|---|---|---|---:|---|
| TW1 | 2025 rounds 1-8 | defaults: baseline model, update | no evidence yet | −$129 | part of A's 2025 +$1,363 |
| TW2 | 2025 rounds 9-24 | gridq+pretrain+reset, min edge 0.10, update | P&L leader after round 8 (+$327) | +$870 | part of A's 2025 +$1,363 |
| TW2 | 2026 | the same (kept after round 16 and before 2026) | still the leader, then most consistent within $400 | +$1,099 | A's 2026 +$1,243 |

The sweep P&L is at the default stake (4k). The demo taker account follows about a third of its picks
(`profiles.DEMO_FOLLOW`), so its paper P&L is roughly a third of those figures. The app labels every backfilled row
as a backtest replay, and the rows stay labelled demo. The story never picks a blend (section 6), so the blend stays
a Pro option only.

**How it runs:** the story's code is **PR #87** (the taker's `HISTORY` becomes TW1 then TW2, and the Strategy page
shows the taker's decisions with their evidence). It must be merged and deployed before this step; no migration.
`story` mode runs after the NASCAR part, in this order, and leaves an `overnight-story.done` or `.failed` marker:

1. **Backup:** `data/backups/db/racinglines-before-demo-taker-story-<UTC>.sql.gz`, trailer checked.
2. **Evidence sweeps:** `racinglines f1 search sweeps/demo-taker-story.toml` (2025, the 16 settings of the story's
   pool, 2 at a time, about 20 to 40 minutes), logged to `data/runs/search/demo-taker-story.log`. It must end with
   `search: finished (16 done)`. They are saved runs (model_runs), so no bucket stage runs at the same time.
3. **Gate, an explicit stop:** `scripts/vm/story_gate.py` runs `story.decisions(conn, taker=True)` and must see the
   defaults before round 1, then `update · gridq+pretrain+reset · min_edge=0.1` after 2025 round 8, kept twice, with
   32 candidates at the last decision. Anything else, or 0 candidates, stops the mode with nothing reset.
4. **Rebuild:** `racinglines f1 demo-history --reset --user taker`. **Always with `--user taker`.** Never a bare
   `--reset`, and never `f1 demo-history --venue polymarket --reset` without it: that would also delete the demo
   maker's Polymarket record, which may not rebuild on the VM.
5. **Log:** a `data_changes` row naming the backup; the thread adds the `docs/data-changes.md` line in the morning.

## Order against the other work

1. **Bucket stages 1 and 2 first** (Mac, minutes; handoff `2026-09-30-data-off-github-stages-1-2.md`). Their checks
   must pass before anything writes to the VM's database. `vm.sh deploy` runs `alembic upgrade head`, so the deploy
   counts as a write too. After that, **no bucket stage runs until the overnight run's marker is in**: the bucket and
   the VM database never change at the same time.
2. **The Mac spot check** of the new pieces: the promotion, the grid ranking and the spike check (owner rule: a Mac
   stop before a VM run of new backtest logic).
3. **Resize the VM for the night.** It is an e2-small: 2 shared vCPUs (about 1 sustained) and 2 GB of memory, which
   also runs Postgres, the web app and MCP. Three parallel sweeps would run out of memory, and on one core the run
   would take well past morning. An e2-standard-4 (4 vCPUs, 16 GB) costs about $0.13 an hour. The resize needs a stop
   and a start: racinglines.bet is down for a minute or two, the Cloudflare tunnel reconnects on its own (it's outbound
   only), and the services start on boot. Resize back in the morning the same way. If the owner would rather not resize,
   run `MODE=f1` on the e2-small with `parallel = 1` and `hours = 3`: then only the golden and model groups finish.
4. **Merge in this order, then deploy main** (`vm.sh deploy`): **#89**, **#90** (the candle fix), **#88** (OG.com
   buy-all), **#87** (the taker story), then this PR. Both Kalshi fixes must be deployed before any tape pull or replay
   save on the VM:
   - **PR #89** rejects the dead-book 0.50 midpoint in the live quote path (`kalshi/sync.py _quote`,
     `exchange_driver.quote`) and keeps MotoGP's UUID rider ids.
   - **PR #90, the candle fix.** The tape pull stores prices through `kalshi/sync.py history_rows`, which #89 does
     not touch. It still averages an empty book's bid of 0 and ask of 1 into a 0.50 price (checked on main:
     `history_rows` returns 0.5 for such a candle). The fix is to skip the midpoint when a side is empty, the same
     rule as #89. `replay` mode checks for it and stops before any pull if the checkout still stores 0.50.
   - **PR #88, OG.com replay prices.** `racinglines markets --exchange og --sport <sport> buy-all`, read-only: one YES
     and one NO of every OG.com market at the first stored price, held, settled or marked. `replay` mode runs it for
     F1 and NASCAR after the replays (OG.com lists no MotoGP) and writes `data/runs/replay-grid/og/<sport>.csv`. Its
     Mac spot check is step 4 of `handoffs/2026-09-30-buy-all-spot-check.md`. OG.com's recorded prices are on the
     VM, so a `NO PRICE` on the Mac is expected; the VM run is where they count.
   - **Mac cleanup first:** run section 1e of the backfill handoff on the Mac (a read-only count of 0.50 prices, then
     back up, delete NASCAR's and MotoGP's Kalshi price rows and pull them again), so the spot-check numbers are clean.
   - **The VM's older candles:** the VM's 2026-09-29 sync stored hourly Kalshi prices for 2026-08-29 to 09-29 through
     the same `history_rows`. A re-pull after the fix writes no row for an empty hour, so it doesn't overwrite an old
     0.50 row. The dry run prints each sport's share at exactly 0.50 (read-only). If it's well above zero, those rows
     get the same cleanup as the Mac, as its own step with a backup and the owner's word.

   Then the **dry run**. Go on only if the golden check passes, the counts show `nascar_cup` races for 2025 and 2026, and the Kalshi probe returns trades and prices.
   MotoGP joins tonight only if the counts also show `motogp_wc` races and its probe is above 0; otherwise NASCAR alone.
5. **`MODE=all`** (F1, then NASCAR and MotoGP, then the demo taker story), started early in the evening, well before a
   live event.
6. **Morning:** markers, log greps, the two reports (`data/runs/search/overnight-vm/report.md`,
   `data/runs/replay-grid/<sport>/grid.md`) and the spike lines pasted back to the thread, which writes the report,
   the decision-log entry and the `docs/data-changes.md` line. Resize back.
7. **Later, each with its own go:** M3 (OG.com venue switch), M4 if MotoGP didn't join tonight (`MODE=replay SPORTS=motogp`), N1 to N5, and bucket stages 3 onward.

### Expected time (estimates from the cloud sweep's rate, not measured on the VM)

| Piece | Runs | Time on an e2-standard-4 |
|---|---:|---:|
| Dry run, including the golden check | 1 sweep | 15 to 40 min |
| F1 broad | 106 jobs, 3 at a time | 1 to 2 h (the cloud did 212 jobs in about 1 h on 4 cores) |
| F1 16k | up to 24 jobs at 4× the cost | 0.5 to 1.5 h |
| F1 walk-forward and default sweeps | 5 | about 1 h |
| NASCAR links and tape | several thousand Kalshi markets at 4 requests/s | 1 to 3 h |
| NASCAR replay saves | about 360 runs | under 1 h |
| NASCAR grid and 16k | 16 + 6 | capped at 3 h, plus the 16k runs |
| Demo taker story | 16 evidence sweeps, then about 38 weekends replayed | 30 min to 1.5 h |

The total is about 5 to 10 hours, so start it early in the evening.

## Rollback

- **Demo taker story:** restore `racinglines-before-demo-taker-story-…` (the step 1 dump).
- **Replay saves:** `racinglines nascar replay --undo BATCH`, with the batch ids from the log (`grep "batch replay-"`).
- **Sweep and walk-forward runs:** ordinary saved runs; they can stay.
- **Links and tape:** additive upserts of exchange data, the kind the recorder writes; harmless to keep.
- **Last resort:** restore `racinglines-before-overnight-f1-…` or `…-replay-…`. A restore also drops anything written
  since, so ask in the thread first.
- **The resize:** stop, set the machine type back to e2-small, start.

## What this plan doesn't cover

- The web app's all-sport P&L demo histories (the owner asked for them after the backfill; they need a separate go).
- Kalshi's F1 taker, OG.com backtests and NASCAR's OG.com cell (N3 to N5).
- Whether the VM's database already has NASCAR's 2025 results: the dry run's counts answer it. If it doesn't, `nascar
  ingest` comes first, with its own backup and the owner's word.
