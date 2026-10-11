# Demo data packs

`--demo [PACK]` on any command runs that command, unchanged, on a **demo store**: a separate Postgres database and
data folder filled from a **data pack** by the real pipeline. The commands to run are in the
[Quickstart](quickstart.md). This page is how it works and how to add a pack.

## What `--demo` does

One resolver (`racinglines/cli/source.py`, called by `racinglines/cli/__init__.py` before anything else) takes
`--demo [PACK]` out of the arguments and points the process at the pack's store:

| Setting | Demo value | Default location |
|---|---|---|
| `DATABASE_URL` | the pack's database, on the same server as the configured one | `racinglines_demo_<pack>` (`RACINGLINES_DEMO_DATABASE_URL` overrides) |
| `RACINGLINES_DATA` | the pack's data folder: raw files, archives, run outputs, live specs | `data/demo/<pack>/` (gitignored; `RACINGLINES_DEMO_DATA` overrides) |
| `RACINGLINES_OFFLINE=1` | FastF1's servers are never called: the store's files are the record | (a general switch, also for machines without FastF1 access) |

Then the command runs as it always does. There is no demo branch in any command, model or pipeline: the backtest is
`pricing.backtest`, the forecast `pricing.forecast`, the live book `pipelines/live_f1.py` with the real crowd and
quoting, the book `books/slips.py`. `PACK` defaults to `kart`; `--demo=PACK` works too. The first `--demo` command
builds the store when it is missing or when the pack has changed (a Rich progress bar; a few minutes).

## What a pack is

A folder with a `pack.toml` manifest, bundled under `racinglines/demo/packs/<name>/` or in a folder named by
`RACINGLINES_DEMO_PACKS` (several, separated by `:`). The manifest holds data and the names of real commands only:

| Key | What |
|---|---|
| `name`, `title`, `about` | the pack's name (what `--demo NAME` takes) and description |
| `sport` | an **existing** sport schema (`sports/<sport>.toml`) the data is stored under: no new sport, no new schema |
| `files` | a folder copied as is into the data folder (e.g. `raw/...` files a real ingest reads, live specs under `live/`) |
| `[generator]` | optional: `entry = "module:function"` writing more data files into the data folder, and its `input` |
| `[load] commands` | the real `racinglines ...` commands that load the data into the database, in order |
| `[book] file` | the sportsbook book `racinglines book price --demo` prices when no FILE is given |
| `tagline` | optional: a line printed once the store is ready (a pack's flavour lives here, never in a command) |
| `[[quickstart]]` | the pack's quickstart: `title`, `run` (the command), `about`, optional `section` (steps group under one heading per section, in first-seen order; none: one list); rendered into [Quickstart](quickstart.md) by `scripts/build_quickstart.py` (`--commands PACK [--section NAME]` lists them) and replayed by the web app's `/term` page (`Pack.sections()` in `racinglines/demo/store.py`) |

The store build (`racinglines/demo/store.py`): create the database (its name must contain `demo`), Alembic upgrade
head and the seed (`racinglines db init`), copy the files, run the generator, run each load command as a
subprocess on the store, record a `data_changes` line, write a marker (`demo-store.json`, a fingerprint of the pack
and its generator). Adding a pack is adding a folder: no command, flag, schema, sport file or code path changes.
`tests/test_demo_store.py` builds a second, tiny pack under `mtb_dh` (synthetic ChronoRace result files loaded by
`racinglines data ingest mtb_dh`) and runs its backtest through the same code.

## The kart pack

`racinglines/demo/packs/kart/`: a synthetic Formula 1 world with a Mario Kart grid, stored under the F1 schema.

- `world.toml`, the generator's input: three seasons (2024-2026, twelve rounds each, 2026's rounds 1-9 raced, sprints
  at rounds 3, 6 and 10), 20 drivers in 10 teams (Mario, Luigi, Peach, Bowser, ...), twelve tracks (Mario Circuit,
  Rainbow Road, Bowser's Castle, ...), each team's car pace and the driver offsets, the tracks' lap times, sector
  shares, trap speeds, how hard passing is and how often a safety car comes out. These are the synthetic world's
  hidden truth; the real model never reads them, it fits the generated laps.
- `racinglines/demo/generate.py` writes FastF1-shaped files for every raced session (practice, sprint qualifying,
  sprint, qualifying, race: results, laps with sectors and speed traps, meta with weather) and each season's
  schedule, the shapes `sources/fastf1/fetch.py` saves; and quotes from a synthetic Polymarket (win, podium, pole,
  teammates' head-to-heads) and Kalshi (win, podium, 2nd place) on rounds 9-11, in the file
  `racinglines data pm-links-export` writes. Seeded: the same input gives the same files.
- The load: `data ingest f1` (the real FastF1 ingest: events, results, laps, track profiles), `model forecast f1
  --save` (files the unraced rounds as scheduled races), `data pm-links-import f1` for each exchange.
- `files/live/f1/demo-2026-09.toml`: the live rehearsal's launch spec (round 9, already raced, so the book settles):
  `[live.crowd] takers = 100`.
- `book.toml`: a generic sportsbook's lines on rounds 10 and 11, one per F1 pricing feature of `book price`.

The synthetic exchanges are data like the rest: prices drawn around the generator's own odds with an exchange's
noise and spread. No real exchange data is in any pack.

## The hosted demo store

`--demo [PACK] --remote`, or `--demo` with `source = "remote"` in `~/.config/racinglines/cli.toml`, uses the pack's
hosted store instead of a local one. The resolver builds nothing locally: it points the command's own `--remote`
path at the pack's demo MCP server (`[remote] mcp_url` in `pack.toml`, `RACINGLINES_DEMO_MCP_URL` overrides it) and
adds `--remote`. Only the commands the hosted server runs take it: `book map|price|settle` (the pack's book sent to
the `map_book` / `price_book` / `settle_book` tools) and `model backtest|forecast f1|mtb_dh` (the command's Lab job,
queued with `run_job` and followed with `get_job`; `racinglines/cli/remote.py`). `model backtest f1 --remote` without
`--demo` runs the same way on whichever server `--remote` names.

The server is the normal one with `--demo`: `racinglines mcp --http --port 8766 --demo kart` on the VM serves the
kart store (its own database `racinglines_demo_kart` and `data/demo/kart/`, built by the same `store.build`), and its
job worker runs the jobs on it. Accounts, `rl_` tokens and OAuth sign-ins are read from production's database
(`RACINGLINES_MCP_ACCOUNTS_URL`), so the same Pro and admin accounts sign in, and the store has no account rows of its
own: jobs are filed without an owner, and every signed-in caller sees the store's jobs. `scripts/vm/demo_store.sh`
builds it (`build`, backup first) and starts the server (`serve`); the owner runs both and adds the `mcp-demo`
hostname to the tunnel. Remote access is in testing; every remote command prints the #aintcare warning
([Quickstart: Remote](quickstart.md#4-remote-testing)).
