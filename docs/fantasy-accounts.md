# Fantasy accounts: sign-up, seasons, bankrolls and stats

Today only an admin can create a racinglines account. There is one admin, two demo logins and one system account.
A session is a stateless 12-hour cookie, and one CSRF token serves the whole process. The soft launch opens sign-up
on Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC), with invite codes and at most 50 players. For it, people need to make
their own accounts: a unique handle, an email address they have proven they own, and a role (maker or taker) that is
locked for the fantasy season. Each account then gets an F$ bankroll and a line on a leaderboard. This page is the
implementation spec for that. It covers what exists, the tables, the `fantasy_schema_v1` migration, the sign-up and
mail flows, session hardening, seasons and the role lock, the F$ ledger, stats and leaderboards, admin tooling,
privacy, and the tasks that build it all. How players trade is in [Fantasy trading](fantasy-trading.md). The
sprint plan is indexed in [Fantasy soft launch](fantasy-launch.md); the calendar, decisions, go/no-go and command
blocks are in the [runbook](fantasy-runbook.md). Proton Mail and DNS are in
[Email setup](email-setup.md), and the VM is in [VM reliability](vm-reliability.md).

**Status:** draft for the owner, Tue 2026-09-29. None of this is built yet. Every new table, route, module, flag and
switch below is marked **new**. Everything else is cited by file and line at `70eec70`. `main` (`1c417b2`) has not
changed `racinglines/web`, `racinglines/db` or `migrations` since then.

**Assumptions.** The sprint runs Tue 29 Sep to Sun 11 Oct 2026. "Next weekend" means F1 round 17, Singapore, 9-11
Oct. PR #71 (`work/deploy-pause`) merges first (OWNER-1). After that, `vm.sh deploy` pauses the VM's timers,
deploys, runs a catch-up step and resumes them. So there is no live-event freeze and no `--force`. A deploy
restarts web for a few seconds, so it is kindest between sessions. "Fantasy" means paper money only:
`POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are never touched. The owner runs every merge, every VM
write and every migration. Nothing here is legal advice.

---

## 1. What exists today

| # | Area | Today (file:line at `70eec70`) | What it means for the launch |
|---|---|---|---|
| 1 | Accounts table | `users` (`racinglines/db/models.py:424-434`) has `username` String(60) under a plain unique constraint, so `Max` and `max` are two accounts. It also has `display_name`, `role` String(10) with no CHECK, `password_hash`, `active`, `created_at` and `prefs` JSONB (which also holds the MCP token hash, `racinglines/mcp/auth.py`). There is no email, no account type and no last-login time | Add email, verification, account type and a session epoch, and make uniqueness case-insensitive |
| 2 | Passwords | scrypt with n=2^14, r=8, p=1 and a 16-byte salt (`racinglines/web/users.py:23-38`) | Keep as is |
| 3 | Creating accounts | Only through the admin's POST `/admin/users` (`racinglines/web/admin.py:83-95`), which calls `create_user` (`users.py:67-76`). `create_user` checks the role and an exact-match duplicate, strips spaces only on insert, and has no password policy. The 8-character minimum lives in the routes (`admin.py:87`, and `admin.py:121` for resets) | Add sign-up; move the policy into `create_user` |
| 4 | Session cookie | `rl_session` holds the user id, the expiry, a session id and an HMAC-SHA256 made with `APP_SECRET` (`racinglines/web/app.py:78-96`). It lasts 12 hours (`SESSION_HOURS`, `app.py:52`) and is HttpOnly, SameSite=Lax, and Secure behind https (`app.py:924-927`). It is stateless: GET `/logout` (`app.py:931-940`) only deletes the browser's copy, so a copied cookie keeps working until it expires. `authenticate` re-reads the user on every request (`app.py:113-118`), so setting `active = false` is the only way to end a session early | Add a way to sign someone out everywhere |
| 5 | `APP_SECRET` | Falls back to a new random value on each process start (`app.py:47`). Every restart then signs everyone out and changes the CSRF token. The VM's setup fills it in (`deploy/vm/setup.sh:62`) | Make it required once players can exist |
| 6 | CSRF | One token per process: HMAC(`APP_SECRET`, "csrf") (`app.py:48`), shared by every user and every session. It is a template global (`app.py:230`), read by the `csrf()` macro (`templates/_macros.html:9`) and by `static/app.js:14-18`, and checked by `check_csrf` (`app.py:150-152`). POST `/login` has no check (`app.py:906-907`), and logout is a GET | Use a token per session, plus a double-submit cookie for signed-out forms |
| 7 | Failed-login throttle | Kept in memory, per IP: 8 failures in 15 minutes gives a 429 (`app.py:55-75`). There is no per-username limit. An IP's entries are trimmed only when that IP comes back, and a restart clears everything. The IP comes from `cf-connecting-ip` (`app.py:61-65`), which anyone could forge if tcp:8000 were public (DEC-8) | Add pruning and a per-username counter (SEC-1). Sign-up and mail limits are counted in the database |
| 8 | HTTP Basic | Accepted for every account on every route (`app.py:107-134`). `scripts/deploy/smoke.sh:22-30` uses it to sign in as the demo accounts | Keep it for staff and demo accounts; refuse it for players |
| 9 | `next` | Goes into redirects without URL-encoding (`app.py:132`, `app.py:917`). The target must start with `/` and not `//` (`app.py:922`) | URL-encode it (SEC-1) |
| 10 | Demo accounts | Identified by username through `RACINGLINES_DEMO_USERS`, default `maker,taker` (`racinglines/web/demo.py:25`; `is_demo` at `demo.py:34`). Their password, `password`, is printed on the login page (`templates/login.html:9-13`). `demo.guard` refuses their writes and logs every request (`demo.py:62-83`). `/logout` is already an allowed POST for them (`demo.py:26`) | Give them account type `demo`; behaviour stays the same |
| 11 | System account | `polymarket-takers`: inactive, password `!no-login` (`users.py:53-64`) | Give it account type `system` |
| 12 | `ensure_admin` | Runs at every start (`app.py:159-162`, `users.py:79-94`). If the `ADMIN_USERNAME` account is missing, it creates it, and prints a generated password when `ADMIN_PASSWORD` is empty. If `ADMIN_PASSWORD` is set and differs from the stored hash, it resets the hash and forces `role = admin`, `active = true` | Whoever holds the `ADMIN_USERNAME` handle would become admin at the next restart. Reserve the name, and never touch a non-staff account |
| 13 | Audit | `U.log` (`users.py:97-105`) appends to `activity_log` (`models.py:437-448`) with the IP and path. `login_failed` keeps the typed username (`app.py:916`, `app.py:130`), which is sometimes a password typed into the wrong box | This is PII: prune it after 90 days |
| 14 | MCP | `SQL_HIDDEN = ("users", "orders")` (`racinglines/mcp/tools.py:24`). The `sql` tool can read `activity_log` (IPs, typed usernames) | Hide `activity_log` and the new token tables (ADM-1) |
| 15 | Private-book bets | `house_bets.counterparty` String(120) stores the username at bet time (`models.py:375`; `place_bet`, `app.py:867-894`), alongside `taker_id` (`models.py:382`). Stake, price and payout are Float (`models.py:377-379`) | Anonymising must rewrite `counterparty`, and the ledger rounds to cents |
| 16 | Stats code | `curve_stats` (`racinglines/reporting/metrics.py:6-19`) reports drawdown as a positive number, with the peak starting at 0. Sharpe is mean / sd (ddof 1) x sqrt(24), or 0.0 when sd is 0 | Reuse it as is |
| 17 | Alembic head | `c8e3f6a2d4b1` (`migrations/versions/20260929_c8e3f6a2d4b1_market_disagreements.py`) | It becomes the `down_revision` of the new revision |

---

## 2. Account types and roles

### Account types (new column `users.account_type`)

| `account_type` | Who | Created by | In fantasy stats and leaderboards | Backfill in `fantasy_schema_v1` |
|---|---|---|---|---|
| `player` | Everyone who signs up through `/signup` | ACC-3 | Yes, once verified, while their membership is `active` and the account is not deleted | None exist yet |
| `staff` | The owner, the admin, collaborators, the R16 testers | `/admin/users`, `ensure_admin` | No | Every other existing account (the column default) |
| `demo` | `maker`, `taker` | Already exist | No | `username IN ('maker', 'taker')` |
| `system` | `polymarket-takers` | `ensure_replay_taker` | No | `username = 'polymarket-takers'` |

The backfill uses the literal default demo usernames. If the VM's `RACINGLINES_DEMO_USERS` is set to anything
else, ACC-2's backfill counts will show it (expected: 2 demo and 1 system). `is_demo()` (`demo.py:34`) keeps
reading `RACINGLINES_DEMO_USERS` this sprint. A test asserts that every account it names has `account_type =
'demo'`.

### App role and season role

| | App role | Season role |
|---|---|---|
| Column | `users.role`: admin, maker or taker | `season_members.role`: maker or taker (new) |
| Controls | Permissions: `allow()` (`app.py:137-145`) and the staff test below | Which bankroll and which board the player gets in that season, and what they may do there |
| Set by | Sign-up (the chosen role), the admin | Verification, which copies `users.role` and sets `locked_at` |
| Changes | For a player, only with the season role (override, or joining a later season) | Only through an admin override with a reason while the season's `status` is not `closed` (§8) |

For a player, `users.role` always equals the `season_members.role` of the open season. The existing role form on
`/admin/users/{id}` (`admin.py:98-129`) will refuse to change a player who has a locked membership, and will point
to `/admin/fantasy/members/{user_id}` instead (ACC-4).

**Staff test (new, `racinglines/web/users.py`):** `is_staff(user)` is true when `user["role"] == "admin"` or
`user["account_type"] == "staff"`. `_user_dict` (`app.py:103-104`) gains `account_type`, `email_verified` (a bool)
and `epoch`.

### Handles

- Normalise first: strip spaces, then lowercase. Then apply the regex `^[a-z0-9][a-z0-9_-]{2,19}$` (3 to 20
  characters).
- Reserved, and refused at sign-up and by `create_user`: admin, root, staff, support, noreply, system, demo, maker,
  taker, polymarket-takers, racinglines, plus the value of `ADMIN_USERNAME` (lowercased).
- Also refused (new rule): any handle that starts with `deleted-`. That prefix is kept for anonymised accounts
  (§12).
- Uniqueness is on `lower(username)`, through `ix_users_username_lower`.
- The handle is the only public identity. Email is never shown to another user. Players can't change their handle
  this sprint.
- Existing staff and demo usernames don't have to match the regex, because only new accounts are checked.
  `ensure_admin` and `ensure_replay_taker` are the only code paths allowed to create a reserved name.

### What each role can do after ROLE-1

"Staff maker" means role `maker` with `account_type = 'staff'`. Demo accounts can look at everything their role
can see, and `demo.guard` refuses all their writes, as today.

