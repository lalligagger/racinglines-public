# Sportsbook slips: EV against the model and the market

`racinglines book map | price | settle` takes a generic sportsbook's lines and slips, written as a book file
([schema](index.md)), and puts three prices beside each bet: **the model's fair probability**, **the linked
prediction-market price** (Polymarket, Kalshi, OG.com) wherever a linked market exists, and **the book's implied
probability** from its odds. It reports the expected value (EV) against the model and against the market, side by
side. F1, NASCAR and MotoGP work the same way: kinds come from the kinds registry (`racinglines/markets/kinds.py`
`KINDS`), sports from `sports/<code>.toml`, and there are no per-sport branches.

Owner decisions this follows: sportsbook analysis is CLI only and stays out of the web app (2026-10-06), and the
command never writes to the database. Every query runs in a `READ ONLY` transaction. The functions behind it
(`racinglines/books/slips.py`: `map_book`, `price_book`, `settle_book`) are what the MCP tools `map_book`,
`price_book` and `settle_book` wrap, with the book passed in as text (`slips.load_text`).

## Two ways to find edge

The model's fair probabilities are useful in two places, and the data behind both is the same:

1. **Prediction markets.** Compare the model with Polymarket and Kalshi directly and take the +EV side on the
   exchange. That is the app's own work (the Markets board, paper trading, the maker and taker strategies) and the
   MCP tool `list_markets`, not this command.
2. **Sportsbooks.** Compare a sportsbook's odds with the model *and* with the exchanges' prices for the same outcome.
   `book price` puts both EVs on every line, `EV model` and `EV market`. A line that is +EV against both is the
   strongest case. A line that is +EV only against the model is a bet on the model being right where the market
   disagrees. A line that is +EV only against the market is a soft book line the model doesn't back.

## Three ways in

