# Alpha layout

The web app's layout for the fantasy alpha (owner, 2026-10-12): four tabs and nothing else. It is a switch, not a
rewrite. The pages it hides are archived, so their routes, templates and tests stay in the code and come back with
one environment variable. The code is in `racinglines/web/layout.py`.

The last staging commit before the layout is **8c3c05d** ("[app] Fantasy first cut: My F$ balance page, manual IOC
trading on recorded books, leaderboard (staging only)", #151). Check it out to see the app as it was.

## What it shows

| Tab | Address | What is on it | Code |
|---|---|---|---|
| **Markets** | `/markets` | Unchanged: the prediction markets now, and what the model says about the busiest prices | `web/views.py`, `templates/board.html` |
| **Trade** | `/trade` | Fantasy trading on the recorded order books: pick a market, see its book, place an IOC order in F$. An order never goes past the recorded book (depth 10) | `web/fantasy_routes.py`, `templates/fantasy_trade.html`, `fantasy/exchange.py` |
| **History** | `/history` | Your F$ (total, cash, by hand, strategy), F$ by hand through the run, open trades with Sell links, every order by hand (refused ones with the reason), your strategy's trades, and the leaderboard (`/history#leaderboard`) | `web/fantasy_routes.py` `history_page`, `templates/history.html`, `fantasy/ledger.py` |
| **Lab** | `/lab` | The advanced tools: follow a strategy (`/strategy/pick`), its performance (`/strategy`), its positions (`/positions`), and for Pro accounts backtests and research (`/lab`). An account without Pro that opens `/lab` goes to `/strategy`. The unread-signals badge sits on the tab | `templates/_lab_nav.html` |

Admins also get **Admin**. The right side of the top bar keeps only the GitHub badge and the account links (name,
Settings or Sign up, Log out).

### The leaderboard's score

Score = ROI × √trades (owner, 2026-10-12). ROI is the P&L (by hand plus strategy) over the F$ staked: what an
account's buys paid, fees included, plus what its strategy paid in, net of what it sold back. Trades counts the
filled orders by hand plus the markets the strategy traded. An account needs `MIN_TRADES` (5) trades to be
ranked, so one lucky trade can't top the board. Accounts with fewer are listed after the ranked ones, by total
F$, with "–" for rank. The demo accounts aren't listed. Open trades count at what they would sell for now (the best
recorded bid). The code is `fantasy/ledger.py` (`MIN_TRADES`, `TRADE_STATS`, `score()`, `ranked()`).

### Old addresses

| Old | Now |
|---|---|
| `/fantasy` (My F$) | 303 to `/history` |
| `/fantasy/trade?...` | 303 to `/trade?...` (the query string is kept) |
| `/leaderboard` | 303 to `/history#leaderboard` |

`POST /fantasy/orders` keeps its address and sends you back to `/trade?link=...`.

### Picking a style (`/strategy/pick`)

Under the alpha layout the picker is five **style cards** instead of the full list (owner, 2026-10-12 19:23-19:55Z,
asking for variety over best performance). Each card has a name, one sentence for a first-timer, its 2026 and 2025
backtests ("backtest, season P&L at our standard sizing", copied from the profile's `why` line) and a Follow button.

| Style | Profile | Note |
|---|---|---|
| Steady | T1 | |
| Head start | T2 | |
| Early bird | T8 | labelled in-sample: tuned on the same seasons it is scored on |
| Big markets only | T6 | |
| Hair trigger | T5 | |

- The names, sentences, numbers and order are one data structure: `ALPHA_STYLES` and `ALPHA_ORDER` in
  `pipelines/profiles.py`. Users never see the codes or the `why` text.
- **Sizing:** Standard (the backtests' fixed stakes) or Kelly, with a fraction slider from 10% to 100% (default 25%),
  quick picks for Quarter, Half and Full, and a tier label (Nitty, Shark, Spicy, Degen). Kelly is labelled untested.
  The choice is saved on the profile as `sizing` and `kelly`. The signal engine doesn't read it yet.
- **Tweak drawer** (closed by default, Pro and admin only): two sliders (edge needed, market volume) and the dice. A
  moved slider is labelled "untested: scored live from the next race weekend".
- Basic accounts pick from the same five by name instead of the random "Your picks" draw. An account already running
  a draw keeps it.
- Makers, the TB blend and the other codes aren't offered. `POST /strategy/pick` refuses them for everyone but admins
  (`MAKERS_OPEN` is untouched, so the Edge Finder still shows makers).
- Saves still pause during a race weekend's signal window.
- `/strategy` drops the venue tabs, the sport select and the "How it chooses" tab. Admins keep the user select.
- The switch is `strategy_pick.alpha_picker()`. With the classic layout the page is unchanged.

## What it hides

- **Live events:** `/live` and everything under it. The bar's Live link goes too.
- **Private books:** `/book` and everything under it (Books / My book). On Markets the "My open markets" KPI goes; on
  Positions the private book's venue option, its P&L plot button, its mention in "About these positions", its rows
  and the in-app bets go, and the "In-app markets you quote are on My book" line goes. `?venue=private` shows all
  venues instead. History's strategy trades leave the private book out.
- **Pitch and Docs links** in the top bar's right side. The pages themselves still answer.
- The old bar's Strategy, Positions, My F$ and Leaderboard links. Their pages live under Lab and History.

Hidden routes answer **404 to everyone but admins**: `layout.guard()` runs inside `authenticate` in
`web/app.py`, for every signed-in page, and checks `HIDDEN_PREFIXES` (`/live`, `/book`). Admins can still open
them to check on them.

## The switch

| `RACINGLINES_LAYOUT` | Layout |
|---|---|
| `alpha` | The alpha layout |
| `classic` | The old bar and every page, as before (the fantasy pages, if on, are linked as Trade and My F$) |
| unset | Follows the fantasy switch, `fantasy/ledger.on()`: alpha where `RACINGLINES_FANTASY=1`, or on staging (`RACINGLINES_ENV=staging`) with that switch unset; classic otherwise, as on production today |

Templates read it through the `alpha_layout()` global (`web/app.py`). `positions_page` in `web/views.py` passes
`hide_private` to its template.

## Bringing the archived pages back

1. **For one deploy:** set `RACINGLINES_LAYOUT=classic` in the app's environment (staging: its env file on the VM)
   and restart the web service. Everything comes back as it was, and nothing in the database changes.
2. **For good, page by page:** remove a prefix from `HIDDEN_PREFIXES` in `web/layout.py` to stop the 404, then add
   its link to the alpha branch of the bar in `templates/base.html` (the `{% if user and alpha_layout() %}` block)
   and drop the `alpha_layout()` / `hide_private` conditions in `board.html` and `positions.html` that hide it.
   That is a code change, so it is a deploy.
3. **The whole alpha:** delete the alpha branch of the bar in `base.html` and make `alpha()` return False. The
   old bar is still there below it, unchanged.

Tests: `tests/test_fantasy_trading.py` (the pages, the redirects, the nav under both layouts, the 404s, the
Positions page) and `tests/test_fantasy_exchange.py` (the score and the switch, without a database).
