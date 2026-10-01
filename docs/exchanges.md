# Exchanges as schemas

A venue with a plain JSON market-data API is **a file, not code**: `exchanges/<code>.toml`, read by one generic
driver (`racinglines/markets/exchange_driver.py`) the same way `sports/<code>.toml` describes a sport. The file says
where the API is, what each endpoint returns and where each field lives, the price units and fee, and how the
venue's markets map onto our prediction kinds per sport. Polymarket and Kalshi predate this and keep their own
packages; they can move onto schemas later. OG.com is the first schema exchange.

Where each exchange stands per sport (data, model, backtest, paper): [Sports and exchanges](coverage.md).

Read-only by construction: the driver only issues GETs of public market data. There is no order code in it, and a
venue's private (trading) API is not part of a schema.

## What a schema holds

| Section | Says |
|---|---|
| `[exchange]` | Code, name, the env var that switches the venue on in the app (off by default), and the taker fee per contract |
| `[api]` | Host (an env var can override it, e.g. a sandbox), path prefix, pacing, and how an error looks (`ok_path`, `ok_value`) |
| `[endpoints.*]` | Path, where the rows are (`data`), how it pages (`next`, `cursor_param`), how it takes ids (`batch_param`), and the time-window limits of the tape and history. An optional `limits = { max_count, max_batch, max_window_days }` states the exchange's own caps; the schema fails to load if the endpoint asks for more, so a wrong `count` or `batch_size` is caught by the tests, not by the first live call |
| `[fields.*]` | A dotted path into the JSON for each thing the driver needs: an instrument's subject, contract and expiry; a ticker's bid, ask and last; a book's levels; a trade's price, size and side; a history point. Times say their unit (`ms`, `ns`, `iso`) |
| `[prices]` | Units (OG.com: dollars, 0 to 1, as strings) |
| `[sports.<code>]` | How the venue lists one of our sports: `event_prefixes` to find its events, `modeled`, and the `[[rules]]` mapping a contract name (regex) to a prediction kind and a subject (driver or team). Without `modeled = true` the sport is tape-only: every link is `unmodeled`, filed under that sport's own competition |

A new venue is a new file plus, if the sport is new to it, a `[sports.*]` block. The schema test
(`tests/test_exchange_schema.py`) checks every file has the sections the driver needs and names real sports.

## OG.com

`exchanges/og.toml`, built from real responses captured on 2026-09-29 (`tests/fixtures/market/og_*.json`, described
in `og_README.txt`). Public market data needs no key. The venue is **off by default**: set
`RACINGLINES_OG_VENUE=1` to show an OG.com column next to Polymarket and Kalshi on the board, race and season pages, and a `/markets/og` list page with the fair-price indicator (below). Each schema exchange gets its own `/markets/<code>` page from its TOML file, registered at import, so a new venue needs no route code. `RACINGLINES_TAPES=1` adds `/markets/tapes`, the recorded tape-only sports' markets (IndyCar, road cycling, Le Mans, SailGP: the schemas with `model_family = "none"`; NASCAR and MotoGP moved to the board once they had a model) per exchange event, market data only.

What it lists of ours: the F1 season futures (Drivers' and Constructors' champion, 20 contracts, expiring
2027-01-31) become linked, priced markets; the NASCAR Cup Champion contracts and SailGP's Championship Winner contracts (`--sport sailgp`, PR #50) are tape-only. Per-Grand-Prix events
exist but have no live instruments between weekends, so race markets appear only around a weekend, and the
schema's `event_prefixes` finds them when they do (their contract names need `[[rules]]` once a live one has been
seen: only the champion contracts have been checked against the API).

```bash
racinglines markets --exchange og sync                    # the F1 futures and their quotes, into market links
racinglines markets --exchange og --sport nascar sync     # NASCAR Cup Champion, tape only
racinglines markets --exchange og --sport sailgp sync     # SailGP Championship Winner, tape only
racinglines markets --exchange og trades                  # the tape the API still serves (about a month)
racinglines markets --exchange og history --start 2026-09-01T00:00     # minute prices (31 days at most per call)
racinglines markets --exchange og books                   # one 50-level order-book snapshot per open market
racinglines markets --exchange og fair                    # the fair-price indicator below
racinglines markets --exchange og --sport nascar buy-all  # debug: one YES + one NO of every market (below)
```

The API keeps only about a month of trades and minute prices, so `trades` and `history` should run at least
weekly, or that history is lost. Prices, trades and books are archived per exchange
(`data/archive/markets/og/`), like Kalshi's.

### The fair-price indicator

`fair` puts the model's price beside OG.com's quote for every open market the model prices (today the two F1
championships, priced by the season forecast), with the edge after the fee:

- **edge YES** = fair − ask − fee (buy YES at the ask)
- **edge NO** = bid − fair − fee (buy NO at 1 − bid)
- **call** = the side with a positive edge, else blank

The fee is the schema's `taker_fee_per_contract` ($0.02, from reviews of the exchange, **not yet checked against
its fee schedule**). A market with no bid (most of OG.com's F1 books are asks only at 1–4¢) shows no NO edge, and a
one-cent ask is not a tradable quote: read the call as an indicator, not a signal. No backtest sits behind it yet:
OG.com is a replay venue since #88, but no strategy has been replayed on its markets yet: the champion replays that
read its futures are merged, off by default and not yet run on the VM (`f1 season-strategy --venue og`, #95;
`RACINGLINES_SEASON_REPLAY=1 racinglines nascar season-replay --venue og`, #96;
[Championship markets](championship-markets.md#championship-replays-backtests)), and its tape starts on 2026-09-29. The same fair price shows beside the OG.com quote on the season board when the
switch is on.

### Debug: buy one of everything

`buy-all` (read-only) takes every market the exchange lists for `--sport`, modeled or not, and buys one YES and one
NO share at the first price the store holds for it, whatever its spread, side or depth: a minute price, a trade, a
book's best bid and ask (their mid, or the one side that quotes) or the sync's last quote. The pair is held, settled
when the exchange resolved the market, else marked at the last price stored, with `--cost` ($0.01) and the schema's
fee per contract on each side. A pair loses exactly its costs and fees, so the P&L shows that each market was found,
priced and valued; the YES and NO sides are the informative split. It is an operator's plumbing check, not a result: per the
owner, buy-all never appears in reporting or the web app (Positions, the nav P&L and the status table filter out any
`buy_all` row, and `demo-history` never stores one), and no cell of the
[status matrix](coverage.md#the-status-matrix) counts it as a backtest. OG.com lists season futures only (F1
champions, the NASCAR Cup champion, SailGP), so buy-all is today the only replay that reaches its markets: the race replays'
`--buy-all` ([CLI](cli.md)) find no OG.com race markets to buy today, and OG.com lists no MotoGP. The race replay does read OG.com as a venue (`racinglines nascar replay --venue og`, and in `--venue all`), so race markets flow in as soon as OG.com lists them and they are synced. Both read every stored price whatever its spread or depth, except a stored 0.50 from an empty book; a trade at any price counts.

Nothing here places an order. OG.com's private API needs FCM onboarding and signed requests, which is a separate
step for the owner.
