# Quickstart

The whole pipeline on synthetic data, with the real commands: install, pick a database, then backtest, forecast, run a
live private book and price a sportsbook's lines. Every command below is a normal `racinglines` command with `--demo`
added; `--demo` only switches the data source to a **demo store** (a separate database and data folder filled from a
[data pack](demo.md)), it changes nothing else. The default pack, `kart`, is a synthetic Formula 1 world with a Mario
Kart grid: every pace, result and price is invented; play money, nothing is traded anywhere.

## 1. Install

```
# LOCAL (Mac), or any machine with Python 3.11+ and Docker
git clone https://github.com/lalligagger/racinglines-public.git && cd racinglines-public
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .      # dependencies + the `racinglines` command
docker compose up -d                                     # PostgreSQL 17 on localhost:5433
```

What a first-time user needs: Python 3.11 or newer, and PostgreSQL. `docker compose up -d` starts the one in
`docker-compose.yml` (port 5433, user, password and database `racinglines`); without Docker, any Postgres 16+ works:
point `DATABASE_URL` at it (see [Database](database.md#setup)). The demo database is created next to the configured
one (`racinglines_demo_kart` on the same server), so the user in the URL needs the right to create databases (the
docker-compose user has it). No API key, no account and no network access are needed for the demo.

## 2. First run: choose where the data comes from

The first command that needs a database, when none is configured (no `DATABASE_URL`, no `db` or `source` in
`~/.config/racinglines/cli.toml`), asks once:

```
racinglines needs a database. Choose one:
  1) local: the Postgres from `docker compose up -d` (localhost:5433)
  2) remote: sign in to racinglines.bet and run `book` commands on the hosted server (testing)
```

The answer is saved as `source` in `~/.config/racinglines/cli.toml` (`racinglines book config source local|remote`
changes it later). Without a terminal (a script, CI) nothing is asked: the command exits with status 2 and prints the
two options. `--demo` always uses a local demo store unless `--remote` is given too (below).

## 3. The quickstart, on the kart pack

The steps below are rendered from the pack's manifest (`racinglines/demo/packs/kart/pack.toml`, `[[quickstart]]`) by
`python3 scripts/build_quickstart.py`; the web app's `/term` replay records the same commands. Run them in order.

<!-- quickstart: kart -->

**1. Build and look at the demo store.** The first --demo command builds the store (a few minutes, with a progress bar): the database, the synthetic files, the real ingest and the exchange links. Later commands reuse it.

```
# LOCAL (Mac), or any machine with Postgres
racinglines db stats --demo
```

**2. Backtest the model.** Every past race priced as of before the weekend, before qualifying and before the race, with track features on and off, scored against the results and against uniform and grid baselines.

```
# LOCAL (Mac), or any machine with Postgres
racinglines model backtest f1 --demo
```

**3. Forecast the rest of the season.** The next races (Rainbow Road is a sprint weekend) and both championships; --save stores the run the book and the web app read.

```
# LOCAL (Mac), or any machine with Postgres
racinglines model forecast f1 --demo --save
```

**4. Run a live private book.** Bowser's Castle (round 9) replayed on a simulated clock: the maker's book opens before practice, reprices after each session from the model's stage runs, 100 simulated takers trade against it, the book closes at lights out and settles from the results.

```
# LOCAL (Mac), or any machine with Postgres
racinglines live run f1/demo-2026-09 --demo --simulate --no-fetch
```

**5. The live event's report.** Markdown, charts and a PDF in the run folder (data/demo/kart/runs/live/demo-2026-09/report/).

```
# LOCAL (Mac), or any machine with Postgres
racinglines live report f1/demo-2026-09 --demo --pdf
```

**6. Price a sportsbook's lines.** The pack's sportsbook book (a generic sportsbook's lines on rounds 10 and 11) against the model's forecast and the exchanges' quotes: EV against each, side by side.

```
# LOCAL (Mac), or any machine with Postgres
racinglines book price --demo
```
<!-- /quickstart -->

Measured on a cloud container (one CPU, 2026-10-11): the store build about 50 s, the backtest about 40 s, the
forecast about 10 s, the live run about 30 s, the report and the book a few seconds each. The PDF needs weasyprint
or a headless Chrome; leave out `--pdf` without them.

Where things go: the database `racinglines_demo_kart`, and the folder `data/demo/kart/` (the generated FastF1 files
under `raw/`, the exchange links under `archive/`, run outputs under `runs/`, the live spec under `live/`). Both
are rebuilt from scratch when the pack changes; drop the database (or delete `data/demo/kart/demo-store.json`) to
rebuild by hand. `RACINGLINES_DEMO_DATABASE_URL` and `RACINGLINES_DEMO_DATA` move them.

Not in the quickstart yet: `strategy replay f1` (the maker replay needs a recorded exchange tape of price history
and trades per market; the kart pack carries quotes only, not a tape).

## 4. Remote (testing)

!!! warning "#aintcare mode"
    racinglines.bet remote access is in testing (#aintcare mode). A review of venue and data-feed terms is pending,
    so data served here is for testing only. Every command that connects to the hosted server prints this warning on
    stderr.

`racinglines book price FILE --remote` runs the book commands on the hosted MCP server instead of a local database
(sign-in through the browser the first time; [MCP: Hosted](mcp.md#hosted-the-vm)). `--demo --remote` sends the same request
to the hosted server's demo store, which holds the kart pack's synthetic data only, never production data:

```
# LOCAL (Mac)
racinglines book price --demo --remote
```

The hosted demo store is set up on the VM by `scripts/vm/demo_store.sh` (owner-run, backup first; see
[Demo data packs](demo.md#the-hosted-demo-store)).

## 5. Rebuild the data yourself

The demo is synthetic. To rebuild the real history locally, every source the code ingests is fetched with your own
machine's network access, and with your own key where one is needed. Keys are never typed on the command line or
committed: put them in your environment, or in a gitignored env file you fill with a hidden prompt, e.g.

```
# LOCAL (Mac): store a key without echoing it or leaving it in the shell history
read -rs -p "WUNDERGROUND_API_KEY: " k && printf 'export WUNDERGROUND_API_KEY=%s\n' "$k" >> .env.local && unset k
chmod 600 .env.local && source .env.local              # .env.local: add it to .git/info/exclude if it isn't ignored
```

| Source | What | Your own key? | Commands (tree A) | Code |
|---|---|---|---|---|
| F1 live-timing archive (via FastF1) | F1 sessions: results, laps, schedule | No | `racinglines data fetch f1 --years 2020-2026`, then `racinglines data ingest f1` | `racinglines/sources/fastf1/fetch.py`, `ingest.py` |
| ChronoRace | UCI downhill results | No (the results key comes from ChronoRace's public page data) | `racinglines data download mtb_dh`, then `racinglines data ingest mtb_dh` | `racinglines/sources/chronorace/download.py`, `ingest.py` |
| NASCAR content feeds (cf.nascar.com) | NASCAR Cup results and laps | No | `racinglines data fetch nascar`, then `racinglines data ingest nascar` | `racinglines/sources/nascar/fetch.py` |
| MotoGP results API (api.motogp.pulselive.com) | MotoGP classifications | No | `racinglines data fetch motogp`, then `racinglines data ingest motogp` | `racinglines/sources/motogp/fetch.py` |
| ProCyclingStats | road cycling results | No key; needs `pip install cloudscraper selectolax`, and runs from a home connection | `racinglines data fetch cycling` (see `racinglines data fetch cycling -h`) | `racinglines/sources/pcs.py`, `racinglines/cli/cycling.py` |
| Polymarket (Gamma API) | market links, prices, trades | No (public market data) | `racinglines markets sync`, `racinglines markets history`, `racinglines markets trades` | `racinglines/markets/polymarket/sync.py` |
| Kalshi (Trade API v2, market data) | market links, prices, trades | No for market data; a key (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`, from your Kalshi account's API keys page) only for the portfolio and order endpoints, which a rebuild doesn't use | `racinglines markets sync --exchange kalshi` (then `history`, `trades`) | `racinglines/markets/kalshi/client.py`, `trade.py` |
| Open-Meteo | weather forecasts per event | No | `racinglines weather fetch` | `racinglines/weather/open_meteo.py` |
| Weather Underground | weather forecasts (optional source) | Yes: `WUNDERGROUND_API_KEY`, the key a Weather Underground personal weather station owner gets; untested (no key has been probed) | `racinglines weather probe`, `racinglines weather fetch` | `racinglines/weather/wunderground.py` |
| IndyCar, WEC, SailGP | results (sources present, not wired into an ingest) | unknown | none yet | `racinglines/sources/indycar/`, `wec/`, `sailgp/` |

Recorded exchange history older than what the exchanges still serve exists only on the VM: a rebuild has whatever
the exchanges return today. Respect each source's terms of use (e.g. `sports/motogp.toml` `[results].terms`) and its
rate limits; the fetchers pace themselves and are safe to re-run.