| Action (route) | Admin | Staff maker | Player maker | Player taker |
|---|---|---|---|---|
| Race, event, athlete and market pages | yes | yes | yes | yes, prices only |
| Launch a Lab job (POST `/lab/run`, `racinglines/web/views.py:434`) | yes | yes | **no** (DEC-10) | no |
| Promote a forecast (POST `/lab/promote/{run_id}`, `views.py:450`) | yes | yes | **no**: promoting changes prices for everyone | no |
| Exchange syncs (POST `/markets/polymarket/sync` `app.py:1016`, `/markets/kalshi/sync` `app.py:1058`, `/markets/{code}/sync` `app.py:1096`) | yes | yes | **no** | no |
| Generate, mirror, reprice, open or close private-book markets (`app.py:672`, `1005`, `1047`, `1086`, `734`, `744`) | yes | yes | yes, within the BOOK-2 bounds and BOOK-3 collateral | no |
| Settle a private-book market (`app.py:757`) | yes | no | no | no |
| Bet on the private book (POST `/book/markets/{id}/take`, `app.py:867`) | no | no | no | yes |
| Exchange paper trades (POST `/fantasy/orders`, new) | no | no | no (DEC-6) | yes |
| See fair values and edge | yes | yes | **only the model fair on private-book markets they generate** (DEC-10). No exchange edges: no edge columns on `/markets` pages or race pages, no `/strategy`, `/positions` or `/orders` (the house's paper trades), no `/live` picks | **never** |
| `/fantasy`, `/leaderboard` (new) | yes | yes | yes, once verified | yes, once verified |
| `/admin/fantasy` (new) | yes | no | no | no |

Player makers are invited outsiders, so the model's fair values and edges are not theirs to relay to a taker. They
see the fair value only where they need it to quote, as in [Fantasy trading](fantasy-trading.md). ROLE-1 tests that
a player maker gets no edge from the `/markets` pages, `/strategy`, `/positions`, `/orders`, the `/live` picks or a race page. The MCP tools stay
admin-only (`RACINGLINES_MCP_ROLES=admin`, the default).

---

## 3. Schema

Everything below ships in one Alembic revision (§4). Money columns are Numeric(12,2) in F$. Timestamps are
`DateTime(timezone=True)`. Seasons are closed, never deleted, and users are anonymised, never deleted. So foreign
keys to `fantasy_seasons` use RESTRICT, and so do the membership and ledger keys to `users`. The derived tables
cascade. Constraint and index names not listed in the conventions are new and are proposals for ACC-1.

### `users` (new columns)

| Column | Type | Null / default | Notes |
|---|---|---|---|
| `email` | String(254) | NULL | Stored as typed, compared with `lower()` |
| `email_verified_at` | timestamptz | NULL | NULL means unverified |
| `terms_version` | String(20) | NULL | `TERMS_VERSION` at acceptance: `2026-10-08` |
| `terms_accepted_at` | timestamptz | NULL | |
| `age_confirmed_at` | timestamptz | NULL | The 18+ attestation. No date of birth is stored (DEC-22) |
| `account_type` | String(10) | NOT NULL DEFAULT `'staff'` | CHECK `ck_users_account_type`: IN (player, staff, demo, system) |
| `session_epoch` | Integer | NOT NULL DEFAULT 0 | Part of `rl_session`. Bumping it ends every session of that user |
| `last_login_at` | timestamptz | NULL | Set by `/login` |
| `deleted_at` | timestamptz | NULL | Set when the account is anonymised |

- **Indexes and checks:**
  - Unique `ix_users_username_lower` ON `(lower(username))`.
  - Unique `ix_users_email_lower` ON `(lower(email))`. NULLs never collide, so staff with no email are fine.
  - CHECK `ck_users_role`: `role IN ('admin', 'maker', 'taker')`.
  - The existing unique constraint on `username` stays.
- **Model:** new mapped columns on `User` (`models.py:424`). `__table_args__` gets the two functional unique
  indexes (`Index(..., func.lower(...), unique=True)`) and the two CHECKs.

### `email_tokens` (new)

| Column | Type | Constraints |
|---|---|---|
| `id` | Integer | PK |
| `user_id` | Integer | NOT NULL, FK `users.id` ON DELETE CASCADE, indexed |
| `purpose` | String(12) | NOT NULL, CHECK IN (verify, reset, email_change) |
| `token_hash` | String(64) | NOT NULL, UNIQUE: the sha256 hex of the raw token |
| `email` | String(254) | NOT NULL: the address the link was sent to (for `email_change`, the new address) |
| `created_at` | timestamptz | NOT NULL DEFAULT now() |
| `expires_at` | timestamptz | NOT NULL: `created_at` + 24 h (verify), 1 h (reset) or 24 h (email_change) |
| `used_at` | timestamptz | NULL. Set when the link is used, or when a newer token of the same purpose replaces it |

Index `ix_email_tokens_user_purpose` on `(user_id, purpose, created_at)`, for the resend limits.

### `invite_codes` (new)

| Column | Type | Constraints |
|---|---|---|
| `id` | Integer | PK |
| `code_hash` | String(64) | NOT NULL, UNIQUE: the sha256 hex of the normalised code |
| `label` | String(80) | NULL: the batch or person, e.g. `soft-launch-wave-1` |
| `season_id` | Integer | NOT NULL, FK `fantasy_seasons.id` ON DELETE RESTRICT. A code works only for its season |
| `created_by` | Integer | NULL, FK `users.id` ON DELETE SET NULL (NULL when made from the CLI) |
| `max_uses` | Integer | NOT NULL DEFAULT 1 |
| `uses` | Integer | NOT NULL DEFAULT 0, CHECK `uses >= 0 AND uses <= max_uses` |
| `expires_at` | timestamptz | NULL |
| `revoked_at` | timestamptz | NULL |
| `created_at` | timestamptz | NOT NULL DEFAULT now() |

A code is 12 characters drawn from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`. That alphabet has 31 characters and leaves out
0, O, 1, I and L, which gives about 2^59 possible codes. Codes print as `XXXX-XXXX-XXXX`. Before hashing, a code is
normalised: uppercased, with dashes and spaces removed. A code is shown once, when it is created, and is never
stored in plain text.

### `fantasy_seasons` (new)

| Column | Type | Constraints |
|---|---|---|
| `id` | Integer | PK |
| `slug` | String(20) | NOT NULL, UNIQUE: `2026-s1`, `2026-dryrun` |
| `name` | String(80) | NOT NULL |
| `status` | String(10) | NOT NULL DEFAULT `'draft'`, CHECK IN (draft, open, closed) |
| `starts_at` | timestamptz | NOT NULL |
| `ends_at` | timestamptz | NULL. NULL means TBD. CHECK `ends_at IS NULL OR ends_at > starts_at` |
| `signup_opens_at` | timestamptz | NOT NULL |
| `signup_closes_at` | timestamptz | NULL. NULL means sign-up stays open while the season is open |
| `bankroll_taker` | Numeric(12,2) | NOT NULL |
| `bankroll_maker` | Numeric(12,2) | NOT NULL |
| `max_stake` | Numeric(12,2) | NOT NULL: the cap per book bet and per exchange order |
| `max_market_liability` | Numeric(12,2) | NOT NULL: the default for `house_markets.max_liability` |
| `notes` | JSONB | NULL. `{"dryrun": true}` marks a dry-run season; owner notes can go here too |
| `created_at` | timestamptz | NOT NULL DEFAULT now() |

There is a unique partial index `ix_fantasy_seasons_one_open` ON `(status) WHERE status = 'open'`, so at most one
season can be open. The launch order depends on this: close `2026-dryrun` first, then open `2026-s1`.

### `season_members` (new)

| Column | Type | Constraints |
|---|---|---|
| `id` | Integer | PK |
| `season_id` | Integer | NOT NULL, FK `fantasy_seasons.id` RESTRICT |
| `user_id` | Integer | NOT NULL, FK `users.id` RESTRICT, indexed |
| `role` | String(5) | NOT NULL, CHECK IN (maker, taker) |
| `locked_at` | timestamptz | NOT NULL: the verification time. The lock holds until the season's status is `closed` |
| `joined_at` | timestamptz | NOT NULL DEFAULT now() |
| `starting_bankroll` | Numeric(12,2) | NOT NULL: copied from the season when the member joins |
| `status` | String(10) | NOT NULL DEFAULT `'active'`, CHECK IN (active, suspended, left) |

UNIQUE `uq_season_members_season_user` on `(season_id, user_id)`.

### `bankroll_entries` (new)

| Column | Type | Constraints |
|---|---|---|
| `id` | BigInteger | PK |
| `season_id` | Integer | NOT NULL, FK `fantasy_seasons.id` RESTRICT |
| `user_id` | Integer | NOT NULL, FK `users.id` RESTRICT |
| `ts` | timestamptz | NOT NULL DEFAULT now() |
| `kind` | String(10) | NOT NULL, CHECK IN (grant, stake, payout, refund, trade, fee, settle, book_pnl, adjust) |
| `amount` | Numeric(12,2) | NOT NULL, signed: + is a credit, - is a debit |
| `ref_table` | String(40) | NULL: the table of the row that caused the entry |
| `ref_id` | BigInteger | NULL |
| `note` | Text | NULL |
| `created_by` | Integer | NULL, FK `users.id` SET NULL (NULL for the tick and for sign-up) |

UNIQUE `uq_bankroll_entries_ref` on `(ref_table, ref_id, kind)`. Index `ix_bankroll_entries_member` on
`(season_id, user_id, ts)`. `balance = SUM(amount)`. §9 has the rules.

### `fantasy_event_results` (new, derived)

| Column | Type | Notes |
|---|---|---|
| `season_id` | Integer | FK `fantasy_seasons.id` ON DELETE CASCADE |
| `user_id` | Integer | FK `users.id` ON DELETE CASCADE |
| `event_key` | String(40) | `events.source_key` for race markets (as `private_book._event_key`, `racinglines/markets/private_book.py:360-361`). For season-level markets, `<competition code>-<year>-season`, e.g. `f1_wdc-2026-season` |
| `venue` | String(10) | CHECK IN (kalshi, polymarket, book) |
| `role` | String(5) | maker or taker |
| `pnl` | Numeric(12,2) | Settled P&L for this event and venue |
| `turnover` | Numeric(12,2) | |
| `bets` | Integer | |
| `won` | Integer | |
| `settled_at` | timestamptz | The latest settlement that fed this row |

PK `(season_id, user_id, event_key, venue)`. It is rebuilt from the ledger by `racinglines fantasy stats --full`.

### `fantasy_stats` (new, derived)

| Column | Type | Notes |
|---|---|---|
| `season_id`, `user_id` | Integer | FKs, ON DELETE CASCADE |
| `venue` | String(10) | CHECK IN (all, kalshi, polymarket, book) |
| `role` | String(5) | |
| `starting_bankroll` | Numeric(12,2) | |
| `balance`, `equity` | Numeric(12,2) | Only on the `all` row. NULL on the venue rows |
| `pnl` | Numeric(12,2) | |
| `roi` | Float | |
| `turnover` | Numeric(12,2) | |
| `bets`, `settled`, `won` | Integer | |
| `hit_rate` | Float | NULL when `settled = 0` |
| `max_drawdown` | Numeric(12,2) | A positive number |
| `sharpe` | Float | x sqrt(24). NULL under 4 events |
| `events` | Integer | |
| `rank` | Integer | NULL when the player is not eligible or is hidden |
| `computed_at` | timestamptz | |

PK `(season_id, user_id, venue)`. §10 defines the numbers.

### The trading tables (same revision)

`fantasy_orders`, `fantasy_fills`, `fantasy_positions`, and the new columns on `house_markets` (`season_id`,
`closes_at`, `max_liability`) and `house_bets` (`season_id`, `fair_prob_at_bet`, `settled_at`) are defined in
[Fantasy trading](fantasy-trading.md). ACC-1 builds them in the same revision.

---

## 4. Migration `fantasy_schema_v1` (ACC-1, ACC-2, OWNER-8)

### Rules

- **One additive revision.** The file is `migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py`, where `MMDD` is
  the day ACC-1 creates it and `<rev>` comes from `alembic revision`.
- **`down_revision`** is the single head at branch time: `c8e3f6a2d4b1` on 29 Sep. ACC-1 runs `alembic heads` when
  it branches and again before the owner merges. The output must be exactly one line. If `main` has moved, rebase
  and repoint `down_revision`. Never merge two heads.
- **Every new column is nullable or has a server default.** `update.sh` migrates before web restarts
  (`deploy/vm/update.sh:24-26`), so the old process briefly runs against the new schema. Additive changes keep that
  safe.
- **Guards first.** Before changing anything, `upgrade()` looks for usernames that differ only by case and for
  roles outside admin, maker and taker. If it finds any, it raises with the list. Postgres runs the revision in one
  transaction, so nothing changes. The owner then fixes those rows by hand, backup first, and runs it again.
- **Order inside `upgrade()`:**
  1. The guards.
  2. The `users` columns.
  3. The `account_type` backfill.
  4. The two CHECKs.
  5. The two `lower()` unique indexes.
  6. The new tables in foreign-key order: `fantasy_seasons`, `invite_codes`, `email_tokens`, `season_members`,
     `bankroll_entries`, `fantasy_event_results`, `fantasy_stats`, then `fantasy_orders`, `fantasy_fills`,
     `fantasy_positions`.
  7. The `house_markets` and `house_bets` columns.
- **No seed rows.** Seasons and invites come from the CLI (§8) at STAGE-1 and LAUNCH-1.
- **A real `downgrade()`.** It is the exact reverse: drop the `house_*` columns, drop the ten tables in reverse
  order, drop the two indexes and the two CHECKs, then drop the nine `users` columns. A downgrade loses every row in
  the new tables. That is why rolling back on the VM means restoring the pre-deploy dump, not running `alembic
  downgrade`.
- **Locks.** `ALTER TABLE users` takes a brief exclusive lock, and `users` has fewer than 10 rows. Adding nullable
  columns to `house_markets` and `house_bets` only changes the catalogue.
- **Same PR:** the models in `racinglines/db/models.py`, and `docs/database.md` (table rows plus a line in the
  migrations table).

```python
# migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py: outline for ACC-1, not final code
revision = "<rev>"
down_revision = "c8e3f6a2d4b1"          # re-check with `alembic heads` at branch time and before merge


def upgrade():
    conn = op.get_bind()
    dupes = conn.execute(sa.text(
        "SELECT lower(username), array_agg(username) FROM users GROUP BY 1 HAVING count(*) > 1")).all()
    roles = conn.execute(sa.text(
        "SELECT DISTINCT role FROM users WHERE role NOT IN ('admin', 'maker', 'taker')")).all()
    if dupes or roles:
        raise RuntimeError(f"fantasy_schema_v1: fix these rows first: case duplicates {dupes}, roles {roles}")
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("terms_version", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("account_type", sa.String(10), nullable=False, server_default="staff"))
    op.add_column("users", sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET account_type = 'demo' WHERE username IN ('maker', 'taker')")
    op.execute("UPDATE users SET account_type = 'system' WHERE username = 'polymarket-takers'")
    op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'maker', 'taker')")
    op.create_check_constraint("ck_users_account_type", "users",
                               "account_type IN ('player', 'staff', 'demo', 'system')")
    op.create_index("ix_users_username_lower", "users", [sa.text("lower(username)")], unique=True)
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table("fantasy_seasons", ...)                       # columns as in section 3
    op.create_index("ix_fantasy_seasons_one_open", "fantasy_seasons", ["status"], unique=True,
                    postgresql_where=sa.text("status = 'open'"))
    ...  # invite_codes, email_tokens, season_members, bankroll_entries, fantasy_event_results, fantasy_stats
    ...  # fantasy_orders, fantasy_fills, fantasy_positions, house_markets / house_bets columns (fantasy-trading.md)


def downgrade():
    ...  # the exact reverse of upgrade(); data in the new tables is lost
```

### Run order

The steps are: ACC-2's trial on a restored copy (Mon 5 Oct), then the data-change record, then the owner's merge
and VM deploy (OWNER-8, Tue 6 Oct 09:00 PDT (16:00 UTC)), then the check. Rollback is last. OPS-8 must already be
in `main`: it adds `--migrate` to `vm.sh deploy`, which dumps the database before migrating. OPS-4 provides
`scripts/ops/restore_scratch.sh`. Both are specified in [VM reliability](vm-reliability.md). Run the LOCAL
commands below from a checkout of `work/acc-1`; a worktree is fine.

```sh
# LOCAL (Mac) — ACC-2 step 1 (Mon 5 Oct): the newest VM dump -> racinglines_scratch, then alembic upgrade head.
# OPS-4's script. It writes the scratch database only and never touches `racinglines`. Keep this shell open for steps 2-3.
UTC=$(date -u +%Y%m%dT%H%M%SZ); LOG=data/backups/acc2-trial-$UTC.log
bash scripts/ops/restore_scratch.sh 2>&1 | tee "$LOG"
```

```sh
# LOCAL (Mac) — ACC-2 step 2: downgrade and upgrade again on the scratch copy, timed (the downgrade's only rehearsal)
export DATABASE_URL=postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines_scratch
{ time .venv/bin/alembic downgrade -1; time .venv/bin/alembic upgrade head; .venv/bin/alembic current; } 2>&1 | tee -a "$LOG"
unset DATABASE_URL
```

```sh
# LOCAL (Mac) — ACC-2 step 3 (read-only): backfill counts, case duplicates, new tables on the scratch copy.
# Expected: demo 2, system 1, staff = the rest; no duplicate rows; new_tables = 10.
PG_BIN=${PG_BIN:-$HOME/miniconda3-arm64/envs/racinglines-db/bin}
"$PG_BIN/psql" postgresql://racinglines:racinglines@localhost:5433/racinglines_scratch \
  -c "SELECT account_type, role, count(*) FROM users GROUP BY 1, 2 ORDER BY 1, 2" \
  -c "SELECT lower(username) AS handle, count(*) FROM users GROUP BY 1 HAVING count(*) > 1" \
  -c "SELECT count(*) AS new_tables FROM information_schema.tables WHERE table_name IN ('email_tokens', 'invite_codes', 'fantasy_seasons', 'season_members', 'bankroll_entries', 'fantasy_event_results', 'fantasy_stats', 'fantasy_orders', 'fantasy_fills', 'fantasy_positions')" \
  2>&1 | tee -a "$LOG"
```

**ACC-2 step 4, the record (in the ACC-1 PR).** Add a section to [Data changes](data-changes.md), headed
`2026-10-06 · VM: fantasy_schema_v1`. It gives the reason, the trial log path and the timings from step 2, and the
backfill counts from step 3. It names the backup as
`data/backups/db/racinglines-before-deploy-<sha>-<UTC>.sql.gz` on the VM; the owner fills in the exact name that
`vm.sh` prints, and DOC-2 commits it. The undo is to restore that dump. The `data_changes` row on the VM is written
by `vm.sh deploy --migrate` (OPS-8), and step 3 below checks for it.

```sh
# LOCAL (Mac) — OWNER-8 step 1, Tue 6 Oct 09:00 PDT (16:00 UTC): merge, then the pre-merge checks (.venv active)
git checkout main && git pull
git merge --no-ff work/acc-1   # ⚠️ needs special attention: DB migration (users columns and CHECKs, 10 new tables, house_* columns); the VM step next needs the owner's sign-off
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat HEAD^1 HEAD -- tests/golden   # must print nothing
git push
```

```sh
# VM (production), run from the Mac with vm.sh — OWNER-8 step 2
# ⚠️ needs special attention: migrates the production database. Needs the owner's explicit sign-off in the same turn.
# vm.sh --migrate (OPS-8) dumps first and prints the dump's name: copy it into the data-changes line.
UTC=$(date -u +%Y%m%dT%H%M%SZ); LOG=data/backups/owner8-deploy-$UTC.log
bash scripts/deploy/vm.sh status 2>&1 | tee "$LOG"                    # note the running sha: the rollback target
bash scripts/deploy/vm.sh deploy main --migrate 2>&1 | tee -a "$LOG"
bash scripts/deploy/smoke.sh https://racinglines.bet 2>&1 | tee -a "$LOG"
```

```sh
# LOCAL (Mac) — open a shell on the VM for step 3
bash scripts/deploy/vm.sh ssh
```

```sh
# VM (production) — OWNER-8 step 3 (read-only): the revision, the dump, the data_changes row, the backfill
# (the rl / rlsql helpers are the same as in fantasy-runbook.md)
rl()    { sudo -u racinglines -H bash -c 'cd /opt/racinglines && set -a && . /etc/racinglines.env && set +a && exec .venv/bin/racinglines "$@"' rl "$@"; }
rlsql() { sudo -u racinglines -H bash -c 'cd /opt/racinglines && docker compose exec -T db psql -U racinglines -d racinglines -v ON_ERROR_STOP=1 -P pager=off'; }
LOG=/opt/racinglines/data/backups/owner8-check-$(date -u +%Y%m%dT%H%M%SZ).log
sudo -u racinglines -H bash -c 'cd /opt/racinglines && set -a && . /etc/racinglines.env && set +a && .venv/bin/alembic current' 2>&1 | sudo tee "$LOG"
rl db changes --limit 3 2>&1 | sudo tee -a "$LOG"
sudo ls -lt /opt/racinglines/data/backups/db | head -3 | sudo tee -a "$LOG"
rlsql <<'SQL' 2>&1 | sudo tee -a "$LOG"
SELECT account_type, role, count(*) FROM users GROUP BY 1, 2 ORDER BY 1, 2;
SQL
```

**Rollback, only if the deploy or the smoke check failed.** There is one runbook for this, and this page doesn't
keep a second copy: [VM reliability, Bad migration](vm-reliability.md#bad-migration). Its order is: deploy the sha
before the migration first (after OPS-8 that deploy skips `alembic` with a warning), then stop the writers, dump
what is there, load the pre-deploy dump, start everything again, smoke through Cloudflare, and record both dumps in
`data_changes`. For OWNER-8 the dump to load is the `racinglines-before-deploy-<sha>-<UTC>.sql.gz` that `vm.sh
--migrate` printed in step 2, and the sha to deploy is the one before the ACC-1 merge. Every step that writes the
VM database needs the owner's explicit sign-off in the same turn (⚠️ needs special attention: it replaces the
production database). Rows written between the dump and the restore are lost from the database, so act quickly.
Book snapshots from that window are also in the recorder's Parquet archive. If any account was anonymised in that
window, re-apply the deletions after the restore (§12, "Backups and restores").

The Mac's own dev database is upgraded only after the merge. Before that, a checkout of `main` would find a
revision it doesn't know.

```sh
# LOCAL (Mac) — after OWNER-8 only: back up the Mac's dev database, then upgrade it (CLAUDE.md: back up first)
UTC=$(date -u +%Y%m%dT%H%M%SZ); PG_BIN=${PG_BIN:-$HOME/miniconda3-arm64/envs/racinglines-db/bin}
"$PG_BIN/pg_dump" --no-owner --no-privileges postgresql://racinglines:racinglines@localhost:5433/racinglines | gzip -6 > data/backups/db/racinglines-before-fantasy-schema-v1-$UTC.sql.gz
.venv/bin/alembic upgrade head
.venv/bin/racinglines db changes --add "fantasy_schema_v1 on the Mac dev database; backup data/backups/db/racinglines-before-fantasy-schema-v1-$UTC.sql.gz"
```

To roll the Mac back, restore that file the same way the VM rollback does, into the local `racinglines` database.

---

## 5. Sign-up (ACC-3)

### States

| `RACINGLINES_SIGNUP` | GET `/signup` | POST `/signup` | Login page |
|---|---|---|---|
| `off` (default) | 404 | 404 | No sign-up link |
| `invite` (the soft launch) | Form, and an invite code is required | The code must be valid for the open season | "Have an invite? Sign up" |
| `open` (not before Thu 22 Oct) | Form, and a code is optional (used if given) | | "Sign up" |

The form also needs an open fantasy season, with `signup_opens_at <= now` and `signup_closes_at` either NULL or
still in the future. Otherwise the page shows "Sign-up is closed" (200) and no form.

`RACINGLINES_SIGNUP_CAP` (new, default 50) counts accounts where `account_type = 'player'` and `deleted_at IS
NULL`. Unverified sign-ups count too, until they expire at 72 hours (§6). At the cap the page shows "Sign-up is
full for now", and POST writes `signup_rejected` with reason `cap`.

### The form (`templates/signup.html`, new)

| Field | Rule | Stored as | Message on error |
|---|---|---|---|
| Invite code | Required under `invite`. Normalised, then matched by sha256. The code must not be revoked or expired, must have `uses < max_uses`, and must belong to the open season | `invite_codes.uses + 1`, through a conditional `UPDATE ... SET uses = uses + 1 WHERE id = :id AND uses < max_uses AND revoked_at IS NULL` in the same transaction as the insert. If no row changes, the sign-up is refused | "That invite code isn't valid." (the same text for every reason) |
| Handle | The rules in §2 | `users.username` and `display_name` | "Handles are 3-20 characters: a-z, 0-9, _ and -, starting with a letter or digit." or "That handle is taken." (also shown for reserved names) |
| Email | Trimmed, at most 254 characters, one `@`, and a dot in the domain. Refused if the domain is `racinglines.bet` (the catch-all would deliver it to support@). Unique by `lower(email)` in the index, and also by a normalised form checked in the same transaction: the `+tag` is dropped, and for `gmail.com` and `googlemail.com` the dots are dropped and the domain becomes `gmail.com` | `users.email` (as typed) | "That doesn't look like an email address." (also for `racinglines.bet`) or "That email already has an account: sign in or reset your password." (this reveals that the address is registered; see Open items) |
| Password | 10-128 characters, and must not contain the handle | `users.password_hash` (scrypt) | "Passwords are 10 to 128 characters and can't contain your handle." |
| Role | Radio buttons, maker or taker, required, neither preselected | `users.role`. The lock is set at verification (§6) | "Pick maker or taker." |
| 18+ | Required checkbox: "I am 18 or older" | `users.age_confirmed_at` | "You must be 18 or older to play." |
| Terms | Required checkbox: "I agree to the Terms, the Privacy notice and the Rules", with a link to each | `users.terms_version = TERMS_VERSION` (`2026-10-08`) and `users.terms_accepted_at` | "Please accept the terms." |
| Turnstile | When both keys are set (DEC-16) | nothing | "Please complete the check." |
| `csrf` | Must match the `rl_csrf` cookie (§7) | nothing | 403 |

After an error the form comes back with a 400 and the fields kept, except the password. The message sits next to
its field.

The copy above the form reads "Paper money only. F$ have no cash value, there are no prizes, and nothing here is
investment advice." This line is on the go/no-go list. The copy next to the role radio reads:

> **Taker**: trade F1 markets at live Kalshi and Polymarket prices, and bet on makers' private-book quotes.
> Starting bankroll F$1,000.
>
> **Maker**: quote your own prices on private-book markets for takers to bet on. Starting bankroll F$10,000.
>
> Your role is locked until the season closes.

The amounts are read from `bankroll_taker` and `bankroll_maker` on the open season, never hard-coded.

!!! note "Owner input: DEC-1, DEC-4, DEC-5, DEC-22"
    The copy assumes no prizes (DEC-1), bankrolls of F$1,000 for takers and F$10,000 for makers (DEC-5), an 18+
    attestation with no date of birth (DEC-22), and a season end still TBD (DEC-4). If any decision lands
    differently, change the season row and the template text. The flow stays the same.

### What a successful POST `/signup` does

The whole thing is one database transaction:

1. Load the open season, then check the sign-up window and the cap.
2. Redeem the invite code with the conditional `UPDATE`.
3. Insert the `users` row: `username = display_name = handle`, `email`, `role`, `account_type = 'player'`,
   `password_hash`, `terms_version`, `terms_accepted_at = now()`, `age_confirmed_at = now()`, `active = true`,
   `email_verified_at = NULL`.
4. Insert an `email_tokens` row: purpose `verify`, expiring in 24 h.
5. Commit.
6. Queue `mail/verify.txt` through the mailer (a background send, MAIL-1) and write the `signup` log row.
7. Set `rl_session` for the new account and redirect 303 to `/account`, which says "We sent a link to" followed
   by the address.

If two sign-ups race, the unique indexes decide: the loser gets the "taken" message.

### Rate limit and Turnstile

- **Counting IPs:** every per-IP limit on this page (sign-up, resend, forgot) counts an IPv6 address by its /64,
  so one host can't step around it by rotating addresses inside its own prefix. IPv4 addresses count as they are.
- **Sign-up limit:** 5 attempts per hour per IP. The count is taken from `activity_log` rows (`signup`, plus
  `signup_rejected` except those with reason `rate`) from that IP in the last hour. Over the limit, the page returns
  429 and a `signup_rejected` row with reason `rate`. Because the count lives in the database, a deploy doesn't
  reset it.
- **Turnstile (DEC-16):** active when `RACINGLINES_TURNSTILE_SITEKEY` and `RACINGLINES_TURNSTILE_SECRET` are both
  set.
  - `signup.html` and `forgot.html` then load `https://challenges.cloudflare.com/turnstile/v0/api.js` and show the
    widget.
  - Before doing anything else, the server posts `secret`, `response` and `remoteip` to
    `https://challenges.cloudflare.com/turnstile/v0/siteverify`, with a 5 s timeout.
  - A failure or a timeout refuses the sign-up (fail closed) and writes `signup_rejected` with reason `turnstile`.
  - It covers every signed-out form that can send mail: `/signup`, `/password/forgot` and the signed-out
    `/verify/resend` form. `/login` sends no mail and relies on the throttle (§7 row 7).
  - Empty keys turn the widget off, which is what local dev and the tests use.
  - The owner creates the widget in Cloudflare and puts both keys only in `/etc/racinglines.env`.
  - Turnstile stays an owner decision (DEC-16), but these forms send mail to any address typed in, so without it
    the only guard is the per-IP and per-address limits, which an attacker rotating IPs can spread out. So the app
    logs a warning at every start while `RACINGLINES_SIGNUP` is not `off` or `RACINGLINES_MAIL_BACKEND=smtp` and the
    keys are empty, and this doc's go/no-go line asks for either the keys set and a working widget, or DEC-16
    recorded as "no". The recommendation is yes, with the Cloudflare rate-limiting rule on `/signup` and
    `/password` from DEC-16.

### `PUBLIC_PATHS`

The tuple at `app.py:53` becomes `("/login", "/static", "/racinglines101", "/signup", "/verify", "/password",
"/terms", "/privacy", "/rules", "/healthz")`. It is a prefix match. So `/verify` covers `/verify/{token}` and
`/verify/resend`, and `/password` covers `/password/forgot` and `/password/reset/{token}`. On public paths,
`authenticate()` still reads the cookie, without ever raising, so these pages can show who is signed in. `/healthz`
belongs to OPS-1.

### `activity_log` rows (ACC-3)

No row ever holds a password, a token, a link or a full email address.

**The request path carries the token.** `U.log` (`users.py:97-105`) stores `request.url.path`, and `demo.guard`
logs every path too, so a GET or POST on `/verify/{token}` or `/password/reset/{token}` would put the raw token into
`activity_log.path`. uvicorn's access log (`racinglines web` runs `uvicorn.run` in `racinglines/cli/web.py:13`,
access log on) would put it in the journal as well. ACC-3 closes both:

