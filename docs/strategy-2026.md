# Strategy to the end of 2026

Findings from a working session on 28 September 2026 between the owner and Claude, over the
racinglines MCP server (`overview`, `track_record`, `edge_finder`, `sql`) and the repo docs. Every
number is from the database on that day unless a web source is cited. The action items live on the
[Roadmap](todo.md#priorities) (U1–U12 there); this page keeps the reasoning behind them. The pre-registered
validation rules are in [Paper trading](paper-trading.md#validation-plan) and the round-16 plan in
the [F1 live test](f1-live-roadmap.md).

## Where things stand

- **The maker's +$12.4k headline is mostly Whistler.** $11.3k of it is the Whistler private book,
  which traded against a simulated crowd. It shows the pricing works, not that there is an edge
  against a real market. On real tapes the maker made +$938 on Polymarket (+$285 in 2025, +$653 in
  2026) and +$75 on Kalshi (+$193, −$119). The taker made +$898 on Polymarket (+$575, +$323).
- **The taker's record rests on two weekends.** Britain 2026 (+$537) and Saudi Arabia 2025 (+$324)
  account for most of it.
- **The taker's record is a third of profile A's, by design.** The params-4h search and the Edge
  Finder (run 1284) give A +$1,363 for 2025 and +$1,243 for 2026. The demo taker follows about a third
  of A's calls (`profiles.DEMO_FOLLOW` 0.33, [Following](paper-trading.md#following)); taking every
  call makes +$2,606, the sum of the two. So A's live proof should count A's own calls, not only the
  demo taker's followed subset.
- **Neither venue has any F1 race markets open.** Polymarket has listed no race since 28 Aug. What is
  open is championship futures:

  | Market | Polymarket volume | Kalshi volume |
  |---|---:|---:|
  | Drivers' champion | ~$38.0M | ~$9.0M |
  | Constructors' champion | ~$4.9M | ~$2.1M |

  Also open: "Action of the Year" (unmodeled), one standings head-to-head, and a Kalshi market on
  whether the Abu Dhabi GP takes place.
- **Maker results depend on the venue.** Profile C makes +$653 on Polymarket's 2026 tape and loses
  $119 on Kalshi's (−$66 before fees). It fills more often on Kalshi and does worse on those fills,
  which suggests Kalshi's takers are better informed ([Kalshi history](kalshi-history.md)).
- **Don't follow the Edge Finder's top rows.** The stage-aware taker leads in-sample (+$1.9k–2.4k
  in 2026) but lost $316 out of sample on 2025.

### The data behind it (28 Sep 2026)

201 events, 28,308 results and 1,166 athletes across two sports: F1 drivers' championships 2020–2026
(2026: 15 of 23 races done) and the UCI Downhill World Cup 2021–2026 (2026 finished at Whistler,
8 of 8). 1,286 model runs, 11,078 market links (Polymarket 7,285, Kalshi 3,793; 74 open on each),
3,869 paper positions and 8,667 strategy signals. Both live forecasts (F1 run 3, downhill run 1287)
were built from code version `1ab8934-dirty`, that is, from uncommitted code.

Worth checking: UCI 2023 shows 7 of 8 events completed and 2025 shows 9 of 10 (a cancelled round or
a missing result each); the F1 forecast keeps run ID 3 while the downhill one is 1287, so the F1 row
may be overwritten in place rather than written as a new run.

## How long each strategy takes to prove

Rough estimates from the Edge Finder's 2025–26 replays of real weekends:

| | Avg per weekend | SD | Weekends to reach about 2 SE |
|---|---:|---:|---:|
| Taker (update, A-like) | ~$83 | ~$262 | **~40** |
| Maker (conservative) | ~$71 | ~$146 | **~17** |

The rest of 2026 has 8 races and 2027 about 24, roughly 32 weekends in all. That is enough to prove
the maker. It is borderline for the taker even if every weekend runs. So:

1. **Freeze A and C now, and write down the success criteria before any live results.**
2. **The maker is the main story and the taker is secondary.** Retuning A partway through restarts
   its count.
3. **Treat each venue as a separate trial.** Polymarket and Kalshi weekends both count, which helps
   the taker most.

## Event tiers

| Tier | Meaning | Examples |
|---|---|---|
| **T1** | A real market is listed. Paper-trade it with frozen profiles and compare with the replay | F1 races on Kalshi or Polymarket, F1 championships |
| **T2** | A real market with no model. Record the tape and book, and score pricing where possible | NASCAR, MotoGP, IndyCar on Kalshi |
| **T3** | No market. Run a simulated pool (a private book like Whistler's). This proves pricing only | F1 weekends that neither venue lists |

**Listing timing:** Polymarket listed 2026 races 29 days ahead until 28 Aug, and has listed none
since. In 2025 Kalshi opened race markets only 2–4 days before each race, so it could still list
round 16 around 30 Sep – 1 Oct.

## The rest of 2026

- **Private books for rounds 16 and 17** prove pricing, not edge. The fair-price scorecard is their
  headline result.
- **Kalshi taker and maker signals** (the open F1-9 item) come before more Polymarket work. Kalshi
  listed every race in 2025–26. If Polymarket stays dark, Kalshi is the only live venue.
- **A Kalshi-specific maker:** tune it with its own sweep instead of porting C, and record it as a
  separate profile (K).
- **Championship markets** are where the liquidity is. The season strategy lost $208 in 2026 because
  the model lagged pre-season. Paper-trade them small, as a separate sleeve, and keep them out of the
  maker/taker proof.
- **When race markets list anywhere,** run A and C live and compare each weekend with its replay.
  That is the existing F1-8 process.

### Week by week

| Dates | Event | Market status | Tier and action |
|---|---|---|---|
| **Now – 1 Oct** | Kalshi recorder and signals, championship sleeve, freeze A and C | – | Wed 30 Sep: check both venues for R16. Thu 1 Oct 18:00 PDT: pick the scenario |
| **2–4 Oct** | **F1 R16, Bahrain GP at Sepang** | None yet; Kalshi possible | If Kalshi lists: **T1**, A and C on Kalshi (C as a control). Otherwise **T3**, the private book (`live/f1/2026-16.toml`). Championship sleeve after the race either way. Optional: record SignalR during FP1 |
| 5–9 Oct | Settle, reconcile, report on R16 | – | `racinglines live report`, the scorecard, the replay check. Build the Kalshi sprint markets |
| **9–11 Oct** | **F1 R17, Singapore (sprint)** | Same as R16 | T1 on Kalshi if listed. Otherwise T3 (`live/f1/2026-17.toml`) |
| Oct weekends | **NASCAR Chase races** (Las Vegas, Charlotte Roval, Phoenix, Talladega, Martinsville) | Kalshi, liquid | **T2:** record every tape |
| 12–23 Oct | Two-week gap | – | Sweep and freeze K, the cross-venue disagreement log, evaluate NASCAR data sources |
| **23–25 Oct** | **F1 R18, United States GP** | Kalshi likely | T1: A, C and K, plus Polymarket if it returns |
| **30 Oct – 1 Nov** | **F1 R19, Mexico City** | Kalshi likely | T1 |
| **6–8 Nov** | **F1 R20, São Paulo**, **NASCAR finale (Homestead, 8 Nov)**, **MotoGP Qatar** | F1 on Kalshi. NASCAR's championship market is deep. MotoGP thin | F1: T1. NASCAR: T2, including the pre-race and in-race book. MotoGP: T2 |
| 9–19 Nov | Mid-season review | – | The sizing decision. Walk-forward with R16–R20 added |
| **20–22 Nov** | **F1 R21, Las Vegas (Saturday race)**, **MotoGP Portugal** | F1 on Kalshi | F1: T1, checking the stage cut-offs for the night schedule. MotoGP: T2 |
| **27–29 Nov** | **F1 R22, Qatar**, **MotoGP Valencia (finale)** | F1 on Kalshi, but the race could be cancelled | F1: T1 once the settlement rules for cancelled races are in. MotoGP: T2 |
| **4–6 Dec** | **F1 R23, Abu Dhabi (finale)** | Kalshi; championships settle | T1. The championship sleeve settles. If the race doesn't happen, write up the settlement |
| 7–31 Dec | Season close | – | See [2027](#2027) |

**Two dates decide the rest of the year:** 30 Sep – 1 Oct, whether Kalshi lists round 16 (October
is T1 or T3); and about 12 Nov, the sizing review.

**Contingencies:**

- **Polymarket returns:** A and C go live there immediately (they were tuned on its flow), and that
  becomes the main record. Kalshi continues alongside.
- **Kalshi doesn't list the F1 races either:** every remaining F1 weekend runs T3. The year's goal
  changes from proving an edge to proving the pricing: the scorecard, plus the championship sleeve
  and the disagreement log on the markets that are open.
- **Downhill:** the 2026 season is over, so there are no live downhill events this year.

## Owner decisions

| Decision | When | Recommendation |
|---|---|---|
| Loss cap for R16 (`max_loss = 500`) | Before 1 Oct | Owner's call |
| Freeze A and C as they are | Now | Yes |
| A takes `rookie` | Now | No; keep A frozen |
| T1 on Kalshi vs T3 for R16 | Thu 1 Oct 18:00 PDT | T1 if Kalshi lists |
| Sizing rule | ~12 Nov | After 4–6 live weekends |
| Add NASCAR for 2027 | December | Only if the tapes and data hold up |
| Promote `gridq+pretrain`; `reset` for 2027 | December | Decide on the walk-forward |

## 2027

December closes 2026 and sets up 2027:

1. **Season report:** live weekends for each venue and profile against their replays, the pricing
   scorecard for all 8 rounds, the championship sleeve, the disagreement log.
2. **Walk-forward re-selection** on 2025 and 2026 across both venues. Choose A′, C′ and K′ for 2027
   and freeze them before Australia.
3. **2027 model:** the pre-season testing ingest (not seeing testing is why the 2026 championship
   calls were wrong), a `reset` decision for the second year of these regulations, and a decision on
   making `gridq+pretrain` the default.
4. **Decide whether to add NASCAR:** look at the recorded Chase tapes (volume, spread, how often
   markets trade) and at data availability. If both hold up, build a model in Jan–Feb and
   paper-trade from the 2027 Daytona 500.
5. **Infrastructure:** the GCP move, and the first real V2 order if validation rule 5 is met.
6. **Downhill:** points validation, Elite and Junior Women data, and the ChronoRace backlog (run
   locally).

Through 2027: the taker takes whichever venue's price is better, and the Polymarket/Kalshi
disagreements beyond fees are logged as a small edge that doesn't depend on the model. The
real-money gate is 4–6 live weekends where fills match the replay, then one small V2 order, then
scale up.

## Other racing sports for 2027

| Sport | Venue and liquidity | Take |
|---|---|---|
| **NASCAR Cup** | Kalshi. The Cup champion market has about $4.4M of volume, and there are per-race markets | **Best next sport.** About 36 races, public data, real volume. Ovals need a different model (pack racing, cautions) |
| **MotoGP** | Kalshi. The champion market has about $20k | Thin, but qualifying/sprint/race maps closely onto the F1 adapter, so it is cheap to add |
| **IndyCar** | Kalshi race markets (about $6.5k for Detroit) | Thin. Record it and watch |
| **Horse racing** | Blocked. Churchill Downs used the Interstate Horseracing Act, and there were no Derby contracts in 2026 | Skip |
| **Downhill / cycling** | No exchange | Keep downhill as a private-book showcase. Grand-tour listings not checked |

**Do this now:** record Kalshi's NASCAR, MotoGP and IndyCar tapes before any model exists. A 2027
backtest needs 2026 tapes, and they can only be collected while they are live.

## Sources

- [Polymarket F1](https://polymarket.com/sports/formula1)
- [Kalshi motorsport](https://kalshi.com/category/sports/motorsport)
- [Kalshi NASCAR Cup champion](https://kalshi.com/markets/kxnascarcupseries/nascar-cup-series-champion/kxnascarcupseries-ncs26)
- [Kalshi MotoGP champion](https://kalshi.com/markets/kxmotogp/moto-gp-world-champion/kxmotogp-26)
- [Kalshi IndyCar, Detroit](https://kalshi.com/markets/kxindycarrace/indycar-race/kxindycarrace-prix26)
- [CNBC: Kentucky Derby and prediction platforms](https://www.cnbc.com/2026/05/01/kentucky-derby-prediction-platforms.html)
- [SportsHandle: why Kalshi and Polymarket can't offer Derby contracts](https://sportshandle.com/prediction-markets-kentucky-derby-kalshi-polymarket-blocked-interstate-horseracing-act-2026/)
- [Yahoo Sports: 2026 NASCAR Chase schedule](https://sports.yahoo.com/articles/2026-nascar-chase-schedule-every-174101251.html)
- [Crash.net: updated 2026 MotoGP calendar](https://www.crash.net/motogp/news/1091546/1/updated-2026-motogp-schedule-full-after-qatar-postponement)
