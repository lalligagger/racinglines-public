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

| Page | What it shows |
|---|---|
| **Markets** (`/`, makers and admin) | **Headline numbers:** exchange outcomes we price and their volume, order books recording, my open markets and worst case, F1 model vs grid-only baseline, running jobs.<br>**Per sport** (F1 first):<br>• next three races as cards: countdown, venue badges (live / pending / soon / mine), our top-3 win probabilities with the exchange price as a tick;<br>• the season card;<br>• later races;<br>• recent results: winner, our pre-race price, Polymarket at the same time. |
| **Race** (`/race/{race_id}`) | The core page:<br>• **Header:** where our fair values come from (run and as-of time), the favourite, the result, venue badges, my book here.<br>• **Chart:** Polymarket price history for the top outcomes, with our fair as dotted lines and markers for qualifying, the race and our as-of time.<br>• **One table per market kind** (win, podium, top 10, make the Final, head-to-head, top constructor): fair bar with market tick, a column per venue, gap, my YES/NO quote (or settled P&L), bets, and the result.<br>• **Quote this race** (upcoming): generate private markets from our fair ± spread, or mirror the Polymarket event.<br>• **Classification** (past): with our win and podium prices, plus links to diagnostics. |
| **Season** (`/season/{competition}`) | The same layout for season-long markets: champion, constructors' champion, season wins, championship head-to-heads. |
| **My book** (`/book`) | Positions across venues. Totals: open markets, bets against me, stakes, EV at fair and worst case (open markets only), settled P&L. One row per event, linking to the race page and to `/house` for per-market management. Admin can filter by maker. |
| **Lab** (`/lab`, makers and admin) | **Run:** backtests, forward-forecast scenarios and event diagnostics with knobs, for F1 and downhill (see below).<br>**Also:** jobs with live progress and logs; scenarios compared with the live forecast, with **Promote to live**; every backtest side by side against the grid baseline; event diagnostics with replay P&L; all runs. |
| **Event diagnostic** (`/diag/{run}`) | One past event as of a cutoff: our prices vs Polymarket, scoring, the paper taking strategy, and the **maker replay with every strategy knob**. Knobs: fill rule, half-spread, shares per quote, max shares per market, max worst-case loss, inventory skew, disagreement filter, minimum 24 h volume, pull time. Replays take a few seconds. See [Market making](market-making.md). |
| **Polymarket** (`/pm`, linked from Markets) | Every listed F1 event, including outcomes we don't price, with **Mirror into my book** and refresh. |
| **Events / Athletes** (`/events`, `/athletes`, linked from Markets and race pages) | Calendar and search; results and prediction history. |
| **Private book** (`/house`, `/house/{id}`, `/house/sheet`) | Per-market management behind My Book: reprice, close, record offline bets, settle, quote sheet. See [House book](#private-book-markets-we-quote). |
| **Run detail** (`/runs/{id}`) | One stored run: parameters, metrics, predictions. `/runs` and `/diag` redirect to the Lab; `/me` redirects makers to My book. |
| **Sign in** (`/login`, `/logout`) | Two one-click demo buttons (**Try as maker**, **Try as taker**; the `maker` / `taker` accounts, password `password`) above the standard username/password form, which the admin uses. |
| `/pitch` | Serves `pitch.html`, behind the same login. |

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

### Roles

| Role | Can do |
|---|---|
| **taker** | Nav: **Markets** (`/bet`) and **My bets** (`/me`). The market board shows open markets from every maker, with YES/NO prices but **no model fair values**; race, season, book and lab pages are closed to takers. Bets are placed at the quoted price, refused if the maker has repriced since the page loaded, with a per-bet cap `MAX_STAKE` (default $100). |
| **maker** | Nav: **Markets**, **My Book**, **Lab**, **Pitch**. **Own** markets only: generate from the live forecast (fair ± spread), reprice, close, see the bets against them. Can launch Lab jobs and promote scenarios. Can't bet, can't touch other makers' markets, and can't settle. |
| **admin** | Everything (maker nav plus **Admin**, which links to activity, users, database, SQL, Polymarket orders and the order log), plus the private book across all makers, settlement (auto and manual), offline bets, Polymarket, and the admin pages below. |

Every route declares the roles allowed (`allow(...)` in `app.py`); anything else gets 403.

**Admin pages**

| Page | Purpose |
|---|---|
| `/admin` | Totals (markets, taker bets, stakes, takers' P&L, makers' worst case), users with activity counts, recent activity. |
| `/admin/activity` | Full activity log, filterable by user and action. Records logins (and failures), market generation, reprices, status changes, bets placed and rejected, settlements, Polymarket links and orders, user changes, database edits and SQL. |
| `/admin/users` | Create users (any role), change role, display name or password, deactivate. You can't demote or deactivate yourself. |
| `/admin/users/{id}` | One user's trading: markets made (exposure, EV, settled P&L), bets placed (P&L), activity. |
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

**Workflow (`/house`):**

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