- `U.log` stores the matched route template (`request.scope["route"].path`, for example `/verify/{token}`) when
  there is one, and otherwise the path with the last segment replaced by `{token}` under `/verify/` and
  `/password/reset/`. `demo.guard` uses the same helper.
- A `logging.Filter` on the `uvicorn.access` logger applies the same redaction before a line reaches the journal.
- The token pages send `Referrer-Policy: no-referrer` (§7 row 15), so the token can't leave in a Referer header.
- Test: `test_no_raw_token_in_activity_log_or_access_log` walks verify, resend and reset and asserts that no
  `activity_log` row and no captured `uvicorn.access` line contains the raw token.

Cloudflare's own request logs are outside the app. A token that reaches them is still single-use and
short-lived (24 h, 1 h for resets), and a used or superseded token opens nothing.

| `action` | When | `user_id` / `username` | `detail` |
|---|---|---|---|
| `signup` | Account created | The new user | season, role, `invite_code_id` (shown on the admin member page, so each account traces to the code that let it in), email domain, turnstile (bool) |
| `signup_rejected` | Any refusal | None; the typed handle goes in `username` | reason: code, handle, handle_taken, email, email_taken, password, role, consent, turnstile, cap, closed or rate |
| `email_verify` | A verify or email_change link confirmed, or the admin marks the email verified | The user | purpose, `by` (link or admin), season, grant amount |
| `verify_resend` | Resend requested | The user if signed in | sent (bool) |
| `password_reset_request` | Forgot form submitted | None | matched (bool), email domain |
| `password_reset` | New password set from a link | The user | new epoch |
| `password_change` | Changed on `/account` | The user | new epoch |
| `email_change` | New address confirmed | The user | old and new email domains |
| `account_delete` | Account anonymised | The user | `by` (self, admin or system), reason (admin; `unverified` for the 72-hour expiry) |
| `login`, `login_failed`, `logout` | Already written today (`app.py:916-920`, `app.py:934`) | | Adds `via` and, for players trying HTTP Basic, reason `player` |

---

## 6. Email verification, reset and email change

### Tokens

- **Generation:** `raw = secrets.token_urlsafe(32)`, i.e. 32 random bytes, which make 43 characters in the link.
  The database stores only `sha256(raw).hexdigest()` in `email_tokens.token_hash`, so the raw token exists only in
  the mail.
- **Use:** a single statement that also checks the account is still the one the link was sent for:

  ```sql
  UPDATE email_tokens t SET used_at = now()
    FROM users u
   WHERE t.token_hash = :h AND t.used_at IS NULL AND t.expires_at > now()
     AND u.id = t.user_id AND u.active AND u.deleted_at IS NULL
     AND (t.purpose = 'email_change' OR lower(u.email) = lower(t.email))
  RETURNING t.user_id, t.purpose, t.email
  ```

  A `verify` or `reset` link only works while the account's address is still the one it was sent to (an
  `email_change` token carries the new address, so it is exempt). If it returns no row, the link is invalid, expired,
  already used or no longer valid for the account, and the page shows one message, "This link has expired or was
  already used", with a resend form.
- **Newest wins:** issuing a token marks older unused tokens of the same user and purpose as used, so only the
  newest link works.
- **Account changes end every link:** a password change on `/account`, a password reset, a confirmed email change,
  a suspension and an anonymisation each mark all of that user's unused `email_tokens` as used, in the same
  transaction. A reset link sent before the password or the address changed stops working at once, not an hour
  later. (Anonymising deletes the rows, §12.)
- **GET shows, POST acts:**
  - GET `/verify/{token}` shows a "Confirm" button. GET `/password/reset/{token}` shows the new-password form.
  - The token is used only by the POST, which also carries the `rl_csrf` check.
  - Mail scanners and link previews fetch links on their own. A GET that used the token would verify or burn it
    before the person ever clicked.

| Purpose | Lifetime | Page | Mail |
|---|---|---|---|
| `verify` | 24 h | `/verify/{token}` | `mail/verify.txt` |
| `reset` | 1 h | `/password/reset/{token}` | `mail/reset.txt` |
| `email_change` | 24 h | `/verify/{token}` | `mail/email_changed.txt`: to the new address with the link, and to the old address as a notice with no link |

### Limits

All limits are counted in the database, so restarts don't reset them. A request over a limit gets the same
"we've sent a link" answer, and nothing is sent.

| Flow | Limit |
|---|---|
| Resend verification (POST `/verify/resend`) | 3 per hour per user (from `email_tokens`), 10 per hour per IP (from `verify_resend` rows) |
| Forgot password (POST `/password/forgot`) | 3 per hour per email address (from `email_tokens`), 10 per hour per IP (from `password_reset_request` rows) |
| Email change (POST `/account`) | 3 per hour per user |
| Any one address | 6 mails per UTC day, whatever the flow (from `email_tokens.email`) |

**The daily mail cap is shared, so part of it is kept for verification.** `RACINGLINES_MAIL_DAILY_CAP` (200) counts
every mail. Forgot, signed-out resend and email-change mail together may use at most half of it (100 a day); past
that they answer as usual and send nothing, so a flood of reset requests can't use up the mail that new invitees
need to verify. At 80% of either count (160 in all, or 80 for forgot, resend and email change) the mailer sends one
alert a day to `RACINGLINES_OPS_NTFY_TOPIC`. MAIL-1 keeps the counts; [Email setup](email-setup.md) describes the
cap itself.

### Flows

- **Verify** (POST `/verify/{token}`, purpose `verify`) runs in one transaction:
  1. Set `email_verified_at`.
  2. Call `seasons.join(open season, user, users.role)` (new). It writes the `season_members` row, with
     `locked_at = now()` and `starting_bankroll` from the season, and posts the `grant` entry (§9).
  3. Commit.
  4. Queue `mail/welcome.txt` and log `email_verify`.

  If no season is open at that moment, verification still succeeds. There is no membership and no grant, and
  `/fantasy` says the next season hasn't opened yet.