| Mode | Flag | Needs | For |
|---|---|---|---|
| **Demo** | `--demo [PACK]` | Postgres (`docker compose up -d`); no data, network or account | A first look. The kart pack's book (`racinglines/demo/packs/kart/book.toml`, a Mario Kart grid) priced by the real code on a local demo store of synthetic data, built on first use, showing each F1 pricing feature ([Quickstart](../quickstart.md)). `--demo --remote` prices it on the pack's hosted demo store instead, with no local database ([Demo data packs](../demo.md#the-hosted-demo-store)). |
| **Hosted** | `--remote` | A racinglines.bet account with MCP access ([MCP: Hosted](../mcp.md#hosted-the-vm)) | Your own book file priced on the VM's live data through the hosted MCP server. The first run opens your browser to sign in. |
| **Local** | `--local` (the default) | Your own database with the data rebuilt (or your own server, below) | Everything, including `--run` and `--sims` |

```
# LOCAL (Mac), or any machine with the package and Postgres: the demo
racinglines model forecast f1 --demo --save     # the model run the book's fair values come from
racinglines book price --demo                   # Rich tables by default; --json for the raw result
racinglines book settle --demo
```

```
# LOCAL (Mac): your own book file on the VM's data (the first run opens the browser to sign in)
racinglines book price FILE --remote --rich
```

```
# LOCAL (Mac) or VM: your own database
racinglines book map    FILE [--json] [--db URL]
racinglines book price  FILE [--json] [--db URL] [--run ID ...] [--sims RACE_ID=FILE.npz ...]
racinglines book settle FILE [--json] [--db URL]
racinglines book render FILE --style hud|card|agnostic [--png] [--json-in PRICED.json]   # render.md
racinglines book view   RESULT.json
```

!!! warning "Remote access is in testing"
    racinglines.bet remote access is in testing (#aintcare mode). A review of venue and data-feed terms is pending,
    so data served here is for testing only. Every command that connects to the hosted server prints this warning on
    stderr (`racinglines/cli/remote.py`).

**Signing in for `--remote`** (`racinglines/cli/remote.py`) uses the same OAuth flow Claude's connector uses. The
first `--remote` prints a racinglines.bet URL and opens it. You sign in if needed and press **Allow** once. The CLI
then keeps the login in `~/.config/racinglines/mcp-login.json` (mode 600, one entry per server;
`RACINGLINES_MCP_LOGIN` moves it). It refreshes the access token on its own and asks again after 30 days of disuse
or a **Disconnect all** in Settings. `racinglines book logout` forgets it. For scripts and machines with no browser,
an account's `rl_` token in `RACINGLINES_MCP_TOKEN` is used instead (Settings > Connect Claude (MCP) > Get a token),
read without echo:

```
# LOCAL (Mac): a token instead of the browser sign-in
read -rs -p "rl_ token: " RACINGLINES_MCP_TOKEN && echo && export RACINGLINES_MCP_TOKEN
racinglines book price FILE --remote
```

**Your own server as the default** (`racinglines/cli/config.py`). If you host the data and the MCP server yourself
([MCP: Once: host the server](../mcp.md#once-host-the-server)), or you only ever use one mode, set the defaults
once in `~/.config/racinglines/cli.toml` (`RACINGLINES_CLI_CONFIG` moves it; written mode 600):

```
# LOCAL (Mac): defaults for every `racinglines book` command
racinglines book config source remote                         # local (default) | remote | demo
racinglines book config mcp_url https://mcp.example.com/mcp   # the server --remote uses
racinglines book config db postgresql+psycopg://...           # the database local mode uses when DATABASE_URL is unset
racinglines book config                                       # show them (the db URL is shown as <set>)
racinglines book config mcp_url --unset                       # remove one
```

Flags win over environment variables, which win over the file: `--demo / --remote / --local` > `source`;
`--mcp-url` > `RACINGLINES_MCP_URL` > `mcp_url` > `https://mcp.racinglines.bet/mcp`; `--db` > `DATABASE_URL` > `db`.

| Command | Does |
|---|---|
| `map` | Resolves every line's legs to a race, athletes and a kind **by exact keys**, and lists every line that stays unmapped with the reason |
| `price` | `map`, plus per leg the model's fair, the market price and, when the leg carries its own odds, the book's implied probability and both EVs; per line (a single or a slip), the payout, the book's, model's and market's probability of the whole bet, how each was computed, flags and both EVs |
| `logout` | Forgets the `--remote` browser sign-in (`--mcp-url` for one server, else all) |
| `config` | Shows or sets the defaults file (above) |
| `view` | Renders a saved `--json` result of `map`, `price` or `settle` the way `--rich` does, with no database (`-` reads stdin), so a result made on the VM can be read anywhere |
| `settle` | `map`, plus each leg's result from the stored classification (`kinds.settle`, through `private_book.outcome_for`), and each line's result, payout and profit per unit staked |

| Option | Meaning |
|---|---|
| `--json` | The whole result as JSON (fields below) |
| `--rich` | A coloured terminal table ([Rich](https://github.com/Textualize/rich), `racinglines/cli/rich_view.py`) instead of plain text: one row per line with a slip's legs nested under it, EV and results green above zero and red below, flags, unmapped lines and assumptions in panels |
| `--db URL` | The database for local mode (default `DATABASE_URL`, else `db` in the defaults file) |
| `--demo [PACK]` | A demo store (`racinglines/cli/source.py`): a local database of synthetic data from a data pack (default kart), built on first use; FILE defaults to the pack's book. `--db` doesn't apply |
| `--remote` | Run on the hosted MCP server instead: the book file is sent to its `map_book` / `price_book` / `settle_book` tools ([MCP: Hosted](../mcp.md#hosted-the-vm)), which return the same result, so `--json`, `--rich` and plain text work unchanged. Read-only, like every MCP read. `--run` is passed on; `--db` and `--sims` are local only |
| `--local` | Your own database, even when the defaults file says otherwise |
| `--mcp-url URL` | The server for `--remote` (default `RACINGLINES_MCP_URL`, else `mcp_url` in the defaults file, else `https://mcp.racinglines.bet/mcp`, the production VM; staging runs no MCP server) |
| `--run ID` | Price the legs of that run's competition from this model run (repeatable, one per sport). Default: the app's own choice per race, `markets/venues.pricing_run` (the live stage or forecast run before the race, the latest as-of run made before the start once it has run) |
| `--sims RACE_ID=FILE` | An `OutcomeSims` archive (`models/outcomes.save_sims`) for one race. Legs on that race are then priced jointly from it (repeatable) |

## The book file

The book file uses the [schema](index.md) as before, with these optional additions:

- `[book] sport`: the sport of the book's `event` key (`sports/<code>.toml`). Without it, a leg must name its own
  `sport` or `race_id`.
- `sport`, `event` and `race_id` on a market table or a leg: that leg's event, so one slip can hold legs on F1,
  NASCAR and MotoGP.
- `driver_id` and `opponent_id`: athlete ids instead of names.
- `odds` on a combo's leg: a parlay with no quoted odds of its own pays the product of its legs' odds (the line's
  `odds` may then be left out).
- `id` on a line: the name that output and errors use (default: its 1-based position).
- `[aliases]`: an exact table from the venue's spelling to our display name (`"Alpha, Ann" = "Ann Alpha"`).
- `box = [x, y, w, h]` on a line and `[book] image`: where `book render --style hud` puts the line's label on the
  book's screenshot ([Bet-slip graphics](render.md#hud-placement-box)). Pricing ignores them; `--json` carries `box`.

A slip is a line whose market is `kind = "combo"` with `legs = [...]` ([combos](index.md), `markets/combos.py`).
This synthetic example has a single and a cross-sport parlay:

```toml
[book]
venue = "book_x"
event = "2026-17"
sport = "f1"
captured_utc = "2026-10-07T09:00Z"
source = "paste"
odds = "decimal"
currency = "USD"

[[lines]]
id = "win"
title = "Race Winner"
selection = "Ann Alpha"
odds = 3.0
market = { kind = "race_win", driver = "Ann Alpha" }

[[lines]]
id = "parlay"
title = "Parlay"
selection = "Cora Cup win + Dan Duke win"
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Cora Cup", sport = "nascar", event = "2026-30", odds = 2.0 },
  { kind = "race_win", driver = "Dan Duke", sport = "motogp", event = "2026-18", odds = 4.0 },
] }
```

## Mapping: exact keys only

- **Race.** `race_id` (the database's `races.id`), or `(sport, season, round)`: the event with that `series_round` in
  the sport's competition and season, in the competition's first category (`sports/<code>.toml`
  `[competition] categories`). No match, or more than one, leaves the leg unmapped.
- **Athlete.** An id in the race's field, or a name equal to a display name in it, after the book's exact
  `[aliases]` table. The field is everyone in the race's predictions, results or linked markets. Case,
  accents and surnames are not matched loosely. A near miss is unmapped and the reason names it.
- **Kind.** The book file's `market.kind`, checked against the registry when the file loads. A race prop (safety car,
  red flag, rain) maps, but no stored run prices it.
- A line whose market is `"unmapped"`, or any of whose legs is unmapped, is listed under `unmapped` and is not
  priced or settled.

## What EV is computed against

For a bet with decimal payout `d` (the stake included: `d = 1 / implied probability`, whatever the odds format) and
probability `p`, EV per unit staked is `p x d - 1`. `edge` is `p - 1/d`.

| Column | Probability |
|---|---|
| `book_prob` | The book's implied probability, `1 / d`, with the book's margin still in it |
| `model_prob` | The model's fair probability from a stored run (`db/reads.model_prob`, the same read the board uses for exchange links), with the leg's side applied (`no` and `under` are the complement) |
| `market_prob` | The linked exchange market's price for the same key (`market_links`: same race, kind, athlete and opponent / team / line; an h2h listed the other way round counts as its complement; an inverted link is flipped). The mid of bid and ask, else the link's last price, else the tape's last price (`markets/store.last_before`). When several exchanges list it, the most recently synced one is used and every quote is listed under `quotes` |
| `ev_model`, `ev_market` | EV against `model_prob` and against `market_prob` |

**Slips.** The payout is the line's quoted odds, else the product of the legs' odds. The model's probability of the
slip:

1. **Legs on different races are independent.** The slip's probability is the product of the races' probabilities.
   This is an assumption, and the output says so (`assumptions`, and a flag on the line).
2. **Legs on the same race are correlated** (a winner is on the podium). They are priced jointly from simulations
   when they are available: an `OutcomeSims` passed with `--sims` (`markets/combos.combo_fair`: the share of
   simulations in which every leg holds), else the newest stored combo run (the Lab job `f1_combo`, `model_runs.kind
   = 'combo'`) holding exactly these legs (its `calibrated: false` flags are passed through). Otherwise the product
   of the legs' marginals is used, and the line is flagged **`correlated: EV approximate`**. No correlation model is
   invented here.
3. The market's slip probability is always the product of its legs' prices. No exchange lists the slip itself. When
   legs share a race, it carries the same flag.

## Model and market: no blend

Both prices and both EVs are shown side by side, and nothing combines them. The owner decided on no blend
(2026-10-07); a blend later would need a new row here in the [F1 roadmap decision log](../f1-roadmap.md) format.

| Date | Decision | Status |
|---|---|---|
| 2026-10-07 | Blend of model fair and prediction-market price for sportsbook slip EV: **none**. `book price` shows both prices and both EVs side by side | Decided (owner) |

## Settlement

Each leg follows the single market's own rule (`kinds.settle`, through `private_book.outcome_for`, the same rule
`markets/combos.settle` applies to a combo's legs), and its side is applied:

| Leg result | When |
|---|---|
| `won` / `lost` | The stored classification decides it |
| `void` | The classification is stored but cannot decide it (for example, an h2h opponent who did not start) |
| `manual` | The results do not record it (the fastest lap, a race prop) |
| `pending` | No classification is stored for the race yet |

For a line: any lost leg loses it (payout 0). Otherwise a pending leg leaves it pending, and a manual leg leaves it
manual. A void leg voids the line and returns the stake (payout 1) under `void_leg = "void_all"`, the default. Under
`"drop_leg"`, the other legs decide, and the payout is re-priced from their odds when the legs carry odds; otherwise
the payout is left to the book. A won line pays `d`. Payout and profit are per unit staked. Cancelled-race venue
rules (`markets/settlement_rules.py`) are not applied here.

## JSON output

`--json` prints one object. Its keys are stable, every key is always present, and a value that does not apply is
`null`.

- `book`: `venue`, `event`, `sport`, `captured_utc`, `odds`, `currency`.
- `lines[]`: `line` (1-based), `id`, `title`, `selection`, `kind` (`combo` for a slip), `status`
  (`mapped` / `unmapped`), `reason`, `n_legs`, `races` (race ids), `odds`, `decimal_odds`, `book_prob`, `model_prob`,
  `model_method` (`single`, `product`, `joint: simulations passed in`, `joint: stored combo run N`, joined by ` x `
  across races), `market_prob`, `market_method`, `flags`, `edge_model`, `edge_market`, `ev_model`, `ev_market`,
  `result`, `payout`, `profit`, `box` (the line's HUD box, or null), `legs`.
- `lines[].legs[]`: `line`, `leg` (`"3"` or `"3.2"`), `status`, `reason`, `sport`, `competition`, `season`, `round`,
  `event_key`, `race_id`, `event`, `kind`, `side`, `athlete_id`, `athlete`, `opponent_id`, `opponent`, `team`,
  `threshold` (an over/under line), `odds` (the leg's own). `price` adds `book_prob`, `run_id`, `run_source`,
  `model_prob`, `model_note`, `market_prob`, `market_exchange`, `market_bid`, `market_ask`, `market_synced_utc`,
  `ev_model`, `ev_market` and `quotes[]` (`exchange`, `link_id`, `token_id`, `prob`, `bid`, `ask`, `closed`,
  `synced_utc`). `settle` adds `result`.
- `unmapped`: the ids of the lines that are not mapped.
- `price` only: `assumptions` (the list above) and `blend` (`"none: ..."`).

Probabilities are fractions, and EV and payout are per unit staked. Tests: `tests/test_book_slips.py`, a synthetic
book on F1, NASCAR and MotoGP races in the Postgres test database.
