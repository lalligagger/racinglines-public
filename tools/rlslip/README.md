# rlslip: slip EV in Rust (demo)

A small Rust command-line demo of `racinglines book price` ([docs/sportsbook/slips.md](../../docs/sportsbook/slips.md)).
It reads a book file of generic sportsbook lines (the [book schema](../../docs/sportsbook/index.md)) and a fair-price
file, and prints for each bet the book's implied probability, the model's and the market's probability, EV against
each, and a fractional-Kelly stake. It needs no database and no network: where the Python command reads a stored model
run and the linked exchange markets, this reads the fair prices from a file.

It is a standalone demo. Nothing in the app, the VM or CI builds or runs it.

## Run

```
# LOCAL (Mac) or CLOUD — needs a Rust toolchain (rustup)
cd tools/rlslip
cargo run --release -- price examples/book.toml --fair examples/fair.toml
cargo run --release -- price examples/book.toml --fair examples/fair.toml --json
cargo run --release -- odds -118 --from american
cargo test
```

The example files are synthetic (made-up names and numbers, like the docs' examples).

## What it computes

Same rules as `racinglines/books/slips.py`:

- Odds: `decimal`, `american`, `fractional`, `cents`, `dollars`, `prob`, converted as `books/schema.py` `to_prob` does
  (the unit tests check the Python values).
- EV per unit staked is `p x d - 1`, with `d` the decimal payout, stake included. Model and market are shown side by
  side; nothing blends them (owner decision, 2026-10-07).
- A slip pays its own odds, else the product of its legs' odds. Its probability is the product of its legs':
  across races that is the independence assumption (flagged); on one race it is flagged
  `correlated: EV approximate`. The Python command can price same-race legs jointly from simulations; this demo
  cannot.
- Fair prices are matched by exact keys (kind, sport, event, driver, opponent, team, line). A `no` or `under` side is
  the complement, and so is an h2h listed the other way round. A leg with no match shows `-`.
- Per market title, the sum of the single lines' implied probabilities (over 100% is the book's margin when the set
  of lines is complete).

## Stakes

`stake = bankroll x kelly x full Kelly`, full Kelly being `(p x d - 1) / (d - 1)` (0 when EV is not positive), with `p`
from `--basis model` (default) or `--basis market`. If the stakes on one book file add up to more than `--max-stake`,
they are all scaled down to it. Defaults: `--bankroll 1000 --kelly 0.25 --max-stake 100`. These defaults are a
demo's, not tuned settings (no decision-log entry).

## The fair-price file

```toml
[fair]
source = "where these came from"
as_of_utc = "2026-10-07T09:00Z"

[[prices]]                 # the yes / over side of one market
kind = "race_win"
driver = "Ann Alpha"       # or team, opponent (h2h), line (over/under)
model = 0.38               # either may be left out
market = 0.33
# sport, event: default to the book's
```
