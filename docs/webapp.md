# Web app & trading

`racinglines/web/` is the maker/taker web app (FastAPI, server-rendered pages, no
JavaScript framework) on top of the [database](database.md). Partial updates (the Live
tab's refresh and replay, the Lab's sections and Edge Finder) are [htmx](https://htmx.org)
attributes on the templates (`static/htmx.min.js`, vendored); the little browser-side state
(open Lab sections, the replay player) is in `static/app.js`. The look is one stylesheet,
`static/style.css`, in sections (tokens, base, layout, components, pages); shared pieces
(the page head, flashes, KPIs, signed money) are macros in `templates/_macros.html`.
A page shows one thing at a time: big pages (Live, Positions, Strategy, a race, a diagnostic,
Quotes) split into tabs (`<nav class="ptabs" data-tabs=…>` with `[data-panel]` sections; the
choice is remembered per browser, `#key` in the URL opens a tab), secondary sections are
`<details class="card" data-remember=…>` with the number that matters in the summary, and a long
table gets a filter box and a row cap (`.scroll[data-rows][data-filter]`, or `table(…, cap=,
filter=)`). All of it is in `app.js`; the server renders every row regardless.

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
- **Use a real staging host as the default branch gate.** The recommended pre-deploy path is a single script:

  ```sh
  bash scripts/deploy/predeploy.sh --staging main
  bash scripts/deploy/predeploy.sh --prod main
  ```

  or the full flow in one command:

  ```sh
  bash scripts/deploy/predeploy.sh --all main
  ```

  The staging step checks `https://staging.racinglines.bet` only. If that hostname is down or the route is
  misconfigured, fix the Cloudflare tunnel first; do not silently switch to a temporary tunnel for the
  release path. Do not leave a Cloudflare tunnel running from the owner Mac in the normal flow.

  For an ad hoc local-only check while debugging a branch, the one-off helper is:

  ```sh
  bash scripts/deploy/staging.sh smoke 8010
  ```

  The helper script uses `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8010`, captures the
  temporary trycloudflare URL, runs `scripts/deploy/smoke.sh`, and exits cleanly. For a stable public
  route, use the VM tunnel and Cloudflare DNS (`staging.racinglines.bet`), not a long-running tunnel on the Mac.
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
       ├─ venue quotes: Polymarket · Kalshi (off with RACINGLINES_KALSHI_VENUE=0) · private book (our own markets)
       └─ result, once the race has run
```

- **Past races:** the exchange column shows the price **at the time of our as-of
  run**, not the resolved 0/1. So "we had 30%, Polymarket 64.5%" compares like
  with like.
- **Adding a venue:** add a `VENUES` entry and rows in `market_links` with
  `exchange = <code>`. Every page then shows its column.

## Pages

**Landing page** (`/login`, where every signed-out visit lands; owner, 2026-10-08). A compact, centered page with no
same-page navigation: what the pricing does for sportsbooks that set their own lines, books on a platform provider's
feed, and the providers themselves; the business infographic; a contact line (hello@racinglines.bet); and the
fantasy-trading beta with sign-up, the two demo buttons (no bigger than the sign-up link) and the sign-in form
(`/login#account`). The infographic has no "How it works" heading. The page names no sportsbook, operator or provider.
The sign-up popup is gone, and the maintenance popup is off (`MAINTENANCE_NOTICE = ""`).

**Beta sign-up** (`/signup`, `RACINGLINES_SIGNUP=1`, off by default; `racinglines/web/accounts.py`). A public page,
linked from the landing page's "Fantasy trade with us" section: username, email (required since 2026-10-08, one
account per address, stored as `users.prefs.email` like the settings page's), password (twice, 10+ characters, stored
only as a scrypt hash) and an 18+ / fantasy-money tick. Accounts made before 2026-10-08 have no email and keep working. Every beta account starts as
**pro** (owner, 2026-10-01; fantasy tiers come later, and an admin can change a role at `/admin/users`). One transaction
creates the account and credits it **1,000 fantasy bucks**, then signs the person in; the demo maker's starting strategy is assigned when the Lab candidates exist. Ten attempts per IP per hour
and a hidden honeypot field; passwords are never logged or echoed back.

