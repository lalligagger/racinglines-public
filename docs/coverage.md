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

**How this was checked.** The repo side (schemas in `sports/*.toml`, `racinglines/markets/venues.py`,
`markets/kalshi/sync.py`, `live/`, the docs) was read directly. The live-listing side (what each venue
lists today, OG.com's pages) comes from web search results only: the cloud session cannot reach
og.com, Kalshi's or Polymarket's APIs, and a device probe was not possible from this thread. Every
line marked *unverified* needs the one-command checks in [What to verify on a device](#what-to-verify-on-a-device).

## The venues

| Venue | What it is | Can we read it? | Can we trade it? | Take |
|---|---|---|---|---|
| **Polymarket** | Crypto exchange, CLOB, public Gamma + CLOB APIs, full trade and price history | Yes: `markets sync/record/archive`, 2025–26 F1 history | Yes (paper today; V2 order path built, `POLYMARKET_TRADING_ENABLED` unset) | Our first venue. **Has listed no F1 race since 28 Aug 2026** ([F1 live roadmap](f1-live-roadmap.md#polymarket-has-stopped-listing-f1-races)). Championships still deep |
| **Kalshi** | CFTC exchange, public REST API with candlesticks and trades, per-market maker fee | Yes: `markets --exchange kalshi`, 2025–26 F1 history ([Kalshi history](kalshi-history.md)) | Yes (paper; `KALSHI_TRADING_ENABLED` unset) | Listed every 2025–26 F1 weekend. The likeliest live venue this autumn |
| **OG.com** | Crypto.com's US prediction market, launched 3 Feb 2026, CFTC contracts via Crypto.com Derivatives North America (the former Nadex). Sports-first, parlays, $0.02 flat fee per contract, market orders only | **No public API**, no order-book depth or volume shown, no historical data layer (per the 2026 reviews; *unverified* against the site itself) | Not programmatically. Web and app only | Not a connectable venue today. Watch it; a Kalshi-shaped connector is not possible until it publishes an API. See [OG.com](#ogcom) |
| **Private book** | Our own simulated pool (`racinglines live`), the demo maker quoting to a simulated crowd and the demo taker | Yes, replayable to the fill | Yes (the T3 tier) | The fallback where no venue lists the event. Proves pricing, not an edge |

Other venues seen in the search results and **not** tracked: Robinhood's prediction-market tab (Kalshi's
contracts resold, so covered by Kalshi), FanDuel Predicts (CME and OG contracts), PrizePicks (picks, not a
book), Octagon. None adds a market Kalshi or Polymarket doesn't already list.

## The grid

Legend: **✓** yes · **~** partly (the note says what) · **✗** no · **–** the venue lists nothing for the
sport · **?** unverified from the cloud. Each cell is H / B / L.

| Sport (schema) | Polymarket | Kalshi | OG.com | Private book | Data source and model |
|---|---|---|---|---|---|
| **F1** (`f1`) | H ✓ 2025–26, 7,285 links · B ✓ A (taker) and C (maker), params-4h · L ✓ signal engine, but **no race listed since 28 Aug** | H ✓ 2025–26, 3,793 links · B ✓ C replayed, K tuned ([Profile K](kalshi-history.md#profile-k), frozen pending owner review) · L ~ U1 done (`venue = kalshi`), **U2 recorder on the VM not running** | H ✗ · B ✗ · L ✗ · listings ? (Crypto.com has an F1 sponsorship; reviews name a motorsport category) | H ✓ Baku test · B ✓ same profiles · L ✓ `live/f1/2026-16.toml` … `2026-23.toml` | FastF1 (network-blocked in the cloud). `position_sim` |
| **UCI downhill** (`mtb_dh`) | – | – (no series found; *unverified*) | – ? | H ✓ Whistler 2026 (7,703 fills) · B ✓ walk-forward, 43 rounds ([Evaluation](evaluation.md)) · L ✓ `racinglines mtb_dh live` | ChronoRace feed (primary) + PDF backfill. `timed_runs`. Season is over; next World Cup spring 2027 |
| **UCI XCO / XCC** (none) | – | – ? | – ? | ✗ no model (the downhill live core is time-based, XCO is a mass start) | ChronoRace serves XC on the same weekend slugs (`_mtb`, once `_xco`): results are fetchable, nothing is ingested |
| **UCI road: grand tours, monuments, Worlds** (none) | H ✗ · listings ✓ Tour de France 2026 winner and top-3 (search results), Vuelta unclear · B ✗ · L ✗ | H ✗ · listings ✓ series `KXCYCLING` (race winner: `-26TDFR`, `-26GIRO`), `KXCYCLINGSTAGE` (every TdF stage), `KXCYCLINGTEAM` · B ✗ · L ✗ | ? | ✗ | No source, no schema, no model. ProCyclingStats is the obvious results source (terms to check). Next listings that could exist: Il Lombardia 10 Oct, then the 2027 spring classics and Giro |
| **UCI track, cyclocross, BMX, gravel** (none) | – ? | – ? (no series found in search) | – ? | ✗ | No source. Track Worlds 14–18 Oct (Shanghai), Cyclocross World Cup from 23 Nov. Expect no markets; confirm once |
| **NASCAR Cup** (`nascar`, tape-only) | H ✗ · **listings ✓ per-race winner markets** (Hollywood Casino 400, 27 Sep 2026) and futures · B ✗ · L ✗ | H ~ U9 sync built (#26), `KXNASCAR*`, fixture-tested only, **never run live** · B ✗ · L ✗ | ? | ✗ | No source (P2 research item), no model. Chase races every October weekend, finale Homestead 8 Nov |
| **MotoGP** (`motogp`, tape-only) | H ✗ · listings ✓ championship winner (25 outcomes) · B ✗ · L ✗ | H ~ U9 sync built, `KXMOTOGP*`, never run · B ✗ · L ✗ | ? | ✗ | No source, no model. Qatar–Valencia rounds Nov |
| **IndyCar** (`indycar`, tape-only) | H ✗ · listings ✓ championship winner, Indy 500 · B ✗ · L ✗ | H ~ U9 sync built, `KXINDYCAR*`, never run · B ✗ · L ✗ | ? | ✗ | Season over (Sept). Nothing to record until March 2027 |
| **SailGP, WEC / Le Mans, Formula E, rally, alpine skiing** (none) | ? | ? | SailGP ✓ (OG has SailGP event contracts through its US SailGP team partnership) · rest ? | ✗ | Not in scope; noted so the search was complete |

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
6. **OG.com — S to scout, blocked to build.** No API means no connector. The item is a one-off manual
   scout of what it lists for F1, NASCAR and cycling, and a quarterly check for an API announcement.
   If one appears, the connector is Kalshi-shaped: client, sync, archive tree, fee model, `Venue` entry
   (about M, the Kalshi connector took two PRs). See [OG.com](#ogcom).
7. **XCO / XCC ingest — M, 2027.** ChronoRace already serves it on the same slugs the downhill ingest
   probes. Worth it only if a venue ever lists MTB, which none does; otherwise a private-book showcase
   like downhill. Off the list until then.
8. **Confirm the "–" cells — S.** One device or VM session to run the checks below and turn every **?**
   into a fact. Cheapest item on this page and the one that changes the others.

Not gaps: horse racing (blocked by law on both venues), track / cyclocross / BMX (no markets expected),
alpine skiing and the rest of the last row (out of scope).

## OG.com

What the search results say (2026 reviews; *unverified* against the site, which the cloud cannot open):

- Launched 3 Feb 2026 by Crypto.com. Contracts are CFTC-regulated, cleared through Crypto.com
  Derivatives North America (formerly Nadex). Available in the US, all states except where prediction
  markets are barred (New York and Arizona are named).
- Sports-first: major US leagues, bigger international events, and a "smattering of niche events", plus
  crypto, economics, politics and culture. Parlays across contracts. A motorsport category is implied by
  Crypto.com's F1 sponsorship and named in one review; SailGP contracts are confirmed through the US
  SailGP team partnership. FanDuel Predicts resells OG's contracts since June 2026.
- **No public API, no order-book depth or volume shown, no historical data, market orders only,
  $0.02 flat fee per contract.** That rules out everything the Kalshi connector does: syncing links,
  recording candlesticks and trades, replaying the maker, and sending an order.

So OG.com goes in the grid as a venue we cannot read or trade, and the roadmap item is to watch it. If
the owner wants a manual read of its F1 or cycling prices as a third opinion for the disagreement log
(U7), that is a spreadsheet, not code.

## What to verify on a device

Run these on the VM or the owner's Mac (both reach the venues; the cloud sandbox does not). Each is a
read-only GET. They settle the **?** cells and the *unverified* lines above.

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

OG.com: the sports it lists and whether any JSON endpoint serves them without a login.

```bash
curl -sL https://og.com/sports | grep -oE '(Motorsport|Formula|F1|NASCAR|MotoGP|IndyCar|Cycling|Tour de France|SailGP)[^<"]{0,40}' | sort -u
curl -sL https://og.com/sports | grep -oE 'https?://[a-z0-9./_-]*(api|graphql)[a-z0-9./_-]*' | sort -u
```

Write the answers into this page's grid and drop the *unverified* marks.

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
