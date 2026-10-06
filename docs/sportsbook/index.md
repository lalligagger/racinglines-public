# Sportsbook and special-event markets: the schema (draft, 2026-10-06)

Owner decisions (2026-10-06): sportsbook analysis stays separate from the web app, CLI tools only; events are defined
by exchange-agnostic schemas; the deployment target is the hosted MCP server (`docs/mcp.md`), not the web app. The
full roadmap (coverage of the three generic sportsbooks (A: decimal odds, B and C: American odds) boards, tiers per market, phases) lives in the HL project
library; this page is the part the repo needs: the schema, the vocabulary, the CLI and the MCP surface.

The owner's rule: sportsbook analysis is CLI only, outside the app and its database for now, and events are defined by
schemas that no venue owns. The repo already defines sports (`sports/<code>.toml`), exchanges (`exchanges/<code>.toml`,
read by `racinglines/exchanges.py`) and input frames (`racinglines/frames/schema.py`) as data with a validator. The
proposal adds three more files of the same kind. Draft examples, built from real board rows, are under
[`schemas/`](schemas/) and load through `racinglines/books/schema.py` (`tests/test_books_schema.py` loads every one).

| File | One per | Holds | Example |
|---|---|---|---|
| `events/<sport>/<season>-<round>-<slug>.toml` | event | sport, season, round, the launch-spec key (`live/f1/2026-17.toml` uses `event = "2026-17"`), `race_id` (the DB's exact key), format, session start times (UTC), the market kinds the event opens and their lines. **No venue, no prices, no entrants** (entrants come from the DB entry list for `race_id`) | [`events-f1-2026-17-singapore.toml`](schemas/events-f1-2026-17-singapore.toml) |
| `venues/<code>.toml` | venue | code, name, `kind = "sportsbook" \| "exchange"`, odds format, currency, who settles, observed caps and voids as notes, and `[[rules]]`: regex on the venue's market title → kind + subject, exactly the shape of `exchanges/og.toml` `[[sports.f1.rules]]`. Selections resolve to the entry list through an exact alias table ("Sainz Jr, Carlos" → "Carlos Sainz"), never fuzzy; an unknown name is `unmapped` | [`venues-book_a.toml`](schemas/venues-book_a.toml) |
| `books/<venue>/<date>-<event>.toml` | capture | venue, event key, capture time (UTC), source (screenshot / paste / api) and its reference, odds format, and `[[lines]]`: the venue's own `title` and `selection` untouched, the odds, a transcription `note`, and the `market` key the rules produced, written into the file so the mapping is reviewable before pricing | [`books-book_a-2026-10-05-singapore.toml`](schemas/books-book_a-2026-10-05-singapore.toml) |
| (same) | capture | A second venue in the same shape, American odds, same event file untouched: sportsbook B's 22-driver winner board from the owner's screenshot (2026-10-05 22:59 PDT). Its overround is 23.3%; the model comparison is the "track sportsbook bets" thread's job | [`books-book_b-2026-10-05-singapore.toml`](schemas/books-book_b-2026-10-05-singapore.toml) |

**Odds presentations** (`venue.odds` and `book.odds`; `racinglines/books/schema.py` checks each, `to_prob` reads a quote
as an implied probability with the venue's margin still in it, `present` writes a fair value in the venue's own units).
The names are provisional: the owner checks them after the merge ([todo: owner decisions](../todo.md#owner-decisions)).

| Name | Looks like | Where | Means |
|---|---|---|---|
| `decimal` | 1.85 | European sportsbooks (sportsbook A) | payout per unit staked, stake included |
| `american` | -118 / +150 | US sportsbooks (sportsbooks B and C) | stake to win 100, or the win on a 100 stake |
| `fractional` | "7/4" | UK sportsbooks | the win per unit staked, as a string |
| `cents` | 37 | Kalshi | price of a $1 YES contract, in cents (1 to 99) |
| `dollars` | 0.37 | Polymarket, OG.com | price of a $1 share, in dollars (0 to 1) |
| `prob` | 0.37 | our fair values | a plain probability |

**What makes it exchange-agnostic.** The market key is `(kind, subject, params)` in the kinds registry's vocabulary
(`racinglines/markets/kinds.py`), the same key Kalshi's and Polymarket's classifiers already produce and OG.com's rules
file produces. A sportsbook A line, an sportsbook C American-odds line and a Kalshi contract for the same thing carry the same key,
so one fair value prices all three and one `settle()` decides them. A new venue is a `venues/<code>.toml`; a new market
type is a kind (with `fair` and `settle`) and one rule line per venue that lists it. Exchanges' own API schemas stay in
`exchanges/`; a `venues/` file for an exchange would hold only its title rules, which for OG.com already live in
`exchanges/og.toml` (one of the two should own them: **decision**).

**The CLI around it** (all read-only against the app; nothing writes to `market_links` or any app table):

| Command | Does |
|---|---|
| `racinglines book map <book.toml>` | applies the venue rules, writes `market` keys into the book file, lists every `unmapped` line and every unknown selection name |
| `racinglines book price <book.toml> --run <id>` | fair value per mapped line from a stored run's predictions (MCP `get_predictions` on the VM, or a local run id), no-vig, shrink, EV, Kelly at the configured fraction and bankroll, picks CSV; the output keeps the run id, commit and latest race in the data on every row |
| `racinglines book settle <book.toml>` | `kinds.settle()` from the classification once the race is in the DB; writes result and payout per line, and updates `ledger.csv` rows that reference the book |
| `racinglines event new <sport> <season> <round>` | writes the event file from the DB (race_id, sessions, format) so the exact key is never typed by hand |

Settings for the shrink (halfway to the book's no-vig price), the Kelly fraction (the owner uses half; the cycling CLI
defaults to a quarter, `racinglines/cli/cycling.py:145-146`), bankroll and the longshot filter live in one TOML with a
decision-log entry. Sportsbook lines stay out of `market_links`, the disagreement log and the app's CLV work until the
owner says otherwise; CLV for hand-placed bets is computed by the CLI from the book's own later captures (or an
exchange's close as a proxy, `docs/todo.md:279`) into the ledger's `closing_odds` column.

**Validation** (built, second commit). `racinglines/books/schema.py` in the style of `frames/schema.py`: `load_event`,
`load_venue`, `load_book` and `load` (picks the schema from the top-level table) return the parsed dict or raise
`BookError` listing every problem with its field: required sections and fields, odds that can be odds in the file's
format (decimal > 1, American an integer of at least 100 either way, prob in (0, 1)), UTC times (ISO 8601 ending in `Z`,
or `"unknown"` for a session), every `market.kind` in `kinds.KINDS` or `props.PROP_KINDS`, every rule title a compilable
regex, every line either `"unmapped"` or a market table carrying the driver / team / opponent / line its payoff needs.
`tests/test_books_schema.py` loads every example under `schemas/` (as `tests/test_exchange_schema.py` does for
`exchanges/`, `docs/exchanges.md:26`). The five classification kinds the vocabulary needed are in the registry with
`fair` and `settle` (`kinds.py`, `default=False`, so the app's summaries and the golden tests are unchanged).

**What the exchanges list today, for the rules files.** Polymarket's safety car / red flag / rain questions are linked but
unpriced (`docs/f1.md:178-181`); Kalshi sprint markets price from the stand-in; Kalshi retirements and "race occurrence"
are `unmodeled` (`kalshi/sync.py:25-28`); OG.com lists only champions and Race Winner (`docs/exchanges.md:34-40`).
Polymarket has listed no F1 race since 28 Aug 2026 (`docs/coverage.md:10`), so near-term exchange coverage means Kalshi
and OG.com.

## MCP surface (the deployment target)

The CLI commands above are the same functions the hosted MCP server exposes, so a thread can price a board from the
VM's current run without a cloud rebuild (owner, 2026-10-06: "the eventual deployment target is to add these
sportsbook/special event analytics to the MCP tools"). Proposed tools, beside the existing `list_markets`,
`get_predictions` and `run_job` (`racinglines/mcp/`):

| Tool | Does |
|---|---|
| `price_book(book_toml, run_id=None)` | the `book price` command on a book file passed as text: mapped lines with fair, no-vig, EV and stake; unmapped lines listed |
| `map_book(venue, lines)` | applies a venue's rules to raw `(title, selection, odds)` rows and returns the market keys, so a thread can transcribe a screenshot and get a reviewable mapping back |
| `settle_book(book_toml)` | results per line from the classification once the race is in |
| `list_kinds()` | the vocabulary: every kind, its status, subjects and known venue wordings (`vocabulary.md`) |

The sportsbook files themselves are not stored in the app's database: a book is passed in and the priced table comes
back, and the owner's ledger stays a file outside the app.

## Vocabulary

[vocabulary.md](vocabulary.md), generated from [`schemas/kinds-vocabulary.toml`](schemas/kinds-vocabulary.toml):
49 kinds, 29 in the registry (16 before this branch, 13 added here: classified, last classified, both cars classified, at least one car classified, both cars in the points, number classified, winning constructor, retire, number of retirements, first, second and third retirement, first retiring constructor), 3 in `props.py` only, 16 proposed, 1 with no data source; 17 seen on two or more
venues, 20 seen only on sportsbook A.