The fantasy bucks live in their own Postgres schema, `accounts.fantasy_ledger` (one row per credit or debit, never
updated; a balance is a sum), apart from the market data in `public`. It is not an alembic migration, because deploys
never change the VM's database: `bash scripts/deploy/vm.sh accounts` backs the database up, runs `racinglines users
setup` (idempotent; every existing active account also gets its 1,000) and switches sign-up on. Until then `/signup`
says sign-up isn't open yet. Rollback: `vm.sh accounts off`.

No reset email is sent automatically. **Forgot your password?** (`/forgot`, linked from the sign-in form
when sign-up is on) writes a reset request to hello@racinglines.bet for the person to send (an
"Open in my email app" link and a Copy button); an admin resets the password and replies with the one-time password.

Admins manage accounts at `/admin/users`: add, change role, deactivate, **Reset password** (a random one-time password
shown once on that page, stored only as a hash, never logged) and **Remove** (only accounts with no markets or bets;
otherwise untick Active). The same from a shell: `racinglines users list | add NAME --role basic | reset-password NAME
| remove NAME | deactivate NAME | activate NAME`.

The nav follows the role:

| Role | Nav |
|---|---|
| **basic** | Markets · Strategy · Positions |
| **pro** | Markets · Strategy · Positions · My Book · Lab · Pitch · Docs |
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
| **Positions** (`/positions`) | The account's ledger. Three highlight cells: **Polymarket P&L** (paper history), **Private book P&L** (live, play money) and **Total P&L**; click one to show only that venue below (`?venue=polymarket|private`). Open and settled counts and realised P&L for the venues shown; a **P&L history** chart with a Polymarket / Private book switch (the two are never plotted together): the Polymarket bankroll curve with its worst drawdown and Sharpe ratio (mean / s.d. of weekend P&L × √24), or the private book's P&L at every poll of the live event (from its saved snapshots) with its worst drawdown; **Coming up** (the next races' calls for a taker, where it would quote for a maker, from `signals.call` / `maker_call`); totals by market type; every position (open, settled, closed), sorted by weekend or by P&L (`?sort=pnl` best first, `-pnl` worst first; the P&L column header toggles it), and with a weekend picked the executions behind it (trades taken or paper fills). A taker's in-app bets, if any, below. With `RACINGLINES_SPORT_PAPER` on (the default), the demo accounts' NASCAR and MotoGP rows are listed too, with race names and dates and a *demo replay, in-sample* pill ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)). Positions never shows a position made by the debug `buy_all` mode. |

**Makers and admin**

| Page | What it shows |
|---|---|
| **Markets** (`/markets`; `/` redirects here), makers and admin | **Headline numbers:** exchange outcomes we price and their volume, order books recording, my open markets and worst case, F1 model vs grid-only baseline, running jobs.<br>**Per sport** (F1 first):<br>• next three races as cards: countdown, venue badges (live / pending / soon / mine), a **new** badge for markets first listed in the last 48 hours, our top-3 win probabilities with the exchange price as a tick;<br>• the season card;<br>• later races;<br>• recent results: winner, our pre-race price, Polymarket at the same time;<br>• **Exchange data**: per exchange, the markets linked for the sport and the trades, price points and book snapshots stored for them, counted over the Parquet archive and the Postgres buffer (the archive is counted in a background thread, never in the request; a zero shows as n/a), with each exchange's historical coverage under the table ([Data](data.md#what-the-exchange-data-counts-show)).<br>With `RACINGLINES_SPORT_STATUS=1` the page opens with **Every sport: status** ([below](#accounts-demo-users-vs-polymarkets-takers)). |
| **Race** (`/races/{race_id}`) | The core page (takers are sent to Markets):<br>• **Header:** where our fair values come from (run, as-of time, and **update cadence**), the favourite, the result, venue badges, my book here. The cadence shows how often prices are refreshed: "updated every 5 min during sessions" for F1 live stage runs, "updated live during sessions" for F1 forecasts, "updated daily" for other sports like NASCAR.<br>• **Chart:** Polymarket price history for the top outcomes, with our fair as dotted lines and markers for qualifying, the race and our as-of time.<br>• **One table per market kind** (win, podium, top 10, make the Final, head-to-head, top constructor): fair bar with market tick, a column per venue, gap, my YES/NO quote (or settled P&L), bets, and the result.<br>• **Quote this race** (upcoming): generate private markets from our fair ± spread, or mirror the Polymarket event.<br>• **Classification** (past): with our win and podium prices, plus links to diagnostics. |
| **Season** (`/seasons/{code}`) | The same layout for season-long markets: champion, constructors' champion, season wins, championship head-to-heads. |
| **Polymarket** (`/markets/polymarket`, linked from Markets) | Every listed F1 event, including outcomes we don't price, with **new** badges (48 hours), **Mirror into my book** and refresh. |
| **My Book** (`/book`; **Books** for admin) | Positions across venues. Totals: open markets, bets against me, stakes, EV at fair and worst case (open markets only), settled P&L. One row per event, linking to the race page and to Quotes. Admin can filter by maker. |
| **Quotes** (`/book/quotes`, `/book/markets/{id}`, `/book/quotes/sheet`) | The private book per race, behind My Book: create and reprice, close, record offline bets, settle, quote sheet. See [Private book](#private-book-markets-we-quote). The quote sheet is open to every role. |
| **Lab** (`/lab`) | **Leads with the Edge Finder**, the headline feature for a maker account, per season (**2026**: every weekend raced so far; **2025**: as if live from its first race). A pinned **benchmark** (the conservative maker on the baseline at default settings) that nothing replaces; a card per chosen combo (a saved configuration × a strategy) with its P&L vs the baseline priced from the same data and vs the benchmark; a **full-season recap** (P&L, volume, return on volume, weekends up, average and s.d. per weekend, best and worst weekend, max drawdown, consistency, fills and markout for makers); and P&L per weekend with season totals. Nothing is simulated on a visit.<br>**Candidates:** ★ on a card saves that configuration × strategy as a named candidate (searches add theirs on import; strategy profiles are candidates too). **Load in Lab** opens the **Edge Finder sweep** form (Run) with every setting filled in; changed settings are highlighted, and the new run joins the Edge Finder.<br>**Edge Finder sweep form:** every setting of `racinglines/pipelines/sweep_settings.py`, grouped (model, entry timing, taker, maker, markets), with **Start from** (defaults, your last run, or a candidate), the season and the **maker venue** (Polymarket, or Kalshi's recorded tape with its maker fee; the takers read Polymarket either way).<br>**Sections, toggled on demand** (each loads from `/lab/section/{key}` the first time it's opened; `/lab#diagnostics` opens one): **Run**; **Jobs** (yours, or everyone's); **Model variants** (click a cell to add that combo); **Scenarios** with **Promote to live**; **Backtests** (+ Edge Finder per model); **Event diagnostics**; **All runs**.<br>**What's stored where:** Edge Finder combos, season and job settings in `users.prefs`; candidates as `model_runs` (`kind='candidate'`); open sections and the jobs filter in the browser; jobs, runs and bets in their own tables. |
| **Event diagnostic** (`/lab/diagnostics/{id}`) | One past event as of a cutoff: our prices vs Polymarket, scoring, the paper taking strategy, and the **maker replay with every strategy knob**. Knobs: fill rule, half-spread, shares per quote, max shares per market, max worst-case loss, inventory skew, disagreement filter, minimum 24 h volume, pull time. Replays take a few seconds. See [Market making](market-making.md). `/lab/diagnostics` opens the Lab's diagnostics section. |
| **Run detail** (`/lab/runs/{id}`) | One stored run: parameters, metrics, predictions. `/lab/runs` redirects to the Lab. |
| **Events / Athletes** (`/events/{id}`, `/athletes/{id}`; linked from Markets and race pages) | Results and prediction history for one event or athlete. No index/search page (removed). Every role can open them; takers don't see predictions. |

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
| **Sign in** (`/login`, `/logout`) | Two one-click demo buttons (**Try as pro**, **Try as basic**; the `maker` / `taker` accounts, which keep their usernames, password `password`) above the standard username/password form, which the admin uses. |
| **Pitch** (`/pitch`) | Serves `pitch.html`. Public: no sign-in, like the login and sign-up pages. |
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

