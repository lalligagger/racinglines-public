# Web app & trading

`racinglines/web/` is the maker/taker web app (FastAPI, server-rendered pages, no
JavaScript framework) on top of the [database](database.md).

```
ADMIN_PASSWORD=choose-one racinglines web        # http://127.0.0.1:8000, user "admin"
```

If `ADMIN_PASSWORD` isn't set, a random password is generated and printed at
startup.

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / random | Required on every page. Browsers get a sign-in page (`/login`, 12-hour session cookie); scripts can use HTTP Basic (`curl -u admin:PASSWORD`). |
| `APP_SECRET` | random per start | Signs the session cookie and the anti-forgery token on every form. Set it to keep sessions across restarts. |
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `8000` | Listen address. Keep it on localhost or a private network. |
| `DATABASE_URL` | docker-compose DB | See [Database](database.md). |

## Reaching it from other devices (Cloudflare tunnel)

```
ADMIN_PASSWORD=... racinglines web                                   # still listens on 127.0.0.1
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000        # prints https://<random>.trycloudflare.com
```

- **The app stays on localhost.** `cloudflared` forwards HTTPS traffic to it, so
  there are no open ports and no router changes.
- **Quick-tunnel addresses are random** and last only while the command runs. For
  a stable address on your own domain, create a named tunnel
  (`cloudflared tunnel login`, then `cloudflared tunnel create`).
- **The address is public: anyone with it reaches the sign-in page.** Protections:
  - a strong `ADMIN_PASSWORD`;
  - failed logins limited to 8 per client IP per 15 minutes (using Cloudflare's
    `CF-Connecting-IP` header);
  - session cookies are `Secure` over HTTPS.
- For stronger protection, put **Cloudflare Access** (email one-time PIN or SSO) in
  front of a named tunnel, especially before setting
  `POLYMARKET_TRADING_ENABLED=true`.

## One shape for every sport, race and venue

Every view reads the same structure (`racinglines/markets/venues.py`):

```
event: a race, or a competition's season
  └─ outcome: kind + subject (e.g. race_win · George Russell, race_h2h · A ahead of B)
       ├─ our fair value:
       │    upcoming: the live forecast
       │    past: the last as-of price made before the start (diagnostic, else an earlier forecast)
       ├─ venue quotes: Polymarket · Kalshi (soon) · private book (our own markets)
       └─ result, once the race has run
```

- **Past races:** the exchange column shows the price **at the time of our as-of
  run**, not the resolved 0/1. So "we had 30%, Polymarket 64.5%" compares like
  with like.
- **Adding a venue:** add a `VENUES` entry and rows in `market_links` with
  `exchange = <code>`. Every page then shows its column.

## Pages

The nav follows the role:

