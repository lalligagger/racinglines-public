# Fantasy trading: exchange markets and private books

**Status:** draft for the owner, Tue 2026-09-29. Nothing on this page is built yet. Every feature is behind a switch
that is off by default.

From the soft launch (Thu 8 Oct 18:00 PDT [Fri 9 Oct 01:00 UTC]), invited players trade F1 with F$, which is paper
money. There are two ways to trade. A **taker** makes exchange paper trades: orders fill against Kalshi's or
Polymarket's live order book at the real prices, and the result is stored only in our own tables. A **maker** quotes
the in-app private book, and human takers bet against those quotes. This page covers both paths: the fill and fee rules,
the tables, settlement, anti-abuse, the pages and the tests. It also covers what stays untouched: the order path
(`racinglines/markets/polymarket/trade.py`, `racinglines/markets/kalshi/trade.py`), the frozen profiles A, C and K, the
demo records and the goldens. The sprint plan is indexed in
[Fantasy soft launch](fantasy-launch.md); every decision (DEC-n), STAGE-1 and the launch blocks are in the
[runbook](fantasy-runbook.md). Accounts, seasons, the ledger and stats are in
[Fantasy accounts](fantasy-accounts.md). The timers and backups this relies on are in
[VM reliability](vm-reliability.md). Mail is in [Email setup](email-setup.md).

## Ground rules

