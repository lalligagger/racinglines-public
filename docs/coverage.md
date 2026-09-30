# Sports and exchanges: status

Where every sport stands on every exchange: what data we hold, what prices it, what has been backtested and how far
the result can be trusted, and what runs live or on paper. **Last reviewed 2026-09-30** against the code on `main`
(after #104), the [overnight VM run](https://github.com/lalligagger/racinglines/blob/main/reports/2026-09-30-overnight-vm-run/report.md)
and the [24-hour report](https://github.com/lalligagger/racinglines/blob/main/reports/2026-09-30-sports-exchanges-24h/report.md).
Nothing here trades real money: `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are unset, and OG.com has
no order code at all.

**The short version.** Only **F1 on Polymarket** has a real model, a backtest that held up in a held-out season, and
live paper trading wired up, and Polymarket has listed no F1 race since 28 Aug 2026. Everything else is one or more
steps short: NASCAR and MotoGP have a simple result-only model and a Kalshi taker replay that has not passed a
held-out season; OG.com is a replay venue with no strategy tested on it; downhill has a real model and no exchange;
IndyCar, road cycling, Le Mans and SailGP are recorded tapes with no model.

## How to read the status

| Word | Means |
|---|---|
| **Real model** | A model with its own features, walk-forward backtested on results and compared with a baseline and the market (F1: [F1 evaluation](f1-evaluation.md); downhill: [Evaluation](evaluation.md)) |
| **Simple baseline model** | A result-only Monte Carlo on recent finishing positions and a team prior (`models/nascar_model.py`, `models/motogp_model.py`): one price per race, made before the weekend, with no practice, qualifying, lap or track features. It runs in the replays and prices the board's columns, and has not been shown to beat the market |
| **Quote only** | The market is synced and recorded; no model prices it |
| **Tape only** | The sport's schema has `model_family = "none"`: links are `unmodeled`, prices, trades and books are recorded, nothing is priced |
| **Robust** | Positive in the target season (2026) **and** the held-out season (2025), beyond the noise floor ([promotion rule](f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default)) |
| **In-sample** | The settings were chosen on the same races they are scored on |

## The status matrix

One row per sport and exchange that lists it (a venue that lists nothing for a sport is left out; see
[Not listed anywhere](#not-listed-anywhere)).

| Sport × exchange | Data we hold | Model | Backtest (caveats) | Live / paper | Main gap |
|---|---|---|---|---|---|
| **F1 × Polymarket** | 2025–26 race weekends and championships, 7,285 links, prices and trade tape | **Real model** (`position_sim`) for race kinds; season forecast for champion, season-wins and standings head-to-head | **Robust.** Taker profile A (+$1,389 in 2026 / +$1,432 in 2025 at 16k sims, PR #85) and maker C; the overnight 106-job sweep kept A. Championship checkpoints **lost** in 2026 (−$566 to −$797, every variant) | Signal engine and paper positions for A and C, stage by stage. Demo taker's paper record 2025 +$450.46 (23 weekends), 2026 +$353.01 (15); only 2026 is out of sample | **No F1 race listed since 28 Aug 2026**, so nothing to trade now |
| **F1 × Kalshi** | 2025–26 history, 3,793 links (29 `KXF1*` series), trades, hourly candles; no order books (no Kalshi book recorder runs) | **Real model** (same as above) | **Maker K** tuned (2026 +$490, 2025 +$659), frozen pending owner review. **Taker not usable**: the replay reads last-trade candles, which spike (1.67% of points >15 pts off the median); bid/ask candles are not stored. Demo maker's Kalshi record 2025 +$193.39, 2026 −$118.84 (backfill) | Paper signals wired (`venue = kalshi`, U1; sprints behind a switch). The Kalshi recorder (U2) does **not** run on the VM | Recorder timer; bid/ask re-pull before any taker result counts |
| **F1 × OG.com** | 20 season futures (Drivers' and Constructors'), trades and minute prices since 29 Sep, book snapshots per `books` run | **Real model** for the champion markets (season forecast) | **None run.** OG.com is a replay venue (#88); the F1 champion replay on Kalshi and OG.com is a draft (#95). Buy-all ran overnight (a plumbing check, not a backtest; output not read) | Fair-price indicator only, behind `RACINGLINES_OG_VENUE=1` (off on the VM). No trading: needs FCM onboarding | Thin books (asks at 1–4¢, about 4 trades a week); fee $0.02 unverified |
| **NASCAR × Kalshi** | 13,599 links (race win, top 3/5/10/20, h2h, pole, fastest lap, champion); on the VM 408 events 2016–26 and 7,544 links with a race; trades and hourly candles; 826 book snapshots from one hand run (29 Sep), no recorder | **Simple baseline** (`NascarCupRace`) for race win, top 3/5/10/20 and h2h; champion: #93 season sim through the Chase, **not calibrated**, offline only | **Not robust.** Taker grid 2026 +$4,226 to +$5,479 (19–21 of 32 races up), 2025 −$242 to −$390 in every setting (1–2 of 8 up). Kalshi last-trade prices, spiky, so indicative only. Nothing tuned | None. PR #97 (draft) would store the replay trades as the demo taker's in-sample Kalshi paper positions, behind `RACINGLINES_SPORT_PAPER=1` | A held-out-positive result; bid/ask prices; tapes timer for the Chase |
| **NASCAR × Polymarket** | 1,101 links on the owner's Mac (per-race winners, Cup champion); tag slug unverified, not run on the VM | Race kinds: same simple baseline; champion: #93, not calibrated | **None.** The replay reads Polymarket (`--venue polymarket`), but no run with a Polymarket NASCAR tape has been reported | None | First VM sync and tape pull |
| **NASCAR × OG.com** | 17 Cup Champion contracts, tape since 29 Sep | Champion: #93, **not calibrated**, offline (`nascar season --quotes`, off by default); `og.toml` keeps the sport `modeled = false` | **None.** Buy-all ran overnight (plumbing check, output not read); the NASCAR champion replay is a draft (#96) | None | Calibration of the season sim; OG.com lists no NASCAR race markets |
| **MotoGP × Kalshi** | 322 links (`KXMOTOGPRACE` 289, `KXMOTOGP` champion 22, `KXMOTOGPTEAMS` 11); on the VM 202 events; tape pulled; 33 book snapshots from one hand run (29 Sep), no recorder | **Simple baseline** (`MotoGPRaceChallenger`) for race win only (race-win log loss 0.0796, not compared with the market or a naive baseline). Sunday race only: sprints are not ingested. Champion and teams: **quote only** | **No verdict.** 16 of 16 grid runs done; the ranking crashed (fixed in #102) and has not been re-run. **No held-out season**: 2025 has no MotoGP race with Kalshi markets. One Mac spot check (2026, $0 volume floor, so not tradeable) made +$413.62 on 93 trades | None (#97 draft, as NASCAR) | A second season of markets; sprint results; champion classifiers |
| **MotoGP × Polymarket** | Champion (25 outcomes) and some per-race winners listed; tag slug unverified, nothing synced on the VM | Champion: **quote only**. Race winners: the baseline could price them, nothing synced | **None** | None | First sync; the champion needs sprints, schedule, standings ([Championship markets](championship-markets.md#what-pricing-motogps-champion-would-take)) |
| **Downhill × private book** | Whistler 2026 live event (7,703 fills); results 2021–26 from ChronoRace | **Real model** (`timed_runs`), walk-forward on 43 rounds | Walk-forward on results (Final-qualification error 38% below a uniform guess). No exchange tape, so **no market backtest** | `racinglines mtb_dh live` on the private book (a simulated crowd; proves pricing, not an edge) | No exchange lists downhill; next World Cup spring 2027 |
| **IndyCar × Kalshi** | 1,374 links (all closed), 167k trades | **Tape only** | None | None | Results source's terms forbid automated use (#75); season over until March 2027 |
| **Road cycling × Kalshi** | Schema built (`road_cycling`, `KXCYCLING*`), **not yet run on the VM**; Kalshi holds 200+ settled markets per series | **Tape only** | None | None | No results source or model |
| **Le Mans × Kalshi** | Schema built (`le_mans`), not yet run | **Tape only** | None | None | No results source or model |
| **SailGP × Kalshi, OG.com** | OG.com 13 Championship Winner links (synced 29 Sep); Kalshi schema built, not yet run | **Tape only** | None | None | No results source or model |

**Buy-all is never a result.** `buy-all` (and the replays' `--buy-all`) buys one YES and one NO of every market to
prove it is found, priced and settled; a pair loses exactly its fees. Per the owner it is never shown in reporting or
the web app, and none of the numbers above come from it.

### Not listed anywhere

- **MotoGP on OG.com**, **IndyCar, road cycling and Le Mans on OG.com**: OG.com lists none of them (probed 2026-09-29).
- **Downhill, XCO/XCC, track, cyclocross, BMX**: no exchange lists mountain biking or track cycling. XCO results are
  fetchable from ChronoRace on the same weekend slugs, nothing is ingested, and there is no mass-start model.
- Horse racing (blocked by law on both US venues), Formula E, rally and alpine skiing: out of scope.

## Model status by sport

| Sport | Schema `model_family` | Results source | What the model uses | How it was checked | Honest status |
|---|---|---|---|---|---|
| **F1** | `position_sim` | FastF1 (cloud-blocked) | Lap and sector times, track and sector properties, practice and qualifying by stage, grid; season forecast by simulation | 129 races, 2021 to Azerbaijan 2026, three stages each; after qualifying top-10 Brier 0.149 vs 0.163 grid-only. Polymarket is as sharp on race winners (sharper after qualifying, and in 2025 at every stage) | Real model; its edge is where the gap to the market is large, not everywhere. Season forecasts lag the market early in a new-regulations season |
| **Downhill** | `timed_runs` | ChronoRace web feed (primary), PDFs opt-in | Run times: rider pace, noise, rider × weekend spread, incident rates; format-aware weekend simulation | 43 World Cup rounds walk-forward ([Evaluation](evaluation.md)) | Real model, nothing to trade it against |
| **NASCAR Cup** | `position_sim` (`NascarCupRace`) | `cf.nascar.com` feeds (probed from the Mac) | Recent finishing positions, recency decay, a team prior; the Chase season sim (#93) adds finishing, stage and bonus points and the 2026 Chase format, with no track types or form drift | Taker replay on Kalshi only (above); no calibration table published beside a naive baseline | Simple baseline. Race-day pricing ignores qualifying, practice and track type; the replay's race spread (2.0 places) is tighter than NASCAR's measured ~7, an open owner decision |
| **MotoGP** | `position_sim` (`MotoGPRaceChallenger`) | `api.motogp.pulselive.com` (unofficial, public; probed from the Mac) | Sunday race results only, same form model as NASCAR | Race-win log loss 0.0796, no baseline comparison; Kalshi replay has no ranked result | Simple baseline, race win only. No sprints, so no season or champion pricing |
| **IndyCar, road cycling, Le Mans, SailGP** | `none` | None cleared (IndyCar's forbids scraping) | – | – | Tape only |

A `market_implied` or Plackett-Luce baseline for the new sports is planned (engine roadmap E7) and not built, and the
generic leak guard (E2) is F1-only today: the NASCAR and MotoGP replays avoid leakage by pricing each race from
results strictly before its start, which is a convention in `pipelines/position_replay.py`, not a checked guard.

## The venues

| Venue | What it is | Can we read it? | Can we trade it? | Take |
|---|---|---|---|---|
| **Polymarket** | Crypto exchange, CLOB, public Gamma + CLOB APIs, full trade and price history | Yes: `markets sync/record/archive`; F1 2025–26 history. Tape-only path for NASCAR, MotoGP, IndyCar through `[markets.polymarket] tags` (#51, slugs unverified) | Paper; V2 order path built, `POLYMARKET_TRADING_ENABLED` unset | Our first venue. **Has listed no F1 race since 28 Aug 2026** ([F1 live roadmap](f1-live-roadmap.md#polymarket-has-stopped-listing-f1-races)). Championships still deep |
| **Kalshi** | CFTC exchange, public REST API with candlesticks and trades, per-market maker fee | Yes: `markets --exchange kalshi`, F1 2025–26 ([Kalshi history](kalshi-history.md)); NASCAR, MotoGP, IndyCar with `--sport` (U9), identified by the sports' resolvers | Paper; `KALSHI_TRADING_ENABLED` unset | Listed every 2025–26 F1 weekend and every NASCAR Cup race; the likeliest live venue this autumn. Its hourly candles are last trades, which spike |
| **OG.com** | Crypto.com's US prediction market (CFTC contracts via Crypto.com Derivatives North America). Sports-first, $0.02 flat fee per contract (from reviews) | **Yes, public market data with no key** (`api.crypto.com/fcm/v1/public/*`), read by a schema (`exchanges/og.toml`, #44). A replay venue since #88. History is short: about a month | Not without **FCM onboarding** and HMAC-SHA256 signing (owner waiting on an API key) | Readable and replayable, not tradable. F1, NASCAR and SailGP season futures only, thin. See [OG.com](#ogcom) |
| **Private book** | Our own simulated pool (`racinglines live`): the demo maker quoting to a simulated crowd and the demo taker | Yes, replayable to the fill | Yes (the T3 tier) | The fallback where no venue lists the event. Proves pricing, not an edge |

Other venues seen and **not** tracked: Robinhood's prediction-market tab (Kalshi's contracts resold), FanDuel
Predicts (CME and OG contracts), PrizePicks (picks, not a book), Octagon. None adds a market Kalshi or Polymarket
doesn't already list.

## The gaps, ranked

Effort: **S** under a day, **M** one to three days, **L** a week or more. Ordered by what changes a cell of the
matrix soonest. None starts without the owner's go ([Roadmap](todo.md#new-sports)).

1. **Kalshi bid/ask prices — S to M.** Every Kalshi taker result (F1, NASCAR, MotoGP) reads hourly last-trade
   candles, which spike. Storing the candles' bid and ask (a re-pull from the VM or the Mac, backup first) is what
   turns those results from indicative into something a taker could have paid.
2. **Kalshi recorder on the VM (U2) and a tapes timer (U9) — S each.** Neither runs: F1-on-Kalshi has no live tape,
   and the NASCAR Chase and MotoGP's last rounds are recorded only when someone runs the sync. Both need the owner's
   sign-off for new VM units.
3. **Read the unread overnight outputs — S.** MotoGP's grid ranking (re-run after #102's deploy), the OG.com buy-all
   CSVs and the NASCAR spike share were written on the VM and not yet read. Until then MotoGP × Kalshi has no verdict.
4. **Champion replays (#95, #96) — drafts.** F1 champion markets on Kalshi and OG.com, NASCAR and MotoGP champion
   markets: built, need a Mac spot check before merge. They would be the first backtest on any OG.com cell.
5. **Calibrate the NASCAR season sim — M.** #93 prices the Cup champion but has never been scored against settled
   seasons (its first Mac run had Larson at 94.6% against 40–55% on the market, before its second revision).
6. **Polymarket tapes for NASCAR and MotoGP — built (#51), first VM run open.** The tag slugs are unverified: run
   `markets --sport nascar sync` on the VM, and `--tags SLUG …` corrects a slug without code.
7. **MotoGP sprints and champion — M.** Ingest sprint classifications (a Mac probe first), then the champion
   classifiers (`KXMOTOGP` to `champion`, a stored-link change needing a backup and `link --apply`) and a season sim
   ([Championship markets](championship-markets.md#what-pricing-motogps-champion-would-take)).
8. **A naive baseline for the new sports (engine E7) — M.** `market_implied` and Plackett-Luce, so NASCAR's and
   MotoGP's simple models are measured against something before anyone reads their P&L as edge.
9. **OG.com follow-ups — S each.** A VM recorder timer (the API keeps about a month), confirm the $0.02 fee,
   per-Grand-Prix contract rules once a race market is live, join OG.com to the U7 disagreement log. Trading only
   after FCM onboarding.
10. **Road cycling, Le Mans, SailGP tapes — schemas built (#50), first VM run open.** A model for any of them is L
    and 2027 at the earliest; road cycling needs a results source whose terms allow it first.
11. **XCO / XCC ingest — M, 2027.** Only if a venue ever lists mountain biking.

Done since the 29 Sep version of this page: Kalshi in the signal engine (#34); NASCAR and MotoGP results, identity
and links on the VM (#60–#69, #75, #77, #98, #100); the NASCAR and MotoGP taker replay (#82, #84); OG.com as a replay
venue and buy-all (#88); dead-book 0.50 prices removed (#89, #90); syncs seed their sport's competition (#57); the
board's exchange data counts over the Parquet archive (#101, #103); the `/markets/og` and `/markets/tapes` pages (#49).

## OG.com

**Corrected 2026-09-29.** An earlier draft of this page, written from 2026 reviews, said OG.com has no
public API. That is wrong. The owner found the docs and a probe from the owner's Mac confirmed them.

What it is: Crypto.com's US prediction market (CFTC contracts via Crypto.com Derivatives North America).
Its API is the "Crypto.com GEN4 FCM US B2C API" at `exchange-developer.crypto.com/fcm-b2c/v1/docs/`, which
og.com's footer links to. It is a different product from Crypto.com's crypto derivatives exchange.

**Public, no key** (100 requests per second per method per IP; a UAT sandbox at `uat-api.3ona.co` also
answers):

| Need | Endpoint under `https://api.crypto.com/fcm/v1/public/` | Note |
|---|---|---|
| Market listing | `get-events`, `get-instruments`, `get-instrument-lifecycle-states` | 12,359 events, 54,676 live instruments on 2026-09-29 |
| Prices | `get-tickers`, `get-book` | 50-level book; tick 0.01, contract size 1 |
| Trades | `get-trades` | Retained about one month |
| History | `get-ticker-histories` | 1-minute bid/ask/last; at most 31 days and 1,000 rows per call. **No candlestick endpoint for event contracts** |
| Stream | `wss://stream.crypto.com/fcm/v1/market` | No auth. Channels `book`, `ticker`, `trade`, `instrument`, `instrumentall`, `settlement`, `tradingstatus` |

**Private** endpoints (orders, positions) need FCM onboarding and HMAC-SHA256 request signing. The owner is
waiting on an API key. No API terms page was found on the docs site; the legal pages are `og.com/legal` and
`og.com/document/legal_us.pdf` (the owner checked them on 2026-09-29: the terms allow this read-only use).

**What it lists** (live instruments, sports grouping): college football 23,938, soccer 9,706, NFL 4,400, NHL
3,015, MLB 555, tennis 297, WNBA 152, golf 144, NBA 110, esports 52, **F1 20, NASCAR 17, sailing 13**,
chess 2; plus politics, culture, economics, crypto, companies and climate. **Not listed:** MotoGP, IndyCar,
any cycling or mountain bike, Le Mans.

**Where it matters to us.** Mostly F1: 20 season futures (Drivers' champion 9, Constructors' 11, expiring
2027-01-31). Per-Grand-Prix events exist (series `F12026`) but had no live instruments, so race markets will
appear only around a weekend. Liquidity is thin: the Norris and Verstappen books were asks only at 1–4¢
(1–5k contracts), no bids, about 4 trades a week. NASCAR is 17 Cup Champion contracts and SailGP 13
Championship Winner contracts. Nothing else on our list. The F1 futures are model-priced (the season forecast);
the NASCAR champion is priced only offline by the uncalibrated #93 season sim; SailGP is tape only.

**Connector built as a schema, not code (PR #44, 2026-09-29).** `exchanges/og.toml` describes the API and one
generic driver reads it, so OG.com needs no OG-specific code. It syncs the F1 futures into market links, records
the tape, minute prices and books, and prints a fair-price indicator (model fair vs quote, net of the fee). It is
read-only and off by default (`RACINGLINES_OG_VENUE=1` shows the venue). Since #88 it is also a replay venue
(`nascar replay --venue og`, `--venue all`), so its race markets flow into the replays once listed and synced; none
are listed today, and the champion replays that would read its futures are drafts (#95, #96). What is left:

1. **A recorder timer on the VM.** The API keeps about a month, so `trades` and `history` must run weekly at
   least. Effort S.
2. **Per-Grand-Prix contract rules** once a live race market has been seen (their names are unchecked). Effort S.
3. **The fee**: $0.02 per contract is from reviews; confirm it in OG.com's fee schedule.
4. **Cross-venue comparison (U7)**: OG.com joins the championship comparison once `markets/disagree.py`, which
   knows Polymarket and Kalshi only, is generalised. Effort S to M.
5. **Trading**: only after FCM onboarding, signed private endpoints and the validation rules. Not started.

Value today is low: thin F1 and NASCAR futures only, no strategy backtested on them, nothing for cycling, MotoGP or
IndyCar. The reason to record early is
history, since the API forgets after a month.

## Spot-check, 2026-09-29 (VM database, read-only)

Historical: this is the state before the first VM syncs of the new sports. The matrix above supersedes it.

Run from the owner's Mac against the live APIs and the VM's database, before the deploy of the overnight batch.
Kalshi F1: 3,793 links, 37,416 trades, 16,083 price rows, archived. OG.com, NASCAR, MotoGP and IndyCar on Kalshi:
**0 links, no archive folder**, as expected until the VM runs the syncs. Polymarket NASCAR, MotoGP, IndyCar,
Kalshi cycling and Le Mans: no schema. Kalshi's cycling and Le Mans series are still listed. Trap: total Kalshi
trades by joining `market_trades` to `market_links` on `token_id` only. `condition_id` is the whole event ticker
there, and joining on it overcounts about 20 times ([Kalshi history](kalshi-history.md)).

## What to verify on a device

Run these on the VM or the owner's Mac (both reach the venues; the cloud sandbox does not). Each is a
read-only GET. They refresh the counts in the matrix above.

Kalshi: every sports series that touches our sports, then the open and settled counts for cycling.

```bash
curl -s 'https://api.elections.kalshi.com/trade-api/v2/series?category=Sports&limit=200' \
  | python3 -c 'import sys,json; [print(s["ticker"], "|", s["title"]) for s in json.load(sys.stdin)["series"]]' \
  | grep -iE 'cycl|tour|giro|vuelta|mtb|mountain|downhill|f1|nascar|motogp|indy|sail|mans|formula|rally|ski'
```

```bash
for s in KXCYCLING KXCYCLINGSTAGE KXCYCLINGTEAM KXNASCAR KXMOTOGP KXINDYCAR; do
  for st in open settled; do
    n=$(curl -s "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=$s&status=$st&limit=200" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["markets"]))')
    echo "$s $st $n"
  done
done
```

Polymarket: what it lists for each sport.

```bash
for q in cycling "tour de france" giro vuelta "mountain bike" nascar motogp indycar "formula 1" sailgp "le mans"; do
  echo "== $q"
  curl -s "https://gamma-api.polymarket.com/public-search?q=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$q")" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(" ", e.get("slug"), "active" if e.get("active") else "closed", e.get("volume")) for e in d.get("events", [])[:15]]'
done
```

OG.com: this was probed on 2026-09-29. To refresh its F1 and NASCAR counts:

```bash
curl -s 'https://api.crypto.com/fcm/v1/public/get-events' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps(d)[:1500])'
```

Write the answers into the matrix above.

## Calendar: what could be listed before year end

| When | Event | Venue that may list it | Our side |
|---|---|---|---|
| 2–4 Oct | F1 round 16, Sepang | Kalshi (Polymarket dark) | A, C ready; K frozen; private book as T3 |
| every Oct weekend | NASCAR Chase (Las Vegas, Charlotte Roval, Phoenix, Talladega, Martinsville) | Kalshi, Polymarket per-race | Recorded only when synced by hand (no timer); simple baseline, replay only |
| 10 Oct | Il Lombardia (last monument) | Kalshi `KXCYCLING` likely, Polymarket maybe | Nothing; item 4 would record it |
| 14–18 Oct | UCI Track Worlds, Shanghai | Probably none | Nothing |
| 9–11 Oct, 23–25 Oct, 30 Oct–1 Nov | F1 rounds 17–19 | Kalshi | As round 16, sprints from U5 |
| 6–8 Nov | F1 São Paulo, NASCAR finale (Homestead), MotoGP Qatar | Kalshi; Polymarket for NASCAR | F1 live; NASCAR and MotoGP replay only |
| 20–22 Nov, 27–29 Nov, 4–6 Dec | F1 Las Vegas, Qatar, Abu Dhabi; MotoGP Portugal, Valencia | Kalshi | F1 live; MotoGP replay only |
| from 23 Nov | UCI Cyclocross World Cup (Tábor, then weekly to Christmas) | Probably none | Nothing |
| Spring 2027 | Classics, Giro, UCI MTB World Cup opener | Kalshi cycling series, Polymarket | Decide over the winter from the 2026 tapes |
