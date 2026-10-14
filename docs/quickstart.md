# Quickstart

> The whole pipeline on synthetic data, with the real commands: install, build a demo store, backtest, forecast, run a live private book and price a sportsbook's lines. About 5 minutes once Postgres is up.

Every command below is a normal `racinglines` command with `--demo` added. `--demo` switches the data source to a
**demo store** (a separate database and data folder filled from a [data pack](demo.md)) and changes nothing else.
The default pack, `kart`, is a synthetic Formula 1 world with a Mario Kart grid: every pace, result and price is
invented; play money, nothing is traded anywhere.

!!! note "What you need"
    Python 3.11 or newer and a PostgreSQL 16+ server. No API key, no account and no network access are needed for
    the demo. The hosted way in needs only Python and a racinglines.bet account with MCP access (in testing).

Prefer to watch first? The same commands, recorded, play in the browser at
[racinglines.bet/docs/quickstart/term](https://racinglines.bet/docs/quickstart/term), no sign-in needed.

## Which way in?

=== "Local (demo store), recommended"

    Everything runs on your machine. The demo store is built on first use (about a minute) and every command works
    on it.

    ### Setup (5 min)

    #### Step 1: Install

    ```bash
    # LOCAL (Mac), or any machine with Python 3.11+ and Docker
    git clone https://github.com/lalligagger/racinglines-public.git && cd racinglines-public
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt && pip install -e .      # dependencies + the `racinglines` command
    ```

    #### Step 2: Start Postgres

    ```bash
    # LOCAL (Mac): PostgreSQL 17 on localhost:5433 (docker-compose.yml)
    docker compose up -d
    ```

    Without Docker, any Postgres 16+ works: point `DATABASE_URL` at it ([Database](database.md#setup)). The demo
    database is created next to the configured one (`racinglines_demo_kart` on the same server), so the user in the
    URL needs the right to create databases (the docker-compose user has it).

    #### Step 3: Check the install

    `racinglines check` runs the pipelines on synthetic data, probes every data source and checks the database
    (about 10 seconds). `--offline` skips the endpoint probes; `--no-db` skips the database.

    === "Command"

        --8<-- "examples/check-offline.md:command"

    === "Output"

        --8<-- "examples/check-offline.md:output"

    #### Step 4: Choose where the data comes from

    The first command that needs a database, when none is configured (no `DATABASE_URL`, no `db` or `source` in
    `~/.config/racinglines/cli.toml`), asks once and saves the answer as `source` in that file. Answer `1`:

    ```text
    racinglines needs a database, and none is configured (no DATABASE_URL, no `db` or `source` in ~/.config/racinglines/cli.toml).
      1) local:  the Postgres of docker-compose.yml on localhost:5433; start it with one command, `docker compose up -d`
                 (then every command works; add --demo for the synthetic demo store, docs/quickstart.md)
      2) remote: sign in to racinglines.bet (the browser opens on first use) and run `racinglines book map|price|settle`
                 on the hosted server, like `racinglines remote ...` and `--remote` on a Lab-job command (in testing);
                 other commands still need a local database
    Choose 1 or 2 [1]:
    ```

    With no terminal to ask on (a script, CI), it prints the same two options and exits with code 2: set
    `DATABASE_URL`, or run `racinglines book config source local` (or `remote`). The same command changes the answer
    later. One resolver makes this choice and the `--demo` one (`racinglines/cli/source.py`).

    Now [run the quickstart](#run-the-quickstart-the-kart-pack).

=== "Hosted (racinglines.bet, in testing)"

    !!! warning "#aintcare mode"
        racinglines.bet remote access is in testing (#aintcare mode). A review of venue and data-feed terms is
        pending, so data served here is for testing only. Every command that connects to the hosted server prints
        this warning on stderr.

    Nothing to install but the CLI itself, no Postgres: `--remote` sends the commands the hosted server runs to
    racinglines.bet, and `--demo --remote` sends them to the pack's **hosted demo store** (`racinglines mcp --http
    --demo` on the VM, over its own database built from the pack: synthetic data only, never production's). The
    outputs below are not shown because these commands need the hosted server, which the docs build cannot reach.

    ### Setup (2 min)

    #### Step 1: Install the CLI

    ```bash
    # LOCAL (Mac), or any machine with Python 3.11+: no Postgres needed
    git clone https://github.com/lalligagger/racinglines-public.git && cd racinglines-public
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt && pip install -e .
    ```

    #### Step 2: Sign in

    The first `--remote` command opens the browser to sign in with your racinglines.bet account (one with MCP
    access: Pro or admin, [MCP: Hosted](mcp.md#hosted-the-vm)) and waits for **Allow**. The login is kept in
    `~/.config/racinglines/mcp-login.json` and refreshed on its own; `racinglines book logout` forgets it. On a
    machine with no browser, an `rl_` token from Settings > Connect Claude (MCP) in `RACINGLINES_MCP_TOKEN` skips
    the sign-in.

    ```bash
    # LOCAL (Mac): the pack's book, priced on the hosted demo store (the browser opens once)
    racinglines book price --demo --remote
    ```

    #### Step 3: Run the model as a hosted job

    On the hosted store the model commands run as the server's Lab jobs (`run_job`, followed with `get_job`), the
    log printed as it arrives, and the run is saved there. They take the job's options only (`--races`, `--sims`,
    `--track`, `--half-life`, `--scenario`; `--half-life-days`, `--junior-weight` for `mtb_dh`).

    ```bash
    # LOCAL (Mac)
    racinglines model backtest kart --demo --remote --races 10  # the backtest as a hosted job
    racinglines model forecast kart --demo --remote             # a forecast scenario on the hosted demo store
    ```

    `db stats`, `live run` and `live report` need a local store. The pack names its server (`[remote] mcp_url` in
    `pack.toml`; `RACINGLINES_DEMO_MCP_URL` overrides it); it answers once the owner has built it on the VM
    (`scripts/vm/demo_store.sh`, [Demo data packs](demo.md#the-hosted-demo-store)). With `source = "remote"` saved
    in `~/.config/racinglines/cli.toml`, `--demo` alone goes to the hosted store too.

    #### Step 4: Pull real data into your own database (optional)

    The same sign-in reaches more of the hosted server ([MCP: More commands on the hosted
    server](mcp.md#more-commands-on-the-hosted-server-remote-racinglines-remote-data-pull)): `--remote` on any command that has a Lab job,
    `racinglines remote tools | call | job`, and `racinglines data pull SPORT`, which copies one sport's shared data
    (race data, model runs, exchange prices, trades and books; never accounts or positions) into a local database:

    ```bash
    # LOCAL (Mac), or any machine with Postgres: a fresh local database, then F1's data from racinglines.bet
    racinglines db init
    racinglines data pull f1
    racinglines data pull f1 --since last          # later: a top-up
    ```

## Run the quickstart (the kart pack)

The steps come from the pack's manifest (`racinglines/demo/packs/kart/pack.toml`, `[[quickstart]]`, rendered by
`python3 scripts/build_quickstart.py`), and every **Output** tab is what the command printed on the pack, captured
by `scripts/docs/capture_examples.py` (never typed by hand). The [browser replay](https://racinglines.bet/docs/quickstart/term)
records the same list. Run them in order.

<!-- quickstart: kart -->

### Step 1: 📦 Install racinglines

From a clone of the repository, in a virtualenv with Python 3.11+: the dependencies and the `racinglines` command.

```bash
# LOCAL (Mac), or any machine with Postgres
pip install -r requirements.txt && pip install -e .
```

### Step 2: 🍄 Build and look at the demo store

The first --demo command builds the store (a few minutes, with a progress bar): the database, the synthetic files, the real ingest and the exchange links. Later commands reuse it.

=== "Command"

    --8<-- "examples/db-stats-demo.md:command"

=== "Output"

    --8<-- "examples/db-stats-demo.md:output"

### Step 3: 📊 Backtest the model

Every past race priced as of before the weekend, before qualifying and before the race, with track features on and off, scored against the results and against uniform and grid baselines.

=== "Command"

    --8<-- "examples/model-backtest-kart-demo.md:command"

=== "Output"

    --8<-- "examples/model-backtest-kart-demo.md:output"

### Step 4: 🔮 Forecast the rest of the season

The next races (Rainbow Road is a sprint weekend) and both championships; --save stores the run the book and the web app read.

=== "Command"

    --8<-- "examples/model-forecast-kart-demo.md:command"

=== "Output"

    --8<-- "examples/model-forecast-kart-demo.md:output"

### Step 5: 🏁 Run a live private book

Bowser's Castle (round 9) replayed on a simulated clock: the maker's book opens before practice, reprices after each session from the model's stage runs, 100 simulated takers trade against it, the book closes at lights out and settles from the results.

=== "Command"

    --8<-- "examples/live-run-kart-demo.md:command"

=== "Output"

    --8<-- "examples/live-run-kart-demo.md:output"
<!-- /quickstart -->

!!! tip "Rich output, or plain"
    `db stats`, `model backtest`, `model forecast`, `live run`, `live report` and `book map|price|settle` print Rich
    output (colour, tables, probability bars), also when piped. `--plain` on any command gives the plain text;
    `NO_COLOR=1` keeps the layout and drops the colour codes, which is how these outputs were captured
    ([CLI: Output](cli.md#output-rich-plain-json)).

Measured on a cloud container (one CPU, 2026-10-14, the capture's own timings): the store build 56 s, the backtest
45 s, the forecast 10 s, the live run 36 s, the book 2 s.

## After the live run

The rehearsal left a settled event in the store. `live status` lists it, and `live report` writes the event report
(Markdown, charts and, with `--pdf`, a PDF, which needs weasyprint or a headless Chrome) under
`data/demo/kart/runs/live/demo-2026-09/report/`.

=== "Command"

    --8<-- "examples/live-status-demo.md:command"

=== "Output"

    --8<-- "examples/live-status-demo.md:output"

The report, with its own summary of the event and the files it wrote:

=== "Command"

    --8<-- "examples/live-report-kart-demo.md:command"

=== "Output"

    --8<-- "examples/live-report-kart-demo.md:output"

## Price a sportsbook's lines

The pack carries a generic sportsbook's lines on rounds 10 and 11 (`racinglines/demo/packs/kart/book.toml`), one
per F1 pricing feature. `book map` resolves every leg to a race, athletes and a market kind by exact keys; `book
price` adds the model's fair, the linked exchange price, the book's implied probability and the EV against each;
`book settle` adds each leg's result and payout once the race is in. `--json` on any of them prints the same result
as JSON ([Sportsbook slips](sportsbook/slips.md)).

=== "Command"

    --8<-- "examples/book-map-demo.md:command"

=== "Output"

    --8<-- "examples/book-map-demo.md:output"

Every leg mapped by its exact keys. Now the prices:

=== "Command"

    --8<-- "examples/book-price-demo.md:command"

=== "Output"

    --8<-- "examples/book-price-demo.md:output"

And the settlement:

=== "Command"

    --8<-- "examples/book-settle-demo.md:command"

=== "Output"

    --8<-- "examples/book-settle-demo.md:output"

Rounds 10 and 11 have not been raced in the pack, so every line settles as `pending`.

## Where things go

| What | Where | Notes |
|---|---|---|
| The demo database | `racinglines_demo_kart`, on the same server as `DATABASE_URL` | `RACINGLINES_DEMO_DATABASE_URL` moves it |
| The demo data folder | `data/demo/kart/` (gitignored) | the generated FastF1 files under `raw/`, the exchange links under `archive/`, run outputs under `runs/`, the live spec under `live/`; `RACINGLINES_DEMO_DATA` moves it |
| The build marker | `data/demo/kart/demo-store.json` | a fingerprint of the pack and its generator: both the database and the folder are rebuilt when the pack changes; delete the marker (or drop the database) to rebuild by hand |

Not in the quickstart yet: `strategy replay f1` (the maker replay needs a recorded exchange tape of price history and
trades per market; the kart pack carries quotes only, not a tape).

## Rebuild the data yourself

The demo is synthetic. To rebuild the real history locally, every source the code ingests is fetched with your own
machine's network access, and with your own key where one is needed. Keys are never typed on the command line or
committed: put them in your environment, or in a gitignored env file you fill with a hidden prompt, e.g.

```bash
# LOCAL (Mac): store a key without echoing it or leaving it in the shell history
read -rs -p "WUNDERGROUND_API_KEY: " k && printf 'export WUNDERGROUND_API_KEY=%s\n' "$k" >> .env.local && unset k
chmod 600 .env.local && source .env.local              # .env.local: add it to .git/info/exclude if it isn't ignored
```

| Source | What | Your own key? | Commands | Code |
|---|---|---|---|---|
| F1 live-timing archive (via FastF1) | F1 sessions: results, laps, schedule | No | `racinglines data fetch f1 --years 2020-2026`, then `racinglines data ingest f1` | `racinglines/sources/fastf1/fetch.py`, `ingest.py` |
| ChronoRace | UCI downhill results | No (the results key comes from ChronoRace's public page data) | `racinglines data download mtb_dh`, then `racinglines data ingest mtb_dh` | `racinglines/sources/chronorace/download.py`, `ingest.py` |
| NASCAR content feeds (cf.nascar.com) | NASCAR Cup results and laps | No | `racinglines data fetch nascar`, then `racinglines data ingest nascar` | `racinglines/sources/nascar/fetch.py` |
| MotoGP results API (api.motogp.pulselive.com) | MotoGP classifications | No | `racinglines data fetch motogp`, then `racinglines data ingest motogp` | `racinglines/sources/motogp/fetch.py` |
| ProCyclingStats | road cycling results | No key; needs `pip install cloudscraper selectolax`, and runs from a home connection | `racinglines data fetch cycling` (see `racinglines data fetch cycling -h`) | `racinglines/sources/pcs.py`, `racinglines/cli/cycling.py` |
| Polymarket (Gamma API) | market links, prices, trades | No (public market data) | `racinglines markets sync`, `racinglines markets history`, `racinglines markets trades` | `racinglines/markets/polymarket/sync.py` |
| Kalshi (Trade API v2, market data) | market links, prices, trades | No for market data; a key (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`, from your Kalshi account's API keys page) only for the portfolio and order endpoints, which a rebuild doesn't use | `racinglines markets --exchange kalshi sync` (then `history`, `trades`) | `racinglines/markets/kalshi/client.py`, `trade.py` |
| Open-Meteo | weather forecasts per event | No | `racinglines weather fetch` | `racinglines/weather/open_meteo.py` |
| Weather Underground | weather forecasts (optional source) | Yes: `WUNDERGROUND_API_KEY`, the key a Weather Underground personal weather station owner gets; untested (no key has been probed) | `racinglines weather probe`, `racinglines weather fetch` | `racinglines/weather/wunderground.py` |
| IndyCar, WEC, SailGP | results (sources present, not wired into an ingest) | unknown | none yet | `racinglines/sources/indycar/`, `wec/`, `sailgp/` |

Recorded exchange history older than what the exchanges still serve exists only on the VM: a rebuild has whatever
the exchanges return today. Respect each source's terms of use (e.g. `sports/motogp.toml` `[results].terms`) and its
rate limits; the fetchers pace themselves and are safe to re-run.

## Next steps

<div class="grid cards" markdown>

-   :material-console: **CLI reference**

    ---

    Every group and command, with its `-h` output and a real run where one is captured.

    [:octicons-arrow-right-24: CLI reference](cli.md)

-   :material-package-variant: **Demo data packs**

    ---

    What `--demo` does, what a pack is, the kart pack, and how to add one of your own.

    [:octicons-arrow-right-24: Demo data packs](demo.md)

-   :material-robot: **Ask Claude instead**

    ---

    The MCP server: the same data and simulations as typed tools for Claude Code, Claude Desktop or the CLI.

    [:octicons-arrow-right-24: MCP server](mcp.md)

-   :material-web: **The web app**

    ---

    Markets, Trade, History and Lab at racinglines.bet, and how to run the app yourself.

    [:octicons-arrow-right-24: Web app](webapp.md)

</div>