- **Resend** (POST `/verify/resend`): a signed-in unverified user gets a button. A signed-out visitor types an
  address. Either way the answer is "If that address has an unverified account, we've sent a new link".
- **Forgot** (POST `/password/forgot`): the answer is always "If an account uses that address, we've sent a link.
  It works for 1 hour." It doesn't reveal whether the address exists. Turnstile applies when it is on.
- **Reset** (POST `/password/reset/{token}`):
  - The password policy applies, and the new hash is saved.
  - `session_epoch + 1` ends every other session, the token is marked used, and this browser gets a fresh
    `rl_session`.
  - Log `password_reset`.
  - A reset does not verify an unverified email: verification is the only path that creates the membership and the
    grant.
- **Email change** (POST `/account`, action `email`) requires the current password. The new address follows the
  sign-up rules in §5 (no `racinglines.bet`, unique by the normalised form).
  - An unverified account (fixing a typo) just replaces `users.email` and gets a fresh verify token. No notice is
    sent.
  - A verified account gets an `email_change` token that carries the new address. `mail/email_changed.txt` goes to
    the new address with the link. The same template, without the link, goes to the old address: "If this wasn't
    you, reset your password and write to support@racinglines.bet".
  - When the link is confirmed: `users.email = new` and `email_verified_at = now()`. It is refused if the new address
    was taken in the meantime. Log `email_change`.

### Unverified players

Right after sign-up an unverified player is signed in. They can reach `/account`, `/verify/resend`,
`/verify/{token}`, POST `/logout` and the public pages. Any other path redirects 303 to `/account` with "Verify
your email to start". They have no membership, no bankroll and no stats, and they appear on no board. The check
lives in `authenticate()`, so no route can forget it.

**Unverified accounts expire after 72 hours.** The daily `--full` pass of `racinglines fantasy tick` anonymises
every `account_type = 'player'` account with `email_verified_at IS NULL` created more than 72 hours earlier, the same
way as §12 (no membership or ledger exists yet, so nothing else changes), and logs `account_delete` with `by=system`
and reason `unverified`. That frees the handle, the address and the cap slot, so unverified sign-ups can't squat an
address or fill the cap for long. `/admin/fantasy` lists unverified accounts with their age.

### Mail

- **Code:** MAIL-1 builds the sender (`racinglines/web/mailer.py`). ACC-3 writes the wording in the plain-text
  templates under `racinglines/web/templates/mail/`.
- **Sender:** every mail comes from `RACINGLINES_MAIL_FROM`, with Reply-To `RACINGLINES_MAIL_REPLY_TO`
  (support@racinglines.bet). It says "Paper money only (F$)" and never uses a bare "$".
- **The four templates:**
  - `verify.txt`: subject "Confirm your email for racinglines". The link, "works for 24 hours", and "If you didn't
    sign up, ignore this mail."
  - `reset.txt`: subject "Reset your racinglines password". The link, "works for 1 hour", and "If you didn't ask,
    ignore this mail; your password hasn't changed."
  - `welcome.txt`: the season name, the role, the starting bankroll in F$, "your role is locked until the season
    closes", and links to `/fantasy` and `/rules`.
  - `email_changed.txt`: the two variants described under Flows.
- **Links:** every link is built from `RACINGLINES_URL` (`https://racinglines.bet` on the VM,
  `deploy/vm/racinglines.env.example:5`), never from the request's Host header. A forged Host header would
  otherwise put someone else's domain into a reset link. Local dev sets `RACINGLINES_URL=http://127.0.0.1:8000`.
- **Backends:** under `RACINGLINES_MAIL_BACKEND=log` (the default), the message goes to the journal and only
  metadata goes to `activity_log`. Under either backend that metadata names the recipient by `user_id` and email
  domain only, never the full address, to match the rule in §5. The rows use the actions `mail_sent` and `mail_failed`
  from the master names list; [Email setup](email-setup.md) logs the same fields. While mail is down, the admin can read the link in the journal or mark the email
  verified on `/admin/fantasy/members/{user_id}` (the admin-verify fallback). SMTP goes through the Proton token for
  noreply@racinglines.bet (DEC-3). Its setup is OWNER-3 and MAIL-2 in [Email setup](email-setup.md).

---

## 7. Sessions and security (SEC-1, ACC-3)

