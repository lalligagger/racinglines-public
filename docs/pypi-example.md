# PyPI page (example)

!!! warning "Example only, not a release"
    This is a draft of what the racinglines page on PyPI could look like. The package is **not on PyPI**: nothing has
    been uploaded and the name is not registered. Publishing waits for the owner's go. Some commands below use the
    new CLI tree (task groups such as `racinglines model forecast f1`, `--demo [PACK]` on any command), which is still being built,
    and the licence wording is an open question.

## Draft metadata

| Field | Draft value |
|---|---|
| Name | `racinglines` |
| Version | 0.2.0 |
| Summary | Fair prices and market making for race sports: F1, MotoGP, NASCAR and UCI downhill against prediction markets |
| Requires | Python >=3.12; `numpy>=2.5`, `pandas>=2.3,<3`, `rich>=15` |
| Extras | `racinglines[remote]`, `racinglines[server]`, `racinglines[dev]` |
| Licence | `LicenseRef-racinglines-NC` (the MIT text plus a non-commercial restriction; see [LICENSE](https://github.com/lalligagger/racinglines-public/blob/main/LICENSE)) |
| Links | [racinglines.bet](https://racinglines.bet), [source](https://github.com/lalligagger/racinglines-public) |

## Draft long description

Everything below is the draft page text as PyPI would show it (from `PYPI.md` on the PyPI draft branch).

---

**Fair prices and market making for race sports.** racinglines turns official timing into win, podium,
head-to-head and championship odds, priced strictly as of any moment and tested on real market tapes, and gives
makers and takers the tools to find and size an edge in race-sport prediction markets (Polymarket, Kalshi, OG.com)
and against generic sportsbook lines.

- **Formula 1**, the big end: a sector-aware car model, practice prior and grid/overtaking finishing model, backtested
  on 129 races (2021 to Azerbaijan 2026, backtest run 931). After qualifying, its top-10 Brier score is **0.149**
  against **0.163** for a grid-only guess.
- **UCI downhill** mountain biking, the small end: modelled and forecast from split timing.
- **NASCAR Cup** and **MotoGP**: results, market links on Kalshi, Polymarket and OG.com, and a simple result-only
  model in replay. No edge has held up in a second season yet.

Nothing is traded with real money: strategies run as backtests, replays on recorded exchange prices, and paper
trading.

### Install

```
pip install racinglines            # the CLI and the demo
pip install "racinglines[remote]"  # + the hosted server (sign in through the browser)
pip install "racinglines[server]"  # + everything to run your own database, web app and MCP server
```

Python 3.11 or newer, and PostgreSQL for the demo store.

### Try it in a minute: the demo

`--demo [PACK]` on any command runs that same command on a demo store: a separate database and data folder built
from a data pack by the real ingest. The default pack, `kart`, is a synthetic Formula 1 world with a Mario Kart grid;
every pace, result and price is made up, and it is play money. It needs PostgreSQL (the demo database is created
next to yours) but no network or account.

```
racinglines db stats --demo                                       # 1. build the demo store and look at it
racinglines model backtest f1 --demo                              # 2. every past race priced and scored
racinglines model forecast f1 --demo --save                       # 3. the rest of the season and the championships
racinglines live run f1/demo-2026-09 --demo --simulate --no-fetch # 4. a live private book on a simulated clock
racinglines live report f1/demo-2026-09 --demo --pdf              # 5. the live event's report
racinglines book price --demo                                     # 6. sportsbook lines: EV against model and exchanges
```

These are the real commands: `--demo` only switches the data source ([Quickstart](quickstart.md)).

### Three ways to run it

| | What you need | What runs |
|---|---|---|
| **Demo** | `pip install racinglines` and PostgreSQL | The six steps above, on a bundled synthetic data pack, with no network or account |
| **Hosted** | A [racinglines.bet](https://racinglines.bet) account with MCP access | `racinglines book price FILE --remote` prices your own book file on the hosted server; the first run signs in through the browser |
| **Self-hosted** | PostgreSQL and `racinglines[server]` | The full pipeline below on your own data, and your own MCP server (`racinglines book config mcp_url URL` makes it the CLI default) |

### Self-hosted quickstart

```
docker compose up -d                  # PostgreSQL (the repo's docker-compose.yml)
racinglines db init                   # tables + reference data
racinglines data fetch f1             # F1 sessions (FastF1)
racinglines data ingest f1            #   -> database
racinglines model forecast f1 --save  # live F1 prices: remaining races + championships
racinglines markets sync              # exchange market links
racinglines check                     # code, data endpoints, database
```

### What it does

- **Collects** official timing into one multi-sport PostgreSQL schema, and exchange history (prices, trades, order
  books) into a Parquet archive.
- **Models** each sport and **simulates** race weekends and seasons thousands of times: win, podium, top 10, pole,
  head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that ended before the cutoff are used, and a leakage guard
  enforces it. Backtests, diagnostics, the live forecast and the signal engine call the same function.
- **Tests strategies on real market data:** maker replays, taker strategies that re-trade after every session, and
  season-long championship strategies, on recorded exchange prices and trades.
- **Prices sportsbook lines and slips** against the model and the exchanges, side by side, never blended.
- **Serves** it all through an MCP server, so a chat client can read the data and run the simulations.

### Links

- Source and full documentation: [github.com/lalligagger/racinglines-public](https://github.com/lalligagger/racinglines-public)
- Live app: [racinglines.bet](https://racinglines.bet)

### Licence

Source-available, not open source: the MIT licence text with an added restriction that allows personal,
non-commercial inspection and study only, and prohibits commercial use (including as a hosted service) without
written permission. See [LICENSE](https://github.com/lalligagger/racinglines-public/blob/main/LICENSE).