| Role | Nav |
|---|---|
| **taker** | Markets · Strategy · Positions |
| **maker** | Markets · Strategy · Positions · My Book · Lab · Pitch · Docs |
| **admin** | Markets · Strategy · Positions · Books (the admin's name for My Book) · Lab · Admin · Pitch · Docs |

Strategy and Positions appear for accounts with a strategy profile, and for admins. The **Strategy** link
carries a badge with the number of unread signals. A paper-account banner (profile, bankroll, return) on
the Markets, My Book and Positions pages links to Strategy and Positions.

**Trading (every role with a strategy profile)**

| Page | What it shows |
|---|---|
| **Markets** (`/markets`), **takers** | Every open Polymarket F1 market (upcoming races first, listed or not yet, then season markets and everything else) with the account's strategy profile's current call on each: side, shares, the most to pay, and heat (`signals.call`; see [Paper trading](paper-trading.md#the-current-call-on-any-market)). Never a fair value or edge. |
| **Strategy** (`/strategy`) | The account's story: paper bankroll (start, now, return), worst drawdown, most capital in use, weekends up, a bankroll curve, and how it has used racinglines. For a maker, every strategy decision with the Edge Finder evidence it had at the time and what the chosen setup then made; for a taker, what it was offered and took by heat, against taking every recommendation. Polymarket only: private-book results are on Positions. Then the track record (every weekend: strategy, trades or fills, P&L, bankroll; backtest replay or live paper) and any weekend's signals by stage, with a link to its positions. Takers never see fair values or edges, only the heat. Admins can pick any user. |
| **Live** (`/live`, every signed-in user; green dot while a final runs, grey once it is over and the page is a replay with a timeline, step and play controls) | A race followed live: leaderboard, riders on course and their split positions, who's up next. Makers also see every rider's rank probabilities, their auto-updating quotes, the private book (crowd fills, positions, event P&L, the crowd's results) and a win-probability chart; takers see their picks' P&L. Refreshes itself every 15 s. See [Live events](live-events.md). |
| **Positions** (`/positions`) | The account's ledger. Three highlight cells: **Polymarket P&L** (paper history), **Private book P&L** (live, play money) and **Total P&L**; click one to show only that venue below (`?venue=polymarket|private`). Open and settled counts and realised P&L for the venues shown; a **P&L history** chart with a Polymarket / Private book switch (the two are never plotted together): the Polymarket bankroll curve with its worst drawdown and Sharpe ratio (mean / s.d. of weekend P&L × √24), or the private book's P&L at every poll of the live event (from its saved snapshots) with its worst drawdown; **Coming up** (the next races' calls for a taker, where it would quote for a maker, from `signals.call` / `maker_call`); totals by market type; every position (open, settled, closed), sorted by weekend or by P&L (`?sort=pnl` best first, `-pnl` worst first; the P&L column header toggles it), and with a weekend picked the executions behind it (trades taken or paper fills). A taker's in-app bets, if any, below. |

**Makers and admin**

| Page | What it shows |
|---|---|
| **Markets** (`/markets`; `/` redirects here), makers and admin | **Headline numbers:** exchange outcomes we price and their volume, order books recording, my open markets and worst case, F1 model vs grid-only baseline, running jobs.<br>**Per sport** (F1 first):<br>• next three races as cards: countdown, venue badges (live / pending / soon / mine), a **new** badge for markets first listed in the last 48 hours, our top-3 win probabilities with the exchange price as a tick;<br>• the season card;<br>• later races;<br>• recent results: winner, our pre-race price, Polymarket at the same time. |
| **Race** (`/races/{race_id}`) | The core page (takers are sent to Markets):<br>• **Header:** where our fair values come from (run and as-of time), the favourite, the result, venue badges, my book here.<br>• **Chart:** Polymarket price history for the top outcomes, with our fair as dotted lines and markers for qualifying, the race and our as-of time.<br>• **One table per market kind** (win, podium, top 10, make the Final, head-to-head, top constructor): fair bar with market tick, a column per venue, gap, my YES/NO quote (or settled P&L), bets, and the result.<br>• **Quote this race** (upcoming): generate private markets from our fair ± spread, or mirror the Polymarket event.<br>• **Classification** (past): with our win and podium prices, plus links to diagnostics. |
| **Season** (`/seasons/{code}`) | The same layout for season-long markets: champion, constructors' champion, season wins, championship head-to-heads. |
| **Polymarket** (`/markets/polymarket`, linked from Markets) | Every listed F1 event, including outcomes we don't price, with **new** badges (48 hours), **Mirror into my book** and refresh. |
| **My Book** (`/book`; **Books** for admin) | Positions across venues. Totals: open markets, bets against me, stakes, EV at fair and worst case (open markets only), settled P&L. One row per event, linking to the race page and to Quotes. Admin can filter by maker. |
| **Quotes** (`/book/quotes`, `/book/markets/{id}`, `/book/quotes/sheet`) | The private book per race, behind My Book: create and reprice, close, record offline bets, settle, quote sheet. See [Private book](#private-book-markets-we-quote). The quote sheet is open to every role. |
| **Lab** (`/lab`) | **Leads with the Edge Finder**, the headline feature for a maker account, per season (**2026**: every weekend raced so far; **2025**: as if live from its first race). A pinned **benchmark** (the conservative maker on the baseline at default settings) that nothing replaces; a card per chosen combo (a saved configuration × a strategy) with its P&L vs the baseline priced from the same data and vs the benchmark; a **full-season recap** (P&L, volume, return on volume, weekends up, average and s.d. per weekend, best and worst weekend, max drawdown, consistency, fills and markout for makers); and P&L per weekend with season totals. Nothing is simulated on a visit.<br>**Candidates:** ★ on a card saves that configuration × strategy as a named candidate (searches add theirs on import; strategy profiles are candidates too). **Load in Lab** opens the **Edge Finder sweep** form (Run) with every setting filled in; changed settings are highlighted, and the new run joins the Edge Finder.<br>**Edge Finder sweep form:** every setting of `racinglines/pipelines/sweep_settings.py`, grouped (model, entry timing, taker, maker, markets), with **Start from** (defaults, your last run, or a candidate) and the season.<br>**Sections, toggled on demand** (each loads from `/lab/section/{key}` the first time it's opened; `/lab#diagnostics` opens one): **Run**; **Jobs** (yours, or everyone's); **Model variants** (click a cell to add that combo); **Scenarios** with **Promote to live**; **Backtests** (+ Edge Finder per model); **Event diagnostics**; **All runs**.<br>**What's stored where:** Edge Finder combos, season and job settings in `users.prefs`; candidates as `model_runs` (`kind='candidate'`); open sections and the jobs filter in the browser; jobs, runs and bets in their own tables. |
| **Event diagnostic** (`/lab/diagnostics/{id}`) | One past event as of a cutoff: our prices vs Polymarket, scoring, the paper taking strategy, and the **maker replay with every strategy knob**. Knobs: fill rule, half-spread, shares per quote, max shares per market, max worst-case loss, inventory skew, disagreement filter, minimum 24 h volume, pull time. Replays take a few seconds. See [Market making](market-making.md). `/lab/diagnostics` opens the Lab's diagnostics section. |
| **Run detail** (`/lab/runs/{id}`) | One stored run: parameters, metrics, predictions. `/lab/runs` redirects to the Lab. |
| **Events / Athletes** (`/events`, `/events/{id}`, `/athletes`, `/athletes/{id}`; linked from Markets and race pages) | Calendar and search; results and prediction history. Every role can open them; takers don't see predictions. |

**Admin only**

| Page | What it shows |
|---|---|
| **Linked markets** (`/markets/linked`, `/markets/linked/lookup`, `/markets/linked/{id}`) | Polymarket markets linked to our predictions, the lookup to link one, and a market's page with the order book and suggested quotes. See [Linking a market](#linking-a-market). |
| **Orders** (`/orders`) | The Polymarket order log. |
| **Admin** (`/admin/…`) | See [Admin pages](#admin-pages) below. |

**Every visitor**

| Page | What it shows |
|---|---|
| **Racinglines 101** (`/racinglines101`, public: no sign-in) | A plain-language intro to makers, takers and the paper-trading demo. Linked from the sign-in page as **I'm already confused.** |
| **Sign in** (`/login`, `/logout`) | Two one-click demo buttons (**Try as maker**, **Try as taker**; the `maker` / `taker` accounts, password `password`) above the standard username/password form, which the admin uses. |
| **Pitch** (`/pitch`) | Serves `pitch.html`, behind the same login. |
| **Docs** (`/docs/`) | Serves these docs as built in `site/` (the pre-push hook builds them; or `python -m mkdocs build -d site`), behind the same login. |

### Launching runs from the Lab

Each run type is a CLI command with typed, range-checked knobs
(`racinglines/web/jobs.py`). Jobs run one at a time in a background thread, as a
subprocess with no shell, and stream their progress into the `jobs` table.

| Job | Knobs | Typical time |
|---|---|---|
| F1 backtest | last N races, recency half-life, simulations, track features (on / off / both) | ~6 s for 5 races, a few minutes for all |
| F1 forward forecast (scenario) | name, half-life, simulations, track features | ~10 s |
| F1 event diagnostic | event, as-of time, half-life, simulations, track features | ~10 s |
| Downhill forward forecast (scenario) | name, half-life, junior weight, simulations | ~1 min |
| Downhill backtest | half-life, junior weight, simulations | a few min |

**Guard rails:**

- **Forecasts from the Lab are saved as `kind='scenario'`.** Live fair prices
  come from the most recently **promoted** forecast (`params.promoted_at`),
  falling back to the newest forecast. Promoting is logged in the activity log.
- **No leakage.** Backtests and diagnostics use the same as-of pricing as the
  CLI, whatever the knobs.
- **Interrupted jobs.** A job running when the app restarts is marked failed
  ("interrupted").

**Routes match page names.** Old URLs (`/`, `/bet`, `/me`, `/signals`, `/pm`, `/house…`, `/race/…`,
`/season/…`, `/diag…`, `/runs…`, and the admin's `/markets/{id}`) redirect to the current ones
(`racinglines/web/legacy.py`).

### Roles

| Role | Can do |
|---|---|
| **taker** | Nav: **Markets**, **Strategy**, **Positions**. **Markets** lists every open Polymarket F1 market with the account's strategy profile's current call on each (side, shares, the most to pay, heat), never a fair value or edge. There is no maker on the other side: takers trade on Polymarket, on paper (see [Paper trading](paper-trading.md)). Race, season, book, Polymarket and Lab pages are closed to takers (a race link sends them to Markets); event and athlete pages show results without predictions. (The in-app private book still exists for makers; a taker's in-app bet is placed at the quoted price, refused if the maker has repriced since the page loaded, with a per-bet cap `MAX_STAKE`, default $100.) |
| **maker** | Nav: **Markets**, **Strategy**, **Positions**, **My Book**, **Lab**, **Pitch**, **Docs** (Strategy and Positions with a strategy profile). **Own** markets only: generate from the live forecast (fair ± spread), reprice, close, see the bets against them. Can launch Lab jobs and promote scenarios. Can't bet, can't touch other makers' markets, and can't settle. |
| **admin** | Everything: the maker nav (My Book is called **Books**) plus **Admin**, which links to activity, users, database, SQL, linked Polymarket markets and the order log. Plus the private book across all makers, settlement (auto and manual), offline bets, Polymarket, any user's Strategy page, strategy profiles (on `/admin/users/{id}`), and the admin pages below. |

Every route declares the roles allowed (`allow(...)` in `app.py`); anything else gets 403.

### Accounts: demo users vs Polymarket's takers

Three accounts are easy to mix up. They are separate entities:

| Account | What it is | Its trades |
|---|---|---|
| `maker` (demo, **Try as maker**) | Our maker, $10,000 paper bankroll from 2025-01-01. 2025: M1 (the defaults: conservative maker, baseline model), then M2 (grid-aware maker, 10-pt filter) after round 8, then M3 (gbm maker, 7-pt filter) after round 16; profile C since the start of 2026. Each switch follows a fixed rule on the Edge Finder's walk-forward evidence (`pipelines/story.py`) | Its own quotes and paper fills (**Strategy**, **Positions**); the in-app markets it opens |
| `taker` (demo, **Try as taker**) | Our taker, $1,000 paper bankroll from 2025-01-01: profile A throughout, following about a third of its recommendations (`follow_rate` 0.33, hotter entries more often). Bankrolls and the follow rate are set in code (`profiles.DEMO_BANKROLL`, `DEMO_FOLLOW`), not in the UI. See [Paper trading](paper-trading.md#the-demo-accounts) | Its own paper trades (**Strategy**, **Positions**) and any bets placed in the app |
| `polymarket-takers` (system, no login) | The Polymarket traders whose real trades filled a replayed maker | Replay fills recorded from a diagnostic page (*Record the replay's fills*); its P&L is that maker's P&L reversed |

Both demo accounts' weekends before live paper trading began are **backtest replays**
(`racinglines f1 demo-history`, `pipelines/demo_history.py`): real Polymarket prices and trades, the
strategy the account ran then, flagged in the database (`detail.backfill`) and labelled in the app.

**Demo sessions are disposable** (`racinglines/web/demo.py`; the demo accounts are `RACINGLINES_DEMO_USERS`,
default `maker,taker`). Every sign-in gets a fresh session id. View settings (Edge Finder combos and season,
job settings, which signals were seen) live in a per-session overlay on top of the account's saved baseline
(`profiles.assign_demo` sets it), so a new sign-in starts clean and two visitors never see each other's
changes; the Lab's browser storage is namespaced by the session. Anything that would create or change data
(Lab jobs, promotion, candidates, the in-app book, bets, Polymarket sync or mirror, recorded replays) is
refused with a message. Every request of a demo session is logged to `activity_log` (`demo_view`,
`demo_post`, `demo_blocked`, with the session id, method, path and query): Admin > Activity.

**Demo-only text.** Explanations that exist only for the demo accounts (their decision rules and habits,
backtest-replay notes) render as info bubbles from the `demo_context` macro (`_macros.html`), tagged
invisibly with `data-tag="demo-context"`. `RACINGLINES_DEMO_CONTEXT=0` hides them all; before real users,
delete every `demo_context` call (`grep -rn demo_context racinglines/web/templates`). The Racinglines 101
page is the demo's own explainer and uses none. Everything else describes the product.

The demo taker is **not** the maker's counterparty. It trades its own strategy against
Polymarket's prices, so if it ever ends up on the opposite side of the demo maker, that's a
coincidence, and the app doesn't pair or net them.

### Admin pages

| Page | Purpose |
|---|---|
| `/admin` | Totals (markets, taker bets, stakes, takers' P&L, makers' worst case), users with activity counts, recent activity. |
| `/admin/activity` | Full activity log, filterable by user and action. Records logins (and failures), market generation, reprices, status changes, bets placed and rejected, settlements, Polymarket links and orders, user changes, database edits and SQL. |
| `/admin/users` | Create users (any role), change role, display name or password, deactivate. You can't demote or deactivate yourself. |
| `/admin/users/{id}` | One user's trading: markets made (exposure, EV, settled P&L), bets placed (P&L), activity; and the user's **strategy profile** (assign any Lab candidate, or clear it). |
| `/admin/db` | Database explorer: every table with row counts. Browse with a column filter and paging, edit or delete a row (confirmation needed; logged with before/after values). Password hashes are never shown. |
| `/admin/sql` | SQL console. **Read** mode runs in a `READ ONLY` transaction, so Postgres rejects any write, including data-modifying `WITH`. **Write** mode needs the toggle and a confirm box. 15 s timeout, 500 rows max. Every statement is logged in full. |

Accounts are in the `users` table, with scrypt password hashes from the standard
library. On startup the admin account is created or updated from
`ADMIN_USERNAME` / `ADMIN_PASSWORD`, or a password is generated and printed if
none is set. Other users are created on `/admin/users`.

### Authentication

- **Accounts:** users come from the `users` table. The session cookie carries the
  user id, and the user and role are re-read on every request, so a deactivation
  or role change takes effect immediately.
- **Browsers:** sent to `/login`. A correct username and password set an HttpOnly,
  SameSite=Lax cookie signed with `APP_SECRET` that lasts 12 hours. It's marked
  `Secure` when the request came over HTTPS (e.g. through the tunnel).
- **Scripts:** HTTP Basic (`curl -u admin:PASSWORD …`) is accepted on every route.
  Non-browser requests without credentials get 401.
- **Throttling:** after 8 failed logins from one client IP within 15 minutes, that
  IP gets 429 until the window passes. This covers both the form and Basic auth.
  Behind Cloudflare, the client IP comes from `CF-Connecting-IP`. The counter is in
  memory and resets on restart.
- **Forms:** every form POST also carries an anti-forgery (CSRF) token.

## Getting predictions for an event weekend

```
racinglines mtb_dh download --events 20260925_mtb --discipline DH --category "Elite Men"  --out-dir data/raw/mtb_dh/chronorace/
racinglines mtb_dh download --events 20260925_mtb --discipline DH --category "Junior Men" --out-dir data/raw/mtb_dh/chronorace/
racinglines mtb_dh ingest data/raw/mtb_dh/chronorace
racinglines mtb_dh forecast --db --save --backtest 0
```

An event that's in the data but has no Final results yet (Timed Training done, Q1
start list published) is treated as **in progress**:

- the field is its real Q1 start list;
- the model is fit only on data from before the weekend;
- each rider's weekend pace is adjusted from this weekend's Timed Training, using
  `weekend_prior` with training noise inflated 1.5×.

There's a safety check on that adjustment: if the Timed Training times are far
more spread out than normal, the session is ignored with a warning. That happened
at **Whistler 2026**, where riders were held on track and times jumped by minutes.

Re-run after each session (e.g. after Q1) to refresh the predictions. **The model
doesn't yet use completed rounds within the weekend.** For example, once Q1 is run
it doesn't lock in who has already qualified.

## Private book (markets we quote)

For events with no exchange market, the app can quote its own YES/NO markets for
**private bets**. Money is handled outside the app; it records quotes, bets,
exposure and settlement. If you offer quotes to the public, that's bookmaking and
needs a licence where you operate.

**Pricing:** prices are what the counterparty pays per $1 of payout.

- YES costs fair + spread/2, and NO costs (1 − fair) + spread/2.
- Prices are rounded up to the cent, so rounding only widens your margin.
- A side isn't offered above 0.97. With a 6-point spread that hides the NO side of
  long shots under about 6%; narrow the spread to offer it.
- A market can be repriced manually (fair value and spread). Manually priced
  markets aren't touched when the rest are repriced.

**Workflow (`/book/quotes`):**

1. Pick the race and **Create / reprice**: choose market types, top N riders and
   spread. Win, podium and make-the-Final riders are the top N by win probability;
   rank markets are the top N in the current standings.
2. Show the **Quote sheet** (phone-friendly) to counterparties.
3. On a market's page, **record each bet** (counterparty, side, stake; the price
   defaults to the current quote and is locked on the bet). The page and book show
   P&L if YES and if NO, EV at fair value, and the worst case.
4. Close a market to stop taking bets. Re-run the forecast (e.g. after Q1) and
   **reprice** open markets; bets already taken keep their price.
5. **Settle:**
   - **Auto-settle from results** covers win, podium and make the Final, once the
     Final start list or results are ingested.
   - **Rank up/down:** settle by hand from the **official UCI standings**. The
     model prices these with placeholder points tables.
   - You can void a market to return all stakes.

| Market | YES means | Priced from | Settled by |
|---|---|---|---|
| `race_win` | Wins the Final | `win_prob` | Final results (auto) |
| `race_podium` | Top 3 in the Final | `podium_prob` | Final results (auto) |
| `race_make_final` | On the Final start list | `make_final_prob` | Final start list (auto) |
| `rank_up` | Championship rank better than now after this race | `rank_up_prob` (simulated standings after this weekend) | Official standings (manual) |
| `rank_down` | Championship rank worse than now after this race | `rank_down_prob` | Official standings (manual) |

Tables: `house_markets` (one per race × athlete × kind) and `house_bets`.

## Polymarket

### Linking a market

1. **Markets → Link a Polymarket market.** Paste a market or event URL/slug, or
   search active events.
2. **For each outcome token**, choose:
   - the athlete (by ID; find it on the Athletes page);
   - the prediction: `race_win`, `race_podium`, `race_top10`, `race_make_final`,
     `champion` or `standings_top3`;
   - for race predictions, the race (a scheduled or in-progress event; blank means
     "the next unknown round");
   - whether the token pays when the prediction **fails** (e.g. the "No" side). The
     fair price is then 1 − p.
3. **The market page** shows the model's fair price (from the latest forecast run),
   the live order book, and suggested maker quotes: 2 ticks inside fair value and
   never crossing the book.

### Placing orders

Every order goes through **Preview → Confirm → Submit**. It's a **post-only GTC
limit order** (maker side only). Before signing, the app checks all of these:

- the price is within (0, 1) and on the market's tick size;
- the size is at least the market minimum;
- the notional (price × size) is ≤ `POLYMARKET_MAX_ORDER_USD`;
- a BUY is below the best ask, and a SELL is above the best bid. Polymarket also
  rejects any post-only order that would cross.

The preview shows the edge against the model and warns when the price is on the
wrong side of fair value. Every attempt is written to the `orders` table with the
model probability, model run, book at the time, and the exchange's response.

| Variable | Default | Meaning |
|---|---|---|
| `POLYMARKET_PRIVATE_KEY` | – | Signer key. Without it the app only does lookups and order books. |
| `POLYMARKET_FUNDER` | – | Address holding funds (Polymarket proxy wallet), if different from the signer. |
| `POLYMARKET_SIGNATURE_TYPE` | `0` | 0 = EOA, 1 = email/Magic proxy, 2 = browser-wallet proxy. |
| `POLYMARKET_API_KEY` / `_SECRET` / `_PASSPHRASE` | – | API credentials. Derived from the key if unset. |
| `POLYMARKET_TRADING_ENABLED` | off | **Must be `true` to send orders.** Otherwise orders are signed locally as a dry run and nothing is sent. |
| `POLYMARKET_MAX_ORDER_USD` | `25` | Per-order notional cap. |
| `POLYMARKET_CLOB_HOST` / `POLYMARKET_GAMMA_HOST` / `POLYMARKET_CHAIN_ID` | Polymarket production / 137 | Endpoints. |

The banner on every page shows the mode: **no credentials**, **dry run**, or **LIVE**
(in red).

!!! danger "Order signing is out of date"
    `racinglines/markets/polymarket/trade.py` signs with Polymarket's V1 client.
    Polymarket moved to CLOB V2 on 2026-04-28 and rejects V1-signed orders, so
    live orders won't be accepted until it's migrated to `py-clob-client-v2`
    (see [Roadmap](todo.md#market-making)). Dry runs still sign locally, in the old
    format.

!!! warning
    Check that your Polymarket account and jurisdiction are eligible before setting
    `POLYMARKET_TRADING_ENABLED=true`. Start with the dry run, then small sizes.
    Point-in-time model probabilities for downhill have limited calibration (see
    [Evaluation](evaluation.md)), especially for winners.

### Market availability

As of 2026-09-26, searching Polymarket for "Whistler", "downhill", "Crankworx" and
"UCI downhill" finds **no downhill markets**. The linking flow works with any
Polymarket market, so markets can be linked as soon as they're listed.

## Tested

Using FastAPI's test client against the Docker database:

- **Login:** requests without a login or with a wrong password get 401.
- **Forms:** a bad anti-forgery token gets 403.
- **Pages:** every page renders.
- **Market flow:** a live market lookup, link and book work.
- **Blocked orders:** preview blocks crossing BUYs and SELLs, over-cap orders and
  off-tick prices. Submitting without confirmation gets 400.
- **Dry run:** a dry-run order is signed with a throwaway key and recorded.
- **Private book:**
  - generate 75 markets;
  - quote sheet;
  - YES and NO bets with correct exposure and EV (e.g. $10 YES at 0.10 plus $50
    NO at 0.97 → −$40 if YES, +$8.45 if NO);
  - auto-settle waits for the Final;
  - manual settlement.
- **Sign-in:**
  - a browser without a session is redirected to `/login`;
  - wrong password → error;
  - right password → cookie → 200;
  - Basic auth → 200;
  - forged cookie → 401;
  - the 9th failure from one IP → 429;
  - all of it checked through the Cloudflare tunnel too.

No real order has been sent.