| # | Change | Task | Where and how |
|---|---|---|---|
| 1 | Cookie format | SEC-1 sets it up; ACC-3 starts checking the epoch | `rl_session` becomes five fields: user id, expiry, session id, epoch, HMAC. It is signed with a key derived from `APP_SECRET` (HMAC(`APP_SECRET`, "rl_session")) and kept apart from the CSRF key. SEC-1 ships the five-field format with epoch always 0 and doesn't check it. ACC-3 then compares the epoch with `users.session_epoch`, which is 0 for everyone after the migration. So only SEC-1's deploy signs everyone out, and only once. The old three- and four-field cookies (`app.py:85-96`) are rejected from SEC-1 on |
| 2 | `session_epoch` | ACC-3, ADM-1 | Bumped on a password change, a password reset, a suspension, the admin's "Revoke sessions", "Sign out everywhere" on `/account`, and anonymising. A cookie whose epoch doesn't match is treated as signed out |
| 3 | Per-session CSRF | SEC-1 | token = HMAC(csrf key, session id), checked by `check_csrf` on every signed-in POST. It has to reach the `csrf()` macro (`_macros.html:9`) and `app.js` (`app.js:14-18`), which read it from the page. SEC-1 picks how, for example by importing `_macros.html` `with context` and reading it from `request.state`, and tests it. A POST with no cookie session (HTTP Basic) is refused, since Basic is for GETs (scripts, `smoke.sh`). The `CSRF_TOKEN` constant goes away, and `tests/test_views.py:158`, `:165`, `:301`, `:306` and `:308` read the token from a page instead |
| 4 | `rl_csrf` double-submit | SEC-1 | For signed-out forms: `/login` (including the two demo buttons), `/signup`, `/password/forgot`, `/password/reset/{token}`, `/verify/{token}` and `/verify/resend`. The GET sets `rl_csrf` (a nonce plus an HMAC; HttpOnly, SameSite=Lax, Secure behind https, 2 h) and puts the nonce in a hidden `csrf` field. The POST needs a valid signature and a field equal to the nonce, or it gets a 403 |
| 5 | POST `/logout` | SEC-1 | GET `/logout` shows a one-button form, so old links still work. The POST signs this browser out and resets the demo overlay, as today (`app.py:935-937`). It doesn't bump the epoch |
| 6 | `next` | SEC-1 | URL-encoded with `urllib.parse.quote` in both redirects (`app.py:132`, `app.py:917`). The same-site check at `app.py:922` stays |
| 7 | Throttle | SEC-1 | Per IP: 8 failures in 15 minutes, as today. Per username (new): 10 failures in 15 minutes on one `lower(username)` refuses that name for 15 minutes from any IP. Pruning: every check drops keys with no failure inside the window, and the dict is capped at 10,000 keys. Demo accounts are exempt from the per-username lock: their password is public, and otherwise anyone could lock the one-click demo for everyone. Staff accounts (the admin included) are locked per (username, IP) instead, so a stranger can lock the admin handle only from their own IP and can't shut the owner out of the abuse tools during an incident. Guessing a staff password from many IPs is still bounded by the per-IP limit, and `/admin` has a second gate (row 16). It stays in memory, so a restart resets it (see Open items) |
| 8 | Rules inside `create_user` | SEC-1 | Normalise the handle, then apply the regex and the reserved names. Password policy (new `U.check_password(password, username)`): 10-128 characters, and must not contain the handle. `admin.py:87` and `admin.py:121` call the same check. `create_user` gains an `account_type` argument, default `staff`, used from ACC-3 on. The demo accounts' existing password is untouched, because the policy applies when a password is set, not at login |
| 9 | HTTP Basic refused for players | ACC-3 | The Basic branch of `authenticate()` (`app.py:120-130`) returns 401 for `account_type = 'player'`, even with the right password. It looks exactly like a wrong password and logs `login_failed` with `via=basic, reason=player`. Staff and demo accounts keep Basic, so `smoke.sh` is unchanged |
| 10 | `APP_SECRET` required | ACC-3 | The app refuses to start if `RACINGLINES_SIGNUP` is not `off`, or `RACINGLINES_FANTASY=1`, while `APP_SECRET` is unset or shorter than 32 characters. Local dev with both off keeps the random fallback |
| 11 | `ensure_admin` only for staff | ACC-3 | If the `ADMIN_USERNAME` account exists with an `account_type` other than `staff`, `ensure_admin` prints a warning and changes nothing |
| 12 | Login | SEC-1 (timing), ACC-3 (email) | The form's `username` field (label: "Handle or email") looks up `lower(username)`, or `lower(email)` when the input contains `@`. Deleted or inactive accounts fail exactly like a wrong password, in the same time: today `U.authenticate` (`users.py:45-47`) skips scrypt when the user is missing or inactive, so an unknown handle or address answers in microseconds and a real one takes a full scrypt, which would reveal which addresses are registered. SEC-1 makes it always run one `verify_password` against a fixed dummy scrypt hash when the user is missing, inactive, deleted, or has an unparseable hash (`!deleted`), and tests the timing ratio. `last_login_at` is set on success |
| 13 | "Sign out everywhere" | ACC-3 | A button on `/account` that bumps `session_epoch` and issues this browser a fresh cookie |
| 14 | No token in logs | ACC-3 | `U.log`, `demo.guard` and the `uvicorn.access` logger record the route template (`/verify/{token}`), never the raw token (§5, "`activity_log` rows") |
| 15 | Security headers | SEC-1 | One middleware on every response: `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` (no clickjacking of the bet, order, settle or SQL buttons), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` (`no-referrer` on the token pages). The script and style parts of the CSP start as `Content-Security-Policy-Report-Only`, allowing `'self'` and `https://challenges.cloudflare.com` for script and frame: several templates use inline `style=` attributes today (`_macros.html`, `board.html`, `live.html`, `race.html`), so an enforced policy would break pages until they are cleaned up. HSTS is turned on by the owner in Cloudflare (SSL/TLS, Edge Certificates) once the tunnel serves only https, which DEC-8 (a) keeps true |
| 16 | The admin surface | SEC-1 (app), owner (Cloudflare) | `/admin*` (including `/admin/sql` with its write toggle and the `/admin/db` explorer) sits on the same public origin as sign-up, behind one password. Two changes before `RACINGLINES_SIGNUP` leaves `off`: (a) the owner puts a Cloudflare Access application (free tier, one-time PIN to the owner's own address) in front of `racinglines.bet/admin*`, which gives the admin a second factor; (b) the app refuses the `/admin/sql` write toggle and `/admin/db` row edits while `RACINGLINES_SIGNUP` is not `off`, pointing to `/admin/fantasy` or a Mac-side fix with a backup. `mcp.racinglines.bet` keeps its bearer token, as [VM reliability](vm-reliability.md) decides |

**Deploy note.** SEC-1 signs everyone out once, and demo overlays reset as they do on any restart. Deploy it in a
between-session window; [VM reliability](vm-reliability.md#deploy-windows) lists them.

**What stays:** the 12-hour lifetime, HttpOnly, SameSite=Lax, Secure behind https, scrypt, and re-reading the user
and role on every request.

---

## 8. Seasons and the role lock (ACC-4)

### Lifecycle

| `status` | Players see | Sign-up | Trading | Stats | How a season gets here |
|---|---|---|---|---|---|
| `draft` | Nothing | No | No | No | `season create` |
| `open` | `/fantasy`, `/leaderboard` | When `RACINGLINES_SIGNUP` is not `off` and the sign-up window is open | Yes, per [Fantasy trading](fantasy-trading.md) | Every tick | `season create --status open` or `season set --status open`. Refused while another season is open |
| `closed` | The final leaderboard under "Past seasons" | No | No new bets, orders or quotes. The tick settles what is left | A final `--full` pass, then frozen | `season close` |

Seasons only move forward: draft, then open, then closed. A closed season never reopens.

**Closing.** `season close <slug>` refuses while bets, maker markets or exchange positions of that season are
unsettled, and lists them. With `--void-open --reason "..."` it voids them first: refunds go through the ledger,
with `fantasy_settle` rows that carry the reason. A dry-run season (`notes.dryrun`) voids whatever is still open
without being asked, with the reason "dry-run season closed". That is why launch step 2 in the
[runbook](fantasy-runbook.md#launch-day) needs no flag. Closing unlocks the roles, since the lock holds only until
`status = closed`, and runs one last `stats --full`.

**`ends_at` NULL means TBD.** A season can be created with no end date. The sign-up page and `/rules` then say:
"Season 1 runs from Thu 8 Oct until a date the owner will announce, expected after the 2026 championship markets
settle (about 7-8 Dec)." The owner sets the date later with `season set 2026-s1 --ends-at ...` or on
`/admin/fantasy/seasons/{id}`. `ends_at` is for display only: a season is closed only by an explicit `close`. The
tick sends one ops alert a day while `now > ends_at` and the season is still open.

!!! note "Owner input: DEC-4, the dates of 2026-s1"
    Recommended: `signup_opens_at` Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC), trading from R17, and `ends_at`
    left NULL until the 2026 championship markets resolve (expected 7-8 Dec, after Abu Dhabi on 6 Dec; earlier if
    Qatar or Abu Dhabi is cancelled). Due Wed 7 Oct 12:00 PDT, for the sign-up page copy.

### The lock

- **When it starts:** `season_members.locked_at` is set at verification. After that, `season_members.role` can't
  change while the season's `status` is not `closed`.
- **Where it is enforced:** in `seasons.change_role` (new), and in the existing role form (`admin.py:98-129`), which
  refuses locked players.
- **Override:** on `/admin/fantasy/members/{user_id}`, the admin picks the new role and writes a reason of at least
  10 characters. It is allowed only while the member has no ledger entries other than the grant. It:
  - writes `role_override` to `activity_log` with the old role, the new role and the reason;
  - updates `season_members.role`, `users.role` and `starting_bankroll`;
  - posts an `adjust` entry for the bankroll difference, whose ref is that `activity_log` row;
  - bumps `session_epoch`.

  The form says it is meant for mistakes within 48 h of sign-up (DEC-10). A member who has already traded waits for
  the next season.
- **Late joiners** get the full starting bankroll whatever the date, so comparisons across join dates should use
  ROI. The owner can set `signup_closes_at` to stop late joins.
- **The next season:** when a later season opens, an existing verified player joins it with a new role choice
  (`seasons.join`), and `users.role` follows the new season role. The join page isn't built this sprint, since
  there is one season. Verification is the only way to join for now.

### `2026-dryrun`

- **What it is for:** the staging rehearsal (STAGE-1, Wed 7 Oct 17:00-21:00 PDT (Thu 8 Oct 00:00-04:00 UTC)).
- **Created by:** `season create 2026-dryrun ... --status open`. A slug ending in `-dryrun`, or the `--dryrun` flag,
  sets `notes = {"dryrun": true}`.
- **Testers:** they sign up as players with 5 tester codes. The owner anonymises them at the end of the rehearsal,
  which frees their handles and emails for real sign-ups.
- **Stats:** computed, so the rehearsal can check the leaderboard, but never shown to players. The leaderboard's
  season list hides dry-run seasons from everyone except staff.
- **End:** closed at launch step 2, before `2026-s1` opens.

### CLI (new: `racinglines/cli/fantasy.py`, and `"fantasy"` added to `GROUPS` at `racinglines/cli/__init__.py:20`)

| Command | What it does | Writes |
|---|---|---|
| `season create <slug> --name --starts-at --signup-opens-at [--ends-at] [--signup-closes-at] --bankroll-taker --bankroll-maker --max-stake --max-market-liability [--status open] [--dryrun]` | A new season, `draft` unless `--status open` | `fantasy_seasons`; `season_update` |
| `season set <slug> [--name] [--ends-at] [--signup-opens-at] [--signup-closes-at] [--status open]` | Edits a season. The bankroll and limit fields are refused once the season has a member | `season_update`, with each change as old and new |
| `season close <slug> [--void-open --reason TEXT]` | Closes a season (see Closing) | `fantasy_seasons.status`; `season_update` |
| `season list` | Slug, status, dates (PDT and UTC), members by role, verified and unverified | nothing |
| `invite create --season <slug> --count N --label TEXT [--max-uses 1] [--expires-at]` | Prints the codes once. Don't tee them into a log | `invite_codes`; `invite_create` |
| `invite revoke <id>` or `invite revoke --season <slug> --all` | Sets `revoked_at` | `invite_revoke` |
| `invite list --season <slug>` | id, label, uses and max, expiry, revoked. Never the codes | nothing |

- **Times:** ISO 8601 with `Z` or an offset. The CLI prints PDT with UTC in brackets.
- **Audit:** the CLI writes `activity_log` rows with no user and `detail.by = "cli:<unix user>@<host>"`.
- **On the VM:** these commands run as the `racinglines` user with `/etc/racinglines.env` loaded (the `rl` helper in
  §4). Each write there follows a `racinglines ops backup`. The launch-day and STAGE-1 blocks in the
  [runbook](fantasy-runbook.md) do that.

**Module (new: `racinglines/fantasy/seasons.py`).** Functions:

- `open_season(conn)`, `get(conn, slug)`
- `create(...)`, `update(...)`, `close(...)`
- `join(session, season, user, role)`, `change_role(session, member, role, reason, admin)`
- `create_invites(session, season, n, label, max_uses=1, expires_at=None, created_by=None)`, which returns the
  plain codes once
- `redeem(session, code, season)`, `revoke(session, invite_id=None, season=None, all_=False, by=None)`

---

## 9. Bankrolls and the F$ ledger (ACC-4)

### Rules

- **One bankroll per member per season,** across all venues (DEC-5). Amounts come from the season row: F$1,000 for
  takers and F$10,000 for makers. The cap per book bet and per exchange order is F$100 (`max_stake`, equal to
  `MAX_STAKE`, `app.py:619`). The cap per maker market is F$1,000 (`max_market_liability`, the default for
  `house_markets.max_liability`).
- **The grant** is posted at verification: kind `grant`, `+starting_bankroll`, with ref `season_members` and the
  member's id.
- **`balance = SUM(amount)`** over the member's entries in that season. There is no stored balance column: with 50
  players or fewer the sum is cheap, and it can never drift.
- **Append-only.** Code never updates or deletes an entry. A correction is a new `adjust` entry.
- **Idempotent.** `UNIQUE(ref_table, ref_id, kind)` plus `INSERT ... ON CONFLICT DO NOTHING` mean that posting the
  same thing twice changes nothing: a retried request, or a tick run twice.
- **Cents.** `house_bets` stakes and payouts are Float, so `ledger.post` rounds to the cent with
  `Decimal(str(round(x, 2)))`.
- **No top-ups** other than an admin adjust with a reason (DEC-5).

### Entry kinds

The trading entries are written by the tasks in [Fantasy trading](fantasy-trading.md), which owns the amounts.
This table is the summary the ledger module is built to.

| `kind` | Who | Sign | `ref_table` / `ref_id` | Written by |
|---|---|---|---|---|
| `grant` | Every member | + starting bankroll | `season_members` / member id | ACC-4, at verification |
| `stake` | Taker | - stake | `house_bets` / bet id | BOOK-3, when the bet is placed |
| `payout` | Taker | + payout if won, 0.00 if lost | `house_bets` / bet id | SETTLE-1 |
| `refund` | Taker | + stake (voided bet), or + cost basis (voided exchange position) | `house_bets` or `fantasy_positions` / id | SETTLE-1, ADM-1 |
| `trade` | Taker | - shares x price on a buy, + on a sell | `fantasy_fills` / fill id | EXCH-1 |
| `fee` | Taker | - fee, once per order (Kalshi) | `fantasy_orders` / order id | EXCH-1 |
| `settle` | Taker | + payout of an exchange position, 0.00 on a loss | `fantasy_positions` / id | SETTLE-1 |
| `book_pnl` | Maker | ± the maker's P&L on one market, 0.00 if void | `house_markets` / market id | SETTLE-1 |
| `adjust` | Any member | ± | A re-settle uses the original ref (one per ref). An admin F$ adjust or a role override uses the `activity_log` row that holds the reason | ADM-1, ACC-4 |

Every settled bet, position and maker market gets exactly one closing entry, even when it is F$0.00. That makes
"settled" a join rather than a guess, and the stats (§10) rely on it.

### Free balance

- **Taker:** free balance = balance. `stake` and `trade` entries are written when the bet or fill happens, so the
  balance is already net of open stakes and open exchange cost. A bet or buy is refused if its cost plus fee is more
  than the free balance.
- **Maker:** free balance = balance - Σ worst case over the maker's unsettled season markets. A market's worst case
  is `-min(pnl_if_yes, pnl_if_no, 0)`: the negative of the `worst` column that `private_book.book()` computes
  (`private_book.py:218-222`). A taker's bet is refused if it would push the maker's free balance below 0 or the
  market's worst case above `max_liability` (BOOK-3).
- `/fantasy` shows balance, free balance and equity.

**Concurrency.** `ledger.lock_member(session, season_id, user_id)` (new) runs `SELECT ... FOR UPDATE` on the
`season_members` row. BOOK-3 and EXCH-1 lock the payer, and the maker too, in ascending `user_id` order, before they
check free balance and post. The concurrency test belongs to BOOK-3.

**Module (new: `racinglines/fantasy/ledger.py`).** Functions:

- `post(session, season_id, user_id, kind, amount, ref_table, ref_id, note=None, created_by=None)`, which returns
  the entry and whether it was new
- `balance(conn, season_id, user_id)`, `free_balance(conn, season_id, user_id)`,
  `open_liability(conn, season_id, maker_id)`
- `lock_member(...)`
- `adjust(session, season_id, user_id, amount, reason, admin)`. It writes the `bankroll_adjust` `activity_log` row
  and the `adjust` entry in one transaction. The amount must be non-zero and at most F$10,000 either way, and the
  reason at least 10 characters.
- `entries(conn, season_id, user_id, limit, offset)`, for the history on `/fantasy`

---

## 10. Stats and leaderboards (STAT-1, STAT-2)

### Definitions

| Metric | Definition |
|---|---|
| `starting_bankroll` | `season_members.starting_bankroll` |
| `balance` | `SUM(bankroll_entries.amount)`, on the `all` row only |
| `equity`, taker | balance + open private-book stakes at cost + open exchange positions at liquidation value (YES shares x best YES bid; NO shares x (1 - best YES ask)), marked from `market_links` `last_bid` / `last_ask`. A missing bid marks at 0 |
| `equity`, maker | balance (settled only). The open worst case is shown on `/fantasy` but not ranked |
| `pnl` | On `all`: equity - starting_bankroll. On a venue row: settled P&L on that venue, plus, for takers, the open mark minus cost |
| `roi` | (equity - starting_bankroll) / starting_bankroll. On venue rows: pnl / starting_bankroll |
| `turnover` | Taker: private-book stakes + exchange fill notional (shares x price, buys and sells). Maker: stakes taken on their markets. Fees go into pnl, not turnover |
| `bets` | Taker: private-book bets + exchange orders with at least one fill. Maker: bets taken on their markets |
| `settled`, `won` | Taker: bets won or lost, plus positions settled (won = a positive P&L). Maker: bets taken on markets that settled (won = bets the taker lost). Voids are left out |
| `hit_rate` | won / settled. NULL when settled = 0 |
| `events`, `max_drawdown`, `sharpe` | Taken from the per-event P&L series: `fantasy_event_results` for that venue (for `all`, summed across venues per `event_key`), ordered by `settled_at` and passed to `reporting.metrics.curve_stats`. Drawdown is positive, with the peak starting at 0. Sharpe = mean / sd (ddof 1) x sqrt(24), stored as NULL under 4 events (`curve_stats` itself returns 0.0 there) |
| `rank` | See Eligibility |

`stats.py` calls `curve_stats`; it never copies it. The test `test_drawdown_and_sharpe_match_curve_stats` pins
this. The sqrt(24) scale matches the paper record's roughly 24 race weekends a year, not the length of the fantasy
season. The leaderboard says so in a footnote.

### Eligibility and exclusions

- **Who gets rows:** only members with `account_type = 'player'`. Demo, staff and system accounts never do.
- **Ranked:** the membership is `active`, `users.deleted_at IS NULL`, `users.active` is true, and the player has 5
  or more settled bets or fills (DEC-13).
  - Takers: settled private-book bets + exchange fills >= 5.
  - Makers: settled bets taken on their markets >= 5.
- **Not ranked yet:** everyone else who qualifies for a row. They are listed under "Not ranked yet", with how many
  more they need.
- **Hidden:** suspended and deleted members keep their rows, so a restore is exact, but get `rank = NULL` and never
  appear on a board.
- **Order:** takers by equity and makers by balance on the `all` row, and by pnl on venue rows. Ties share a rank.

### Boards (DEC-13)

- There are two boards, one for takers and one for makers, and they are never mixed, because the private book is
  zero-sum between the two.
- **Venue filter:** all, kalshi, polymarket or book. Makers only have book this sprint, since they don't quote
  exchange markets (DEC-6).
- **Season list:** open and closed seasons. Dry-run seasons are shown to staff only.

### Recompute

- **`racinglines fantasy stats`** (incremental) recomputes members of the open season who have a ledger entry newer
  than their `computed_at`, plus every taker with an open exchange position, because marks move. It runs inside
  every `racinglines fantasy tick` (`racinglines-fantasy.timer`, every 10 minutes, SETTLE-1).
- **`racinglines fantasy stats --full`** covers every member of the open season, and a closed season once, when it
  closes. It rebuilds `fantasy_event_results` from the ledger, then `fantasy_stats`. This is the nightly `--full`:
  the tick runs it when the oldest `computed_at` in the open season is more than 24 hours old. That gives one full
  pass a day with no extra timer. Run it by hand after an adjust or a re-settle. With 50 players or fewer it takes
  about a second.
- **Invariant, tested:** an incremental run followed by `--full` gives identical rows.
- **Spot check (go/no-go):** for 3 players, the `balance` in `fantasy_stats` equals the sum of their
  `bankroll_entries`.

### Pages (STAT-2)

- **`/fantasy` (new)** shows the signed-in member's season, role and lock line, balance, free balance, equity, ROI
  and board rank. It lists their open private-book bets and exchange positions (marked), their maker markets with
  worst cases (makers), and their ledger history, 50 per page. Takers see prices, never fair values or edges.
- **`/leaderboard` (new)** is for signed-in, verified accounts only.
  - It shows handles only: no email and no display names.
  - Columns: rank, handle, equity (takers) or balance (makers), ROI, P&L, settled, hit rate, max drawdown, Sharpe,
    events.
  - The signed-in player's row is highlighted. 50 rows per page. "Computed at" is shown in PDT with UTC in
    brackets.
- Both pages return 404 when `RACINGLINES_FANTASY=0`. The nav links in `base.html` appear only when it is on.
- **No fair value for takers:** no page a taker can reach renders `fair_prob`, fair, edge or model columns. The test
  follows `test_signals_page_hides_fair_from_takers` (`tests/test_views.py:201`).

### MCP tool (new)

`leaderboard(conn, season=None, role="taker", venue="all", limit=None, offset=0)` lives in
`racinglines/mcp/tools.py` and is registered in `racinglines/mcp/server.py`.

- `season=None` means the open season.
- It returns rank, handle, equity or balance, roi, pnl, settled, hit_rate, max_drawdown, sharpe, events and
  computed_at, paged with `P.page`, ranked rows first.
- Handles only.
- Only accounts in `RACINGLINES_MCP_ROLES` (default `admin`, `mcp/auth.py`) can reach it. `docs/mcp.md` gets a line
  for it.

---

## 11. Admin tooling (ADM-1)

Every page here is admin-only (`allow("admin")`). Every POST carries the per-session CSRF token. Every action writes
an `activity_log` row with its reason.

| Page (new) | Shows | Actions and their `activity_log` rows |
|---|---|---|
| `/admin/fantasy` | The open season: status, dates in PDT and UTC, members by role, verified and unverified, unverified accounts with their age (they expire at 72 h, §6), open bets and positions, the size of the unsettled queue. The switch values (read-only). Member search: a handle prefix or an exact email, `?q=` and `&page=`, 50 per page | Read-only |
| `/admin/fantasy/seasons/{id}` | One season | Edit the name, dates and sign-up window. draft to open, open to closed (the close rules in §8) → `season_update`, with each change as old and new |
| `/admin/fantasy/invites` | The codes per season: id, label, uses and max, expiry, revoked. Never the codes | Create (the codes are shown once) → `invite_create`. Revoke → `invite_revoke` |
| `/admin/fantasy/members/{user_id}` | Handle, email, verified, account type, memberships, balance, free balance, equity, recent ledger and activity | Suspend or unsuspend (with a reason; bumps the epoch) → `member_suspend`. Role override (with a reason) → `role_override`. F$ adjust (amount and reason) → `bankroll_adjust`. Revoke sessions (bumps the epoch) → `user_update` with `changes.session_epoch`, the action `admin.py:128` already writes. Mark email verified (the fallback when mail fails) → `email_verify` with `by=admin`. Anonymise (a reason, plus the handle typed again) → `account_delete` with `by=admin` |
| `/admin/fantasy/settle` | The manual settle queue ([Fantasy trading](fantasy-trading.md)) | Settle, void, or re-settle with a reason → `fantasy_settle`, `fantasy_resettle` |

**Suspension.** It sets `season_members.status = 'suspended'` and bumps `session_epoch`. The maker's open markets
are closed. The member can sign in again, sees "suspended" on `/fantasy`, and can't bet, order or quote. Their open
bets and positions settle normally, and they vanish from the boards. For a full block, the admin also unticks
Active on `/admin/users` (existing).

**`/admin/users` (existing, `admin.py:78-129`).** It shows `account_type`. Its totals split by account type (ROLE-1
changes `USERS_SQL`, `admin.py:33-43`). Role changes for locked players are refused (ACC-4).

**Cautions for the SQL console and the database explorer.**

- `/admin/sql` (`admin.py:297-330`), with its write toggle, and `/admin/db` (`admin.py:214-292`) can change any
  row. That bypasses the ledger rules, the required reasons and the audit trail of `/admin/fantasy`.
- **Rule:** never change the fantasy tables, `users.email`, `users.role`, `users.account_type` or
  `users.session_epoch` by hand. Use `/admin/fantasy`. If a hand fix is unavoidable: back up first (CLAUDE.md), add
  a `data_changes` note, and post a compensating `adjust` rather than editing `bankroll_entries`.
- **ADM-1 makes the database explorer read-only** for `bankroll_entries`, `season_members`, `fantasy_seasons`,
  `invite_codes`, `email_tokens`, `activity_log` and the `fantasy_*` tables. The row form refuses with a pointer to
  `/admin/fantasy`. `activity_log` is on the list because it is the audit trail for every admin power (adjust,
  role override, verify, anonymise, settle): an edited row would rewrite history.
- **While sign-up is on** (`RACINGLINES_SIGNUP` not `off`), the console's write toggle and every explorer row edit
  are refused outright (§7 row 16). A hand fix then happens on the VM with `psql`, after `racinglines ops backup`,
  with a `data_changes` note.
- **The ledger explains itself.** Every admin action that posts to `bankroll_entries` (adjust, role-override
  regrant, settle, void) copies its reason into `bankroll_entries.note` as well as the `activity_log` row, so the
  ledger still says why even if the log is ever lost.
- **Pruning only blanks.** The 90-day step in §12 sets `ip` and `username` to NULL. Nothing ever deletes an
  `activity_log` row or edits its `action` or `detail`.
- **ADM-1 also hides columns:** `("email_tokens", "token_hash")` and `("invite_codes", "code_hash")` join
  `HIDDEN_COLUMNS` (`admin.py:24`).
- **The console's default query** reads `activity_log` (`admin.py:299`), which holds IPs. That is acceptable
  because the console is admin-only and logs every query it runs (`sql_read` / `sql_write`, `admin.py:328`).

---

## 12. Privacy and data handling (ACC-3, ADM-1, LEGAL-1)

### What personal data exists

| Data | Where | Why | Kept | Who sees it |
|---|---|---|---|---|
| Email address | `users.email`, `email_tokens.email` | Sign-in, verification, reset, support | Until deletion, when it is set to NULL and the tokens are deleted | The player and the admin. Never other players, never a board, never MCP (`users` is hidden) |
| Password | `users.password_hash` (scrypt) | Sign-in | Until deletion (`!deleted`) | Nobody (hidden in the database explorer, `admin.py:24`) |
| Handle | `users.username`, `house_bets.counterparty`, `activity_log.username` | Public identity | Replaced by `deleted-<id>` at deletion | Every signed-in player |
| IP address | `activity_log.ip` | Abuse checks, rate limits | 90 days, then NULL | The admin |
| Usernames typed on failed logins | `activity_log.username` on `login_failed` and `signup_rejected` rows | Abuse checks | 90 days, then NULL | The admin |
| 18+ and terms acceptance | `users.age_confirmed_at`, `terms_version`, `terms_accepted_at` | Proof of consent | As long as the account row exists | The admin |
| Game history | `bankroll_entries`, `house_bets`, `fantasy_orders` / `fills` / `positions`, `fantasy_stats` | The game itself | Kept after deletion under `deleted-<id>`, hidden from boards | The player and the admin. Counterparties see a handle |
| Bot check | Cloudflare Turnstile (a third party) | Bot protection on the public forms | Cloudflare's policy | |
| Mail | Proton (a third party) | Sending verification and reset mail | Proton's policy | |
| Backups | Nightly dumps on the VM and in the bucket, pre-change dumps, disk snapshots ([VM reliability](vm-reliability.md)) | Recovery | 7 dumps on the VM disk; 35 days in `gs://$RACINGLINES_GCS_BUCKET/db/nightly/`, plus 30 days of old object versions; 14 days of snapshots (`racinglines-daily`) | The owner. Never a cloud session or the Mac dev database in raw form (below) |

**Pruning.** ADM-1 adds a step to the daily `--full` pass of `racinglines fantasy tick` in
`racinglines/cli/fantasy.py`:

```sql
UPDATE activity_log SET ip = NULL WHERE ts < now() - interval '90 days' AND ip IS NOT NULL;
UPDATE activity_log SET username = NULL
 WHERE ts < now() - interval '90 days' AND action IN ('login_failed', 'signup_rejected') AND username IS NOT NULL;
```

This is a routine write, like the recorder's and the tick's own, and the nightly dump covers it
([VM reliability](vm-reliability.md)).

**MCP.** `SQL_HIDDEN` (`mcp/tools.py:24`) becomes `("users", "orders", "activity_log", "email_tokens",
"invite_codes")`. The check at `mcp/tools.py:641-643` and the row counts at `mcp/tools.py:118` pick this up. The
fantasy tables hold only user ids and no PII, and handles come only through the `leaderboard` tool.

### Deletion = anonymise

A player deletes their own account with POST `/account/delete`, giving the current password and typing their handle
again. The admin can do it from the member page. Either way, one transaction:

- `users`:
  - `username` and `display_name` become `deleted-<id>`
  - `email` and `email_verified_at` are set to NULL
  - `password_hash` becomes `!deleted`, which can never verify, because `verify_password` needs six `$`-separated
    parts (`users.py:32-38`)
  - `prefs` is set to NULL, `active = false`, `deleted_at = now()`, and `session_epoch + 1`
- `house_bets.counterparty = 'deleted-<id>'` where `taker_id` is the user.
- `activity_log.username = 'deleted-<id>'` where `user_id` is the user.
- The user's `email_tokens` rows are deleted.
- `season_members.status = 'left'`. The maker's open markets are set to `closed`, so no new bets can arrive. Open
  bets and positions stay and settle normally, which keeps counterparties' ledgers right.
- The ledger, `fantasy_event_results` and `fantasy_stats` are kept, hidden from the boards.
- Log `account_delete`.

The handle and the email address become free for a new sign-up. Anonymising can't be undone.

### Backups and restores

Whole-database dumps carry everything in the table above, including emails, password hashes, IPs and
`email_tokens`, and anonymising doesn't reach a dump that was already taken. Three rules follow. They belong to the
backup tasks in [VM reliability](vm-reliability.md) (OPS-3, OPS-4), and the DOC-1 review carries them there:

1. **No player PII outside the owner's copies.** The bucket's "latest" copy that `scripts/cloud/bucket.sh restore`
   and cloud sessions read, and every restore onto the Mac dev or scratch database, must not carry player PII.
   Today `bucket.sh` dumps the whole database with no exclusions (`scripts/cloud/bucket.sh:31`, copied to `db/`
   at `:38-39`). Before `RACINGLINES_SIGNUP` leaves `off`, that copy is made with `pg_dump --exclude-table-data` for `email_tokens`,
   `invite_codes` and `activity_log`, and with the player rows' PII blanked (email, password hash, the consent
   timestamps) on a restored scratch copy before it is dumped for sharing. The full nightly dumps stay owner-only.
   The owner also confirms uniform bucket-level access and public access prevention on the bucket.
2. **The privacy page says how long backups keep data** (the row above), and that a deleted account's data can
   survive in them for up to 35 days plus 30 days of object versions, and 14 days in snapshots.
3. **A restore re-applies deletions.** Anonymising also appends one line, the user id and the UTC time (no other
   data), to `/var/lib/racinglines/deletions.log` on the VM, outside the database. After any restore (the
   [Bad migration](vm-reliability.md#bad-migration) runbook and the other restore paths), the owner re-runs
   Anonymise from `/admin/fantasy/members/{user_id}` for every id in that file newer than the dump, before sign-up
   is switched back on.

### Export on request

A player writes to support@racinglines.bet from their registered address. The owner checks that it is the same
address, then runs the read-only export below and replies from Proton with the file. The response time is stated on
the privacy page (owner input, DEC-22). The file contains PII: never commit it, and delete both copies once it is
sent.

```sh
# LOCAL (Mac) — open a shell on the VM
bash scripts/deploy/vm.sh ssh
```

```sh
# VM (production) — read-only: one player's data as JSON in your home directory (set USER_ID first)
USER_ID=123; UTC=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u racinglines -H bash -c "cd /opt/racinglines && docker compose exec -T db psql -U racinglines -d racinglines -At -c \"SELECT json_build_object(
  'user', (SELECT row_to_json(u) FROM (SELECT id, username, email, role, account_type, created_at, email_verified_at, terms_version, terms_accepted_at, age_confirmed_at, last_login_at FROM users WHERE id = $USER_ID) u),
  'memberships', (SELECT json_agg(s) FROM season_members s WHERE user_id = $USER_ID),
  'ledger', (SELECT json_agg(b ORDER BY b.id) FROM bankroll_entries b WHERE user_id = $USER_ID),
  'book_bets', (SELECT json_agg(h ORDER BY h.id) FROM house_bets h WHERE taker_id = $USER_ID),
  'exchange_orders', (SELECT json_agg(o ORDER BY o.id) FROM fantasy_orders o WHERE user_id = $USER_ID),
  'exchange_positions', (SELECT json_agg(p ORDER BY p.id) FROM fantasy_positions p WHERE user_id = $USER_ID),
  'stats', (SELECT json_agg(f) FROM fantasy_stats f WHERE user_id = $USER_ID),
  'activity', (SELECT json_agg(a ORDER BY a.id) FROM activity_log a WHERE user_id = $USER_ID))\"" > ~/export-user-$USER_ID-$UTC.json
ls -l ~/export-user-$USER_ID-$UTC.json
```

```sh
# LOCAL (Mac) — copy the export off the VM (use the file name the ls above printed)
gcloud compute scp racinglines-vm:~/export-user-<id>-<UTC>.json . --project racinglines --zone us-west1-b --tunnel-through-iap
```

```sh
# VM (production) — once the export is sent, remove the VM copy
rm ~/export-user-<id>-<UTC>.json
```

### The privacy, terms and rules pages (LEGAL-1, DEC-22)

LEGAL-1 writes a plain-language draft for the owner, with counsel if the owner wants. It is not legal advice.
Owner placeholders go wherever a decision is still open. All three pages are public. Each shows
"Version 2026-10-08" (`TERMS_VERSION`) and is linked from the sign-up form and the footer.

- **`/terms`:**
  - who runs racinglines (owner placeholder)
  - F$ are paper money with no cash value and can't be transferred; there are no prizes and no fees (DEC-1)
  - 18 or older; one account per person; not available where prohibited, with no geo-blocking at the soft launch
  - not investment advice
  - no promise that the service is always available
  - data sources and attribution (Kalshi, Polymarket, F1 data; DEC-7 placeholder)
  - suspension and termination
  - how the terms change (a new `TERMS_VERSION`)
  - contact: support@racinglines.bet
- **`/privacy`:**
  - the table above, in plain words
  - the processors: Proton for mail, Cloudflare for the tunnel and Turnstile, Google Cloud (us-west1) for hosting
  - the cookies: `rl_session`, `rl_csrf`, and Turnstile's
  - IPs kept 90 days
  - deletion means anonymising, and backups keep a deleted account's data for up to 35 days (plus 30 days of old
    versions and 14 days of disk snapshots); a restore re-applies deletions
  - export on request, with the response time (placeholder)
  - no sale of data
  - contact
- **`/rules`:**
  - roles and the lock
  - bankrolls, the F$100 cap per bet and per order, and the F$1,000 cap per maker market
  - markets close at the start of the session that decides them (DEC-14)
  - settlement from results or venue resolution, and the void rules
  - the Kalshi fee on exchange paper trades
  - how the boards rank (DEC-13)
  - fair play: one account each (addresses are compared without `+tags`, and Gmail addresses without dots), no
    collusion between maker and taker accounts; collusion voids the results involved and can lead to suspension

`TERMS_VERSION = '2026-10-08'` lives in `racinglines/web/accounts.py`. Bumping it should ask players to accept the
new terms at their next sign-in. That flow isn't built this sprint (see Open items).

---

## 13. Demo accounts after launch (DEC-15, ROLE-1)

| What changes | What stays |
|---|---|
| `account_type = 'demo'` (the backfill) | One-click **Try as maker** and **Try as taker**, password `password` (`login.html:9-13`) |
| The `demo_context` bubbles (`_macros.html:52`, `DEMO_CONTEXT` at `app.py:228-229`) show only to demo viewers, and only while `RACINGLINES_DEMO_CONTEXT` isn't 0. They are hidden for everyone else, not deleted, which replaces the "delete every call" note at `app.py:225-227` | `demo.guard`: read-only, disposable sessions, every request logged (`demo.py`) |
| `/live` labels the demo taker's picks "demo taker" for viewers who aren't demo (`live_f1.html`, `live_picks.html`) | Never members of a fantasy season, so never in stats, boards or player totals. Their paper record (`paper_positions`, the story) is untouched |
| Admin totals split by account type | HTTP Basic for demo accounts, so `scripts/deploy/smoke.sh` passes unchanged. OPS-9 adds GET checks for `/healthz`, `/terms`, `/privacy`, `/rules` and `/signup` |
| With `RACINGLINES_FANTASY=1`, players' `/markets` redirects to `/fantasy/markets`, or to `/fantasy` while `RACINGLINES_FANTASY_EXCHANGE=0`. Demo and staff accounts keep `/markets` | The demo tests in `tests/test_views.py` pass once SEC-1 adds a login helper that knows about CSRF. Today the `clients` fixture posts `/login` with no token (`test_views.py:71-90`) |
| The login page: "Handle or email" label, a sign-up link when sign-up is on, and the `rl_csrf` field on the demo buttons | The per-username lock never applies to demo accounts |

---

## 14. Switches, tests and tasks

### Switches used here

Every new switch lives in `/etc/racinglines.env` on the VM and is off or safe by default. Secrets (the Turnstile
secret, `APP_SECRET`, the SMTP token) live only there.

| Switch | Default | Used for |
|---|---|---|
| `RACINGLINES_FANTASY` (new) | `0` | The nav, `/fantasy`, `/leaderboard`. When it is on, `APP_SECRET` is required |
| `RACINGLINES_SIGNUP` (new) | `off` | `off`, `invite` or `open` (§5). When it isn't off, `APP_SECRET` is required |
| `RACINGLINES_SIGNUP_CAP` (new) | `50` | The limit on player accounts |
| `RACINGLINES_FANTASY_BOOK`, `RACINGLINES_FANTASY_EXCHANGE` (new) | `0` | Trading ([Fantasy trading](fantasy-trading.md)). `/fantasy` shows only what is on |
| `RACINGLINES_MAIL_BACKEND` (new) | `log` | Mail ([Email setup](email-setup.md)) |
| `RACINGLINES_TURNSTILE_SITEKEY`, `RACINGLINES_TURNSTILE_SECRET` (new) | empty | The Turnstile widget on `/signup`, `/password/forgot` and the signed-out `/verify/resend` form |
| `RACINGLINES_URL` (existing) | `https://racinglines.bet` on the VM | The base of every mail link |
| `APP_SECRET` (existing) | A random value per start | The cookie and CSRF keys |
| `MAX_STAKE` (existing) | `100` | The per-bet cap (F$100), alongside the season's `max_stake` |
| `RACINGLINES_DEMO_USERS`, `RACINGLINES_DEMO_CONTEXT` (existing) | `maker,taker`, `1` | The demo accounts and the bubbles |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` (existing) | `admin`, empty | `ensure_admin`. `ADMIN_USERNAME` is reserved |
| `RACINGLINES_MCP_ROLES` (existing) | `admin` | Who can call the `leaderboard` tool |

Never touched: `POLYMARKET_TRADING_ENABLED`, `KALSHI_TRADING_ENABLED`.

### Tests

- **Which database, today:** `test_engine` (`tests/conftest.py:77-98`) rebuilds `racinglines_test` from the
  migrations each session, but only code handed that engine uses it. The app and the CLI call `get_engine()`
  (`racinglines/db/config.py:22-23`), which is `lru_cache`d and reads `DATABASE_URL`, falling back to the dev
  database. So today's app-level tests run against the **dev database**: the `clients` fixture
  (`tests/test_views.py:71-90`) logs in through `TestClient(app)` and writes `login` rows to the dev
  `activity_log`. Sign-up, ledger and settle tests written that way would create users and F$ rows there.
- **New fixture (SEC-1):** `app_test_db` in `tests/conftest.py`. It depends on `test_engine`, sets `DATABASE_URL`
  to the test database with `monkeypatch.setenv` before `racinglines.web.app` is imported, calls
  `get_engine.cache_clear()` before and after, and yields a `TestClient`. Every new test in the table below that
  touches a database or the app uses `test_engine` or `app_test_db`, never the dev database, so they need no backup.
  Existing tests keep their current fixtures; moving them over is not in this sprint.
- **Fixtures** go in `tests/fixtures/fantasy/`.
- **Golden tests** (`tests/golden`) don't change.

| File | Task | Tests (names are proposals) |
|---|---|---|
| `tests/test_auth.py` (new) | SEC-1, ACC-3 | `test_login_requires_csrf`, `test_csrf_token_is_per_session`, `test_logout_is_post_and_get_shows_a_form`, `test_next_is_url_encoded_and_stays_on_site`, `test_throttle_prunes_idle_ips`, `test_throttle_per_username_spares_demo`, `test_create_user_normalises_and_refuses_reserved_handles`, `test_create_user_password_policy`, `test_old_cookie_format_is_rejected`, `test_demo_one_click_login_still_works`, `test_session_epoch_bump_ends_sessions`, `test_basic_auth_refused_for_players`, `test_ensure_admin_never_touches_a_player`, `test_app_secret_required_when_signup_on`, `test_login_by_handle_or_email_case_insensitive`, `test_login_unknown_user_takes_scrypt_time` (timing ratio), `test_throttle_staff_lock_is_per_ip`, `test_security_headers_on_every_page`, `test_admin_sql_write_refused_while_signup_on` |
| `tests/test_signup.py` (new) | ACC-3 | `test_signup_off_is_404`, `test_signup_invite_needs_a_valid_code`, `test_invite_code_single_use_under_race`, `test_signup_cap`, `test_handle_rules_and_reserved`, `test_email_case_duplicate_refused`, `test_password_length_bounds`, `test_role_and_consents_required`, `test_turnstile_checked_when_keys_set` (siteverify mocked), `test_signup_rate_limit_per_ip`, `test_unverified_user_reaches_only_account_and_resend`, `test_verify_get_does_not_use_the_token`, `test_verify_token_single_use_and_expiry`, `test_verify_creates_locked_membership_and_grant`, `test_resend_limit`, `test_forgot_same_answer_for_unknown_email`, `test_reset_bumps_epoch_and_expires_in_1h`, `test_email_change_confirms_new_address_and_notifies_old`, `test_account_delete_anonymises`, `test_mail_links_use_racinglines_url_not_host_header`, `test_signup_writes_activity_log_rows_without_secrets`, `test_no_raw_token_in_activity_log_or_access_log`, `test_account_change_ends_open_links`, `test_reset_refused_after_email_change`, `test_email_normalised_for_uniqueness`, `test_own_domain_refused`, `test_ipv6_counted_by_64`, `test_reset_share_of_daily_cap`, `test_unverified_expire_after_72h` |
| `tests/test_fantasy_schema.py` (new) | ACC-1 | `test_upgrade_downgrade_upgrade`, `test_backfill_account_types`, `test_case_duplicate_usernames_stop_the_migration`, `test_role_and_account_type_checks`, `test_one_open_season_index`, `test_models_match_migration` (functional indexes compared by name) |
| `tests/test_fantasy_seasons.py` (new) | ACC-4 | `test_season_lifecycle_moves_forward_only`, `test_ends_at_null_is_tbd`, `test_role_lock_refuses_change_without_reason`, `test_role_override_with_reason_regrants_and_logs`, `test_late_joiner_gets_full_bankroll`, `test_invite_codes_hashed_used_revoked_expired`, `test_close_refuses_open_items_unless_void`, `test_dryrun_close_voids_open_items`, `test_cli_season_and_invite` |
| `tests/test_ledger.py` (new) | ACC-4 | `test_balance_is_sum`, `test_post_is_idempotent_per_ref_and_kind`, `test_taker_free_balance_is_net_of_stakes`, `test_maker_free_balance_minus_worst_case`, `test_adjust_needs_reason_and_refs_activity_log`, `test_entries_are_append_only`, `test_amounts_round_to_cents` |
| `tests/test_fantasy_stats.py` (new) | STAT-1 | `test_drawdown_and_sharpe_match_curve_stats`, `test_sharpe_null_under_4_events`, `test_equity_marks_at_bid`, `test_roi_and_hit_rate`, `test_eligibility_minimum_5`, `test_only_players_get_rows`, `test_suspended_and_deleted_hidden`, `test_incremental_equals_full`, `test_venue_pnl_sums_to_all` |
| `tests/test_views.py` | ROLE-1, STAT-2, LEGAL-1 | `test_player_maker_cannot_launch_lab_promote_or_sync`, `test_player_maker_sees_no_edges`, `test_staff_maker_keeps_lab`, `test_demo_bubbles_only_for_demo_viewers`, `test_fantasy_off_is_404`, `test_leaderboard_login_only_handles_only`, `test_leaderboard_hides_fair_from_takers`, `test_terms_privacy_rules_are_public` |
| `tests/test_mcp.py` | STAT-2, ADM-1 | `test_leaderboard_tool_handles_only`, `test_sql_hides_activity_log_and_token_tables` |
| `tests/test_admin_fantasy.py` (new) | ADM-1 | `test_admin_only`, `test_suspend_bumps_epoch_and_closes_markets`, `test_adjust_writes_entry_and_log`, `test_role_override_needs_reason`, `test_admin_verify_fallback`, `test_anonymise_from_admin`, `test_member_search_pages`, `test_ip_prune_after_90_days`, `test_db_explorer_refuses_ledger_edits`, `test_db_explorer_refuses_activity_log_edits`, `test_adjust_reason_in_ledger_note` |

### Tasks

The tasks come from the plan in the [runbook](fantasy-runbook.md). The P2 branches stack on
`work/acc-1` until OWNER-8 merges it, then each one rebases onto `main`. The merge order (FABLE-1)
is: OPS-8 → ACC-1 (OWNER-8) → SEC-1 → MAIL-1 → ACC-3 → ACC-4 → ROLE-1 → BOOK-3 → EXCH-1 → STAT-1 → SETTLE-1 →
STAT-2 → ADM-1. SEC-1 has no schema change, so it may merge in P1. If it hasn't, it keeps its place in that order.

| ID | Task | Role · model | Size | Depends on | Money flag | When |
|---|---|---|---|---|---|---|
| SEC-1 | Auth hardening, no schema change (§7 rows 1, 3-8, 12 timing, 15, 16(b); the `app_test_db` fixture) | own · Opus | L (~35 calls, 9 files) | none | none. Signs everyone out once: deploy between sessions | P1, Tue 29 Sep - Sun 4 Oct |
| ACC-1 | `fantasy_schema_v1` plus the models (§3, §4) | own · Opus, Fable reviews | L (~30 calls, 4 files) | OPS-8 (to merge) | ⚠️ DB migration | On a branch by Fri 2 Oct. Merged only at OWNER-8 |
| ACC-2 | Trial on a restored copy, and the data-change record (§4) | own · Opus | S (~10 calls) | ACC-1, OPS-4 | ⚠️ writes the scratch database only | Mon 5 Oct |
| OWNER-8 | Apply the migration on the VM (§4) | owner | S (~30 min) | ACC-2, OPS-8 | ⚠️ needs special attention: a migration against the VM, with the owner's sign-off in the same turn | Tue 6 Oct 09:00 PDT (16:00 UTC) |
| ACC-3 | Sign-up, verify, reset, account, deletion, epoch (§5-§7) | own · Opus | XL (~45 calls, 12 files) | ACC-1, SEC-1, MAIL-1 | none | P2, by Wed 7 Oct |
| ACC-4 | Seasons, membership, ledger, CLI (§8-§9) | implement · Sonnet, Fable reviews the ledger rules | L (~28 calls, 7 files) | ACC-1 | ⚠️ ledger | P2 |
| ROLE-1 | Player makers vs staff, demo separation (§2, §13) | implement · Sonnet | M (~22 calls, 9 files) | ACC-1 | none | P2 |
| STAT-1 | `fantasy/stats.py` and `racinglines fantasy stats [--full]` (§10) | implement · Sonnet | M (~18 calls, 3 files) | ACC-4 | none | P2 |
| STAT-2 | `/fantasy`, `/leaderboard`, the MCP `leaderboard` tool (§10) | implement · Sonnet | M (~20 calls, 8 files) | STAT-1 | none | P2 |
| ADM-1 | `/admin/fantasy`, `SQL_HIDDEN`, IP pruning (§11-§12) | implement · Sonnet, Fable reviews settle and adjust | L (~28 calls, 5 files) | ACC-4, SETTLE-1 | ⚠️ manual settlement and F$ adjustments | P2 |
| LEGAL-1 | Drafts of `/terms`, `/privacy`, `/rules` (§12) | implement · Sonnet | S (~10 calls, 5 files) | OWNER-2 | none | P1, after decision batch A |

**Dispatch briefs** (name the model on every spawn, per CLAUDE.md):

```text
# SEC-1 — Opus (own). EST: ~35 calls, 9 files
Scope: racinglines/web/app.py, racinglines/web/users.py, racinglines/web/admin.py, racinglines/web/demo.py,
       racinglines/web/templates/login.html, racinglines/web/templates/base.html, scripts/deploy/smoke.sh,
       tests/conftest.py (the app_test_db fixture), tests/test_auth.py (new), tests/test_views.py
Done when: section 7 rows 1, 3-8, the timing part of 12, 15 and 16(b) hold; app_test_db keeps every new test off
           the dev database; the one-click demo logins and smoke.sh pass; no schema change
Verify: python -m pytest tests/test_auth.py tests/test_views.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# ACC-1 — Opus (own), Fable reviews. EST: ~30 calls, 4 files
Scope: racinglines/db/models.py, migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py (new),
       tests/test_fantasy_schema.py (new), docs/database.md
Done when: every table and column in section 3 and fantasy-trading.md exists; guards, backfill and a real
           downgrade; `alembic heads` prints one line
Verify: upgrade, downgrade -1, upgrade on a scratch database; python -m pytest tests/test_fantasy_schema.py -m "not live";
        python -m pytest -m "not live"
Report: files changed, the verify commands and their last lines, the alembic heads output, what you did not check
```

```text
# ACC-2 — Opus (own). EST: ~10 calls
Scope: scripts/ops/restore_scratch.sh (OPS-4's script, used as is), docs/data-changes.md
Done when: section 4 LOCAL steps 1-3 ran on racinglines_scratch with timings, backfill counts (demo 2, system 1)
           and no duplicates; the data-changes section is in the ACC-1 PR
Verify: the log data/backups/acc2-trial-<UTC>.log exists and its last lines show `alembic current` = the new revision
Report: the log path, the timings, the counts, what you did not check
```

```text
# ACC-3 — Opus (own). EST: ~45 calls, 12 files
Scope: racinglines/web/accounts.py (new), racinglines/web/users.py, racinglines/web/app.py, racinglines/web/demo.py,
       racinglines/cli/web.py (the uvicorn.access filter), templates signup, verify, forgot, reset, account (new),
       login, base; tests/test_signup.py (new), tests/test_auth.py
Done when: sections 5-7 hold behind RACINGLINES_SIGNUP=off by default; sign-up 5/h per IP, resend 3/h per user,
           forgot 3/h per email and 10/h per IP (IPv6 by /64), 6 mails a day per address; no raw token in
           activity_log or the access log; account changes end every open link; unverified users reach only
           /account and /verify/resend, and expire at 72 h
Verify: python -m pytest tests/test_signup.py tests/test_auth.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# ACC-4 — Sonnet (implement), Fable reviews the ledger rules. EST: ~28 calls, 7 files
Scope: racinglines/fantasy/__init__.py, seasons.py, ledger.py (new), racinglines/cli/fantasy.py (new; plus "fantasy"
       in GROUPS at racinglines/cli/__init__.py:20), racinglines/web/admin.py, tests/test_fantasy_seasons.py,
       tests/test_ledger.py (new)
Done when: sections 8-9 hold; the CLI flags match the STAGE-1 and launch blocks in fantasy-runbook.md
Verify: python -m pytest tests/test_fantasy_seasons.py tests/test_ledger.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# ROLE-1 — Sonnet (implement). EST: ~22 calls, 9 files
Scope: racinglines/web/app.py, views.py, jobs.py, admin.py; templates _macros.html, live_f1.html, live_picks.html,
       login.html; tests/test_views.py
Done when: the section 2 role table and the section 13 table hold; demo accounts and smoke.sh behave as today
Verify: python -m pytest tests/test_views.py -m "not live"; bash scripts/deploy/smoke.sh http://127.0.0.1:8000
Report: files changed, the verify commands and their last lines, what you did not check
```

```text
# STAT-1 — Sonnet (implement). EST: ~18 calls, 3 files
Scope: racinglines/fantasy/stats.py (new), racinglines/cli/fantasy.py, tests/test_fantasy_stats.py (new)
Done when: section 10 definitions hold; curve_stats is called, not copied; incremental equals --full
Verify: python -m pytest tests/test_fantasy_stats.py tests/test_reporting_metrics.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# STAT-2 — Sonnet (implement). EST: ~20 calls, 8 files
Scope: racinglines/web/app.py, templates fantasy.html, leaderboard.html (new), base.html; racinglines/mcp/tools.py,
       racinglines/mcp/server.py; tests/test_views.py, tests/test_mcp.py
Done when: /fantasy and /leaderboard as in section 10, 404 while RACINGLINES_FANTASY=0; no fair value reaches a
           taker; the MCP leaderboard tool returns handles only
Verify: python -m pytest tests/test_views.py tests/test_mcp.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# ADM-1 — Sonnet (implement), Fable reviews settle and adjust. EST: ~28 calls, 5 files
Scope: racinglines/web/admin.py, racinglines/web/templates/admin_fantasy.html (new), racinglines/mcp/tools.py,
       racinglines/fantasy/ledger.py, tests/test_admin_fantasy.py (new); plus the prune step in racinglines/cli/fantasy.py
Done when: section 11 pages and actions, each writing its activity_log row with the reason; SQL_HIDDEN extended;
           IPs pruned after 90 days; the database explorer refuses ledger and activity_log edits; admin reasons also
           land in bankroll_entries.note; the member page shows the invite code that created the account
Verify: python -m pytest tests/test_admin_fantasy.py tests/test_mcp.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

```text
# LEGAL-1 — Sonnet (implement). EST: ~10 calls, 5 files
Scope: racinglines/web/templates/terms.html, privacy.html, rules.html (new), racinglines/web/app.py, tests/test_views.py
Done when: the three public pages carry the section 12 outline, "Version 2026-10-08", and an owner placeholder
           wherever DEC-1, DEC-4, DEC-7 or DEC-22 is open; each says it is a draft and not legal advice
Verify: python -m pytest tests/test_views.py -m "not live"
Report: files changed, the verify command and its last line, the placeholders left for the owner
```

**Docs obligations.**

- ACC-1 updates `docs/database.md`.
- STAT-2 adds the `leaderboard` tool to `docs/mcp.md`.
- DOC-2 updates `docs/webapp.md` (roles, accounts, auth) and `docs/cli.md` (the `fantasy` group) after the merges.
- Every change passes `mkdocs build --strict`.

### What this doc's tasks put on the go/no-go

| Go/no-go line (in the [runbook](fantasy-runbook.md#go-no-go)) | Evidence from these tasks |
|---|---|
| `fantasy_schema_v1` applied on the VM after a dump | OWNER-8 step 3 log: `alembic current`, `db changes`, the dump's name; the ACC-2 trial log |
| `APP_SECRET` set | A web restart keeps an existing session signed in |
| Sign-up rehearsal passed | STAGE-1 lines for sign-up, verify, grant, lock, reset, deletion, and the cap |
| Terms live with `TERMS_VERSION` 2026-10-08 | `/terms`, `/privacy` and `/rules` return 200. The sign-up page says "paper money, no prizes, no cash value" |
| Stats: players only, handles only, no fair value for takers | `/leaderboard` screenshot; 3 spot checks of `fantasy_stats` balance against the `bankroll_entries` sum |
| Admin: suspend, adjust with a reason, void, revoke sessions | `activity_log` rows `member_suspend`, `bankroll_adjust`, `fantasy_settle`, `user_update` |
| Demo unaffected | One-click demo logins work; `smoke.sh` passes against https://racinglines.bet |
| Admin behind Cloudflare Access (§7 row 16) | A signed-out browser on `https://racinglines.bet/admin` gets the Cloudflare Access PIN page; `/admin/sql` refuses writes while `RACINGLINES_SIGNUP` is not `off` |
| Bot check decided (DEC-16) | Either the Turnstile keys are set and the widget shows on `/signup`, `/password/forgot` and `/verify/resend`, or DEC-16 is recorded as "no" |
| No player PII in shared dumps (§12) | The bucket's "latest" copy has no rows in `email_tokens`, `invite_codes` or `activity_log`, and no player email |

The last three lines are go/no-go lines 20, 22 and 23 in the [runbook](fantasy-runbook.md#go-no-go) (line 20
also accepts SEC-1's fallback when Cloudflare Access is not on).

---

## 15. Names used across these docs

This is the subset of the conventions block this page uses, copied word for word. The master copy is in
[Fantasy soft launch](fantasy-launch.md).

```text
TERMS
- fantasy season = one row in fantasy_seasons. This is never the racing `seasons` table. First season slug: 2026-s1. Dry-run/staging season slug: 2026-dryrun. It is closed before launch and left out of stats.
- app role = users.role (admin|maker|taker); it controls permissions. season role = season_members.role (maker|taker); it is the choice made at sign-up, locked by season_members.locked_at until the season's status becomes closed.
- account type = users.account_type: player (signed up through /signup), staff (owner, admin, collaborators, R16 testers), demo (maker, taker), system (polymarket-takers). Only players appear in leaderboards and fantasy stats.
- handle = users.username. Lowercase, regex ^[a-z0-9][a-z0-9_-]{2,19}$. It is the only public identity; email is never shown to another user. Reserved: admin, root, staff, support, noreply, system, demo, maker, taker, polymarket-takers, racinglines, plus the value of ADMIN_USERNAME.
- F$ = fantasy dollars: paper money, no cash value, not transferable. Player-facing copy never uses a bare "$".
- private book = the in-app DB book (house_markets / house_bets). live book = the file-based demo book under data/runs/live/<run>/ (demo maker plus simulated crowd). Players never trade the live book, and the crowd never fills a player's quote.
- exchange paper trade = a player's order filled against a venue's live order book (Kalshi, Polymarket) and stored only in fantasy_orders / fantasy_fills / fantasy_positions. It never goes into paper_positions or strategy_signals, and never through racinglines/markets/polymarket/trade.py or racinglines/markets/kalshi/trade.py.
- equity: taker = balance + open private-book stakes at cost + open exchange positions at liquidation value (YES shares x best YES bid; NO shares x (1 - best YES ask)), marked from market_links last_bid/last_ask. maker = balance (settled only; open worst case shown, not ranked). ROI = (equity - starting_bankroll) / starting_bankroll.
- closed dry run = R16, Thu 1 Oct to Sun 4 Oct, 5 or fewer admin-created staff tester accounts, no sign-up. staging rehearsal = Wed 7 Oct on the VM with RACINGLINES_SIGNUP=invite and tester codes in season 2026-dryrun. soft launch = RACINGLINES_SIGNUP=invite from Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC). open sign-up = RACINGLINES_SIGNUP=open (not before Thu 22 Oct).
- Times: owner-facing times in PDT with UTC in brackets; systemd OnCalendar in UTC.

TABLES: one additive Alembic revision fantasy_schema_v1, file migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py, down_revision = the single head at branch time (c8e3f6a2d4b1 on 29 Sep)
- users (+): email String(254) NULL; email_verified_at; terms_version String(20); terms_accepted_at; age_confirmed_at; account_type String(10) NOT NULL DEFAULT 'staff' CHECK IN (player,staff,demo,system); session_epoch Integer NOT NULL DEFAULT 0; last_login_at; deleted_at. Indexes: unique ix_users_username_lower ON lower(username), unique ix_users_email_lower ON lower(email). CHECK users.role IN (admin,maker,taker). Backfill: maker, taker -> demo; polymarket-takers -> system; everything else -> staff.
- email_tokens: id, user_id FK CASCADE, purpose (verify|reset|email_change), token_hash String(64) UNIQUE (sha256 hex), email, created_at, expires_at, used_at. TTL: verify 24 h, reset 1 h, email_change 24 h.
- invite_codes: id, code_hash String(64) UNIQUE, label, season_id FK, created_by FK SET NULL, max_uses DEFAULT 1, uses DEFAULT 0, expires_at, revoked_at, created_at.
- fantasy_seasons: id, slug UNIQUE, name, status (draft|open|closed), starts_at, ends_at NULL (NULL = TBD), signup_opens_at, signup_closes_at NULL, bankroll_taker Numeric(12,2), bankroll_maker Numeric(12,2), max_stake Numeric(12,2), max_market_liability Numeric(12,2), notes JSONB, created_at.
- season_members: id, season_id FK, user_id FK, role (maker|taker), locked_at, joined_at, starting_bankroll Numeric(12,2), status (active|suspended|left). UNIQUE(season_id, user_id).
- bankroll_entries: id, season_id, user_id, ts, kind (grant|stake|payout|refund|trade|fee|settle|book_pnl|adjust), amount Numeric(12,2) signed, ref_table, ref_id, note, created_by. UNIQUE(ref_table, ref_id, kind). balance = SUM(amount).
- fantasy_orders: id, season_id, user_id, market_link_id FK, exchange (kalshi|polymarket), token_id, side (yes|no), action (buy|sell), shares_req, limit_price, status (filled|partial|rejected), reject_reason, book JSONB (levels used, fetched_at), created_at.
- fantasy_fills: id, order_id FK, season_id, user_id, market_link_id, exchange, side, action, shares, price, fee, ts.
- fantasy_positions: id, season_id, user_id, market_link_id, exchange, yes_shares, no_shares, cost, fees, status (open|settled|void), outcome Boolean NULL, payout, settled_at. UNIQUE(season_id, user_id, market_link_id).
- fantasy_event_results: season_id, user_id, event_key, venue (kalshi|polymarket|book), role, pnl, turnover, bets, won, settled_at. PK(season_id, user_id, event_key, venue).
- fantasy_stats: season_id, user_id, venue (all|kalshi|polymarket|book), role, starting_bankroll, balance, equity, pnl, roi, turnover, bets, settled, won, hit_rate, max_drawdown (positive number), sharpe (x sqrt(24); NULL under 4 events), events, rank, computed_at. PK(season_id, user_id, venue).
- house_markets (+): season_id FK NULL, closes_at, max_liability Numeric(12,2). house_bets (+): season_id FK NULL, fair_prob_at_bet, settled_at.

ENV (in /etc/racinglines.env on the VM; every new one is off or safe by default)
RACINGLINES_FANTASY=0|1 (master switch: nav, /fantasy, /leaderboard); RACINGLINES_SIGNUP=off|invite|open (default off); RACINGLINES_SIGNUP_CAP=50; RACINGLINES_FANTASY_BOOK=0|1; RACINGLINES_FANTASY_EXCHANGE=0|1; RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 (stays 0 this sprint); RACINGLINES_MAIL_BACKEND=log|smtp (default log); RACINGLINES_SMTP_HOST=smtp.protonmail.ch; RACINGLINES_SMTP_PORT=587; RACINGLINES_SMTP_USER=noreply@racinglines.bet; RACINGLINES_SMTP_TOKEN (secret, never in git); RACINGLINES_MAIL_FROM=racinglines <noreply@racinglines.bet>; RACINGLINES_MAIL_REPLY_TO=support@racinglines.bet; RACINGLINES_MAIL_DAILY_CAP=200; RACINGLINES_TURNSTILE_SITEKEY and RACINGLINES_TURNSTILE_SECRET (empty = widget off); RACINGLINES_OPS_NTFY_TOPIC (ops alerts, separate from RACINGLINES_NTFY_TOPIC for market alerts); RACINGLINES_HEALTHCHECK_PING_URL (dead-man ping). Existing: RACINGLINES_URL=https://racinglines.bet (base for mail links); RACINGLINES_GCS_BUCKET; APP_SECRET (must be set); MAX_STAKE (per-bet cap, F$100); RACINGLINES_KALSHI_SPRINTS; RACINGLINES_CANCELLED_RACE_RULES (not changed by fantasy); RACINGLINES_DEMO_USERS; RACINGLINES_DEMO_CONTEXT. Never touched: POLYMARKET_TRADING_ENABLED, KALSHI_TRADING_ENABLED.

COOKIES: rl_session = uid|expires|sid|epoch|HMAC (epoch = users.session_epoch; bumping it ends every session). rl_csrf = signed double-submit token for unauthenticated forms.

ROUTES
Public (add to PUBLIC_PATHS): /signup, /verify/{token}, /verify/resend, /password/forgot, /password/reset/{token}, /terms, /privacy, /rules, /healthz.
Signed in: /account (GET/POST), /account/delete (POST), /fantasy, /fantasy/markets, /fantasy/orders (POST), /fantasy/book, /book/markets/{id}/take (existing POST), /leaderboard, POST /logout (GET /logout shows a confirm form).
Admin: /admin/fantasy, /admin/fantasy/seasons/{id}, /admin/fantasy/invites, /admin/fantasy/members/{user_id}, /admin/fantasy/settle.

CLI: racinglines fantasy season create|set|close|list; racinglines fantasy invite create|revoke|list; racinglines fantasy tick [--full]; racinglines fantasy stats [--full]; racinglines mail test --to <addr>; racinglines ops health [--alert]; racinglines ops backup [--label <task>].

CODE: racinglines/fantasy/{seasons,ledger,book,exchange,settle,stats}.py; racinglines/markets/books.py (read-only live order books; does not import polymarket/trade.py); racinglines/web/{accounts,mailer,health}.py; racinglines/ops/{health,backup}.py; racinglines/cli/{fantasy,ops,mail}.py; TERMS_VERSION = '2026-10-08' in racinglines/web/accounts.py. Templates: signup, verify, forgot, reset, account, terms, privacy, rules, fantasy, fantasy_markets, fantasy_book, leaderboard, admin_fantasy (.html); mail/verify.txt, mail/reset.txt, mail/welcome.txt, mail/email_changed.txt. Tests: tests/test_auth.py, test_signup.py, test_mailer.py, test_fantasy_schema.py, test_fantasy_seasons.py, test_ledger.py, test_private_book.py, test_fantasy_book.py, test_fantasy_exchange.py, test_fantasy_settle.py, test_fantasy_stats.py, test_health.py, test_ops_health.py, test_ops_backup.py; fixtures in tests/fixtures/fantasy/.

activity_log actions (new): signup, signup_rejected, email_verify, verify_resend, password_reset_request, password_reset, password_change, email_change, account_delete, role_override, bankroll_adjust, member_suspend, invite_create, invite_revoke, season_update, fantasy_order, fantasy_order_rejected, fantasy_settle, fantasy_resettle, mail_sent, mail_failed.

SYSTEMD (deploy/vm/systemd/): racinglines-health.service + .timer (every 5 min); racinglines-backup.service + .timer (daily 10:00 UTC); racinglines-kalshi-sync.service + .timer (every 30 min, daily closed sync; this is U2); racinglines-fantasy.service + .timer (every 10 min: close, settle, stats). Existing and unchanged in name: racinglines-web, racinglines-recorder, racinglines-signals(.timer), racinglines-live-f1@<event>(.timer), racinglines-live-dh@, racinglines-mcp, cloudflared. GCE: snapshot resource policy racinglines-daily (14-day retention) on disk racinglines-vm.

BACKUPS: pre-change data/backups/db/racinglines-before-<task>-<UTC>.sql.gz (CLAUDE.md); nightly data/backups/db/racinglines-nightly-<UTC>.sql.gz (7 kept on disk) and gs://$RACINGLINES_GCS_BUCKET/db/nightly/ (35-day lifecycle); owner-run logs /opt/racinglines/data/backups/<name>-<UTC>.log.

EMAIL (Proton Mail Plus, 10-address cap): admin@racinglines.bet (owner mailbox), support@racinglines.bet (catch-all target and reply-to), noreply@racinglines.bet (app sender, holds the SMTP token). DMARC reports go to the rua address from Cloudflare DMARC Management.
```

---

## What this doesn't cover

- How players trade: fills, fees, closing times, private-book collateral, settlement and the settle queue. See
  [Fantasy trading](fantasy-trading.md).
- VM monitoring, backups, the `vm.sh --migrate` guard (OPS-8), `restore_scratch.sh` (OPS-4) and the incident
  runbooks. See [VM reliability](vm-reliability.md).
- Proton Mail, DNS, the SMTP token and how the mailer works inside. See [Email setup](email-setup.md).
- The calendar, the decisions table, the go/no-go checklist, and the STAGE-1 and launch-day blocks. See
  the [runbook](fantasy-runbook.md).
- Prizes, payments, identity checks and geo-blocking. None are offered (DEC-1, DEC-22). Nothing here is legal
  advice.
- Two-factor sign-in for players (the admin gets a second factor from Cloudflare Access, §7 row 16), passkeys,
  social sign-in, handle changes, public profiles, a self-service data export, a join page for later seasons, a
  public leaderboard, and any mail beyond the four templates.

## Open items

1. **Email enumeration at sign-up.** "That email already has an account" reveals which addresses are registered.
   That is accepted for the invite-only launch (limited to 5 per hour per IP). The alternative, which reveals
   nothing, needs a fifth mail template. Decide before open sign-up (Thu 22 Oct at the earliest).
2. **A throttle kept in the database.** The login throttle lives in memory and resets on every deploy. Sign-up,
   resend and forgot limits are already counted in the database. The login throttle could move there too after the
   soft launch.
3. **Anyone can lock a player's handle.** The per-username lock (10 failures in 15 minutes) lets anyone lock a
   player handle for 15 minutes. Accepted for the soft launch. Staff handles, the admin's included, are locked per
   (username, IP) instead, and `/admin` sits behind Cloudflare Access before sign-up opens (§7 rows 7 and 16).
4. **Public leaderboard later.** DEC-7 (data terms) and DEC-13 keep boards login-only for now.
5. **SEC-1 scope.** `tests/test_mcp.py:218` and `:249` create users with password `"pw"`, which the new policy in
   `create_user` refuses. Recommendation: add `tests/test_mcp.py` to SEC-1's scope and use passwords of 10 or more
   characters. FABLE-1 decides; the worker doesn't bend the test.
6. **Files outside the plan's lists.** Adding `"fantasy"` to `GROUPS` in `racinglines/cli/__init__.py` (ACC-4); the
   prune step in `racinglines/cli/fantasy.py` (ADM-1); `docs/mcp.md` (STAT-2). If LEGAL-1 merges before ACC-3, it
   creates `racinglines/web/accounts.py` holding only `TERMS_VERSION`, and ACC-3 extends it.
7. **Admin F$ adjust ref differs from the trading doc.** [Fantasy trading](fantasy-trading.md) describes a later
   admin F$ adjust as having "no ref". This page gives it the `activity_log` row that holds the reason, which keeps
   it traceable and makes a double-submit harmless. The columns stay nullable, so both readings fit the schema. The
   DOC-1 review should pick one and align the two pages.
8. **The demo backfill assumes default usernames.** It assumes the VM runs the default `RACINGLINES_DEMO_USERS`.
   ACC-2's counts (2 demo, 1 system) confirm it on a copy of the VM's data.
9. **Unverified accounts** count toward the cap until they expire at 72 hours (§6). Whether they should count at
   all is for open sign-up to decide.
10. **Re-accepting the terms** when `TERMS_VERSION` changes isn't built. The terms must not change during 2026-s1
    unless that flow is added.
11. **12-hour sessions** mean players sign in about twice a day. A longer "remember me" is a later decision.
12. **Eligibility wording.** §10 reads DEC-13's "5 or more settled bets or fills" as settled book bets plus exchange
    fills for takers, and settled bets taken for makers. The owner should confirm this with batch B (Mon 5 Oct).
13. **One open season at a time** is enforced by an index. That suits 2026. Seasons that overlap would need the
    index dropped and a season picked explicitly at sign-up.
14. **Harder multi-account checks.** Email normalisation (§5) stops one Gmail inbox from making many accounts, but
    not a second mailbox. Disposable-domain blocking needs a list to maintain and is left out. The maker-taker pair
    report (over 50% of volume, the same IP) is in [Fantasy trading](fantasy-trading.md); with no prizes (DEC-1)
    collusion only bends the board, and `/rules` says it voids results. Revisit if prizes are ever considered.
15. **A database-level guard on `activity_log`.** The app uses one database role, so revoking UPDATE and DELETE on
    `activity_log` would also block the 90-day prune. A trigger that allows only the prune's column changes would
    work; it would be a second migration, so it is left for after the soft launch. Until then the guard is the app:
    the explorer's read-only list and the write toggle refused while sign-up is on (§11).
16. **Cross-doc follow-ups for DOC-1:** the backup rules in §12 go into [VM reliability](vm-reliability.md)
    (OPS-3, OPS-4); the reserved share of the daily cap goes into [Email setup](email-setup.md); the three new
    go/no-go lines (§14) are lines 20, 22 and 23 in the [runbook](fantasy-runbook.md#go-no-go).
17. **Owner placeholders still open:** DEC-4 (the end date), DEC-5 (amounts), DEC-16 (Turnstile yes or no), DEC-22
    (terms wording and the export response time), DEC-7 (the attribution text).
