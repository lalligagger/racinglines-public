# Coverage: every sport, every venue

One grid, written 2026-09-29, of every sport racinglines has data for or could reasonably take on, crossed
with every venue that could list it, and for each cell three questions:

- **H** · is there **historical market data** in our database or archive (`market_links`,
  `market_price_history`, `market_trades`, `data/archive/markets/<exchange>/`)?
- **B** · is there a **backtested and optimised strategy** on that venue's tape (a Lab candidate or a frozen
  profile, judged by the rules in [Paper trading](paper-trading.md#validation-plan))?
- **L** · is a **live strategy wired up** for the next events (the signal engine or `racinglines live`
  can run it this weekend with nobody writing code)?

The gaps below are roadmap items with effort estimates, not work in progress. Nothing here runs by
default, and no new sweep or connector starts without the owner's say ([Roadmap](todo.md#new-sports)).

**Updated 2026-09-29, after the overnight batch (PRs #23–#45).** Since this grid was first written: Kalshi is in the
signal engine (U1, #34), the recorder-side tape syncs for NASCAR, MotoGP and IndyCar exist (U9, #26), OG.com is a
schema connector (#44), and Kalshi maker profile K is tuned ([Kalshi history](kalshi-history.md#profile-k)). What did
not change: nothing has run live on the VM yet. A spot-check of every combo below is written up as a handoff
(`handoffs/2026-09-29-spot-check-exchange-coverage.md` in the project files).

**How this was checked.** The repo side (schemas in `sports/*.toml`, `racinglines/markets/venues.py`,
`markets/kalshi/sync.py`, `live/`, the docs) was read directly. The venue side was probed read-only from the
owner's Mac on 2026-09-29 (unauthenticated GETs against OG.com's, Kalshi's and Polymarket's public
endpoints), because the cloud session cannot reach them. Counts are a snapshot of that evening. Cells still
marked **?** were not probed.

## The venues

| Venue | What it is | Can we read it? | Can we trade it? | Take |
|---|---|---|---|---|
| **Polymarket** | Crypto exchange, CLOB, public Gamma + CLOB APIs, full trade and price history | Yes: `markets sync/record/archive`, 2025–26 F1 history | Yes (paper today; V2 order path built, `POLYMARKET_TRADING_ENABLED` unset) | Our first venue. **Has listed no F1 race since 28 Aug 2026** ([F1 live roadmap](f1-live-roadmap.md#polymarket-has-stopped-listing-f1-races)). Championships still deep |
| **Kalshi** | CFTC exchange, public REST API with candlesticks and trades, per-market maker fee | Yes: `markets --exchange kalshi`, 2025–26 F1 history ([Kalshi history](kalshi-history.md)) | Yes (paper; `KALSHI_TRADING_ENABLED` unset) | Listed every 2025–26 F1 weekend. The likeliest live venue this autumn |
| **OG.com** | Crypto.com's US prediction market, launched 3 Feb 2026, CFTC contracts via Crypto.com Derivatives North America (the former Nadex). Sports-first, parlays, $0.02 flat fee per contract | **Yes, public market data with no key**: the "Crypto.com GEN4 FCM US B2C API" (`api.crypto.com/fcm/v1/public/*`), 50-level book, trade tape, 1-minute bid/ask/last history, WebSocket. History is short: 31 days per call, trades kept about a month | Not without **FCM onboarding** and HMAC-SHA256 request signing (owner is waiting on an API key) | Readable now, tradable later. Its F1, NASCAR and SailGP books are thin. See [OG.com](#ogcom) |
| **Private book** | Our own simulated pool (`racinglines live`), the demo maker quoting to a simulated crowd and the demo taker | Yes, replayable to the fill | Yes (the T3 tier) | The fallback where no venue lists the event. Proves pricing, not an edge |

Other venues seen in the search results and **not** tracked: Robinhood's prediction-market tab (Kalshi's
contracts resold, so covered by Kalshi), FanDuel Predicts (CME and OG contracts), PrizePicks (picks, not a
book), Octagon. None adds a market Kalshi or Polymarket doesn't already list.

## The grid

Legend: **✓** yes · **~** partly (the note says what) · **✗** no · **–** the venue lists nothing for the
sport · **?** not probed. Each cell is H / B / L.

| Sport (schema) | Polymarket | Kalshi | OG.com | Private book | Data source and model |
|---|---|---|---|---|---|
| **F1** (`f1`) | H ✓ 2025–26, 7,285 links · B ✓ A (taker) and C (maker), params-4h · L ✓ signal engine, but **no race listed since 28 Aug** | H ✓ 2025–26, 3,793 links (29 `KXF1*` series, `KXF1RACE` 22 open) · B ✓ C replayed, K tuned ([Profile K](kalshi-history.md#profile-k), frozen pending owner review; **2026 +$490, 2025 +$659**) · L ~ U1 done (`venue = kalshi`, #34), U5 sprints (#36, behind a switch) and the reconcile / scorecard checks built, **U2 recorder on the VM not running** | H ✗ (API keeps about a month) · B ✗ · L ✗ · **20 season futures listed** (Drivers' and Constructors', expire 2027-01-31); per-GP events exist but had no live instruments; books thin, asks only at 1–4¢, about 4 trades a week | H ✓ Baku test · B ✓ same profiles · L ✓ `live/f1/2026-16.toml` … `2026-23.toml` | FastF1 (network-blocked in the cloud). `position_sim` |
| **UCI downhill** (`mtb_dh`) | – (probed: nothing on mountain bike) | – (probed: no series) | – (probed) | H ✓ Whistler 2026 (7,703 fills) · B ✓ walk-forward, 43 rounds ([Evaluation](evaluation.md)) · L ✓ `racinglines mtb_dh live` | ChronoRace feed (primary) + PDF backfill. `timed_runs`. Season is over; next World Cup spring 2027 |
| **UCI XCO / XCC** (none) | – (probed) | – (probed) | – (probed) | ✗ no model (the downhill live core is time-based, XCO is a mass start) | ChronoRace serves XC on the same weekend slugs (`_mtb`, once `_xco`): results are fetchable, nothing is ingested |
| **UCI road: grand tours, monuments, Worlds** (none) | H ✗ · listings ✓ Tour 2026 (about $1.3M volume), Vuelta, Il Lombardia · B ✗ · L ✗ | H ✗ · **settled history ✓ at least 200 markets in each of `KXCYCLING`, `KXCYCLINGSTAGE`, `KXCYCLINGTEAM`, `KXCYCLINGJERSEY`, plus `KXTOURDEFRANCE`**; 0 open now · B ✗ · L ✗ | – (probed: no cycling) | ✗ | No source, no schema, no model. ProCyclingStats is the obvious results source (terms to check). Next listings that could exist: Il Lombardia 10 Oct, then the 2027 spring classics and Giro |
| **UCI track, cyclocross, BMX, gravel** (none) | – ? | – ? | – (probed) | ✗ | No source. Track Worlds 14–18 Oct (Shanghai), Cyclocross World Cup from 23 Nov. Expect no markets; not probed beyond OG.com |
| **NASCAR Cup** (`nascar`, tape-only) | H ✗ · **listings ✓ per-race winner markets** and futures · B ✗ · L ✗ | H ~ U9 sync built (#26, merged), `KXNASCAR*` (17 series, **`KXNASCARRACE` 72 open**), fixture-tested only, **never run live** · B ✗ · L ✗ | H ✗ · **17 Cup Champion futures only** | ✗ | No source (P2 research item), no model. Chase races every October weekend, finale Homestead 8 Nov |
| **MotoGP** (`motogp`, tape-only) | H ✗ · listings ✓ championship winner (25 outcomes) **and per-race Grand Prix winners** (Germany, Netherlands, Czechia, about $34k–$100k volume each, seen 2026-09-29) · B ✗ · L ✗ | H ~ U9 sync built, `KXMOTOGP*` (3 series, 22 open), never run · B ✗ · L ✗ | – (probed: not listed) | ✗ | No source, no model. Qatar–Valencia rounds Nov |
| **IndyCar** (`indycar`, tape-only) | H ✗ · listings ✓ championship winner, Indy 500 · B ✗ · L ✗ | H ~ U9 sync built, `KXINDYCAR*` (9 series), never run · B ✗ · L ✗ | – (probed: not listed) | ✗ | Season over (Sept). Nothing to record until March 2027 |
| **SailGP, Le Mans, Formula E, rally, alpine skiing** (none) | SailGP, Le Mans ✓ listed | SailGP ✓ (`KXSAILGP` 13 open, `KXSAILGPRACE` 13), Le Mans ✓ (`KXLEMANS24H`) | SailGP ✓ 13 Championship Winner contracts | ✗ | Not in scope; noted so the search was complete |

Reading across: **F1 is the only sport with all three marks on any real venue**, and only on Polymarket,
which is not listing. On Kalshi F1 is one step short (the VM recorder). Everything else is either private
book only (downhill) or has markets and nothing on our side (road cycling, NASCAR, MotoGP, IndyCar).

## The gaps, ranked

Effort: **S** under a day, **M** one to three days, **L** a week or more. Each is a roadmap item; none is
started.

1. **Kalshi recorder on the VM (U2) — S.** The only thing between F1-on-Kalshi and a full row. Needs the VM
   or the owner's device (Kalshi is network-blocked in the cloud). Already P0 in [Roadmap](todo.md#priorities).
2. **Run the NASCAR / MotoGP tape sync for real (U9) — S.** The code shipped in #26 and has never seen the
   live API. One command on the VM per sport, then a timer. Every October Chase weekend not recorded is
   a weekend of 2027 backtest data lost.
3. **Polymarket tapes for NASCAR, MotoGP, IndyCar — M.** New since the strategy session: Polymarket lists
   per-race NASCAR winners and MotoGP / IndyCar futures. The Polymarket sync knows F1 only
   (`markets/polymarket/links.py`); the tape-only path exists for Kalshi. Generalise the Polymarket sync to
   a named sport the way U9 did for Kalshi (`[markets.polymarket]` in `sports/<code>.toml`, links
   `unmodeled`). Then the December "NASCAR for 2027?" call has both venues' tapes.
4. **UCI road cycling as a tape-only sport — S for Kalshi, M with Polymarket.** A `sports/road_cycling.toml`
   with `model_family = "none"` and `[markets.kalshi] series = ["KXCYCLING", "KXCYCLINGSTAGE",
   "KXCYCLINGTEAM"]` records Kalshi's tapes with no other code (the U9 path). Include closed 2026 markets
   (`--include-closed`) to pull the Tour, Giro and Vuelta history Kalshi still serves. Polymarket's cycling
   markets come with item 3. This is the owner's "all UCI cycling events" ask at its cheapest.
5. **A road-cycling model — L, 2027.** Stage racing is a different problem from a timed run or a
   position sim (GC vs stage, teams, breakaways). Decide after the 2026 tapes show volume; the
   grand-tour winner markets look like the only deep ones. Results source and its terms first
   ([Data](data.md)), then a `[sport]` schema. Not before the F1 and downhill validations are done.
6. **OG.com: connector built (PR #44, a schema); recorder and trading open.** A VM recorder timer is S. Trading is
   blocked on FCM onboarding and the owner's API key. See [OG.com](#ogcom).
7. **XCO / XCC ingest — M, 2027.** ChronoRace already serves it on the same slugs the downhill ingest
   probes. Worth it only if a venue ever lists MTB, which none does; otherwise a private-book showcase
   like downhill. Off the list until then.
8. **OG.com follow-ups — S each.** A VM recorder timer (trades, history and books at least weekly, since the API
   keeps about a month), confirm the $0.02 fee in OG.com's fee schedule, per-Grand-Prix contract rules once a race
   market is live, join OG.com to the U7 disagreement log.
9. **A browse page for schema exchanges — done (PR #49, 2026-09-29).** `/markets/og` (and one page per future
   schema exchange, from `exchanges/`) lists the venue's markets with the fair-price indicator, behind
   `RACINGLINES_OG_VENUE=1`; `/markets/tapes`, behind `RACINGLINES_TAPES=1`, lists the tape-only sports' markets and
   what has been recorded. Not verified on real rows until the VM's first syncs have run.
10. **Confirm the "–" cells — S.** One device or VM session to run the checks below and turn every **?**
   into a fact. Cheapest item on this page and the one that changes the others. The spot-check handoff covers it.

Not gaps: horse racing (blocked by law on both venues), track / cyclocross / BMX (no markets expected),
alpine skiing and the rest of the last row (out of scope).

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

**Where it matters to us.** Only F1: 20 season futures (Drivers' champion 9, Constructors' 11, expiring
2027-01-31). Per-Grand-Prix events exist (series `F12026`) but had no live instruments, so race markets will
appear only around a weekend. Liquidity is thin: the Norris and Verstappen books were asks only at 1–4¢
(1–5k contracts), no bids, about 4 trades a week. NASCAR is 17 Cup Champion contracts and SailGP 13
Championship Winner contracts. Nothing else on our list.

**Connector built as a schema, not code (PR #44, 2026-09-29).** `exchanges/og.toml` describes the API and one
generic driver reads it, so OG.com needs no OG-specific code. It syncs the F1 futures into market links, records
the tape, minute prices and books, and prints a fair-price indicator (model fair vs quote, net of the fee). It is
read-only and off by default (`RACINGLINES_OG_VENUE=1` shows the venue). What is left:

1. **A recorder timer on the VM.** The API keeps about a month, so `trades` and `history` must run weekly at
   least. Effort S.
2. **Per-Grand-Prix contract rules** once a live race market has been seen (their names are unchecked). Effort S.
3. **The fee**: $0.02 per contract is from reviews; confirm it in OG.com's fee schedule.
4. **Cross-venue comparison (U7)**: OG.com joins the championship comparison once `markets/disagree.py`, which
   knows Polymarket and Kalshi only, is generalised. Effort S to M.
5. **Trading**: only after FCM onboarding, signed private endpoints and the validation rules. Not started.

Value today is low: thin F1 futures only, nothing for cycling, MotoGP or IndyCar. The reason to record early is
history, since the API forgets after a month.

## Spot-check, 2026-09-29 (VM database, read-only)

Run from the owner's Mac against the live APIs and the VM's database, before the deploy of the overnight batch.
Kalshi F1: 3,793 links, 37,416 trades, 16,083 price rows, archived. OG.com, NASCAR, MotoGP and IndyCar on Kalshi:
**0 links, no archive folder**, as expected until the VM runs the syncs. Polymarket NASCAR, MotoGP, IndyCar,
Kalshi cycling and Le Mans: no schema. Kalshi's cycling and Le Mans series are still listed. Trap: total Kalshi
trades by joining `market_trades` to `market_links` on `token_id` only. `condition_id` is the whole event ticker
there, and joining on it overcounts about 20 times ([Kalshi history](kalshi-history.md)).

## What to verify on a device

Run these on the VM or the owner's Mac (both reach the venues; the cloud sandbox does not). Each is a
read-only GET. They refresh the counts and settle the remaining **?** cells.

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

Write the answers into this page's grid and drop the remaining **?** marks.

## Calendar: what could be listed before year end

| When | Event | Venue that may list it | Our side |
|---|---|---|---|
| 2–4 Oct | F1 round 16, Sepang | Kalshi (Polymarket dark) | A, C ready; K frozen; private book as T3 |
| every Oct weekend | NASCAR Chase (Las Vegas, Charlotte Roval, Phoenix, Talladega, Martinsville) | Kalshi, Polymarket per-race | Tape only, once U9 runs |
| 10 Oct | Il Lombardia (last monument) | Kalshi `KXCYCLING` likely, Polymarket maybe | Nothing; item 4 would record it |
| 14–18 Oct | UCI Track Worlds, Shanghai | Probably none | Nothing |
| 9–11 Oct, 23–25 Oct, 30 Oct–1 Nov | F1 rounds 17–19 | Kalshi | As round 16, sprints from U5 |
| 6–8 Nov | F1 São Paulo, NASCAR finale (Homestead), MotoGP Qatar | Kalshi; Polymarket for NASCAR | F1 live; the rest tape |
| 20–22 Nov, 27–29 Nov, 4–6 Dec | F1 Las Vegas, Qatar, Abu Dhabi; MotoGP Portugal, Valencia | Kalshi | F1 live; MotoGP tape |
| from 23 Nov | UCI Cyclocross World Cup (Tábor, then weekly to Christmas) | Probably none | Nothing |
| Spring 2027 | Classics, Giro, UCI MTB World Cup opener | Kalshi cycling series, Polymarket | Decide over the winter from the 2026 tapes |