| Rule | How it is held |
|---|---|
| Paper money only (F$). No cash value, no prizes (DEC-1). | Copy says F$ everywhere. `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are never read, set or proposed by anything here. |
| Fantasy code never reaches the order path. | `racinglines/fantasy/*.py` and `racinglines/markets/books.py` (new) never import `polymarket/trade.py` or `kalshi/trade.py`, and never call `post_order`. A new guard test sits next to `test_signal_code_never_touches_the_order_path` in `tests/test_signals.py`. A second, runtime check is in `tests/test_fantasy_exchange.py`. |
| Takers never see fair value or edge. | Taker pages show venue prices, maker quotes and the maker's handle only. They show no model probability, no edge, and no strategy-profile call (a call is the model's edge in another form). |
| Human ledgers are separate. | Players' trades live in `fantasy_orders`, `fantasy_fills`, `fantasy_positions`, `house_bets` and `bankroll_entries`. They never touch `paper_positions` or `strategy_signals`, which the engine deletes and rewrites on every run (`pipelines/signals.py:532`, `pipelines/season_strategy.py:331`, `markets/crowd.py:240`, `pipelines/demo_history.py:37-39`). |
| Goldens stay byte-identical. | `git diff --stat main -- tests/golden` is empty on every PR on this page. `tests/golden/f1_maker_replay.json` is the one that NEXT-1 must keep. |
| Everything is switched off by default. | Book features: `RACINGLINES_FANTASY_BOOK`. Exchange features: `RACINGLINES_FANTASY_EXCHANGE`. Both sit under the master switch `RACINGLINES_FANTASY`. `RACINGLINES_FANTASY_EXCHANGE_MAKERS` stays 0 this sprint. |
| The global cancelled-race switch is not changed. | `RACINGLINES_CANCELLED_RACE_RULES` keeps its value. Fantasy settlement passes `rules=False` and applies the private book's void rule itself (see [Settlement](#settlement-settle-1-dec-11)). |

## What is tradable at the soft launch (DEC-20)

This is the build scope (DEC-20, batch A, due Wed 30 Sep 18:00 PDT). The final list is due Wed 7 Oct 12:00 PDT.
Kind codes are the `market_links.prediction` / `house_markets.kind` values. The race kinds (`race_*`) are defined in
`racinglines/markets/kinds.py`; the season kinds (`champion`, `constructors_champion`, `season_wins_ge`,
`standings_h2h`) are listed in `PREDICTION_KINDS` in `racinglines/db/reads.py`.

| Venue and market | Kinds | Taker at launch | Maker at launch | Later |
|---|---|---|---|---|
| Kalshi F1 race, R17 Singapore | `race_win`, `race_podium`, `race_top10`, `race_constructor_top`; `race_pole` and `race_h2h` if listed | Exchange paper trade (EXCH-1) | No (DEC-6) | Makers: NEXT-1, R19 at the earliest |
| Kalshi F1 sprint, R17 | `race_sprint_win`, `race_sprint_pole` | Only if Kalshi lists them and `RACINGLINES_KALSHI_SPRINTS=1` on the VM (DEC-12) | No | Same as above |
| Kalshi F1 season futures | `champion`, `constructors_champion` | Exchange paper trade | No | Same as above |
| Polymarket F1 season futures | `champion`, `constructors_champion` | Exchange paper trade | No | `season_wins_ge` and `standings_h2h`: owner input |
| Polymarket F1 race | none listed since 28 Aug | Same rules as Kalshi race, if a market is listed | No | |
| Private book, F1 R17 | Generated: `race_win`, `race_podium`, `race_top10`. Mirrored from Kalshi or Polymarket: `race_pole`, `race_h2h`, `race_constructor_top` | Bet (BOOK-1, BOOK-3) | Quote (BOOK-3) | Private-book season markets: owner input |
| Private book, sprint kinds | `race_sprint_win`, `race_sprint_pole` | Excluded | Excluded | Once `private_book.race_outcomes` reads the sprint rounds (it reads `race`/`final` and `qual` only today) |
| Live book (demo) | the file-based book under `data/runs/live/<run>/` | Never (DEC-9) | Never | |
| OG.com F1 | | Coming soon | Coming soon | NEXT-2, once its fee is confirmed ([Coverage](coverage.md#ogcom)) |
| NASCAR, MotoGP, IndyCar (Kalshi tapes) | `unmodeled` | Coming soon | Coming soon | NEXT-2 |
| UCI downhill | | Coming soon | Coming soon | No event until 2027 |

The tradable list is a code default in `racinglines/fantasy/exchange.py` (new). When the key is present, it is
overridden by `fantasy_seasons.notes["tradable"]` (`{"kalshi": [kinds], "polymarket": [kinds], "book": [kinds]}`).
The owner can therefore drop a venue (the DEC-7 fallback) or add a kind with `racinglines fantasy season set`
(ACC-4), with no deploy.

!!! note "Owner input: the final market list (DEC-20, DEC-12, DEC-7)"
    "More info coming." Until Wed 7 Oct 12:00 PDT this table is the build scope, not the launch list. To fill in:
    (1) Polymarket `season_wins_ge` and `standings_h2h`: in or out. (2) R17 sprint kinds: in only if Kalshi lists
    them by Wed 7 Oct. (3) Private-book season markets: in or out. (4) Kalshi: in, unless its market-data terms
    forbid showing prices to third parties (DEC-7). Then the launch is the private book plus Polymarket season
    futures.

!!! note "Owner input: season dates (DEC-4)"
    `fantasy_seasons.ends_at` stays NULL (TBD). Season futures resolve after Abu Dhabi (6 Dec), expected 7-8 Dec, so
    exchange positions on them stay open until then and count in equity at their liquidation value.

### R17 closing times (DEC-14)

A market closes at the start of the session that decides it. This applies to exchange trades and book bets alike.
Times come from the same rule as `pipelines/weekend_sweep.schedule(2026)`, which builds `closes` and `race_start`
through `core/stages.build` from `sports/f1.toml` `[stages]`. The web order path never calls `schedule()` itself:
each call imports `fastf1`, asks FastF1's servers for the schedule (falling back to the saved copy only on an error)
and rewrites `data/raw/f1/fastf1/<year>/schedule.parquet`. That is a heavy import, an unbounded network wait and a
disk write on a 2 GB box. Instead:

- EXCH-1 splits the per-row loop of `weekend_sweep.schedule` into a pure `schedule_from_frame(sch, year)` that
  `schedule()` then calls. This is a refactor with identical output: the existing weekend-sweep tests and every
  golden stay byte-identical.
- `fantasy/exchange.load_schedule(year)` (new) reads the saved `data/raw/f1/fastf1/<year>/schedule.parquet` with
  pandas and passes it to `schedule_from_frame`. There is no `fastf1` import, no network call and no write. The
  result, `{round: dict}`, is cached in-process for an hour and keyed on the file's mtime. The cache wrapper is new
  code.
- The fantasy tick (SETTLE-1) keeps the parquet fresh: once an hour it calls `weekend_sweep.schedule(2026)` inside
  its own oneshot process, with a 60 s timeout. A failure there is logged and the saved copy stays in use.

| Kinds | Close at | R17 (PDT [UTC]) |
|---|---|---|
| `race_sprint_pole` | Sprint Qualifying start (`[stages.closes]`) | Fri 9 Oct 05:30 [12:30] |
| `race_sprint_win` | Sprint start (`[stages.closes]`) | Sat 10 Oct 02:00 [09:00] |
| `race_pole` | Qualifying start (`[stages.closes]`) | Sat 10 Oct 06:00 [13:00] |
| `race_win`, `race_podium`, `race_top10`, `race_h2h`, `race_constructor_top` | Race start (`until = "Race"`) | Sun 11 Oct 05:00 [12:00] |
| `champion`, `constructors_champion` (proposed, part of DEC-14) | Paused while a Race or Sprint session runs: from its start to start + its `[sessions.schedule]` minutes + 30 | Sprint Sat 10 Oct 02:00-03:15 [09:00-10:15]; Race Sun 11 Oct 05:00-08:00 [12:00-15:00] |

`core/stages.is_open(kind, t, closes)` returns True for any kind that is missing from `closes`. The race kinds are
not listed there, because the race itself is `until`. The new helper `fantasy/exchange.closes_at(link, sched)`
therefore returns `closes.get(kind) or race_start` for every `race_*` kind. It fails closed: a race link with no
`params.event_key`, a round missing from the schedule, or a missing or unreadable parquet is refused with
`no_schedule`.

## Exchange paper trading for takers (EXCH-1)

### Price source: `racinglines/markets/books.py` (new)

This is a read-only fetcher for live order books. It never imports `polymarket/trade.py` or `kalshi/trade.py`.

| Venue | Request | Parsing |
|---|---|---|
| Kalshi | `GET /trade-api/v2/markets/{ticker}/orderbook?depth=10`, the same path as `kalshi/client.Client.orderbook`, through the Kalshi `Client`'s httpx client (its `transport` is mocked in tests) | `kalshi/sync.book_row(ticker, ob, ts, depth=10)` (existing): YES bids, and NO bids converted to YES asks at 1 - p, best first |
| Polymarket | `GET {POLYMARKET_CLOB_HOST}/book?token_id=` (default `https://clob.polymarket.com`), read from the environment directly | Its own parser, written to the same shape as `polymarket/trade.book` but never importing it: bids descending, asks ascending, `tick_size`, `min_order_size`, and the book's `timestamp` if present |

- `Book` (new dataclass): `exchange`, `token_id`, `bids` and `asks` as `[(price, size)]` best first (YES side),
  `fetched_at` (UTC), `venue_ts` (Polymarket's `timestamp`, else None) and `tick_size`.
- `get(exchange, token_id, now=None) -> Book` (new) keeps a process-local cache keyed by `(exchange, token_id)`,
  behind a lock, with at most 2,000 entries. `CACHE_S = 10`: a cached book up to 10 s old is reused. When it is older,
  `get` fetches again. If that fetch fails, a cached book up to `MAX_AGE_S = 30` s old is still served (and flagged).
  Past 30 s, `get` raises `StaleBook`. With no cache at all, it raises `BookUnavailable`.
- Timeouts: `sources/http.request` retries 5 times with waits of up to 120 s (`MAX_TRIES`, `MAX_WAIT`), which is too long for a
  web request. `books.py` calls `http.request(client, "GET", path, tries=2, params=...)` on an httpx client with a
  5 s timeout, so a player's order waits at most about 12 s. The per-host pacing in `sources/http.py`
  (`HOST_INTERVAL`) still applies.
- The list on `/fantasy/markets` shows `market_links.last_bid` / `last_ask` from the sync, with its age. It makes
  no venue call. A live book is fetched only for the market panel (`/fantasy/markets?link=<id>`) and at order time.

### Order flow: `POST /fantasy/orders`

Form fields: `market_link_id`, `side` (yes, no), `action` (buy, sell), `shares` (whole shares), `limit_price`
(0.01-0.99) and `csrf_token`. The panel prefills the limit at the best ask for a buy and the best bid for a sell.
Every step below is in `fantasy/exchange.place(...)` (new), called from the route in `racinglines/web/app.py`.

1. Gate. `RACINGLINES_FANTASY` and `RACINGLINES_FANTASY_EXCHANGE` must both be on. A request refused here writes no
   row and returns 404.
2. Per-user rate limit (in memory, one uvicorn process; see [Limits](#limits)). A refused request writes no
   order row. At most one `fantasy_order_rejected` audit row is written per user per minute.
3. Validate the input, the membership (a season role of `taker`, status `active`), the kind allow-list, the link
   (`NOT closed`, `active`, `resolved_yes IS NULL`), the closing time and the order cap.
4. Fetch the book with `books.get`. **No database lock is held during the HTTP call.**
5. In one transaction: `SELECT ... FOR UPDATE` on the player's `season_members` row, then check the balance, walk
   the book, insert `fantasy_orders` and `fantasy_fills`, upsert `fantasy_positions` and write the ledger entries.
6. Write an `activity_log` row: `fantasy_order`, with the order id, fills and fee, or `fantasy_order_rejected`, with
   the reason.
7. Redirect (303) to `/fantasy/markets?link=<id>&msg=...` with the fills, the fee and the new position.

Every refusal after step 2 still writes a `fantasy_orders` row with `status = 'rejected'` and a `reject_reason`, so
the admin pages and the report can count refusals.

### Fill model

An order fills immediately or not at all, like immediate-or-cancel. Takers only: nothing rests on a book.

- **Buy:** walk the ask levels from the best one up. At each level, take `min(level size, shares still wanted)` while the
  level price is at or below `limit_price`. Stop at the limit, at the requested shares, or at the end of the
  visible depth (10 levels).
- **Sell (close):** walk the bid levels from the best one down, at or above the limit. Selling more than the position
  holds is refused (`sell_exceeds_position`). There is no short selling.
- **One side per position:** buying NO while holding YES on the same link (or the other way round) is refused
  (`opposite_side_held`). The player sells first. This keeps positions simple, and it is what a CHECK on
  `fantasy_positions` enforces.
- **Status:** `filled` (every requested share filled), `partial` (at least one share, fewer than requested; the rest is
  cancelled), `rejected` (none).
- **Cost basis:** `fantasy_positions.cost` is the average-cost basis of the shares still held. A buy adds
  `shares x price`. A sell removes `shares x average cost`, and its realized P&L shows up only in the ledger, as the
  sell's `trade` entry minus that basis.
- **No shared depletion:** two players who buy the same level within one 10 s cache window both fill against the
  full visible size. This is a documented limitation. It is bounded by the F$100 order cap and the 50-player invite
  cap. [Open questions](#open-questions) covers it.

Worked example (Kalshi, YES asks 0.41 x 120, 0.42 x 300, 0.44 x 500; buy 200 YES, limit 0.42):

| | Shares | Price | Notional (F$) | Fee term 0.07 x C x P x (1 - P) |
|---|---|---|---|---|
| Level 1 | 120 | 0.41 | 49.20 | 2.03196 |
| Level 2 | 80 | 0.42 | 33.60 | 1.36416 |
| Order | 200 | | 82.80 | 3.39612, charged as **F$3.40** |

The ledger gets `trade` -49.20, `trade` -33.60 and `fee` -3.40. The position ends with `yes_shares` 200,
`cost` 82.80 and `fees` 3.40. If YES happens, the position settles at +200.00 (P&L +113.80); if NO, at 0.00
(P&L -86.20).

### The NO side and Polymarket's outcome-0 links

- A book is always read on the link's own token, as the YES side. The NO prices are derived from it, as
  `maker_replay.to_yes` does for trades. The NO ask levels are `1 - YES bid` (walked from the highest YES bid down).
  The NO bid levels are `1 - YES ask`. Example: YES bids 0.39 x 150 and 0.38 x 400 make NO asks 0.61 x 150 and
  0.62 x 400.
- Kalshi: one link per market ticker, and the token is the YES contract (`kalshi/sync.link_rows`), so this is exact.
- Polymarket: `polymarket/sync.py` links outcome 0 only, except `race_h2h`, which links both tokens (index 0 and 1).
  `/fantasy/markets` lists one row per `condition_id` for `race_h2h` (the outcome-0 link), the same pairing
  `private_book.mirror_event` uses. A player who wants the other driver buys NO. Positions are stored on the
  outcome-0 link, so the same bet can't be held twice through the two tokens. POST refuses the outcome-1 link
  (`kind_not_tradable`).
- Settlement reads `market_links.resolved_yes` of that same link. YES shares pay F$1 when it is true, and NO shares
  pay F$1 when it is false.

### Fees (coded assumptions for the owner to confirm)

| Venue | Rule | Source in code |
|---|---|---|
| Kalshi | `ceil_cent(0.07 x sum over fills of C x P x (1 - P))`, charged **once per order**, on buys and sells alike. For a single-level fill this equals `venue_replay.Kalshi.taker_fee(price, contracts)` exactly, and a test asserts it. | `venue_replay.Kalshi.TAKER_FEE = 0.07` |
| Polymarket | 0 | `venue_replay.Polymarket.TAKER_FEE = 0.0` (the class has no `taker_fee` method, so `fantasy/exchange.fee(exchange, fills)` (new) applies the same formula with the class's rate) |

Two examples: 10 contracts at 0.55 cost F$0.18 (0.17325 rounded up); 100 NO at 0.61 costs F$1.67. The fee is
written as one `fee` ledger entry per order. It is stored on the order's first `fantasy_fills` row, with 0 on the
others, so `sum(fantasy_fills.fee)` equals the order's fee.

!!! note "Owner input: fees"
    Confirm (a) that Kalshi's F1 markets use the 0.07 taker schedule, rounded per order and not per fill, and
    (b) that Polymarket charges no taker fee on F1 season markets. Until then, both are coded assumptions and are
    labelled that way on `/rules`.

### Limits

| Limit | Value | Where |
|---|---|---|
| Order cap | Refused when `shares x limit_price` is over `min(MAX_STAKE, fantasy_seasons.max_stake)`: F$100 (DEC-5). Fills never exceed the limit, so notional never exceeds the cap. | `fantasy/exchange.py` |
| Balance | A buy needs `shares x limit + worst-case fee` to be at most the balance, checked under the row lock | same |
| Shares | Whole shares, at least `market_links.min_size` (Kalshi 1, Polymarket usually 5) | same |
| Limit price | 0.01-0.99 (a UI confirm appears when the limit is more than 5 cents through the best price) | form and server |
| Rate | 10 orders a minute and 200 a day per user (coded defaults; tune after the staging rehearsal) | in memory, `fantasy/exchange.py` |
| Closing | [R17 closing times](#r17-closing-times-dec-14) | `fantasy/exchange.closes_at` |
| Staleness | Refused when the book is over 30 s old | `books.get` |

### Rejection reasons

`fantasy_orders.reject_reason` is String(40). These are the codes:

| Code | Meaning |
|---|---|
| `bad_input` | Side, action, shares or limit out of range |
| `not_a_member` | No `season_members` row in the open season (demo, system and most staff accounts) |
| `not_a_taker` | Season role is `maker` (exchange makers are deferred, DEC-6) |
| `member_suspended` | `season_members.status = 'suspended'` |
| `kind_not_tradable` | Kind or venue not in the tradable list, or an outcome-1 Polymarket link |
| `market_closed` | Link closed, inactive or already resolved |
| `session_started` | Past `closes_at`, or a season future during a paused session (DEC-14) |
| `no_schedule` | A race link whose round has no schedule (fails closed) |
| `book_unavailable` | The fetch failed and there is no cached book |
| `stale_book` | The cached book is over 30 s old |
| `no_liquidity` | The side is empty, or no level is within the limit |
| `over_order_cap` | `shares x limit_price` is over F$100 |
| `insufficient_balance` | The balance can't cover the worst case |
| `opposite_side_held` | Holds the other side of this link |
| `sell_exceeds_position` | Sells more shares than it holds |

`rate_limited` is only an audit reason. No order row is written for it.

### Module outline: `racinglines/fantasy/exchange.py` (new)

| Name | Does |
|---|---|
| `DEFAULT_TRADABLE` | The kind lists per venue from the matrix above. Sprint kinds only when `kalshi/sync.sprints_enabled()` |
| `tradable(season)` | `season.notes["tradable"]` if set, else `DEFAULT_TRADABLE` |
| `load_schedule(year)` | Reads the saved schedule parquet through `weekend_sweep.schedule_from_frame`; cached an hour, keyed on the file's mtime; never imports `fastf1` |
| `closes_at(link, sched)` | The closing rule above. `sched` is `load_schedule(2026)` |
| `walk(levels, shares, limit)` | A pure function: `[(price, shares)]` taken from best-first levels |
| `yes_to_no(book)` | Derives NO bids and asks from the YES book |
| `fee(exchange, fills)` | The fee rules above |
| `place(session, conn, user, season, link_id, side, action, shares, limit, now=None, get_book=books.get)` | The order flow. `get_book` is injectable for tests |
| `liquidation_value(position, link)` | YES x `last_bid`, NO x (1 - `last_ask`), the equity mark STAT-1 uses |
| `Rejected(reason)` | An exception carrying one of the codes above |

## Tables owned here

All of these ship in the single additive revision `fantasy_schema_v1` (ACC-1). The revision, the backup, the
restored-copy trial and the owner's `vm.sh deploy --migrate` are in [Fantasy accounts](fantasy-accounts.md).
Nothing on this page runs a migration.

### `fantasy_orders`, `fantasy_fills`, `fantasy_positions`

| Table | Column | Type and constraint |
|---|---|---|
| `fantasy_orders` | `id` | BigInteger PK |
| | `season_id` | FK `fantasy_seasons.id` NOT NULL, ON DELETE RESTRICT |
| | `user_id` | FK `users.id` NOT NULL, RESTRICT (deletion anonymises and never deletes rows) |
| | `market_link_id` | FK `market_links.id` NOT NULL, RESTRICT |
| | `exchange` | String(20), CHECK IN (kalshi, polymarket) |
| | `token_id` | String(100); kept so the row can still be read if a link is rebuilt |
| | `side` | String(3), CHECK IN (yes, no) |
| | `action` | String(4), CHECK IN (buy, sell) |
| | `shares_req` | Numeric(12,2), CHECK > 0 |
| | `limit_price` | Numeric(6,4), CHECK 0.01-0.99 |
| | `status` | String(10), CHECK IN (filled, partial, rejected) |
| | `reject_reason` | String(40) NULL; CHECK `(status = 'rejected') = (reject_reason IS NOT NULL)` |
| | `book` | JSONB: `{"fetched_at", "age_s", "venue_ts", "side_walked", "levels": [[p, s], ...], "best_bid", "best_ask"}` |
| | `created_at` | timestamptz, server default now(). Index `(season_id, user_id, created_at)` |
| `fantasy_fills` | `id` | BigInteger PK |
| | `order_id` | FK `fantasy_orders.id` NOT NULL, RESTRICT; indexed |
| | `season_id`, `user_id`, `market_link_id` | As on the order (FKs, RESTRICT) |
| | `exchange`, `side`, `action` | As on the order |
| | `shares` | Numeric(12,2), CHECK > 0 |
| | `price` | Numeric(6,4), CHECK > 0 AND < 1 |
| | `fee` | Numeric(12,2) NOT NULL DEFAULT 0, CHECK >= 0 (the order's fee on its first fill) |
| | `ts` | timestamptz |
| `fantasy_positions` | `id` | BigInteger PK |
| | `season_id`, `user_id`, `market_link_id` | FKs, RESTRICT. UNIQUE(season_id, user_id, market_link_id) |
| | `exchange` | As above |
| | `yes_shares`, `no_shares` | Numeric(12,2) NOT NULL DEFAULT 0, CHECK >= 0; CHECK NOT (yes_shares > 0 AND no_shares > 0) |
| | `cost` | Numeric(12,2) NOT NULL DEFAULT 0 (average-cost basis of the shares held) |
| | `fees` | Numeric(12,2) NOT NULL DEFAULT 0 |
| | `status` | String(10), CHECK IN (open, settled, void) |
| | `outcome` | Boolean NULL (NULL when an admin settles at a price) |
| | `payout` | Numeric(12,2) NULL |
| | `settled_at` | timestamptz NULL. Partial index on `(market_link_id) WHERE status = 'open'` for the tick |

### `house_markets` and `house_bets` additions

| Table | New column | Type | Use |
|---|---|---|---|
| `house_markets` | `season_id` | FK `fantasy_seasons.id` NULL | Set on markets that season makers create. NULL means demo, legacy or admin markets, which the fantasy tick never touches |
| | `closes_at` | timestamptz NULL | From the closing rule, set at generate or mirror time. The bet path checks it directly and does not wait for the tick |
| | `max_liability` | Numeric(12,2) NULL | Per-market worst-case cap. NULL means `fantasy_seasons.max_market_liability` (F$1,000, DEC-5) |
| `house_bets` | `season_id` | FK `fantasy_seasons.id` NULL | Always the market's season (enforced in `fantasy/book.py`, tested) |
| | `fair_prob_at_bet` | Float NULL | The market's `fair_prob` when the bet was taken, for stats and abuse review. Never shown to takers |
| | `settled_at` | timestamptz NULL | Set when the bet's ledger entry is written |

`house_bets.stake` and `payout` stay Float, as today. Ledger amounts are rounded to cents when they are written
(`Numeric(12,2)`).

### Migration outline (this page's part of `fantasy_schema_v1`)

```python
# migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py (ACC-1), the trading part only; upgrade order after
# fantasy_seasons / season_members / bankroll_entries, which fantasy-accounts.md defines
op.create_table("fantasy_orders", ...)        # columns and CHECKs as above
op.create_table("fantasy_fills", ...)
op.create_table("fantasy_positions", ..., sa.UniqueConstraint("season_id", "user_id", "market_link_id"))
op.add_column("house_markets", sa.Column("season_id", sa.Integer, sa.ForeignKey("fantasy_seasons.id"), nullable=True))
op.add_column("house_markets", sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True))
op.add_column("house_markets", sa.Column("max_liability", sa.Numeric(12, 2), nullable=True))
op.add_column("house_bets", sa.Column("season_id", sa.Integer, sa.ForeignKey("fantasy_seasons.id"), nullable=True))
op.add_column("house_bets", sa.Column("fair_prob_at_bet", sa.Float, nullable=True))
op.add_column("house_bets", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True))
# downgrade: drop the six columns, then fantasy_positions, fantasy_fills, fantasy_orders (reverse order)
```

Every new column is nullable, so existing `house_markets` and `house_bets` rows are unchanged. There is no backfill.

### Ledger entries written (`bankroll_entries`)

Idempotency comes from `UNIQUE(ref_table, ref_id, kind)`. `balance = SUM(amount)`.

| Event | `kind` | `amount` | `ref_table` / `ref_id` | Task |
|---|---|---|---|---|
| Exchange buy, per fill | `trade` | -shares x price | `fantasy_fills` / fill id | EXCH-1 |
| Exchange sell, per fill | `trade` | +shares x price | `fantasy_fills` / fill id | EXCH-1 |
| Exchange fee, per order | `fee` | -fee | `fantasy_orders` / order id | EXCH-1 |
| Exchange position settles | `settle` | +payout (0.00 on a loss; one per position) | `fantasy_positions` / id | SETTLE-1 |
| Exchange position voided | `refund` | +cost (basis of the held shares; fees stay paid) | `fantasy_positions` / id | SETTLE-1, ADM-1 |
| Book bet placed (taker) | `stake` | -stake | `house_bets` / bet id | BOOK-3 |
| Book bet won or lost (taker) | `payout` | +payout if won, 0.00 if lost | `house_bets` / bet id | SETTLE-1 |
| Book bet voided (taker) | `refund` | +stake | `house_bets` / bet id | SETTLE-1 |
| Book market settled (maker) | `book_pnl` | `pnl_if_yes` or `pnl_if_no` over season bets that aren't void (0.00 if void) | `house_markets` / market id | SETTLE-1 |
| Re-settle correction | `adjust` | new amount - old amount, note = the admin's reason | the original ref (one re-settle per ref; later fixes are an admin F$ adjust with no ref) | ADM-1 |

Invariants the tests assert: every settled season bet has exactly one `payout` or `refund` entry. Every settled season
market has one `book_pnl` entry. For each market, the takers' entries plus the maker's `book_pnl` sum to zero.

### EXCH-0: probe fixtures and the Kalshi read budget

This is a read-only probe from the Mac, as CLAUDE.md requires before any full run. The cloud sessions can't reach the
venues. Kalshi has listed R16 as `KXF1RACE-BAH26`.

!!! warning "The fixture folder needs an allow-list entry (decided)"
    `tests/test_no_data_in_git.py` fails on any file under `tests/fixtures/` outside `ALLOWED_DATA`, and
    `tests/fixtures/fantasy/` is not on that list today. Decision: the fixtures stay in `tests/fixtures/fantasy/`
    (the plan's name). EXCH-0 adds `"tests/fixtures/fantasy/"` to `ALLOWED_DATA` in the same change, a one-line
    edit to test infrastructure that does not change any assertion, with a `tests/fixtures/fantasy/README.txt`
    giving the source, the date and the trimming (as `tests/fixtures/market/og_README.txt` does). Because EXCH-0
    edits a test file, it is an implement task (Sonnet), not a read-only scout task. `work/exch-0` merges in P0,
    before EXCH-1 and OPS-5, which depend on it. The [runbook](fantasy-runbook.md) lists it in the same
    place.

```bash
# LOCAL (Mac) — EXCH-0 step 1: the R16 Kalshi race event's market tickers (public GET, no credentials)
cd ~/py_dev/racinglines            # the EXCH-0 branch's checkout
curl -s "https://api.elections.kalshi.com/trade-api/v2/events/KXF1RACE-BAH26?with_nested_markets=true" \
  | .venv/bin/python -c 'import json,sys; b=json.load(sys.stdin); ms=(b.get("event") or {}).get("markets") or b.get("markets") or []; [print(m["ticker"], m.get("yes_bid_dollars"), m.get("yes_ask_dollars"), m.get("volume_fp") or m.get("volume")) for m in ms]'
```

```bash
# LOCAL (Mac) — EXCH-0 step 2: one Kalshi order book with its headers and latency (the most-traded ticker from step 1)
T=<ticker>
mkdir -p tests/fixtures/fantasy
curl -s -D "$TMPDIR/kalshi_headers.txt" -w 'latency %{time_total}s\n' \
  "https://api.elections.kalshi.com/trade-api/v2/markets/$T/orderbook?depth=10" -o tests/fixtures/fantasy/kalshi_orderbook_bah26.json
grep -i -E 'ratelimit|retry-after|date' "$TMPDIR/kalshi_headers.txt"; wc -c tests/fixtures/fantasy/kalshi_orderbook_bah26.json
```

```bash
# LOCAL (Mac) — EXCH-0 step 3: an open Polymarket F1 champion token from the local database (read-only SELECT)
.venv/bin/python -c "from sqlalchemy import text; from racinglines.db.config import get_engine; print(get_engine().connect().execute(text(\"SELECT token_id, question FROM market_links WHERE exchange = 'polymarket' AND prediction = 'champion' AND NOT closed ORDER BY volume DESC NULLS LAST LIMIT 1\")).first())"
```

```bash
# LOCAL (Mac) — EXCH-0 step 4: that token's CLOB book with headers and latency
TOK=<token_id>
curl -s -D "$TMPDIR/pm_headers.txt" -w 'latency %{time_total}s\n' \
  "https://clob.polymarket.com/book?token_id=$TOK" -o tests/fixtures/fantasy/polymarket_book_f1_champion.json
grep -i -E 'ratelimit|retry-after|date' "$TMPDIR/pm_headers.txt"; wc -c tests/fixtures/fantasy/polymarket_book_f1_champion.json
```

```bash
# LOCAL (Mac) — EXCH-0 step 5: keep the fixtures small (trim to 10 levels a side if over 20 KB), then the guard test
python -m pytest tests/test_no_data_in_git.py
```

The probe fills in this table (in this doc, in the EXCH-0 PR):

| Finding | Kalshi | Polymarket |
|---|---|---|
| Levels returned at depth 10 | | |
| Price format (`*_dollars` strings or cents) | | |
| Book timestamp field | none expected (we use `fetched_at`) | `timestamp` expected |
| Rate-limit headers | | |
| Latency (3 calls) | | |

**Read budget.** The 10 s cache limits the web process to 6 book GETs a minute per ticker, however many players
trade. `sources/http.HOST_INTERVAL` limits one process to 4 GETs a second on `api.elections.kalshi.com` (0.25 s) and
about 6.7 on `clob.polymarket.com` (0.15 s). The Kalshi sync timer (OPS-5) is a separate process with its own
pacing, so the two can together reach about 8 Kalshi GETs a second. R17 is roughly 100 Kalshi race tickers
(22 win, 22 podium, 22 top 10, 11 constructor, plus pole and head-to-heads if listed). Only tickers with an open
panel or an order are fetched, and 40 of them busy at once would fill the 240 a minute. Kalshi's published read
limit is not verified here. If a 429 shows up at R16 or in staging, `CACHE_S` rises to 20 s.

## Makers on exchange markets: deferred (DEC-6, NEXT-1)

Player makers quote the private book only this season. The reasons, from the code:

- **The fill loop is inline.** `maker_replay.replay(data, p)` quotes, walks the tape and caps fills in one loop over
  stages and markets. There is no function a human's standing quote could call.
- **Golden parity.** Profiles A, C and K are scored with this replay, and `tests/golden/f1_maker_replay.json` must stay
  byte-identical. Refactoring the loop during a launch sprint risks the frozen records.
- **The tape arrives only in the signals window.** Trades are fetched by the signal engine's weekend window, so a
  human quote would fill hours late, or not at all, between windows.
- **No cancel or lifetime concept.** The replay re-posts every `step_min` and pulls quotes before each session. A
  human quote needs a lifetime, a cancel and a queue position that persist between requests.

Design sketch for NEXT-1 (Fable designs, Opus builds, R19 at the earliest, behind
`RACINGLINES_FANTASY_EXCHANGE_MAKERS`):

1. Factor the per-trade fill decision out of `replay()` into a pure function (`fill_against(quote, trade, state, p)`,
   new) that `replay()` calls. The exit test: the golden file and `tests/test_replay.py` are unchanged.
2. Add a `fantasy_quotes` table (new, a later revision) holding a player's resting bid and ask per link, with
   `placed_at`, `expires_at`, `cancelled_at` and a queue position from the latest `market_book_snapshots` row.
3. The Kalshi sync timer fetches trades for links that have live player quotes every 30 min, outside the signals
   window. Each new trade after `placed_at` goes through `fill_against`, and the fills land in `fantasy_fills` as the
   maker's side.
4. Settlement is the same as for taker positions (`resolved_yes`). The maker board ranks on settled balance.

## Private book with human makers and takers (BOOK-1, BOOK-2, BOOK-3; DEC-9)

### Which book

Players use the **private book**: the database book in `house_markets` / `house_bets`, served by
`racinglines/markets/private_book.py` and the `/book/...` routes. The **live book** (the demo maker and the simulated
crowd, `markets/crowd.py`, `data/runs/live/<run>/`) is untouched. Players never trade it, the crowd never fills a
player's quote, and `racinglines-live-f1@<event>` runs as before ([Live events](live-events.md#the-private-book-and-its-takers)).

### Maker actions and bounds

| Action | Existing code | Change | Task |
|---|---|---|---|
| Generate R17 markets from the forecast | `private_book.generate(...)`, `POST /book/quotes/generate` | One "latest forecast" rule. `latest_race_predictions` picks the forecast run by `coalesce((params->>'promoted_at')::timestamptz, created_at) DESC, id DESC`, the ordering of `db/reads.latest_forecast_run`, in place of `max(model_run_id)`. A transaction advisory lock per (maker, race) stops concurrent generates duplicating markets whose `market_link_id` is NULL, which `uq_house_market_maker` can't catch because NULLs are distinct. Player makers: kinds `race_win`, `race_podium`, `race_top10`, R17 only | BOOK-2, BOOK-3 |
| Mirror an exchange event | `private_book.mirror_event(...)`, `POST /markets/{polymarket,kalshi}/mirror` | Player mirrors skip sprint kinds and any kind outside `tradable(season)["book"]`. `season_id` and `closes_at` are set on creation | BOOK-3 |
| Reprice | `private_book.set_price(...)`, `POST /book/markets/{id}/price` | Bounds: fair 0.01-0.99, spread 0.02-0.30, and after rounding `yes_price + no_price >= 1.00`. A side over `MAX_PRICE` (0.99) stays unoffered, as today. Refused after `closes_at` | BOOK-2 |
| Open or close | `POST /book/markets/{id}/status` | Reopening after `closes_at` is refused | BOOK-3 |
| Settle | admin only, `POST /book/markets/{id}/settle` | Only `open` or `closed` markets. A re-settle needs an admin reason and writes `fantasy_resettle` | BOOK-2 |

Makers can't bet, on their own markets (`record_bet` already refuses `taker_id == maker_id`) or on anyone's, because
the season role is locked.

### Maker collateral (DEC-5)

- Worst case of a market = `-min(pnl_if_yes, pnl_if_no, 0)` over its bets that aren't void (the `worst` column of
  `private_book.book`).
- Free balance of a maker = balance - the sum of worst cases over the maker's season markets that are `open` or `closed`
  and not yet settled. Balance moves only at settlement (`book_pnl`), so collateral is a reservation, not a ledger entry.
- A bet is refused (`maker_over_capacity`) if, after it, the market's worst case would exceed its `max_liability`
  (F$1,000 by default) or the maker's free balance would go below 0. With F$10,000 a maker can carry 10 markets at the
  full cap.

### Taker bet flow

`/fantasy/book` (BOOK-1) lists open season markets with the maker's handle, the YES and NO prices and the close time.
Each has a bet form that posts to the existing `POST /book/markets/{id}/take` with `side`, `stake`, `quoted` and
`next=/fantasy/book`. After BOOK-3 the route calls `fantasy/book.take(...)` (new):

1. The gates: `RACINGLINES_FANTASY_BOOK`, a season role of `taker`, status `active`, the market's `season_id` equal to the
   open season, `status = 'open'` and `now < closes_at`.
2. `0 < stake <= min(MAX_STAKE, fantasy_seasons.max_stake)`, which is F$100.
3. `SELECT ... FOR UPDATE` on the `house_markets` row, then on both `season_members` rows (taker and maker) in
   ascending `user_id` order, so two bets can't deadlock.
4. The price-moved refusal (existing): the current `yes_price` / `no_price` must equal `quoted`.
5. The taker's balance must cover the stake. The stake is debited when the bet is placed, so balance is already net of
   open stakes. Then the maker-capacity check.
6. `private_book.record_bet(...)` with `taker_id`, then `season_id` and `fair_prob_at_bet` on the new `house_bets`
   row, and a `stake` ledger entry, all in one transaction.
7. Audit (the existing `bet_place` / `bet_rejected`). Redirect to `next`, which must start with `/fantasy/` or
   `/markets`. Today it always goes to `/markets`.

Before BOOK-3 (the R16 closed dry run, if BOOK-1 and BOOK-2 are deployed by Thu 1 Oct 12:00 PDT), bets are recorded
as today, with no F$ ledger.

### Closing, counterparties and sprint kinds

- `closes_at` uses the [closing rule](#r17-closing-times-dec-14). The tick sets `status = 'closed'` at or after it,
  but the bet and reprice paths check `closes_at` themselves, so a 10-minute tick can't leave a gap.
- The counterparty is shown by handle only: the taker sees the maker's `users.username`, and the maker sees the
  taker's (`private_book.bets` already uses `coalesce(u.username, hb.counterparty)`). Never an email.
- Sprint kinds are excluded from player generate and mirror: `private_book.race_outcomes` reads the `race`/`final`
  and `qual` rounds only, so a sprint market could never settle.

### Changes by file

| File | Change | Task |
|---|---|---|
| `racinglines/web/templates/fantasy_book.html` (new) | Taker list and bet forms. No fair, spread, EV or worst case | BOOK-1 |
| `racinglines/web/views.py`, `racinglines/web/app.py` | `GET /fantasy/book` (404 unless `RACINGLINES_FANTASY_BOOK`); `place_bet` honours `next` | BOOK-1 |
| `racinglines/markets/private_book.py` | Quote bounds in `set_price` and `generate`; `settle()` refuses statuses other than open or closed unless given `resettle_reason`; `with_for_update=True` in `record_bet` and `settle`; one latest-forecast rule; advisory lock in `generate`; `settle_from_exchange` notes name `ml.exchange` (today it always says "Polymarket") and take an optional `market_ids` (new, default None = today's behaviour) | BOOK-2 |
| `racinglines/fantasy/book.py` (new) | `take`, `capacity(maker, season)`, `closes_at_for(market)`, player generate and mirror wrappers | BOOK-3 |
| `racinglines/web/templates/house.html`, `house_market.html` | For player makers: the collateral panel (balance, open worst case, free balance, per-market cap), `closes_at`, taker handles | BOOK-3 |

## Settlement (SETTLE-1, DEC-11)

### `racinglines fantasy tick`, step by step

`racinglines/fantasy/settle.py` (new) runs from `racinglines/cli/fantasy.py`. The whole tick takes
`pg_try_advisory_lock` on a fixed key. If a previous tick is still running, it logs a line and exits 0. It only
touches rows with `season_id IS NOT NULL`, plus `fantasy_positions`.

1. **Close.** `house_markets` that are `open` with `closes_at <= now` become `closed`.
2. **Settle book markets from results.** For each race with open or closed season markets, check the race status
   first: `settlement_rules.race_status("f1", event_key, settlement_rules.db_status(conn, race_id))`.
   - `cancelled`: the private book's U8 rule, applied directly: `private_book.settle(session, id, None, "auto: race
     cancelled, private book rule: void")` for every season market of the race, generated or mirrored alike.
   - Otherwise: `private_book.settle_from_results(session, conn, race_id, market_ids=<season ids>, rules=False)`.
     `rules=False` means the environment is never read (`settlement_rules.enabled(False)` is False), so
     `RACINGLINES_CANCELLED_RACE_RULES` changes nothing here, and a relocated race (R16, the Bahrain GP at Sepang,
     `RACE_STATUS`) settles on its result. The function waits for at least 5 classified finishers.
3. **Settle mirrored markets from any exchange.** `private_book.settle_from_exchange(session, conn,
   market_ids=<season mirrored ids>)` settles those whose link has `resolved_yes`, which covers what results can't
   decide.
4. **Settle exchange positions.** For open `fantasy_positions` on links that have `resolved_yes`: payout = YES shares
   x 1 when true, NO shares x 1 when false. The status becomes `settled`, with `outcome`, `payout` and `settled_at`
   set. The position's link is refreshed first, by an on-demand closed sync when an event has ended and any of its
   links with open positions has `resolved_yes IS NULL` and `synced_at` older than 1 h:
   `kalshi/sync.sync(session, conn, 2026, include_closed=True)` or `polymarket/sync.sync(...)` with
   `include_closed=True`. That is at most once an hour per ended event. OPS-5's daily closed sync covers the rest.
5. **Ledger payouts, as a reconciliation.** Write the `payout` / `refund` / `book_pnl` / `settle` entries for
   **every** season bet, market or position that is settled or void and has no entry yet, and set
   `house_bets.settled_at`. Because this step reconciles rather than following steps 2-4, a market settled by
   another path still gets paid: the admin's `POST /book/markets/{id}/settle`, or `settle_from_exchange` through
   `pm_sync`.
6. **Stats refresh.** `fantasy/stats.py` (STAT-1) runs for the members touched in steps 4-5. The nightly `--full`
   is described in [Fantasy accounts](fantasy-accounts.md).
7. **Alerts.** Anything still unsettled 24 h after its race's scheduled start raises one ops alert per item per day
   to `RACINGLINES_OPS_NTFY_TOPIC` (OPS-2's sender).

**Backup before settling (CLAUDE.md).** Before the first settlement write for an event (steps 2-5), the tick runs
`racinglines.ops.backup` with the label `pre-settle-<event_key>` (for R17, `pre-settle-2026-17`), which writes
`data/backups/db/racinglines-before-pre-settle-2026-17-<UTC>.sql.gz`, its `data_changes` row and the bucket copy
(OPS-3). It does this once per event, and the `data_changes` row is the marker. If the dump fails, the tick settles
nothing for that event, raises one ops alert and retries at the next tick: it fails closed. The dump takes about 30 MB
and under a minute (the 29 Sep hand dump was 14.5 MB), inside the unit's 15 min timeout. Season futures use the label
`pre-settle-<season slug>-futures`.

The tick prints one line: `closed=N book_settled=N mirrored_settled=N positions_settled=N ledger_entries=N queued=N`.
The race classification reaches `results` through `signals.refresh_fastf1` (`racinglines f1 fetch` then
`racinglines f1 ingest`), which the live-f1 unit's results update and the signals timer both run.

### Idempotency and the re-settle guard

- Running the tick twice changes nothing: statuses gate steps 1-4, and `UNIQUE(ref_table, ref_id, kind)` plus the
  reconciliation query gate step 5. A test asserts this.
- `private_book.settle` refuses a market that is already `settled` or `void` unless `resettle_reason` is given
  (BOOK-2). Only `/admin/fantasy/settle` (ADM-1) passes one. A re-settle writes `fantasy_resettle` to `activity_log`,
  plus one `adjust` entry per affected bet, position or market (new amount minus old). After that, corrections go
  through an admin F$ adjust with a reason.
- A `fantasy_positions` row is settled only once. Moving it from `settled` back to `open` is not possible.

### The admin queue

`/admin/fantasy/settle` (ADM-1) lists, oldest first:

| Case | Example | Admin actions |
|---|---|---|
| Exchange link closed, `resolved_yes` NULL | Kalshi "fair price" on a race cancelled or not started within 48 h (`settlement_rules`, `FAIR`); Polymarket's 50-50 on a head-to-head | YES, NO, at a price p (payout = YES x p + NO x (1 - p)), or void (refund the cost basis) |
| Book market that results can't decide 24 h after the race | `outcome_for` returns None | YES, NO or void |
| Anything unsettled 24 h after the race | Venue resolution lag | Wait, or settle by hand with a reason |

Every action needs a reason and writes an `activity_log` row: `fantasy_settle`, or `fantasy_resettle` for a re-settle.

### Timing

| Step | R17 (PDT [UTC]) |
|---|---|
| Race start: race kinds close | Sun 11 Oct 05:00 [12:00] |
| Race classification in `results` | about 08:00 [about 15:00], about 3 h after the start |
| Pre-settle dump (`pre-settle-2026-17`) | at the first tick that has something to settle, just before it |
| Book markets settled | at the next tick, by about 08:10 [15:10] |
| Kalshi positions settled | after Kalshi resolves and the hourly closed sync picks it up. The lag is unmeasured, so R16 records it |
| Manual queue cleared (SETTLE-2) | Sun 11 Oct 18:00 [Mon 12 Oct 01:00] |
| Unsettled alert | Mon 12 Oct 05:00 [12:00], 24 h after the start |
| Season futures | after Abu Dhabi (6 Dec): expected 7-8 Dec |

### The unit (`deploy/vm/systemd/`, new)

```ini
# racinglines-fantasy.service — one fantasy tick: close, settle, stats (SETTLE-1). Started by the .timer.
[Unit]
Description=racinglines fantasy tick
After=network-online.target docker.service

[Service]
Type=oneshot
User=racinglines
WorkingDirectory=/opt/racinglines
EnvironmentFile=/etc/racinglines.env
ExecStart=/opt/racinglines/.venv/bin/racinglines fantasy tick
TimeoutStartSec=15min
```

```ini
# racinglines-fantasy.timer
[Unit]
Description=racinglines fantasy tick every 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

The owner installs and enables it. The blocks are in [VM reliability](vm-reliability.md).

**The tick ignores `RACINGLINES_FANTASY` (decided here, for SETTLE-1).** The switch only hides the pages and refuses
new orders and bets. The tick gates on the data instead: it runs whenever any `fantasy_seasons` row has status `open`,
or any season has open `fantasy_positions` or unsettled season `house_bets`, and it exits 0 with nothing to do
otherwise. The [off switch](fantasy-runbook.md#off-switch) (`RACINGLINES_SIGNUP=off` plus `RACINGLINES_FANTASY=0`)
therefore stops sign-up and trading but never settlement. The only way to stop settlement is to stop
`racinglines-fantasy.timer`. The tick touches `data/runs/heartbeat/fantasy-tick` on every run, even with nothing to do,
so the health check's "fantasy tick under 30 min" alarm fires if the timer stops while positions are open.

### Launch-weekend backups (every 6 h)

The nightly dump runs at 10:00 UTC, two hours before the R17 race closes its markets, so on its own it would miss the
busiest orders. The extra dumps are a drop-in on `racinglines-backup.timer` (04:00, 16:00 and 22:00 UTC), installed
by the owner by Thu 8 Oct 16:00 UTC and removed Tue 13 Oct: the blocks are in
[VM reliability, launch-weekend backup drop-in](vm-reliability.md#launch-weekend-backup-drop-in).

### Settle day, owner-run (SETTLE-2)

⚠️ These steps write settlement to the production database and touch a live-event unit. Each block runs in the VM
shell opened in step 1. Each block appends to the same log file.

```bash
# LOCAL (Mac) — SETTLE-2 step 1: open a shell on the VM
bash scripts/deploy/vm.sh ssh
```

```bash
# VM (production) — step 2: start the log, then check the tick has been running (read-only)
export LOG=/opt/racinglines/data/backups/r17-settle-$(date -u +%Y%m%dT%H%MZ).log
systemctl list-timers racinglines-fantasy.timer --no-pager 2>&1 | sudo tee -a "$LOG"
journalctl -u racinglines-fantasy --since "3 hours ago" --no-pager | tail -20 | sudo tee -a "$LOG"
```

```bash
# VM (production) — step 3: ⚠️ backup before clearing the manual queue (a DB write follows). The tick has already
# taken pre-settle-2026-17 before its own settlement writes; this one covers the manual queue
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines ops backup --label before-r17-settle' 2>&1 | sudo tee -a "$LOG"
```

Step 4, in the browser: `https://racinglines.bet/admin/fantasy/settle`. Clear each queued item with a reason.

```bash
# VM (production) — step 5: one tick by hand, then a second that must report all zeros (idempotency check)
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines fantasy tick && .venv/bin/racinglines fantasy tick' 2>&1 | sudo tee -a "$LOG"
```

```bash
# VM (production) — step 6: backup after settlement, then save the leaderboard into the log
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines ops backup --label after-r17-settle && .venv/bin/racinglines fantasy stats' 2>&1 | sudo tee -a "$LOG"
```

```bash
# VM (production) — step 7: ⚠️ live-event unit: disable the R17 live timer once every market is settled
sudo systemctl disable --now racinglines-live-f1@2026-17.timer 2>&1 | sudo tee -a "$LOG"
```

```bash
# VM (production) — rollback, only if settlement is wrong: stop the tick, then follow the "fantasy tick stuck or
# settlement wrong" runbook in vm-reliability.md. Compare against a restore of the tick's pre-settle-2026-17 dump on
# scratch (it holds every order up to the first automatic settlement), not the nightly dump or before-r17-settle
sudo systemctl stop racinglines-fantasy.timer 2>&1 | sudo tee -a "$LOG"
```

`racinglines ops backup` is new (OPS-3). Until it merges, use the `pg_dump` block in
[VM reliability](vm-reliability.md), which writes `data/backups/db/racinglines-before-<task>-<UTC>.sql.gz`. Either
way, the backup gets a `data_changes` row and a [Data changes](data-changes.md) line.

## Anti-abuse

| Threat | Rule | Where enforced | Task |
|---|---|---|---|
| Self-dealing: one person runs a maker and a taker and moves F$ between them through a mispriced quote | (1) One account per verified email, with the email normalised for uniqueness (lowercase; `+tag` stripped; dots stripped for `gmail.com` and `googlemail.com`; `@racinglines.bet` and known disposable domains refused), single-use invite codes each issued to one named recipient, and a season role locked for the season. `/admin/fantasy/members/{user_id}` shows which invite created the account. (2) Caps: F$100 a bet, F$1,000 worst case per market. (3) Admin review of maker-taker pairs on `/admin/fantasy`: pairs where one taker is over 50% of a maker's settled volume, or one maker over 50% of a taker's; the same IP within 90 days (`activity_log`, which a second network defeats, so it is a hint only); bets where `abs(fair_prob_at_bet - model fair) > 0.25`. The pair report is part of the ADM-1 go/no-go before the soft launch and is read again before any leaderboard is published. (4) `/rules` says that collusion or multiple accounts void the results of every account involved. There are no prizes (DEC-1), so this protects the leaderboard's fairness; any later prize needs stronger identity checks first | `fantasy/book.py`, the email normaliser in `racinglines/web/accounts.py` ([Fantasy accounts](fantasy-accounts.md)), ADM-1 report, `rules.html` | BOOK-3, ACC-3, ADM-1, LEGAL-1 |
| Latency games on a live session | Markets close at the start of the session that decides them (DEC-14). Season futures pause during Race and Sprint (proposed). Books over 30 s old are refused | `fantasy/exchange.closes_at`, `books.get`, `fantasy/book.take` | EXCH-1, BOOK-3 |
| Latency games on a repriced book quote | The price-moved refusal (existing): the `quoted` price must equal the current price | `place_bet` | BOOK-1 |
| Fat fingers | Taker: limit 0.01-0.99, the F$100 cap, a confirm when the limit is more than 5 cents through the touch. Maker: fair 0.01-0.99, spread 0.02-0.30, yes + no >= 1.00 | forms and server | EXCH-1, BOOK-2 |
| Order spam and venue read load | 10 orders a minute and 200 a day per user; the 10 s book cache; host pacing | `fantasy/exchange.py`, `sources/http.py` | EXCH-1 |
| A bad actor | `season_members.status = 'suspended'`: orders and bets refused (`member_suspended`); the maker's open markets closed; sessions ended through `session_epoch` ([Fantasy accounts](fantasy-accounts.md)). Open positions still settle, or an admin voids them | ADM-1 | ADM-1 |
| Informed flow into the crowd | Not possible: the crowd never fills a player's quote (DEC-9) | by design | |

## Pages and UI

| Route | Serves | Task |
|---|---|---|
| `/fantasy` | Balance, equity, open exchange positions at their liquidation value, open book bets, order history (with reject reasons) and settled history | STAT-2 |
| `/fantasy/markets` | Exchange markets by R17 kind, then season futures, per venue. Each row: subject, venue, bid, ask (from `market_links`, with the sync age), close time (PDT [UTC]) and the player's position. `?link=<id>` opens the live panel: 5 levels a side from `books.get`, "Prices: Kalshi, fetched 12:34:56 UTC" (DEC-7 attribution) and the order form | EXCH-1 |
| `POST /fantasy/orders` | The order flow above | EXCH-1 |
| `/fantasy/book` | Open private-book markets for the open season, maker handle, YES and NO price, close time, bet form | BOOK-1, BOOK-3 |
| `POST /book/markets/{id}/take` | Existing. Through `fantasy/book.take` after BOOK-3 | BOOK-3 |
| `/book`, `/book/quotes`, `/book/markets/{id}` | Existing maker pages, plus the collateral panel and close times for player makers | BOOK-3 |
| `/markets` | For players, it redirects to `/fantasy/markets` (ROLE-1). Demo and staff takers keep today's page | ROLE-1 |

What each role and account type sees:

| | Player taker | Player maker | Staff (admin, testers) | Demo (`maker`, `taker`) |
|---|---|---|---|---|
| `/fantasy/markets` | Trade | Read-only, with a note that makers quote the private book this season | Trade in `2026-dryrun` when a member; admin sees everything | Prices read-only, "sign up to trade", no form |
| `/fantasy/book` | Bet | Read-only | As members | Read-only |
| `/book` pages | No | Own markets | Admin: every maker | As today (writes refused in demo sessions) |
| Fair value or edge | Never | Own generated markets' fair only (they quote from it). No edge columns on race pages, and no `/markets`, `/signals` or `/live` picks (ROLE-1) | Yes | As today |
| Strategy-profile calls | Never on fantasy pages | No | Yes | As today on `/markets` |

## Switches

| Switch | Default | Effect here |
|---|---|---|
| `RACINGLINES_FANTASY` | 0 | Master switch. When 0, the `/fantasy*` routes return 404 and new orders and bets are refused. The tick ignores it and keeps closing and settling (see [The unit](#the-unit-deployvmsystemd-new)) |
| `RACINGLINES_FANTASY_BOOK` | 0 | `/fantasy/book`, and the player gates on `/take` |
| `RACINGLINES_FANTASY_EXCHANGE` | 0 | `/fantasy/markets` trading and `POST /fantasy/orders` |
| `RACINGLINES_FANTASY_EXCHANGE_MAKERS` | 0 | Stays 0 this sprint (NEXT-1) |
| `RACINGLINES_KALSHI_SPRINTS` | off (existing) | Sprint kinds are linked, and so tradable, only when on (DEC-12) |
| `MAX_STAKE` | 100 (existing) | Capped further by `fantasy_seasons.max_stake` |
| `RACINGLINES_CANCELLED_RACE_RULES` | existing | Not changed by fantasy. The tick passes `rules=False` |
| `POLYMARKET_CLOB_HOST`, `KALSHI_API_HOST` | existing | Read by `books.py` for its base URLs |

## Tests

| File | Tests (new unless marked) | Task |
|---|---|---|
| `tests/test_fantasy_exchange.py` | `test_buy_walks_ask_levels_to_the_limit`; `test_depth_cap_makes_a_partial_fill`; `test_no_side_maps_through_the_yes_book`; `test_sell_closes_at_the_bid_and_never_goes_short`; `test_opposite_side_refused`; `test_kalshi_fee_rounds_up_per_order` (0.17325 becomes 0.18, and the worked example gives 3.40); `test_single_level_fee_equals_venue_replay_taker_fee`; `test_polymarket_fee_is_zero`; `test_order_cap`; `test_cache_reused_within_10s`; `test_stale_book_refused_after_30s`; `test_closed_at_session_start` (pole at Qualifying, win at Race, sprint kinds, R17 times); `test_no_schedule_fails_closed` (including a missing parquet); `test_order_path_never_imports_fastf1`; `test_rate_limit_per_user`; `test_rejections_write_an_order_row`; `test_outcome_1_polymarket_link_refused`; `test_parses_exch0_fixtures`; `test_takers_never_see_fair_or_calls` (renders `/fantasy/markets`); `test_import_graph_has_no_order_path` (a subprocess imports `racinglines.fantasy.exchange` and `racinglines.markets.books`, then asserts neither `trade` module is in `sys.modules`); `test_paper_tables_untouched` (row counts of `paper_positions` and `strategy_signals` before and after) | EXCH-1 |
| `tests/test_signals.py` | One new test, `test_fantasy_code_never_touches_the_order_path`, next to the existing `test_signal_code_never_touches_the_order_path`. It checks the source text of every `racinglines/fantasy/*.py` and `racinglines/markets/books.py` for `polymarket.trade`, `polymarket import trade`, `kalshi.trade`, `kalshi import trade` and `post_order`. Every existing test in the file stays unchanged | EXCH-1 |
| `tests/test_private_book.py` | The first committed tests for generate, bet and settle: `test_generate_uses_the_promoted_forecast`; `test_generate_does_not_duplicate_null_link_markets`; `test_quote_bounds`; `test_take_refused_when_the_price_moved`; `test_take_refused_over_max_stake`; `test_settle_only_open_or_closed`; `test_resettle_needs_a_reason`; `test_settle_from_exchange_note_names_the_exchange`; `test_fantasy_book_hides_fair_value`; `test_fantasy_book_off_by_default` | BOOK-1, BOOK-2 |
| `tests/test_fantasy_book.py` | `test_taker_stake_debited_and_balance_checked`; `test_maker_collateral_within_free_balance`; `test_max_liability_per_market`; `test_two_bets_against_a_maker_at_capacity_one_refused` (two threads, separate sessions, Postgres); `test_closes_at_blocks_bets_before_the_tick`; `test_sprint_kinds_excluded_from_player_mirrors`; `test_bet_season_matches_market_season`; `test_counterparty_shown_by_handle`; `test_book_is_zero_sum` | BOOK-3 |
| `tests/test_fantasy_settle.py` | `test_tick_twice_changes_nothing`; `test_cancelled_race_voids_season_markets_with_the_env_switch_on_or_off`; `test_relocated_r16_settles_on_the_result`; `test_mirrored_market_settles_from_exchange_resolution`; `test_exchange_position_settles_from_resolved_yes`; `test_closed_link_without_resolution_goes_to_the_queue`; `test_market_settled_elsewhere_is_still_paid`; `test_resettle_writes_an_adjust_delta`; `test_demo_and_legacy_markets_untouched` (`season_id` NULL); `test_auto_close_at_closes_at`; `test_unsettled_after_24h_alerts_once`; `test_closed_sync_at_most_hourly`; `test_every_settled_bet_has_one_ledger_entry`; `test_tick_settles_with_the_fantasy_switch_off`; `test_tick_writes_heartbeat_when_idle`; `test_pre_settle_backup_once_per_event`; `test_backup_failure_skips_settlement_and_alerts` | SETTLE-1 |
| Unchanged | `tests/test_settlement_rules.py`, the existing tests in `tests/test_signals.py`, `tests/test_replay.py`, `tests/test_venue_replay.py` and every file in `tests/golden/` ([Testing](testing.md#golden-baselines)) | all |

Postgres tests use the `test_engine` fixture (`tests/conftest.py`: a fresh `racinglines_test` database built from
the migrations, and a skip when there is no Postgres). That fixture only covers code that is handed the engine.
**Today's app-level tests do not use it:** `tests/test_views.py` logs in through `TestClient(app)`, and the app and
CLI use `racinglines.db.config.get_engine()`, which is `lru_cache`d on `DATABASE_URL` and defaults to the dev
database, so those tests write `activity_log` rows to the dev database. Written the same way, the tests on this page
would create users, bets and F$ ledger rows there. So SEC-1 (the first P1 task to add app-level tests; see
[Fantasy accounts](fantasy-accounts.md)) adds a new fixture, `app_test_db`, in `tests/conftest.py`: it depends on
`test_engine`, sets `DATABASE_URL` to the test database before `racinglines.web.app` is imported, calls
`get_engine.cache_clear()` (and again on teardown), and yields a `TestClient`. Every new app-level or CLI test on this
page (BOOK-1, BOOK-3, EXCH-1, SETTLE-1) uses `app_test_db`, and none uses the existing `clients` fixture. Until SEC-1
merges, BOOK-1 carries the same fixture in its own branch. Venue calls are mocked, with the Kalshi `Client`'s
`transport` and an httpx mock transport for the CLOB. No test touches the network.

## Task list

The role and model for every task come from the plan. The owner merges every PR. Each task runs on its own branch
off `main` (`work/<task-id>`).

| Task | Title | Role / model | Files | Size | Depends on | Money-adjacent |
|---|---|---|---|---|---|---|
| EXCH-0 | Read-only Mac probe; save the Kalshi and Polymarket book fixtures; note depth, timestamps and rate-limit headers; add the `ALLOWED_DATA` entry | implement / Sonnet | `tests/fixtures/fantasy/kalshi_orderbook_bah26.json`, `tests/fixtures/fantasy/polymarket_book_f1_champion.json`, `tests/fixtures/fantasy/README.txt`, `tests/test_no_data_in_git.py` (one `ALLOWED_DATA` entry) | S (~10 calls) | none | No |
| BOOK-1 | `/fantasy/book` taker page and bet form, behind `RACINGLINES_FANTASY_BOOK`; first committed tests | implement / Sonnet | `racinglines/web/app.py`, `racinglines/web/views.py`, `racinglines/web/templates/fantasy_book.html`, `racinglines/web/templates/base.html`, `tests/test_private_book.py` | M (~18 calls) | none | ⚠️ bet path |
| BOOK-2 | Private-book safety fixes (bounds, settle guard, `FOR UPDATE`, latest-forecast rule, de-dup, exchange note) | implement / Sonnet (Fable reviews) | `racinglines/markets/private_book.py`, `racinglines/web/app.py`, `tests/test_private_book.py` | M (~20 calls) | BOOK-1 | ⚠️ settlement code |
| BOOK-3 | Private book for players: balances, collateral, `max_liability`, `closes_at`, `season_id`, `fair_prob_at_bet`, handles, no sprint kinds | own / Opus (Fable reviews) | `racinglines/fantasy/book.py`, `racinglines/markets/private_book.py`, `racinglines/web/app.py`, `racinglines/web/views.py`, `racinglines/web/templates/house.html`, `racinglines/web/templates/house_market.html`, `racinglines/web/templates/fantasy_book.html`, `tests/test_fantasy_book.py` | L (~35 calls) | ACC-4, BOOK-2 | ⚠️ bet and collateral rules |
| EXCH-1 | Exchange paper trading for takers | own / Opus (Fable reviews fill and fee rules) | `racinglines/fantasy/exchange.py`, `racinglines/markets/books.py`, `racinglines/pipelines/weekend_sweep.py` (the `schedule_from_frame` split only), `racinglines/web/app.py`, `racinglines/web/templates/fantasy_markets.html`, `tests/test_fantasy_exchange.py`, `tests/test_signals.py` | XL (~40 calls) | ACC-4, EXCH-0 | ⚠️ paper fill and fee logic |
| SETTLE-1 | `racinglines fantasy tick` and `racinglines-fantasy.service`/`.timer` | own / Opus (Fable reviews) | `racinglines/fantasy/settle.py`, `racinglines/cli/fantasy.py`, `deploy/vm/systemd/racinglines-fantasy.service`, `deploy/vm/systemd/racinglines-fantasy.timer`, `tests/test_fantasy_settle.py` | L (~32 calls) | BOOK-3, EXCH-1, STAT-1, OPS-5 | ⚠️ settlement plus a new VM unit |
| SETTLE-2 | Sun 11 Oct settle day: queue cleared by 18:00 PDT, backups, leaderboard snapshot, live timer off | owner / owner + Haiku | `/admin/fantasy/settle` | S | OPS-10 | ⚠️ settlement and a live-event unit |
| NEXT-1 | Makers on exchange markets | decide then own / Fable (design), Opus (build) | `racinglines/markets/strategies/maker_replay.py`, `racinglines/fantasy/exchange.py`, `tests/golden/f1_maker_replay.json` (unchanged) | XL | OWNER-10 | ⚠️ touches the replay that scores the frozen profiles |
| NEXT-2 | Tape-only sports and OG.com for takers | own / Opus | `deploy/vm/systemd/`, `racinglines/fantasy/exchange.py`, `exchanges/og.toml` | L | OWNER-10 | ⚠️ new VM units and settlement sources |

Verify, per task (LOCAL (Mac)):

| Task | Command | Done when |
|---|---|---|
| EXCH-0 | `python -m pytest tests/test_no_data_in_git.py` | Both fixtures and the README committed, each fixture under 20 KB, `tests/fixtures/fantasy/` in `ALLOWED_DATA`, and the findings table filled in |
| BOOK-1 | `python -m pytest tests/test_private_book.py tests/test_views.py -m "not live"` | `/fantasy/book` returns 404 with the switch off; a bet posts and returns to `/fantasy/book` |
| BOOK-2 | `python -m pytest tests/test_private_book.py tests/test_settlement_rules.py -m "not live"` | Bounds and guards tested; goldens unchanged |
| BOOK-3 | `python -m pytest tests/test_fantasy_book.py tests/test_private_book.py -m "not live"` | The concurrency test passes against Postgres |
| EXCH-1 | `python -m pytest tests/test_fantasy_exchange.py tests/test_signals.py -m "not live"` | Fills and fees match the EXCH-0 fixtures; the guard tests pass |
| SETTLE-1 | `python -m pytest tests/test_fantasy_settle.py tests/test_settlement_rules.py -m "not live"` | Two ticks in a row give the same database; a tick with `RACINGLINES_FANTASY=0` still settles; each event's first settlement write is preceded by its `pre-settle-<event>` dump |
| All | `racinglines check`, `python -m pytest -m "not live"`, `mkdocs build --strict`, `git diff --stat main -- tests/golden` (empty) | Before any merge is proposed |

Merge order for this page's tasks, inside the plan's sequence. EXCH-0 goes in P0. BOOK-1 and BOOK-2 form the P1 book
batch. In P2 the order is OPS-8 -> ACC-1 (OWNER-8) -> SEC-1 -> MAIL-1 -> ACC-3 -> ACC-4 -> ROLE-1 -> BOOK-3 ->
EXCH-1 -> STAT-1 -> SETTLE-1 -> STAT-2 -> ADM-1.

```bash
# LOCAL (Mac) — P0/P1: EXCH-0 fixtures, then the P1 book batch (each branch is a PR the owner merges)
git checkout main && git pull
git merge --no-ff work/exch-0            # fixtures + ALLOWED_DATA entry; test_no_data_in_git.py must pass
git merge --no-ff work/book-1            # ⚠️ needs special attention: bet path (new taker page posting to /take)
git merge --no-ff work/book-2            # ⚠️ needs special attention: settlement code (settle guard, FOR UPDATE); Fable reads the diff first
python -m pytest -m "not live" && git diff --stat main@{1} -- tests/golden
git push
```

```bash
# LOCAL (Mac) — P2: this page's branches, in the plan's slots (ACC-1, SEC-1, MAIL-1, ACC-3, ACC-4, ROLE-1 merged before; STAT-1 between)
git checkout main && git pull
git merge --no-ff work/book-3            # ⚠️ needs special attention: bet and collateral rules, ledger writes; after ACC-4 and ROLE-1
git merge --no-ff work/exch-1            # ⚠️ needs special attention: paper fill and fee logic; the order-path guard must pass
git merge --no-ff work/stat-1            # (fantasy-accounts.md) needed by SETTLE-1
git merge --no-ff work/settle-1          # ⚠️ needs special attention: settlement + new VM unit racinglines-fantasy.timer
racinglines check && python -m pytest -m "not live" && mkdocs build --strict
git diff --stat main@{1} -- tests/golden  # must print nothing
git push
```

## Open questions

| Question | Why it matters | Recommendation |
|---|---|---|
| Kalshi's read rate limit for unauthenticated market data | It sets `CACHE_S` and how many tickers can be busy at once | EXCH-0 records the headers; watch for 429s at R16 and in staging; raise the cache to 20 s if needed |
| Fee confirmation: Kalshi 0.07 rounded per order (not per fill); Polymarket 0 on F1 season markets | Every taker's P&L | Owner confirms against each venue's fee page by Wed 7 Oct. `/rules` labels them as assumptions until then |
| Informed takers in the crowd. `markets/crowd.py` is uninformed: random sides and budgets, no view on fair | Player makers may see little flow with 50 or fewer players, and human takers are their first informed counterparties | DEC-9 keeps the crowd away from players for 2026-s1. Revisit at the retro whether a later season lets a simulated crowd, including informed takers, fill player quotes |
| Should player makers see fair values? Today the maker role sees the full race page (fair, edges against every venue) | A player maker could pass fair values or edges to a taker friend | ROLE-1/DEC-10: player makers keep the model fair only on markets they generate (they need it to quote). Race pages hide fair values and edges from player makers, and `/markets`, `/signals` and `/live` picks are closed to them. ROLE-1 adds a test that a player maker cannot reach any of them. The MCP tools stay admin-only (today's default). [Fantasy accounts](fantasy-accounts.md) section 2 must say the same; the owner confirms with DEC-10 |
| Season futures during a race (DEC-14 extension) | A 10 s-old book around a crash is a latency game on `champion` | Pause during Race and Sprint, as proposed above; the owner confirms with DEC-14 |
| Shared depletion of visible depth | Two players can fill the same level | Accept for the soft launch; if the report shows it, add a per-level, per-window fill ledger |

## Names used across these docs

The subset of the conventions block this page uses, copied word for word. The master copy is in
[Fantasy soft launch](fantasy-launch.md).

```text
NAMES EVERY DOC USES EXACTLY (docs/fantasy-launch.md holds the master copy; the other docs repeat the subset they use, word for word)

TERMS
- fantasy season = one row in fantasy_seasons. This is never the racing `seasons` table. First season slug: 2026-s1. Dry-run/staging season slug: 2026-dryrun. It is closed before launch and left out of stats.
- app role = users.role (admin|maker|taker); it controls permissions. season role = season_members.role (maker|taker); it is the choice made at sign-up, locked by season_members.locked_at until the season's status becomes closed.
- account type = users.account_type: player (signed up through /signup), staff (owner, admin, collaborators, R16 testers), demo (maker, taker), system (polymarket-takers). Only players appear in leaderboards and fantasy stats.
- handle = users.username. Lowercase, regex ^[a-z0-9][a-z0-9_-]{2,19}$. It is the only public identity; email is never shown to another user. Reserved: admin, root, staff, support, noreply, system, demo, maker, taker, polymarket-takers, racinglines, plus the value of ADMIN_USERNAME.
- F$ = fantasy dollars: paper money, no cash value, not transferable. Player-facing copy never uses a bare "$".
- private book = the in-app DB book (house_markets / house_bets). live book = the file-based demo book under data/runs/live/<run>/ (demo maker plus simulated crowd). Players never trade the live book, and the crowd never fills a player's quote.
- exchange paper trade = a player's order filled against a venue's live order book (Kalshi, Polymarket) and stored only in fantasy_orders / fantasy_fills / fantasy_positions. It never goes into paper_positions or strategy_signals, and never through racinglines/markets/polymarket/trade.py or racinglines/markets/kalshi/trade.py.
- equity: taker = balance + open private-book stakes at cost + open exchange positions at liquidation value (YES shares x best YES bid; NO shares x (1 - best YES ask)), marked from market_links last_bid/last_ask. maker = balance (settled only; open worst case shown, not ranked). ROI = (equity - starting_bankroll) / starting_bankroll.
- closed dry run = R16, Thu 1 Oct to Sun 4 Oct, 5 or fewer admin-created staff tester accounts, no sign-up. staging rehearsal = Wed 7 Oct on the VM with RACINGLINES_SIGNUP=invite and tester codes in season 2026-dryrun. soft launch = RACINGLINES_SIGNUP=invite from Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC). open sign-up = RACINGLINES_SIGNUP=open (not before Thu 22 Oct).
- Times: owner-facing times in PDT with UTC in brackets; systemd OnCalendar in UTC.

TABLES: one additive Alembic revision fantasy_schema_v1, file migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py, down_revision = the single head at branch time (c8e3f6a2d4b1 on 29 Sep)
- fantasy_seasons: id, slug UNIQUE, name, status (draft|open|closed), starts_at, ends_at NULL (NULL = TBD), signup_opens_at, signup_closes_at NULL, bankroll_taker Numeric(12,2), bankroll_maker Numeric(12,2), max_stake Numeric(12,2), max_market_liability Numeric(12,2), notes JSONB, created_at.
- season_members: id, season_id FK, user_id FK, role (maker|taker), locked_at, joined_at, starting_bankroll Numeric(12,2), status (active|suspended|left). UNIQUE(season_id, user_id).
- bankroll_entries: id, season_id, user_id, ts, kind (grant|stake|payout|refund|trade|fee|settle|book_pnl|adjust), amount Numeric(12,2) signed, ref_table, ref_id, note, created_by. UNIQUE(ref_table, ref_id, kind). balance = SUM(amount).
- fantasy_orders: id, season_id, user_id, market_link_id FK, exchange (kalshi|polymarket), token_id, side (yes|no), action (buy|sell), shares_req, limit_price, status (filled|partial|rejected), reject_reason, book JSONB (levels used, fetched_at), created_at.
- fantasy_fills: id, order_id FK, season_id, user_id, market_link_id, exchange, side, action, shares, price, fee, ts.
- fantasy_positions: id, season_id, user_id, market_link_id, exchange, yes_shares, no_shares, cost, fees, status (open|settled|void), outcome Boolean NULL, payout, settled_at. UNIQUE(season_id, user_id, market_link_id).
- fantasy_event_results: season_id, user_id, event_key, venue (kalshi|polymarket|book), role, pnl, turnover, bets, won, settled_at. PK(season_id, user_id, event_key, venue).
- fantasy_stats: season_id, user_id, venue (all|kalshi|polymarket|book), role, starting_bankroll, balance, equity, pnl, roi, turnover, bets, settled, won, hit_rate, max_drawdown (positive number), sharpe (x sqrt(24); NULL under 4 events), events, rank, computed_at. PK(season_id, user_id, venue).
- house_markets (+): season_id FK NULL, closes_at, max_liability Numeric(12,2). house_bets (+): season_id FK NULL, fair_prob_at_bet, settled_at.

ENV (in /etc/racinglines.env on the VM; every new one is off or safe by default)
RACINGLINES_FANTASY=0|1 (master switch: nav, /fantasy, /leaderboard); RACINGLINES_SIGNUP=off|invite|open (default off); RACINGLINES_SIGNUP_CAP=50; RACINGLINES_FANTASY_BOOK=0|1; RACINGLINES_FANTASY_EXCHANGE=0|1; RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 (stays 0 this sprint); RACINGLINES_MAIL_BACKEND=log|smtp (default log); RACINGLINES_SMTP_HOST=smtp.protonmail.ch; RACINGLINES_SMTP_PORT=587; RACINGLINES_SMTP_USER=noreply@racinglines.bet; RACINGLINES_SMTP_TOKEN (secret, never in git); RACINGLINES_MAIL_FROM=racinglines <noreply@racinglines.bet>; RACINGLINES_MAIL_REPLY_TO=support@racinglines.bet; RACINGLINES_MAIL_DAILY_CAP=200; RACINGLINES_TURNSTILE_SITEKEY and RACINGLINES_TURNSTILE_SECRET (empty = widget off); RACINGLINES_OPS_NTFY_TOPIC (ops alerts, separate from RACINGLINES_NTFY_TOPIC for market alerts); RACINGLINES_HEALTHCHECK_PING_URL (dead-man ping). Existing: RACINGLINES_URL=https://racinglines.bet (base for mail links); RACINGLINES_GCS_BUCKET; APP_SECRET (must be set); MAX_STAKE (per-bet cap, F$100); RACINGLINES_KALSHI_SPRINTS; RACINGLINES_CANCELLED_RACE_RULES (not changed by fantasy); RACINGLINES_DEMO_USERS; RACINGLINES_DEMO_CONTEXT. Never touched: POLYMARKET_TRADING_ENABLED, KALSHI_TRADING_ENABLED.

ROUTES
Signed in: /account (GET/POST), /account/delete (POST), /fantasy, /fantasy/markets, /fantasy/orders (POST), /fantasy/book, /book/markets/{id}/take (existing POST), /leaderboard, POST /logout (GET /logout shows a confirm form).
Admin: /admin/fantasy, /admin/fantasy/seasons/{id}, /admin/fantasy/invites, /admin/fantasy/members/{user_id}, /admin/fantasy/settle.

CLI: racinglines fantasy season create|set|close|list; racinglines fantasy invite create|revoke|list; racinglines fantasy tick [--full]; racinglines fantasy stats [--full]; racinglines mail test --to <addr>; racinglines ops health [--alert]; racinglines ops backup [--label <task>].

CODE: racinglines/fantasy/{seasons,ledger,book,exchange,settle,stats}.py; racinglines/markets/books.py (read-only live order books; does not import polymarket/trade.py); racinglines/web/{accounts,mailer,health}.py; racinglines/ops/{health,backup}.py; racinglines/cli/{fantasy,ops,mail}.py; TERMS_VERSION = '2026-10-08' in racinglines/web/accounts.py. Templates: signup, verify, forgot, reset, account, terms, privacy, rules, fantasy, fantasy_markets, fantasy_book, leaderboard, admin_fantasy (.html); mail/verify.txt, mail/reset.txt, mail/welcome.txt, mail/email_changed.txt. Tests: tests/test_auth.py, test_signup.py, test_mailer.py, test_fantasy_schema.py, test_fantasy_seasons.py, test_ledger.py, test_private_book.py, test_fantasy_book.py, test_fantasy_exchange.py, test_fantasy_settle.py, test_fantasy_stats.py, test_health.py, test_ops_health.py, test_ops_backup.py; fixtures in tests/fixtures/fantasy/.

activity_log actions (new): signup, signup_rejected, email_verify, verify_resend, password_reset_request, password_reset, password_change, email_change, account_delete, role_override, bankroll_adjust, member_suspend, invite_create, invite_revoke, season_update, fantasy_order, fantasy_order_rejected, fantasy_settle, fantasy_resettle, mail_sent, mail_failed.

SYSTEMD (deploy/vm/systemd/): racinglines-health.service + .timer (every 5 min); racinglines-backup.service + .timer (daily 10:00 UTC); racinglines-kalshi-sync.service + .timer (every 30 min, daily closed sync; this is U2); racinglines-fantasy.service + .timer (every 10 min: close, settle, stats). Existing and unchanged in name: racinglines-web, racinglines-recorder, racinglines-signals(.timer), racinglines-live-f1@<event>(.timer), racinglines-live-dh@, racinglines-mcp, cloudflared. GCE: snapshot resource policy racinglines-daily (14-day retention) on disk racinglines-vm.

BACKUPS: pre-change data/backups/db/racinglines-before-<task>-<UTC>.sql.gz (CLAUDE.md); nightly data/backups/db/racinglines-nightly-<UTC>.sql.gz (7 kept on disk) and gs://$RACINGLINES_GCS_BUCKET/db/nightly/ (35-day lifecycle); owner-run logs /opt/racinglines/data/backups/<name>-<UTC>.log.
```

## What this doesn't cover

- Accounts, sign-up, sessions, seasons, the grant, the ledger module itself, stats and the leaderboard. See
  [Fantasy accounts](fantasy-accounts.md).
- The alembic revision as a whole, its backup, the restored-copy trial and the owner's migration on the VM. See
  [Fantasy accounts](fantasy-accounts.md).
- Installing the timer, health checks, backups and the incident runbooks. See [VM reliability](vm-reliability.md).
- Real-money trading of any kind. The order path, the trading flags and `vm.sh public on` are out of scope, and no
  step here proposes them.
- The demo maker's live book and its crowd, the signal engine, and the A, C and K records. They are unchanged and
  are covered in [Paper trading](paper-trading.md), [Live events](live-events.md) and
  [Market making](market-making.md).
- Makers on exchange markets (NEXT-1) and tape-only sports and OG.com (NEXT-2) beyond the sketch above.
- Kalshi's and Polymarket's data-display terms (DEC-7). The owner reads them (LEGAL-2). This page only attributes
  prices and keeps them behind a login.

## Open items

- [x] **Fixture allow-list (EXCH-0).** Decided: the fixtures stay in `tests/fixtures/fantasy/`, and EXCH-0 (now
      implement / Sonnet) adds the `ALLOWED_DATA` entry and merges in P0 as `work/exch-0`.
- [x] **The tick under the off switch.** Decided: the tick ignores `RACINGLINES_FANTASY` and gates on season data
      (see [The unit](#the-unit-deployvmsystemd-new)); `test_tick_settles_with_the_fantasy_switch_off` covers it.
- [ ] **Link rebuilds.** `racinglines f1 pm-links-import` deletes and re-inserts `market_links` rows
      (`markets/polymarket/links.py:103`). With `ON DELETE RESTRICT` from the fantasy tables it will refuse any token
      that has fantasy orders. That is intended on the VM (the import is for cloud sessions). ACC-1's reviewer
      confirms RESTRICT over SET NULL.
- [ ] **Duplicate generated markets.** A partial unique index on `house_markets (race_id, athlete_id, kind, maker_id)
      WHERE market_link_id IS NULL` would enforce the BOOK-2 de-dup in the schema. It is not in the conventions, so
      BOOK-2 uses an advisory lock instead. Decide at FABLE-1 whether ACC-1 adds it, and check the production data
      for existing duplicates in the ACC-2 trial.
- [ ] **Second settlement path.** `pm_sync` (admin) calls `settle_from_exchange` over every mirrored market. The
      tick's reconciliation step pays out whatever it settles, but BOOK-2 should pass
      `market_ids` there too so that season markets settle in one place.
- [ ] **Resolution lag.** R16 records Kalshi's resolution lag and whether its closed-sync result field is `yes`/`no`
      for every F1 kind. These are the numbers for the [timing table](#timing).
- [ ] **Owner inputs.** The final market list (DEC-20, DEC-12, DEC-7) by Wed 7 Oct 12:00 PDT; the fee
      confirmation; the season-futures pause (DEC-14); whether player makers see fair values (DEC-10).
      These go in [Owner decisions](todo.md#owner-decisions) with the rest of the DEC batch.