The roles are **admin**, **pro** and **basic** (`racinglines/web/roles.py`). Until 2026-09-30 pro was called `maker`
and basic `taker`; accounts created before then still carry the old value in `users.role` and are read as the new
role everywhere (`roles.canonical`), so no migration was needed. To retire the aliases run, after a backup,
`UPDATE users SET role = 'pro' WHERE role = 'maker'` and `UPDATE users SET role = 'basic' WHERE role = 'taker'`.
The words *maker* and *taker* below (and everywhere else in these docs) mean the two kinds of strategy, which keep
their names.

**Tiers.** A pro account may run any strategy profile, maker or taker, including a blend, and has the Lab (Edge
Finder, sweeps, backtests, diagnostics, replays). A basic account runs only **Your picks** (below) and has no Lab,
book or fair values. `/admin/users/{id}` refuses to assign a basic account anything else, and refuses to make an
account basic while it runs something else. A basic account already running **A** (the rule before 2026-09-30)
keeps working, role edits included, until it is re-assigned (`roles.LEGACY_BASIC_PROFILES`).

**The taker shortlist and blends.** `profiles.TAKER_TOP` ranks ten taker profiles, **T1** to **T10**, from the taker
re-sweep (Lab candidates with source `taker-resweep`, created by `racinglines f1 profiles` like A and C). A *blend*
(`profiles.COMBOS`; today **TB**, half T1 and half T8) is a profile with `members` `[(code, weight)]` instead of one
strategy: the signal engine and the demo backfill run each member as itself with its stakes scaled by its weight
(`TakerParams.scale`; the $2 minimum rebalance is not scaled), store its rows under its own candidate and the blend's
name, and tag each signal `detail.member`. A blend isn't a candidate; assign it on `/admin/users/{id}` by its code.
Pages that read one strategy (the Markets page's calls, the "every recommendation" line) use the first member's.

**Basic picks.** A basic account's profile is the blend of `roles.BASIC_PICKS` (3) codes drawn from `TAKER_TOP` by
`roles.basic_members(user_id)`, at 1/3 each, named **Your picks**. The draw is seeded with `roles.BASIC_SEED` and the
account id: the same three every time, never re-rolled at login, nothing written until an admin assigns it (the
**Your picks** option on `/admin/users/{id}`, which shows the draw). Change `BASIC_SEED` to re-draw every account
(each then needs re-assigning). A basic account never sees which strategy made a pick: on Strategy, Positions and
Markets, and in the MCP tools (`track_record`, `list_positions`, `list_signals`, for a basic caller its own account
only), profile, strategy and member names and codes read **Your picks** / taker, and there's no fair value or edge.
Instead each entry has a 1 to 3 star rating, computed on the server from the edge over the minimum edge of the
strategy that made it (`roles.pick_stars`: 2x or more, 3 stars; 1.5x, 2; else 1), next to the heat. Pro and admin
pages are unchanged.

| Role | Can do |
|---|---|
| **basic** | Nav: **Markets**, **Strategy**, **Positions**. **Markets** lists every open Polymarket F1 market with the account's strategy profile's current call on each (side, shares, the most to pay, heat), never a fair value or edge. There is no maker on the other side: takers trade on Polymarket, on paper (see [Paper trading](paper-trading.md)). Race, season, book, Polymarket and Lab pages are closed to takers (a race link sends them to Markets); event and athlete pages show results without predictions. (The in-app private book still exists for makers; a taker's in-app bet is placed at the quoted price, refused if the maker has repriced since the page loaded, with a per-bet cap `MAX_STAKE`, default $100.) |
| **pro** | Nav: **Markets**, **Strategy**, **Positions**, **My Book**, **Lab**, **Pitch**, **Docs** (Strategy and Positions with a strategy profile). Any strategy profile, maker or taker. **Own** markets only: generate from the live forecast (fair ± spread), reprice, close, see the bets against them. Can launch Lab jobs and promote scenarios. Can't bet, can't touch other makers' markets, and can't settle. |
| **admin** | Everything: the pro nav (My Book is called **Books**) plus **Admin**, which links to activity, users, database, SQL, linked Polymarket markets and the order log. Plus the private book across all makers, settlement (auto and manual), offline bets, Polymarket, any user's Strategy page, strategy profiles (on `/admin/users/{id}`), and the admin pages below. |

Every route declares the roles allowed (`allow(...)` in `app.py`); anything else gets 403.

### Accounts: demo users vs Polymarket's takers

Three accounts are easy to mix up. They are separate entities:

| Account | What it is | Its trades |
|---|---|---|
| `maker` (demo, **Try as pro**) | Our maker, $10,000 paper bankroll from 2025-01-01. 2025: M1 (the defaults: conservative maker, baseline model), then M2 (grid-aware maker, 10-pt filter) after round 8, then M3 (gbm maker, 7-pt filter) after round 16; profile C since the start of 2026. Each switch follows a fixed rule on the Edge Finder's walk-forward evidence (`pipelines/story.py`) | Its own quotes and paper fills (**Strategy**, **Positions**); the in-app markets it opens |
| `taker` (demo, **Try as basic**) | Our taker, $1,000 paper bankroll from 2025-01-01: TW1 (the defaults) for 2025 rounds 1-8, then TW2 (grid-aware model with the reset, 10-pt edge) by the same walk-forward rule as the maker ([Paper trading](paper-trading.md#the-takers-history)), following about a third of its recommendations (`follow_rate` 0.33, hotter entries more often). Bankrolls and the follow rate are set in code (`profiles.DEMO_BANKROLL`, `DEMO_FOLLOW`, per account and kind of strategy: the basic demo takes 0.33 of its taker picks, the pro demo fills every pick of a taker strategy when it runs one), not in the UI. See [Paper trading](paper-trading.md#the-demo-accounts) | Its own paper trades (**Strategy**, **Positions**) and any bets placed in the app |
| `polymarket-takers` (system, no login) | The Polymarket traders whose real trades filled a replayed maker | Replay fills recorded from a diagnostic page (*Record the replay's fills*); its P&L is that maker's P&L reversed |

Both demo accounts' weekends before live paper trading began are **backtest replays**
(`racinglines f1 demo-history`, `pipelines/demo_history.py`): real Polymarket prices and trades, the
strategy the account ran then, flagged in the database (`detail.backfill`) and labelled in the app.
The maker can also have a Kalshi record (`f1 demo-history --venue kalshi`, [Kalshi history](kalshi-history.md)).
Positions shows it beside the Polymarket record and Strategy under its Polymarket / Kalshi switch
(`?venue=kalshi`); `RACINGLINES_KALSHI_VENUE=0` hides it.

**OG.com and recorded tapes** (both off by default). With `RACINGLINES_OG_VENUE=1`, OG.com shows beside Polymarket and
Kalshi on the board, race and season pages, and `/markets/og` lists its markets with the fair-price indicator per side
(edge YES = fair − ask − fee, edge NO = bid − fair − fee, and the call), refresh and mirror, read-only. Every schema
exchange in `exchanges/` gets its own `/markets/<code>` page this way ([Exchanges](exchanges.md)). With
`RACINGLINES_TAPES=1`, `/markets/tapes` lists the tape-only sports' markets (IndyCar, road cycling, Le Mans, SailGP: the schemas with `model_family = "none"`; NASCAR and MotoGP show on the board instead) per exchange
event: what is linked, the volume and favourite, and what has been recorded (trades, price points, book snapshots and
their last timestamps). It is market data only: no model, positions or P&L. With both switches off every page renders as before.

**Every sport's status** (off by default, `RACINGLINES_SPORT_STATUS=1`; `racinglines/web/sport_status.py`). Markets
opens with one row per sport schema, modeled or tape only, for both roles: race data (races with results, the latest
result, the next event), exchange markets (links per exchange, open, tied to a race, last sync), model (the schema's
model family, the latest live forecast run, the stored as-of replay prices, season forecasts), backtests (backtest runs
in the database, the replay settings grid under `data/runs/replay-grid/<sport>`) and, for Pro and admin, the demo
accounts' paper record per sport (settled P&L, never a buy_all row). Each cell is green (there), amber (partial), red
(missing) or grey (not applicable: a tape-only sport has no model by design), so a sport with no model or no data
says so rather than disappearing. With the switch on, every sport with exchange data opens on the board. A modeled sport
with no live forecast run but with replay saves (NASCAR, MotoGP: `<sport> replay --save`, as-of runs made before each
race) gets its board section too: the next races with the exchanges' prices (no fair price until a forecast is stored)
and the recent races with the model's pre-race price on the winner. `<sport> forecast --save` (in `vm.sh demo`) stores a live forecast for
the next scheduled races, and the section then reads like F1's: live prices from that run. It is the replay's model and
settings on every result so far, the field taken from the latest race; refresh it after each race. The Pro
account's Strategy page also splits its record by sport and strategy (*Where the P&L came from*: the F1 maker, the
NASCAR / MotoGP taker demo). `bash scripts/deploy/vm.sh demo` turns this and `RACINGLINES_SPORT_PAPER` on and stores
the NASCAR / MotoGP demo rows for both demo accounts ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)).

`RACINGLINES_SPORT_PAPER` (the NASCAR / MotoGP demo paper rows in the nav P&L, Positions and Strategy) is **on by
default** since 2026-09-30 (`pipelines/sport_paper.py` `enabled`): unset means on, `1`/`true`/`yes`/`on` means on, and
any other value (`0`, an empty string) turns it off, so every page reads as before. `RACINGLINES_SPORT_STATUS` stays
**off by default**. Every one of these rows is labelled *demo replay, in-sample*: the settings were picked on the same
seasons they are replayed on, so the P&L shows what the strategy would have done, not that it has an edge.

**NASCAR and MotoGP on the board, today.** NASCAR has a live forecast once `nascar forecast --save` has run (the
next scheduled Cup races, the field taken from the latest race). MotoGP has no upcoming races stored (its ingest
loads finished events only), so `motogp forecast` has nothing to price and its section shows recent results
(the RDR category) with the replay-save prices, and no next races, until its calendar is ingested.

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

### JSON API

Off by default: every route answers 404 unless `RACINGLINES_JSON_API=1` is set where the app
runs (`racinglines/web/api.py`). Read-only, behind the same login as the pages (cookie or HTTP
Basic), and only what the events and athletes pages show every signed-in user:

| Route | Returns |
|---|---|
| `GET /api/v1/events?season=&competition=` | events, newest first |
| `GET /api/v1/events/{id}` | one event and its classification, every round |
| `GET /api/v1/athletes?q=&limit=200` | athletes with result counts (limit at most 1,000) |
| `GET /api/v1/athletes/{id}` | one athlete, identifiers and results (practice left out) |

```
RACINGLINES_JSON_API=1 racinglines web
curl -u taker:PASSWORD 'http://localhost:8000/api/v1/events?competition=uci_dhi_wc&season=2026'
```

No model prices, quotes, positions or market data. Open questions for the owner before it goes
further:

- **What's public:** results only (today), or model prices too (the pages hide them from takers)?
- **Who can use it:** any account (today), a new API role or keys, or no login for results?
- **Data terms:** F1 timing data (FastF1 / F1's terms), OpenF1's non-commercial terms and UCI /
  ChronoRace results may not allow redistribution; check before anything leaves the private demo.
- **Limits:** a per-client rate limit, and paging for the larger lists.

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
| `POLYMARKET_ORDER_VERSION` | `2` | Exchange order version for dry runs. Live orders use the version the CLOB reports. |

The banner on every page shows the mode: **no credentials**, **dry run**, or **LIVE**
(in red).

!!! note "CLOB V2 signing: dry-run tested only"
    `racinglines/markets/polymarket/trade.py` signs with Polymarket's V2 client
    (`py-clob-client-v2`), since Polymarket rejects V1-signed orders from 2026-04-28.
    A dry run builds the V2 order and signs it locally (EIP-712 domain version 2) with
    no network call. `tests/test_polymarket_trade.py` recovers the signer from that
    signature. **No order has been sent with it.** Posting, open orders and cancels are
    untested against the live CLOB. Check them with the owner's approval and a small
    size before relying on them.

!!! warning
    Check that your Polymarket account and jurisdiction are eligible before setting
    `POLYMARKET_TRADING_ENABLED=true`. Start with the dry run, then small sizes.
    Point-in-time model probabilities for downhill have limited calibration (see
    [Evaluation](evaluation.md)), especially for winners.

### Market availability

As of 2026-09-26, searching Polymarket for "Whistler", "downhill", "Crankworx" and
"UCI downhill" finds **no downhill markets**. The linking flow works with any
Polymarket market, so markets can be linked as soon as they're listed.

## Kalshi

Kalshi's F1 markets are synced and their history stored (links, trades, hourly prices, in Postgres and
`data/archive/markets/kalshi/`), and the web app shows them at parity with Polymarket (on by default; with
`RACINGLINES_KALSHI_VENUE=0` the venue column says "Kalshi (soon)", the book page "Kalshi: coming soon", and no Kalshi
row appears anywhere): its quotes on the board, race and season pages, a `/markets/kalshi` list with mirror and refresh, the maker's Kalshi
record on Positions and Strategy, and the Kalshi replay in the Lab's event diagnostics (the page-by-page list is in
[Kalshi history](kalshi-history.md#in-the-app)). There's no linking flow to build: `markets --exchange kalshi sync`
links every F1 market it can classify ([F1](f1.md#kalshi-alignment)). Orders are dry runs unless
`KALSHI_TRADING_ENABLED=true` ([CLI](cli.md#kalshi-exchange-kalshi)). How Kalshi's feed differs from
Polymarket's: [Data](data.md#exchange-history-kalshi-and-polymarket).

**Cross-venue disagreement panel** (`RACINGLINES_DISAGREE=1`, off by default; the Markets page is byte-identical
without it): a collapsible card at the foot of the Markets page with the latest tick of the disagreement log
(`market_disagreements`, written by `racinglines markets disagree` and by the recorder's passes,
[CLI](cli.md#racinglines-markets)) for every outcome listed on both Polymarket and Kalshi: each venue's mid and top
of book, our fair, each venue's fee-adjusted taker edge, the gap (Kalshi mid − Polymarket mid) and the gap net of both
taker fees, widest first, with the last seven days' count of liquid rows above fees. Rows where a venue's stored tape
shows nothing traded in the prior 24 h are greyed: that gap is on paper. Nothing renders while the log is empty.
The log itself and what its columns mean: [Kalshi history](kalshi-history.md#cross-venue-disagreement-log).

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
