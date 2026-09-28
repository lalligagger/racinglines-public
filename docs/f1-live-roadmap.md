# F1 live test roadmap: round 16, 2–4 October 2026

The working plan for the first live F1 test, kept up to date as we go. Tick items off
as they land and add every decision to the [decision log](#11-decision-log). The
general F1 plan is the [F1 roadmap](f1-roadmap.md) (this test is its phase F1-8); the
downhill run it builds on is [Live events](live-events.md).

**Status (28 Sep 2026):** the venue is confirmed and **Polymarket has no markets for
this race**. We build for [scenario B](#6-primary-plan-scenario-b-no-polymarket-markets):
a mock private book like Whistler's, pricing every market Polymarket usually lists,
updated at session ends only. We switch to the [backup plans](#7-backup-plans) if
markets appear.

---

## 1. Business context

### The story so far

The demo maker is racinglines' developer. They have been using the tool as a paper
maker on Polymarket's F1 markets since March 2025 (+$938 on paper). Last weekend they
ran a **private beta** at the Whistler downhill World Cup final: their own book, quoted
live by racinglines, against 1,000 simulated fantasy/paper traders and one tracked
beta user ([report](live-events.md)). This weekend is the next chapter: **the first F1
private book**.

### Polymarket has stopped listing F1 races

Polymarket listed every 2026 race up to Baku, with the same five markets each time,
almost always 29 days before the race. **Since 28 August it has listed no new race
markets at all**: not this race, and not Singapore (round 17, 11 Oct), which would
normally have appeared around 12 Sep. It has published nothing explaining why. Its
own markets show the backdrop:

- The 2026 Bahrain GP **has already settled once on Polymarket**: the original winner
  market (for 12 April) resolved "Other" on 15 March under its "canceled or rescheduled
  after Apr 19" rule. This weekend's race is legally the same Grand Prix, held in
  another country: an awkward fit for Polymarket's templates.
- Its traders doubt the rest of the Gulf season: Qatar 57.5%, UAE 60.5%, Saudi Arabia
  31% to host a race in 2026; "Will the Abu Dhabi GP take place?" trades at 53%.
- But Singapore is missing too, and has nothing to do with the Gulf, so this looks
  like a general pause in listings, not caution about one race.

Details and sources: [section 3](#3-polymarket-the-evidence).

### What it means for racinglines

- **Dependence on one venue is a real risk.** A month-long gap in Polymarket's F1
  listings means a Polymarket-only maker has nothing to quote. Rounds 16–17 are
  unlisted today, and the Gulf rounds (Qatar 29 Nov, Abu Dhabi 6 Dec) may be unlisted
  or cancelled.
- **The private book is the answer, and this weekend proves it.** If racinglines can
  list, price, quote and settle a full F1 race on its own, it covers exactly the
  races the public venues skip. The pitch: *"Polymarket didn't list the Bahrain GP in
  Malaysia. We did."*
- **Two books, one model, clean separation.** When Polymarket is back, the same model
  paper-trades there, and the Positions page already keeps the two venues apart.
- **Things to watch before anything goes beyond a private demo:** F1 data terms (the
  live timing is F1's property), OpenF1's non-commercial terms, and settlement rules
  for relocated or cancelled races (settle on the FIA classification; void a race that
  doesn't happen).

---

## 2. The event

It's a **replacement venue**. The Bahrain Grand Prix (originally 12 April, in Sakhir)
and the Saudi Arabian Grand Prix were cancelled after the 2026 Iran war broke out. F1,
the FIA and the governments of Bahrain and Malaysia then reinstated the Bahrain race at
**Sepang, Malaysia**, under the Bahrain name, with Bahrain keeping the ticket and race
proceeds. It's F1's first race at Sepang since the 2017 Malaysian Grand Prix, and it
fills a weekend the original calendar left empty between Baku (26 Sep) and Singapore
(11 Oct).

| | |
|---|---|
| Official name | Formula 1 Gulf Air Bahrain Grand Prix in Malaysia 2026 |
| Circuit | Sepang International Circuit, Selangor, Malaysia |
| Round | 16 of 23 · event key `2026-16` (race id 134, venue `kuala-lumpur`) |
| Format | Conventional, no sprint (Singapore, round 17, is the sprint weekend) · 22 drivers, 11 teams |
| Sepang in our data | None: FastF1 goes back to 2020 and the last race here was 2017, so the model has no history at this track (check what the track features do with it in B2) |

**Sessions.** Every session is overnight in Pacific time, so everything runs
unattended.

| Session | UTC | Pacific (PDT) | Stage cut-off (UTC) |
|---|---|---|---|
| — | | | pre-weekend: Fri 2 Oct 03:30 (Thu 20:30 PDT) |
| FP1 | Fri 2 Oct 04:30 | Thu 1 Oct 21:30 | after FP1: 06:00 |
| FP2 | Fri 2 Oct 08:00 | Fri 2 Oct 01:00 | after FP2: 09:30 |
| FP3 | Sat 3 Oct 04:30 | Fri 2 Oct 21:30 | after FP3: 06:00 |
| Qualifying | Sat 3 Oct 08:00 | Sat 3 Oct 01:00 | after Quali: 09:30 |
| Race | Sun 4 Oct 07:00 | Sun 4 Oct 00:00 (Sat night) | results expected ~10:00 |

Sources: [Wikipedia: 2026 Bahrain Grand Prix](https://en.wikipedia.org/wiki/2026_Bahrain_Grand_Prix),
[formula1.com: Malaysia joins the 2026 calendar as host of the Bahrain GP](https://www.formula1.com/en/latest/article/formula-1-and-fia-confirm-malaysia-will-join-2026-calendar-as-host-venue-for-bahrain-grand-prix.6lL7vjFEM2VVynRHvg1TCf),
[Motorsport.com: why the Bahrain GP is in Malaysia](https://www.motorsport.com/f1/news/why-is-the-2026-bahrain-grand-prix-taking-place-in-malaysia/10859526/),
[Wikipedia: 2026 Bahrain and Saudi Arabian Grands Prix](https://en.wikipedia.org/wiki/2026_Bahrain_and_Saudi_Arabian_Grands_Prix).
Schedule: FastF1 (`data/raw/f1/fastf1/2026/schedule.parquet`).

---

## 3. Polymarket: the evidence

**No markets for this race as of 28 Sep 2026, 00:30 UTC.** Searches for "Bahrain",
"Malaysia", "Malaysian", "Sepang" and "Kuala" find no 2026 F1 markets (only the 2023
and 2025 Bahrain GPs). The open "Azerbaijan Grand Prix" markets that close on 3–4 Oct
are round 15's, still waiting to resolve, not a calendar clash.

**When Polymarket listed each 2026 race** (the winner market's creation date):

| Rounds | Listed | Days before the race |
|---|---|---|
| 1 Australia, 2 China | 4 Mar, 11 Mar | 4, 4 (season start) |
| 3 Japan, 4 Miami | 11 Mar, 22 Apr | 18, 11 (after the Bahrain/Saudi cancellations) |
| 5 Canada … 11 Hungary | every 29 days | 29 |
| 12 Netherlands | 18 Aug | 5 (after the summer break) |
| 13 Italy, 14 Spain, 15 Azerbaijan | 8 Aug, 15 Aug, 28 Aug | 29 |
| **16 Bahrain in Malaysia, 17 Singapore** | **not listed** (due ~5 Sep and ~12 Sep) | |

Each race gets the same five markets: Driver Winner, Driver Podium Finish, Driver Pole
Position, Head-to-Head, and a constructor market. Since 28 Aug only props have been
added: rain in Spain and Baku, and "Will the 2026 F1 Abu Dhabi Grand Prix take place?"
(15 Sep, 53%).

**The original 2026 Bahrain market**, "Bahrain Grand Prix: Driver Winner" (listed 14
Mar): *"If the 2026 F1 Bahrain Grand Prix is canceled or rescheduled to a date after
Apr 19, 2026, this market will resolve to 'Other.'"* It resolved **Other** on 15 Mar.

**"Which countries will host an F1 race in 2026?"** (listed 20 Aug) offers only Qatar
(57.5%), the UAE (60.5%) and Saudi Arabia (31%). Its rules: *"The official name or
sponsor title of the Grand Prix will have no bearing on the resolution of this market;
only the physical location of the circuit will be considered."*

**Chance of a late listing:** possible (a race was listed 4–5 days out three times this
year, each after a break), but don't count on it.

**Our matcher, if it does list:** "Bahrain Grand Prix" and "Malaysia Grand Prix"
resolve to `2026-16`; "Malaysian Grand Prix", "Sepang…" and "Kuala Lumpur…" don't
(`GP_ALIASES` in `racinglines/markets/polymarket/sync.py`), and would be stored as
`unmodeled`: prices but no model price, so no signals. Build item B0 fixes that.

**How to re-check** (the recorder also picks new markets up by itself within 30 minutes):

```sh
curl -s "https://gamma-api.polymarket.com/events?tag_slug=f1&order=creationDate&ascending=false&limit=8" \
  | python3 -c "import json,sys; [print(e['creationDate'][:10], e['title']) for e in json.load(sys.stdin)]"
```

Sources: [Polymarket: Bahrain GP Driver Winner (April 2026)](https://polymarket.com/event/f1-bahrain-grand-prix-winner-2026-04-12),
[Polymarket F1](https://polymarket.com/predictions/f1), Polymarket's public API
(`gamma-api.polymarket.com`), and our recorder's `market_links`.

---

## 4. Scope

- **The mock demo, as at Whistler:** our own private book, the demo maker quoting it,
  1,000 simulated takers plus the demo taker, positions on the Positions page, a
  replay and a report. Play money; nothing traded anywhere.
- **Every usual Polymarket race market priced**, even though Polymarket hasn't listed
  them: winner, podium, pole, head-to-head and "which constructor scores 1st".
- **Updates at session ends only.** The engine wakes once per stage (after each
  session's data lands), not on a live feed. There is no continuous polling this
  weekend.
- **Polymarket paper trading only if markets appear** ([backup plans](#7-backup-plans)).
- **Out:** a live timing feed (deferred, [section 5](#5-live-data-source)); in-race
  pricing and trading ([F1-7](f1-roadmap.md)); real orders
  (`POLYMARKET_TRADING_ENABLED` is unset, and signing needs the CLOB V2 migration);
  Kalshi; Polymarket's props (safety car, red flag, rain, fastest lap in practice).
- **The race is display-only.** Quotes freeze after qualifying's stage, and the book
  closes at lights out.

---

## 5. Live data source

**Decision: no live feed this weekend.** The model reprices between sessions, and the
demo updates at session ends, so the FastF1 archive (each session's data, available
minutes to an hour after it ends) is all the engine needs. It's what the signal engine
already downloads.

For later (in-session updates, in-race trading), the options are:

| Option | Live? | Access | Notes |
|---|---|---|---|
| FastF1 archive (current) | No: after each session | Free, 500 calls/h | Used this weekend |
| F1 SignalR stream (`livetiming.formula1.com/signalr`) | Yes, ~1 s | Free, unofficial; may need a formula1.com / F1 TV login for some topics; likely outside F1's terms | FastF1's `SignalRClient` records it |
| OpenF1 | Yes, ~3 s | €9.90/month for live (6 req/s); non-commercial terms | Cleanest API |
| AWS (F1 Insights) | – | No public API (broadcast graphics) | Not an option |

**Optional, off the critical path:** record SignalR during FP1 with FastF1's client,
to learn whether it needs a login. It costs nothing and informs the next decision.

---

## 6. Primary plan: scenario B (no Polymarket markets)

### Multi-sport design: one live core, one adapter per sport

Every live demo has its own kind of data stream, and more sports will add more:
- **Downhill:** a timing feed polled every few seconds, with a Monte Carlo of the rest of the final.
- **F1 this weekend:** the model's stage runs, once per session.
- **Later, perhaps:** F1 SignalR, or another sport's timing provider.

So the stream stays sport-specific. Everything *around* it is shared, following the
repo's pattern: sports differ **as data** (`sports/<code>.toml`, read through
`racinglines/sports.py`), with per-sport `sources/` and `models/`, and shared
`markets/`, database and web layers.

| Layer | Shared or per sport | Where |
|---|---|---|
| **The data stream and pricing** | Per sport: an *adapter* | `pipelines/live_dh.py` (ChronoRace polls, final Monte Carlo); `pipelines/live_f1.py` (stage runs, session ends) |
| **Markets and settlement rules** | Shared code; each sport's market kinds and wording as data | `markets/private_book.py` (`KINDS`, `outcome_for`); a `[live]` section in `sports/<code>.toml` |
| **Quoting** (spread, inventory lean, per-market cap, freeze and close) | Shared; parameters per sport and event | A new `markets/quoting.py` (today's `live_dh.quote`, generalised) |
| **The book, the crowd, the demo taker's picks** | Shared | `markets/crowd.py` (B1) |
| **Positions sync** (`venue='private'`) and P&L | Shared | `markets/crowd.py` |
| **Run folder, snapshots, replay, live/replay state** | Shared | A new `pipelines/live.py`: the folder layout, `latest` / `snap_times` / `load_at` / `state`, and an **event registry** (which live events exist and which adapter each uses) |
| **The Live tab** | Shared shell; the body per sport | `live.html` keeps the status dot, replay bar and polling; each sport renders its own body partial (`live_mtb_dh.html`, `live_f1.html`) |
| **Settings** | Data | `sports/<code>.toml` `[live]`: cadence, market kinds, spreads, crowd size and budgets; frozen per event into `meta.json` |

**The adapter interface** (each sport implements these four; everything else comes
from the core):

| Function | Returns |
|---|---|
| `markets(event)` | The markets and their fair values now |
| `step(event, now)` | New stream data, if any; the engine's update if something changed |
| `outcomes(event)` | Settled results per market, when known |
| `view(snapshot, role)` | What the sport's body partial needs, for the maker or the taker |

**Ground rules:**
- **Nothing downhill breaks.** `live_dh.py` keeps its public names by importing them
  back from the core, so its CLI, the Whistler run folder and its replay work unchanged
  (the [F1 roadmap](f1-roadmap.md)'s rule: nothing renamed or moved from the outside).
- A test proves it: Whistler's book re-derived from its fills, and its replay pages,
  match what they are today.
- **A new sport means:** a new adapter, a `[live]` section, and a body partial. No
  changes to the core, the book, the crowd or the Live tab's shell.

### What runs

A new engine, `racinglines/pipelines/live_f1.py`, the F1 counterpart of `live_dh.py`,
run as `racinglines f1 live --event 2026-16`. Every run is **one idempotent step**: it
acts only when something new has happened since the last run, and does nothing
otherwise. A LaunchAgent calls it every 5 minutes, like the signal engine, so there's
no long-running process to supervise.

| Update | When (PDT) | What the engine does |
|---|---|---|
| 1. Pre-weekend | Thu 1 Oct 20:30 | Lists the 100 markets, prices and quotes them, places the demo taker's picks, freezes the settings: **the book opens** |
| 2. After FP1 | Thu 23:00 | Crowd trades the window since the last update; reprice; requote |
| 3. After FP2 | Fri 02:30 | The same |
| 4. After FP3 | Fri 23:00 | The same |
| 5. After Quali | Sat 02:30 | The same; **quotes freeze**; pole markets settle from qualifying; the pre-race window opens |
| 6. Lights out | Sun 00:00 | Crowd trades the pre-race window; **the book closes** |
| 7. Results | Sun ~03:00 | Everything settles from the race classification; final P&L; the Live dot turns grey |

Updates 2–5 wait for the signal engine's stage run (it prices each stage 30 minutes
after the session, once FastF1 has the data), so a late archive delays that update and
nothing else.

Each update writes to `data/runs/live/2026-16/` in Whistler's layout:
- `latest.json` and `snaps/<ts>.json.gz`: one snapshot per update, so the replay steps through the weekend;
- `book.json`, `crowd.jsonl`, `picks.json`;
- `meta.json`, with every version kept.

It also syncs both demo accounts' positions to `paper_positions` (`venue='private'`,
event key `2026-16`), so Positions and the banner show the F1 private book next to
Polymarket.

### The market set: Polymarket's usual five (100 markets)

Modelled on Baku (round 15), the last race Polymarket listed:

| Market (Polymarket's name) | Our markets | Fair value from the stage run | Settles on |
|---|---|---|---|
| Driver Winner | 22 | `win_prob` | Race classification |
| Driver Podium Finish | 22 | `podium_prob` | Race classification |
| Driver Pole Position | 22 | `extra.pole_prob` | Qualifying classification (Sat) |
| Head-to-Head | 23 pairs: the 11 teammate pairs plus Baku's 12 cross-team pairs (e.g. Hamilton vs Piastri, Hamilton vs Russell) | `extra.h2h[a][b]` | Race classification order |
| Which Constructor Scores 1st? | 11 | the run's `race_constructor_top` metric | Race points |

- Polymarket's placeholder outcomes ("Other", "Driver A–E") are left out: they only exist for last-minute entry changes.
- If a driver change is announced, their markets are listed at the next update.
- Every fair value is already stored by each stage run: `model_runs` of kind `diagnostic` with a `sweep_stage`, with `race_predictions.extra` holding `pole_prob` and the head-to-head matrix.
- `private_book.outcome_for` already settles all five kinds.
- The model is the demo maker's profile, C (`gbm`).

**Every fair price is kept, whether or not anyone trades it.** Each update saves all
100 fair values and quotes. The report can then show how our prices moved through the
weekend and score them against the result (Brier score, log loss), exactly as if
Polymarket had listed the markets.

### Quoting rules (frozen at the pre-weekend update)

- Fair ± a half-spread: **3¢ pre-weekend, 2.5¢ after FP1 and FP2, 2¢ after FP3 and
  qualifying**. Tighter as the model sees more of the weekend.
- Lean against inventory; at most 2,500 shares per market either way (as at Whistler).
- No quote on a decided market (pole after qualifying), or below 1¢ or above 99¢.
- Quotes stay as posted until the next update. Frozen after qualifying's update;
  closed at lights out.

### The crowd

- The same 1,000 anonymous takers and $10–200 budgets as Whistler, seeded and
  replayable.
- **One batch per update:** the crowd trades the window since the last update against
  the quotes posted at its start, scaled to the window's length at a steady per-hour
  rate. Fills get times spread across the window, so the replay and the report show
  them in order.
- **Pre-race window** (after qualifying to lights out, about 22 hours): fresh $100 caps
  and a higher pace, like Whistler's late window.
- **Optional (decide Monday):** a 10% share of *informed* takers, who trade in the
  direction of the next session's result instead of at random. Whistler's crowd was
  uninformed by construction, which flatters the maker.

### The demo taker (the beta user)

- **Hype picks:** about 12 YES bets at $25 at the pre-weekend update, chosen on names
  and stories, not value, as at Whistler.
- **Optional:** profile A's calls against our quotes at each update. A runs a different
  model (`gridq+pretrain+reset`) from the maker's C (`gbm`), so this is a real
  model-against-model test.

### The Live tab for F1

- `/live` picks its event from a registry, in place of Whistler's hard-coded name. The
  green dot shows from the pre-weekend update until the results; grey afterwards.
- **The F1 layout, per update:**
  - the weekend's stages, with the current one highlighted;
  - the latest session's classification;
  - all 100 markets' fair values and quotes, grouped by market type, with the move since the last update;
  - the private book (P&L, positions, the crowd's results);
  - the demo taker's picks.
- **Replay:** steps through the 7 updates with the controls built for Whistler.

### Build items (scenario B)

Each item lists what "done" means. B0 matters in every scenario.

- [x] **B0. Name aliases** *(Mon)*
  - "Malaysian", "Sepang", "Kuala Lumpur" and "Bahrain Grand Prix in Malaysia" resolve to `2026-16` (`GP_ALIASES`).
  - Done: `tests/test_gp_aliases.py` resolves each name; the April Bahrain market's date still doesn't match.
- [x] **B1. The shared live core** *(Mon)*
  - `markets/crowd.py`: the book, the crowd, picks, P&L and positions sync, moved out of `live_dh.py`; add windowed batches (a length in hours, fills timed across it).
  - `markets/quoting.py`: quotes with a spread, inventory lean, cap, freeze and close.
  - `pipelines/live.py`: the run folder, snapshots, replay, live/replay state, and the event registry.
  - A `[live]` section in `sports/mtb_dh.toml` with today's downhill values.
  - `live_dh.py` imports all of it back under its old names.
  - Done: Whistler's book re-derived from `crowd.jsonl` still matches exactly, its replay pages are unchanged, and the downhill tests pass (`tests/test_live_core.py`; all 82 replay and Positions pages checked byte for byte during the build).
- [x] **B2. The F1 adapter: markets and prices** *(Mon)*
  - `live_f1.markets(event)`: the 100 markets and their fair values from the latest stage run; head-to-head pairs taken from the last race Polymarket listed. `race_pole`, `race_h2h` and `race_constructor_top` wording added to `KINDS_F1`.
  - A `[live]` section in `sports/f1.toml`: session-end cadence, the five market kinds, the spreads by stage, crowd settings.
  - Done: priced for Baku (`2026-15`) from its stored stage runs (runs 197–201, profile C): winner 1, podium 3, pole 1, constructors 1, and each pair 1, at every stage. **99 markets, not 100:** Baku's listing had a Lindblad–Tsunoda pair, and Tsunoda isn't in the 2026 field, so it's left out. Round 16 takes its pairs from Baku (the last race listed).
  - Sepang: the venue slug is `kuala-lumpur` (FastF1's location). The track features treat it as unknown: `venue_known` 0, not a street circuit, the neutral `x_track` / `ease`. Pricing round 16 as of 29 Sep works: the grid is simulated from qualifying pace, with no track history.
- [x] **B3. The F1 adapter: the engine step** *(Tue)*
  - `live_f1.step`: the seven updates above as one idempotent step, driving the shared core (quoting, crowd batches, freeze and close, settlement through `outcome_for`, positions sync, snapshots).
  - Done: Baku's weekend on a simulated clock (`tests/test_live_f1.py`; `racinglines live run live/f1/2026-15.toml --simulate --no-fetch`): all seven updates in order; pole settles at the after-Quali update, everything else at results; quotes freeze after qualifying and close at lights out; the book reconciles with its 2,600-odd fills; the positions synced to `paper_positions` sum to the maker's P&L.
- [x] **B4. The Live tab: shared shell, F1 body** *(Tue–Wed)*
  - `live.html` becomes the shell (status dot, replay bar, polling) over the registry; today's downhill body moves unchanged into `live_mtb_dh.html`; a new `live_f1.html` body with the F1 layout.
  - Done: Baku renders update by update for the maker and the taker, and in replay (`tests/test_live_f1.py`); takers see prices, never fair values. Whistler's 82 replay and Positions pages are byte-identical. F1 replay plays at a fixed 2 s per update at 30× (updates are hours apart); the live page refreshes every 30 s.
- [x] **B5. The demo taker** *(Wed)*
  - Hype picks written at the pre-weekend update (`live_f1.make_picks`, from the launch spec's `[[picks]]`: name, market, hype, why; `vs` for a head-to-head), bought YES at the maker's ask for $25 each. A pick the book doesn't quote is left out.
  - Optional: A's calls against our quotes. Not built (the default: hype picks only).
- [x] **B6. Operations** *(Wed)*
  - A LaunchAgent per event (`racinglines live agent live/f1/2026-16.toml --install`: label `bet.racinglines.live.2026-16`, a step every 5 minutes, log in the run folder), with a lock in the run folder so steps can't overlap.
  - An alert when an update is more than 2 hours late (`[live.poll] late_alert_h`), once per update, through the usual alert channels (`markets/alerts.deliver`); `racinglines live status` shows lateness too.
  - Settings frozen into `meta.json` at the pre-weekend update, with the head-to-head pairs; a changed schema or spec is ignored with a warning unless `--unfreeze` (then add a decision-log line).
  - Done: `tests/test_live_f1.py` (lock, plist, frozen settings, the lateness alert); round 16's opening dry-run on a simulated clock (99 markets, 90 quoted, 12 picks). The LaunchAgent itself is only loadable on the Mac.
- [ ] **B7. Rehearsal on Baku** *(Wed–Thu)*
  - The whole weekend on a simulated clock, run under the LaunchAgent.
  - Done: all seven updates happen, pole settles after qualifying and everything else after the race, Positions is correct, replay works.
- [x] **B8. Report command** *(Thu, stretch)*
  - `racinglines live report <spec> [--pdf]`, generalising the Whistler report: book P&L by update, the crowd, the demo taker, and the fair-price scorecard (Brier score and log loss per market kind at each update, and the biggest moves). Written to the run folder's `report/`: Markdown, HTML with the charts inline, SVG charts, and a PDF through headless Chrome.
  - Done: Whistler's report from its run folder (run folder unchanged); tests on the synthetic third sport.

### Weekend runbook (PDT)

| When | What | Check |
|---|---|---|
| Wed evening | **Checkpoint 1**: any Polymarket listing? | Decision log |
| Thu 18:00 | **Checkpoint 2**: pick the scenario | Decision log |
| Thu 20:30 | Update 1: **the book opens** | `/live` shows 100 quotes; picks placed; `meta.json` frozen |
| Thu 23:00 | Update 2 (after FP1) | Repriced; crowd batch filled |
| Fri 02:30 | Update 3 (after FP2) | |
| Fri 23:00 | Update 4 (after FP3) | |
| Sat 02:30 | Update 5 (after Quali): **quotes frozen**; pole settles | Pole P&L on Positions |
| Sun 00:00 | Update 6: **lights out, book closed** | |
| Sun ~03:00 | Update 7: **results, everything settled** | Book reconciles; Positions updated; dot grey |

Only the book opening (Thursday 20:30) and the results are worth watching live; every
other update runs by itself.

---

## 7. Backup plans

**A. Polymarket lists before FP1** (found at checkpoint 1 or 2)

1. Check the markets link to `2026-16` on the Markets page. If they show as
   `unmodeled`, apply B0 or add the alias they used, then restart the recorder
   (`launchctl kickstart -k gui/$UID/bet.racinglines.recorder`).
2. The signal engine paper-trades them with no change (profiles A and C, from the
   first stage it reaches).
3. **The private book carries on unchanged.** Positions shows both venues for the
   same race: the first like-for-like comparison.
4. Our fair prices can be compared with Polymarket's at every update in the report.
   Take the head-to-head pairs from Polymarket's actual listing if it differs from Baku's.

**C. Polymarket lists mid-weekend**

- The signal engine joins at the next stage; earlier stages are recorded as not quoted,
  and nothing is backfilled.
- The private book is unaffected. Log the time; the report keeps the two phases apart.

**D. The FastF1 archive is late or rate-limited**

- The update waits for the stage run, and quotes stay as posted meanwhile.
- If a stage is more than 2 hours late, the alert fires. Skip the stage and note it;
  the next one prices normally.

**E. The session schedule changes** (tropical storms are common at Sepang)

- **Qualifying cancelled:** pole markets are void. The grid comes from the stewards;
  the after-Quali update prices from FP3.
- **Race red-flagged or shortened:** the official classification stands.
- **Race postponed:** the book stays closed and settles when the race runs.
- **Race cancelled:** every market is void and stakes are returned
  (`private_book.settle(..., None)`).

**F. The engine fails**

- Each run is one step from the saved state (`book.json`), so the next run carries on.
  The lock stops overlapping runs (Whistler's two-poller problem).
- An update missed while it was down happens on the next run, with the crowd batch
  covering the whole gap.

---

## 8. Build schedule

| Day | Build | Checkpoints |
|---|---|---|
| **Mon 28** | B0, B1, B2 | Decide the open questions (section 10) |
| **Tue 29** | B3, B4 | |
| **Wed 30** | B4, B5, B6; first rehearsal (B7) | Signal engine starts on its own (log shows `2026-16` pre-weekend); **checkpoint 1** |
| **Thu 1** | Second rehearsal under the LaunchAgent; B8 if time allows; fixes only | **Checkpoint 2, 18:00 PDT**; book opens 20:30 |
| **Fri 2 – Sun 4** | No code changes except logged fixes | Runbook above |
| **Mon 5** | Reconcile, report, retrospective | Section 9 |

**Minimum viable version** if the week runs short: B0–B3 and B6 (the book, priced,
settled and synced to Positions). The Live tab can show the book's snapshots in its
existing layout, and the report can be written by hand as Whistler's was.

## 9. After the weekend (Mon 5 Oct)

- [ ] Settle and reconcile: the book matches its logged fills exactly (as Whistler's did).
- [ ] Report: book P&L by update, the crowd, the demo taker, and **the fair-price
  scorecard** for all 100 markets (how each price moved, Brier score and log loss
  against the result).
- [ ] Decide:
  - Run the same for Singapore (round 17, a sprint weekend) if Polymarket still hasn't listed it?
  - Add a live feed (SignalR or OpenF1) for in-session updates?
  - Is in-race trading (F1-7) worth scoping?

**Success:**
- All seven updates on time, unattended.
- All 100 markets priced at every stage, and scored against the result.
- Pole settled on Saturday and everything else on Sunday.
- The book reconciled with its fills.
- The Live tab and replay working for F1.
- Positions keeping the venues apart.
- In scenario A, Polymarket paper fills compared with the replay.

## 10. Open questions (decide Monday)

| Question | Default if nobody decides |
|---|---|
| Crowd: informed takers, and what share? | None, as at Whistler |
| Demo taker: hype picks only, or A's calls too? | Hype picks only |
| Add top-10 finishes (+22 markets) beyond Polymarket's usual five? | No |
| Record SignalR during FP1 as an experiment? | Yes, if it takes under an hour to set up |

## 11. Decision log

| Date | Decision |
|---|---|
| 2026-09-28 | Round 16 confirmed as the relocated Bahrain GP at Sepang. No Polymarket markets for rounds 16 or 17 (race listings paused since 28 Aug). Plan for scenario B; switch if markets appear. |
| 2026-09-28 | Price every usual Polymarket race market (winner, podium, pole, head-to-head, constructor: 100 markets, modelled on Baku's listing) even though none are listed, and keep every fair price for scoring. |
| 2026-09-28 | Updates at session ends only; no live feed this weekend. The FastF1 archive drives pricing and the page; SignalR / OpenF1 deferred. |
| 2026-09-28 | Otherwise a mock private-book run like Whistler's: the demo maker, 1,000 simulated takers and the demo taker, play money. |
| 2026-09-28 | The race is display-only: quotes freeze after qualifying's update, and the book closes at lights out. |
| 2026-09-28 | Multi-sport design: one live core (book, crowd, quoting, positions, run folder, replay, registry, the Live tab's shell) and one adapter per sport for its data stream, pricing and page body; sport settings as data in `sports/<code>.toml`. Downhill keeps working unchanged. |
| 2026-09-29 | Shared quotes round away float noise before the cent floor / ceiling (0.40 ± 0.03 quotes 0.37 / 0.43). Downhill keeps its old rounding (`tidy=False`, sometimes a cent wider), so Whistler's numbers stay identical. |
| 2026-09-29 | The Live tab is green while an event isn't over and either updated within its sport's `stale_h` (downhill 6 h) or its next scheduled update isn't more than that overdue. F1 updates are up to 20 h apart, so F1 snapshots carry `next_at`. |
| 2026-09-29 | `/live` shows the registry's most recently updated event; `?event=` picks another. Once the F1 book opens, it replaces Whistler as the default. |
| 2026-09-29 | Head-to-head pairs with a driver not in the field are left out (Baku's Lindblad–Tsunoda): round 16 has 99 markets. |
| 2026-09-29 | Updates missed while the engine was down merge into the next one (marked skipped in the snapshot), and its crowd batch covers the whole gap. A stage whose run never arrives by lights out is skipped. |
| 2026-09-29 | Each crowd batch's seed is derived from the event and update label (logged in `crowd.jsonl`), so a rehearsal replays exactly. Window fills are timed uniformly across the window and filled in time order. |
| 2026-09-29 | F1 crowd pace: 0.0006 hits per taker, per quoted market, per hour (about 60 an hour across the book), and 3× in the pre-race window with fresh $100 caps. Chosen a priori; Baku's rehearsal gives about 2,600 fills. |
| 2026-09-29 | One LaunchAgent per event (`bet.racinglines.live.<run>`), so a downhill final and an F1 weekend can run side by side. |
| 2026-09-29 | The head-to-head pairs are fixed at the book's opening (in `meta.json`): a Polymarket listing that appears mid-weekend doesn't change the book's markets. |

