# Exchanges as schemas

A venue with a plain JSON market-data API is **a file, not code**: `exchanges/<code>.toml`, read by one generic
driver (`racinglines/markets/exchange_driver.py`) the same way `sports/<code>.toml` describes a sport. The file says
where the API is, what each endpoint returns and where each field lives, the price units and fee, and how the
venue's markets map onto our prediction kinds per sport. Polymarket and Kalshi predate this and keep their own
packages; they can move onto schemas later. OG.com is the first schema exchange.

Read-only by construction: the driver only issues GETs of public market data. There is no order code in it, and a
venue's private (trading) API is not part of a schema.

## What a schema holds

| Section | Says |
|---|---|
| `[exchange]` | Code, name, the env var that switches the venue on in the app (off by default), and the taker fee per contract |
| `[api]` | Host (an env var can override it, e.g. a sandbox), path prefix, pacing, and how an error looks (`ok_path`, `ok_value`) |
| `[endpoints.*]` | Path, where the rows are (`data`), how it pages (`next`, `cursor_param`), how it takes ids (`batch_param`), and the time-window limits of the tape and history |
| `[fields.*]` | A dotted path into the JSON for each thing the driver needs: an instrument's subject, contract and expiry; a ticker's bid, ask and last; a book's levels; a trade's price, size and side; a history point. Times say their unit (`ms`, `ns`, `iso`) |
| `[prices]` | Units (OG.com: dollars, 0 to 1, as strings) |
| `[sports.<code>]` | How the venue lists one of our sports: `event_prefixes` to find its events, `modeled`, and the `[[rules]]` mapping a contract name (regex) to a prediction kind and a subject (driver or team). Without `modeled = true` the sport is tape-only: every link is `unmodeled`, filed under that sport's own competition |

A new venue is a new file plus, if the sport is new to it, a `[sports.*]` block. The schema test
(`tests/test_exchange_schema.py`) checks every file has the sections the driver needs and names real sports.

## OG.com

`exchanges/og.toml`, built from real responses captured on 2026-09-29 (`tests/fixtures/market/og_*.json`, described
in `og_README.txt`). Public market data needs no key. The venue is **off by default**: set
`RACINGLINES_OG_VENUE=1` to show an OG.com column next to Polymarket and Kalshi on the board, race and season pages, and a `/markets/og` list page with the fair-price indicator (below). Each schema exchange gets its own `/markets/<code>` page from its TOML file, registered at import, so a new venue needs no route code. `RACINGLINES_TAPES=1` adds `/markets/tapes`, the recorded tape-only sports' markets (NASCAR, MotoGP, IndyCar) per exchange event, market data only.

What it lists of ours: the F1 season futures (Drivers' and Constructors' champion, 20 contracts, expiring
2027-01-31) become linked, priced markets; the NASCAR Cup Champion contracts are tape-only. Per-Grand-Prix events
exist but have no live instruments between weekends, so race markets appear only around a weekend, and the
schema's `event_prefixes` finds them when they do (their contract names need `[[rules]]` once a live one has been
seen: only the champion contracts have been checked against the API).

```bash
racinglines markets --exchange og sync                    # the F1 futures and their quotes, into market links
racinglines markets --exchange og --sport nascar sync     # NASCAR Cup Champion, tape only
racinglines markets --exchange og trades                  # the tape the API still serves (about a month)
racinglines markets --exchange og history --start 2026-09-01T00:00     # minute prices (31 days at most per call)
racinglines markets --exchange og books                   # one 50-level order-book snapshot per open market
racinglines markets --exchange og fair                    # the fair-price indicator below
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
one-cent ask is not a tradable quote: read the call as an indicator, not a signal. No backtest sits behind it and
none is planned for this venue. The same fair price shows beside the OG.com quote on the season board when the
switch is on.

Nothing here places an order. OG.com's private API needs FCM onboarding and signed requests, which is a separate
step for the owner.
