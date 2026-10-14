<!-- Captured by scripts/docs/capture_examples.py (id help-book, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.1 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines book -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines book [-h] [--demo | --remote | --local] [--mcp-url TOP_MCP_URL]
                        {render,new,map,price,settle,export,view,logout,config} ...

racinglines book <command> FILE [options]: generic sportsbook lines and slips against our model and the prediction
markets (racinglines/books/slips.py, docs/sportsbook/slips.md). CLI only, outside the web app; read-only on the
database.

    map      resolve every line's legs to a race, athletes and a kind by exact keys; list what stays unmapped
    price    + the model's fair, the linked exchange price, the book's implied probability, EV against each
    settle   + each leg's and line's result from the stored classification, and the payout per unit staked
    render   one HTML page (and --png) of the priced board: hud (on the book's screenshot), card, or agnostic (model
             and exchanges only), with stakes from markets/books.toml (docs/sportsbook/render.md)
    new      a book file draft from loose text ("A over B 1.57", "A vs B 1.57 2.25", "Name 4.35"): --from-text
    export   the book's staked lines (a line's `stake`, `placed_utc`) priced and settled, as ledger rows:
             `--ledger OUT.csv` (racinglines/books/ledger.py, docs/sportsbook/slips.md#ledger-export); refuses an
             existing OUT unless --force, never appends
    view     render a saved --json result of map, price or settle with Rich (no database)
    logout   forget the browser sign-in that --remote keeps
    config   show or set the CLI's defaults (racinglines/cli/config.py): `config`, `config KEY VALUE`, `config KEY --unset`

Where the data comes from (map, price, settle, export), three modes; the default is the defaults file's `source`, else local:
    --local                a local database (--db, else DATABASE_URL, else the defaults file's `db`): you rebuild the
                           data or run the app and its MCP server yourself
    --demo [PACK]          a demo store (racinglines/cli/source.py): a separate local database of synthetic data from a
                           data pack (default kart), built on first use, priced by the same code as --local. FILE
                           defaults to the pack's book (racinglines/demo/packs/kart/book.toml); `racinglines model
                           forecast kart --demo --save` first gives it model prices. Rich by default.
                           `--demo [PACK] --remote` (or the defaults file's source = remote) prices it on the pack's
                           hosted demo store instead (its [remote] mcp_url; synthetic data only)
    --remote               the VM's hosted MCP server (racinglines/cli/remote.py): live model runs and exchange prices.
                           Signs in through the browser the first time (kept in ~/.config/racinglines/mcp-login.json),
                           or uses RACINGLINES_MCP_TOKEN (an rl_ token) when set. --mcp-url URL, RACINGLINES_MCP_URL or
                           the defaults file's `mcp_url` point it at your own server (default
                           https://mcp.racinglines.bet/mcp)

Options (map, price, settle, export):
    --json                 the whole result as JSON (stable keys: docs/sportsbook/slips.md#json-output)
    --rich                 a coloured table (Rich; racinglines/cli/rich_view.py): the default; --plain (any command) or
                           RACINGLINES_PLAIN=1 prints the plain text
    --db URL               the database (default DATABASE_URL)
price and export:
    --run ID               price legs of that run's competition from it (repeatable; default: the app's own choice
                           per race, markets/venues.pricing_run)
    --sims RACE_ID=FILE    an OutcomeSims archive (.npz, models/outcomes.save_sims) for a race: legs on that race are
                           priced jointly from it (repeatable)
price:
    --asof UTC             price as it stood then (follow a book through a weekend): the newest model run cut off by
                           then and each exchange's last tape price by then, no bid/ask (local only)
render (FILE = a book file, priced like `price`; or a cycling price output folder or CSV; or leave it out with
--json-in):
    --style hud|card|agnostic   --image PNG   --out PATH.html   --png   --chrome PATH   --json-in PRICED.json
    --bank --kelly --cap --min-ev --scale --drop-under    override markets/books.toml [stake]
new:
    --from-text TXT --venue CODE --event KEY --odds FORMAT --out FILE.toml [--sport CODE] [--currency USD]

positional arguments:
  {render,new,map,price,settle,export,view,logout,config}
    render              An HTML page (and PNG) of the priced board: hud, card or agnostic.
    new                 A book file draft from loose text lines.
    map                 Resolve each line's legs by exact keys.
    price               Model fair, market price, book implied probability and EV per leg and per
                        slip.
    settle              Results and payouts from the stored classification.
    export              The staked lines, priced and settled, as ledger rows (--ledger OUT.csv).
    view                Render a saved --json result with Rich (no database).
    logout              Forget the browser sign-in --remote keeps.
    config              Show or set the CLI's defaults (source, mcp_url, db).

options:
  -h, --help            show this help message and exit
  --demo                as `--demo` after the command
  --remote              as `--remote` after the command
  --local               as `--local` after the command
  --mcp-url TOP_MCP_URL
                        as `--mcp-url` after the command
```
<!-- --8<-- [end:output] -->
