# Bet-slip graphics: `racinglines book render`

`racinglines book render` turns a priced board into one self-contained HTML page, and a PNG when a headless Chromium
is around, in three styles. It reads the same prices as [`book price`](slips.md): the model's fair probability from
the app's pricing run, every linked exchange quote (Polymarket, Kalshi, OG.com) with its sync time, and the book's
odds. Sizing comes from a settings table (`markets/books.toml`), not from code. The command is CLI only and read-only
on the database, like the rest of `racinglines book`. Code: `racinglines/books/render.py` and `render.css`. Tests:
`tests/test_book_render.py` (no database).

| Style | Shows |
|---|---|
| `hud` | The book's own screenshot with our label on each line: the stake or PASS, the model's chance, the market price used and its exchange, and the EV against the model and against the market. Each label sits in the line's `box`. Lines without a box are listed in a side panel next to the screenshot, with the totals and the sizing rule |
| `card` | The same content per line in the racinglines dark style (1200 px wide), grouped by market kind, without the screenshot |
| `agnostic` | No book odds and no stakes. Per selection: a bar for the model's chance, a tick per exchange where its quote is tight, and the minimum decimal odds worth taking. The title is neutral ("Matchups and potential winners to watch") |

Every output ends with the same footer: the model run ids and their source, each exchange's latest sync time, the
board's capture time (not on `agnostic`), "calibration unvalidated" (the C48 calibration check is not done), "Not
betting advice", and racinglines.bet.

## Commands

```
# LOCAL (Mac) or VM — price from the database and render
racinglines book render books/book_a/2026-10-10-singapore.toml --style hud --png

# LOCAL (Mac) — render a saved `book price --json` result, no database needed
racinglines book price books/book_a/2026-10-10-singapore.toml --json > priced.json      # on a machine with the DB
racinglines book render --json-in priced.json --style card --png
racinglines book render books/book_a/2026-10-10-singapore.toml --json-in priced.json --style hud --png   # boxes and image from the file

# LOCAL (Mac) — road cycling: the folder `racinglines cycling price` wrote
racinglines book render reports/2026-10-10-il-lombardia --style agnostic --png

# LOCAL (Mac) — a book file draft from pasted lines
racinglines book new --from-text board.txt --venue book_a --event 2026-17 --odds decimal --out books/book_a/2026-10-10-singapore.toml
```

| Option | Meaning |
|---|---|
| `FILE` | A book file (priced through `price_book`, as `book price` does), a `cycling price` output folder or one of its CSVs, or a `.json` priced result. It can be left out when `--json-in` is given |
| `--style hud\|card\|agnostic` | The style (default `card`) |
| `--image PNG` | The book's screenshot, for `hud`. Default: `[book] image` in the book file, relative to the file |
| `--out PATH.html` | Default: `<input stem>-<style>.html` next to the input |
| `--png` | Also write `PATH.png`. The page is measured in a first headless pass and then captured at its full size, at the device pixel ratio in `[render] dpr` (2 for `card` and `agnostic`, 1 for `hud`, which keeps the screenshot's own pixels). The capture is cropped with Pillow when it is installed |
| `--chrome PATH` | The Chromium to use. Without it: `$RACINGLINES_CHROME`, then `chromium`, `chromium-browser`, `google-chrome`, `google-chrome-stable` or `chrome` on `PATH`, then `/opt/pw-browsers/chromium-*/chrome-linux/chrome` (Playwright) and the macOS app folders. If none is found, the command stops with an error that lists where it looked |
| `--json-in PRICED.json` | A saved `book price --json` result. Given together with a book file, the file supplies `box` and `image` (for JSON saved before those fields existed) |
| `--run ID`, `--db URL` | As for `book price` |
| `--bank --kelly --cap --min-ev --scale --drop-under` | Override `markets/books.toml [stake]` for this call. The owner's nominal sizing is `--scale 0.1 --drop-under 0.50` |

## HUD placement: `box`

A book file's `[[lines]]` entry may carry `box = [x, y, w, h]`, in pixels on the screenshot. The box is **where the
label goes**: a free area of that line's row, between the selection and the odds, so the label covers neither of
them. Draw it when the screenshot is transcribed. The label's three lines of text scale with the box's height (a
48 px box gives 12 px text). A line without a box goes in the side panel, so a board can be rendered before any box is
drawn. `[book] image` names the screenshot, relative to the book file. Both fields are optional and validated by
`racinglines/books/schema.py`, and `book price --json` carries `box` on each line.

```toml
[book]
venue = "book_a"
event = "2026-17"
sport = "f1"
captured_utc = "2026-10-09T11:00Z"
source = "screenshot"
image = "2026-10-09-h2h.png"
odds = "decimal"
currency = "USD"

[[lines]]
id = "1"
title = "Head to Head"
selection = "Ann Alpha"
odds = 2.0
box = [262, 100, 270, 48]
market = { kind = "race_h2h", driver = "Ann Alpha", opponent = "Bea Beta" }
```

## Sizing: the v2 rule, as data

`markets/books.toml [stake]` holds the rule. One function (`render.size`) applies it to every sport and venue:

1. **Market price.** The market price is the tightest linked exchange quote that has both a bid and an ask and a
   spread (ask - bid) of at most `[market] max_spread` (0.20), taken at its mid. A tie in spread goes to the most
   recently synced quote. A slip's market price is the product of its legs' prices. This choice differs from `book
   price`'s `market_prob`, which takes the freshest quote whatever its spread, so the EV against the market here is
   computed against this price.
2. **Bet or pass.** Bet only when the EV (`p x decimal odds - 1`) is at least `min_ev` (5%) against **every**
   probability named in `require` (`["model", "market"]`). A line with no price for one of them is a pass, and its
   label says so ("no market price: no bet under the rule"). This applies to every cycling line, since no exchange
   lists those races. Unmapped lines are not priced.
3. **Size.** `kelly` (half) Kelly on the lowest of the required probabilities, on a `bank` of $1,000:
   `bank x kelly x (p x d - 1) / (d - 1)`.
4. **Floor and cap.** Each bet is at least `floor` ($1). If the book's total is over `cap` ($100 per venue per event,
   meaning one book file), the floor bets stay at the floor and the rest are scaled down to fill what is left. When the
   floors alone would pass the cap, the cap is split evenly.
5. **Nominal sizing.** Every stake is then multiplied by `scale`, and a stake under `drop_under` is dropped, with the
   reason shown on the line.

Changing the rule means changing the table, not the code: `require = ["model"]` sizes on the model alone, and
`min_ev`, `kelly`, `bank`, `floor` and `cap` are numbers. Model and market are still never blended (the 2026-10-07
decision in [slips](slips.md#model-and-market-no-blend)): sizing uses the lower of the two, not a mix.

## Agnostic numbers

- **Ticks.** One tick per exchange, only where the quote has both a bid and an ask and a spread of at most
  `[agnostic] max_spread` (0.10). Below that, the mid means little.
- **Minimum odds.** `margin / min(model, every tight mid)`, with `margin = 1.05`. When no mid is tight, the model alone
  is used. For example, with the model at 40% and a tight Kalshi mid at 38%, the minimum odds are 1.05 / 0.38 = 2.76.
- Lines with no model price (unmapped lines, race props) and slips are left out. The note gives their count.

## Road cycling

`racinglines cycling price` writes `reports/<event>/futures.csv` (rider, `win_p`, the book's `book` odds) and
`matchups.csv` (`a`, `a_odds`, `a_p`, `b`, `b_odds`, `b_p`). `render` reads them as they are (`rows_from_cycling`):
one "to win" line per rider and both sides of each matchup. It names `settings.csv` and the files' write time in the
footer. What is missing from the cycling CLI on main today:

- **No run id or commit.** The footer names the folder, the settings and the write time instead.
- **No blend.** The cycling CLI on main prices from the model alone. The halfway blend with the book's no-margin
  price lives only in the one-off HUD scripts, so `render` shows the model's price.
- **No exchange prices.** The default rule therefore passes on every cycling line. `--min-ev` and a `require =
  ["model"]` table size them on the model alone, if the owner decides that.
- **No team names.** These are not in the CSVs, so the graphic shows riders only.

## Loose text: `book new --from-text`

The input is one bet per line:

| Input | Becomes |
|---|---|
| `Race Winner:` | A title for the lines after it (default "Winner" for singles, "Head to Head" for matchups) |
| `Ann Alpha over Bea Beta 1.57` | One line: Ann Alpha at 1.57 (`beats` and `ahead of` work too) |
| `Ann Alpha vs Bea Beta 1.57 2.25` | Two lines: Ann Alpha over Bea Beta at 1.57, and Bea Beta over Ann Alpha at 2.25 |
| `Cid Cee 4.35` | One line on the current title |

Odds are read in `--odds` (`decimal`, `american` such as `+150` and `-118`, `fractional`, `cents`, `dollars`,
`prob`) and checked like a book file's. Titles and selections are kept as written. Every market is left `"unmapped"`,
and its note records what the line was read as. Write each market table, then run `book map`. Lines that match no
pattern, or whose odds are not valid in the format, are listed at the top of the file and on the terminal. They are
not guessed. The command refuses to overwrite an existing file.

## Decision log

Same format as the [F1 roadmap decision log](../f1-roadmap.md). These are tuned settings in `markets/books.toml`:

| Date | Decision | Status |
|---|---|---|
| 2026-10-09 | Sportsbook sizing, the v2 rule: bet only when EV >= 5% against the model **and** against the market; half Kelly on min(model, market); $1,000 bank; $1 minimum; the event's total scaled down to the $100 per-venue-per-event cap. Owner's nominal sizing on top: x0.1, drop stakes under $0.50 (`--scale 0.1 --drop-under 0.50`) | Decided (owner) |
| 2026-10-09 | Market price for the rule: the tightest two-sided exchange quote with a spread of 20 points or less, at its mid (as the Singapore FP1 head-to-head HUD) | Default, owner to confirm |
| 2026-10-09 | Agnostic graphic: an exchange tick only where the spread is 10 points or less; minimum odds = 1.05 / min(model, tight mids) | Default, owner to confirm |
