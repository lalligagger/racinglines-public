# Fantasy soft launch: sprint roadmap (29 Sep - 11 Oct 2026)

racinglines already prices F1 races, paper-trades them on Kalshi and Polymarket, and ran a live private book at
Whistler against a simulated crowd. The owner asked for a sprint through next weekend: a soft launch of fantasy
trading across every supported market, with players signing up as makers or takers and keeping that role for the
first fantasy season. That needs unique logins, per-user stats in the database, and a VM that stays up and fresh.
This page is the index: the verdict, the phases, the owner's dates and the decisions, with links. The detail
pages below are the reference.

**Status:** draft for the owner, Tue 2026-09-29; checked again Wed 2026-09-30 evening. **Built:** PR #71 (deploys
pause the timers, merged), the VM cutover (racinglines.bet runs on the GCE VM, `n2-standard-2`, which the owner keeps),
and the data the launch shows (F1, plus NASCAR and MotoGP status and demo rows on Markets). **Not built:** sign-up,
mail, the fantasy tables, the health, backup and Kalshi sync timers, and the staging host. Copilot builds SEC-1,
MAIL-1, ACC-1 and ACC-3 locally on Fri 2 – Sat 3 Oct, behind `RACINGLINES_SIGNUP=off`. **CI and a staging host
(STG-1 to STG-4, [Roadmap](todo.md#priorities)) are now the top open item**: STAGE-1 below rehearses on that host
once it exists, instead of on production with the dry-run season. Every decision is open until the owner signs it.

| Page | What it holds |
|---|---|
| [Fantasy launch runbook](fantasy-runbook.md) | The day-by-day calendar, every task with its role, model and money flag, the merge sequence, the full decision table, the staging rehearsal, the go/no-go checklist, the launch, off-switch and rollback blocks, risks, the report outline |
| [Fantasy accounts](fantasy-accounts.md) | Sign-up, email verification, sessions, seasons and the role lock, the F$ ledger, stats and leaderboards, admin tooling, privacy, and the `fantasy_schema_v1` migration |
| [Fantasy trading](fantasy-trading.md) | Exchange paper trades for takers, the private book with human makers and takers, settlement, anti-abuse |
| [VM reliability](vm-reliability.md) | Targets, monitoring and alerts, data freshness, backups and restore, deploys after PR #71 and the deploy windows, capacity, incident runbooks |
| [Email setup](email-setup.md) | Proton Mail on racinglines.bet, every DNS record in Cloudflare, what (not) to do at Squarespace, and app mail through a Proton SMTP token |

---

## Summary

The full scope (open sign-up, every supported market, makers quoting on exchange markets, tape-only sports) cannot
ship safely by Singapore. What can ship is an **invite-gated F1 soft launch**. Go/no-go is Thu 8 Oct 12:00 PDT
(19:00 UTC) and sign-up opens **Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC)**, six and a half hours before the
Singapore book opens. Takers make exchange paper trades on Kalshi and Polymarket F1 markets at live venue prices,
and bet the in-app private book. Makers quote the private book only. The earliest safe date for open sign-up is
Thu 22 Oct. Makers on exchange markets and the tape-only sports come no earlier than R19. It is paper money (F$)
only: `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are never touched. If the go/no-go fails, R17
becomes closed dry run #2 and the soft launch moves to Thu 22 Oct; with the fantasy code first on production on
Tue 6 and Wed 7 Oct, that fallback is the expected outcome if the staging rehearsal finds a P0.

| | At the soft launch (Thu 8 Oct 18:00 PDT) | Later |
|---|---|---|
| Who can join | Invited players only: `RACINGLINES_SIGNUP=invite`, `RACINGLINES_SIGNUP_CAP=50` (DEC-2) | Open sign-up (`RACINGLINES_SIGNUP=open`) not before Thu 22 Oct, decided at the retro (OWNER-10) |
| Takers | Exchange paper trades on Kalshi F1 (R17 race kinds; sprint per DEC-12) and Kalshi/Polymarket F1 season futures; bets on the private book | Tape-only sports and OG.com (NEXT-2), R19 or later |
| Makers | Quote the private book only (DEC-6) | Exchange markets (NEXT-1), R19 or later |
| Sports | F1 only | NASCAR, MotoGP, IndyCar stay tape-only this sprint; downhill has no event until 2027 |
| Money | F$ only: takers F$1,000, makers F$10,000, F$100 per bet or order (DEC-5, recommended); no prizes, no fees (DEC-1) | Any prize is a new decision taken with counsel |
| Season | `2026-s1`, trading from R17, `ends_at` left NULL (TBD) until the owner sets it (DEC-4) | Recommended end once the 2026 championship markets resolve (7-8 Dec) |
| Public surface | https://racinglines.bet through the Cloudflare tunnel only; `vm.sh public on` is never run (DEC-8) | Same |
| Off switch | `RACINGLINES_SIGNUP=off` plus `RACINGLINES_FANTASY=0`: sign-up closes and the pages hide, while the fantasy tick keeps settling open positions (it gates on season status) | Same |
| Fallback | R17 = closed dry run #2 with 25 or fewer invited testers; soft launch Thu 22 Oct (DEC-23) | |

The market-by-market scope (which Kalshi, Polymarket, OG.com and private-book markets are tradable, by whom) is in
[Fantasy trading](fantasy-trading.md). The final list is signed with DEC-20 on Wed 7 Oct.

## Assumptions

- **Sprint window:** Tue 29 Sep to Sun 11 Oct 2026 (13 days), plus Mon 12 Oct for the retro and report.
  "Next weekend" means **F1 R17, Singapore** (sprint format), 9-11 Oct. R16 (2-4 Oct, the Bahrain GP run at
  Sepang) is this weekend and serves as a closed reliability dry run.
- **No live-event freeze.** PR #71 (branch `work/deploy-pause`, pending the owner's merge) makes `vm.sh deploy`
  pause the VM's timers, deploy, run a catch-up step and resume them. A failed deploy is recorded in
  `/var/lib/racinglines/deploy-paused` and resumed by the next deploy. There is no `--force`. Deploys may run
  during R16 and R17; between sessions is kindest, because the web app restarts for a few seconds. The same PR
  rewrites the freeze text in `CLAUDE.md` and [VM deploy](vm-deploy.md). Merging it is the first owner step
  (OWNER-1).
- **The owner runs every VM write and every merge.** Claude sessions produce branches, worker footers and
  paste-ready, environment-labelled blocks that tee to logs. Running `vm.sh public on` and any DB migration
  against the VM need the owner's explicit sign-off in the same turn.
- **"Fantasy" means paper money only** (F$, no cash value).
- **Times** are PDT with UTC in brackets. systemd `OnCalendar` values are UTC.
- **The VM cutover happens Wed 30 Sep**, as planned in [VM deploy](vm-deploy.md#cutover). If it slips, the P1 ops
  items move with it, and the R16 dry run runs on whichever host serves racinglines.bet.
- **Kalshi listing lead time:** Kalshi listed R16 about 5.4 days out, so R17 is expected about Mon 5 - Tue 6 Oct.
  If it has not listed by Thu 8 Oct, the exchange side of the launch is F1 season futures only.
- **Audience:** 50 or fewer invited players, F1 only.
- **Email:** Proton Mail Plus (1 domain, 10 addresses) is enough. Cloudflare stays the authoritative DNS
  (`kipp.ns.cloudflare.com`, `zara.ns.cloudflare.com`); Squarespace stays the registrar only.
- **Alembic head** is `c8e3f6a2d4b1` on 29 Sep. ACC-1 re-checks `alembic heads` when it branches.
- **"More info coming":** the market details arrive by Wed 7 Oct 12:00 PDT. Until then workers build to the
  recommended decisions, and anything undecided stays switched off.
- PR #66 (`docs/engine-roadmap.md`) is unrelated to this sprint.

## Phases

| Phase | Dates | Goal | Owner steps | Exit criterion | Detail |
|---|---|---|---|---|---|
| P0 Unblock, decide, cut over | Tue 29 - Wed 30 Sep | PR #71 merged, build-scope decisions signed, VM cutover with the public port closed, the sprint docs merged | OWNER-1 PR #71 by Wed 12:00 PDT; OWNER-4 cutover; OWNER-2 batch A by Wed 18:00 PDT | `vm.sh status` shows PR #71's sha; `vm.sh public off`; batch A signed | [Runbook P0](fantasy-runbook.md#p0-unblock-decide-cut-over-tue-29-sep-wed-30-sep) |
| P1 Reliability build, R16 closed dry run | Tue 29 Sep - Sun 4 Oct | Health, backup and Kalshi sync timers, snapshots and ops alerts on before the R16 book; features built on branches behind switches | LEGAL-2a and the early decisions Thu 1 Oct; ops batch deployed by Thu 12:00 PDT; OPS-7 hardening; DRY-1 with 5 or fewer staff testers; OWNER-3 Proton in the R16 weekend | Timers active and a test alert on the phone before Thu 20:30 PDT; the R16 incident log | [Runbook P1](fantasy-runbook.md#p1-reliability-build-and-r16-closed-dry-run-tue-29-sep-sun-4-oct), [VM reliability](vm-reliability.md) |
| P2 Schema, features, rehearsal | Mon 5 - Wed 7 Oct | OPS-6 and OPS-8 Monday; `fantasy_schema_v1` on the VM Tue 09:00 PDT; accounts batch Tue, trading batch Wed, each after a Fable read; two-part staging rehearsal; R16 settlement replay | OWNER-5 R16 routine; batch B; OWNER-8 migration with sign-off; MAIL-2; LEGAL-2; batch C; STAGE-1 parts A and B | Every P2 PR merged with switches off, golden diff empty, rehearsal and replay passed | [Runbook P2](fantasy-runbook.md#p2-schema-on-the-vm-fantasy-features-staging-rehearsal-mon-5-oct-wed-7-oct), [Fantasy accounts](fantasy-accounts.md), [Fantasy trading](fantasy-trading.md) |
| P3 Go/no-go and soft launch | Thu 8 Oct | Decide on evidence at 12:00 PDT; open invite-gated sign-up at 18:00 PDT | GO-1 sign-off; LAUNCH-1 (~45 min) | Every go/no-go line signed; the first invited player verified and granted F$ | [Go / no-go](fantasy-runbook.md#go-no-go), [Launch day](fantasy-runbook.md#launch-day) |
| P4 Singapore weekend | Fri 9 - Sun 11 Oct | On call, deploys only in the windows, every position settled by Sunday evening | OPS-10 on call and the support@ inbox; SETTLE-2 Sun from ~08:00 PDT | No outage over 15 min; everything settled or queued with a reason by Sun 18:00 PDT | [Runbook P4](fantasy-runbook.md#p4-singapore-soft-launch-weekend-f1-r17-fri-9-oct-sun-11-oct), [deploy windows](vm-reliability.md#deploy-windows) |
| P5 Retro and report | Mon 12 Oct, then to Thu 22 Oct | The soft-launch report at the project's bar; the open sign-up call | OWNER-10 retro decisions | `reports/2026-10-11-singapore-fantasy/report.md` with a verdict | [Runbook P5](fantasy-runbook.md#p5-retro-report-and-the-road-to-open-sign-up-mon-12-oct-follow-on-to-thu-22-oct) |

## The owner's dates

The full calendar, with race sessions and the build column, is in the [runbook](fantasy-runbook.md#calendar).

| When (PDT) | Owner step |
|---|---|
| Wed 30 Sep 12:00 | OWNER-1: merge and deploy PR #71; then OWNER-4 cutover |
| Wed 30 Sep 18:00 | Decision batch A |
| Thu 1 Oct 12:00 | LEGAL-2a (Kalshi and Polymarket data terms); DEC-18, DEC-19; the ops batch merged and deployed |
| Thu 1 Oct 18:00 | Early decisions DEC-1, 5, 7, 10, 11, 13, 14; OPS-7 hardening done; DRY-1 starts (testers created after a backup) |
| Fri 2 - Sun 4 Oct | OWNER-3 Proton Mail and DNS (steps in [Email setup](email-setup.md)); on call for R16 |
| Mon 5 Oct | OWNER-5 R16 routine; DEC-17 by 12:00 and resize if yes; Proton green by 12:00; OPS-6 + OPS-8 deployed; batch B by 18:00 |
| Tue 6 Oct 09:00 | OWNER-8 `fantasy_schema_v1` on the VM, with sign-off; then SEC-1 + MAIL-1, MAIL-2, LEGAL-2 by 12:00, the accounts batch by 16:00 |
| Tue 6 Oct 18:00 | STAGE-1 part A (accounts, mail, the role lock) |
| Wed 7 Oct 12:00 | Batch C; OWNER-9 R17 listings; the trading batch by 16:00; REPLAY-1 on the Mac |
| Wed 7 Oct 17:00 | STAGE-1 part B (book, exchange, settlement, admin) |
| Thu 8 Oct 12:00 | GO-1 go/no-go |
| Thu 8 Oct 18:00 | LAUNCH-1: sign-up opens (Fri 9 Oct 01:00 UTC); R17 live timer on before Fri 00:30 |
| Sun 11 Oct 08:00 | SETTLE-2; manual queue clear by 18:00 |
| Mon 12 Oct | OWNER-10 retro; REPORT-1 |

## Decisions

The full table (options, recommendation, reasons) is in the [runbook](fantasy-runbook.md#decisions). Until a
decision is signed, workers build to its recommendation behind a switch that is off. None of this is legal advice.

| ID | Question | Recommendation (short) | Needed by |
|---|---|---|---|
| DEC-1 | Prizes? | None: F$ with no cash value, no fees | Thu 1 Oct 18:00 |
| DEC-2 | Invite-only or open, and who tests R16? | Invite codes, cap 50; R16 5 or fewer staff testers | Wed 30 Sep 18:00 (A) |
| DEC-3 | App mail provider? | Proton SMTP now, a transactional provider before open sign-up if needed | Wed 30 Sep 18:00 (A) |
| DEC-4 | Season `2026-s1` dates? | From the soft launch; `ends_at` TBD, recommended after the championship markets resolve | Wed 7 Oct 12:00 (C) |
| DEC-5 | Bankrolls and limits? | Takers F$1,000, makers F$10,000, F$100 per bet or order, F$1,000 per maker market | Thu 1 Oct 18:00 |
| DEC-6 | Makers on exchange markets at launch? | No; private book only; NEXT-1 from R19 | Wed 30 Sep 18:00 (A) |
| DEC-7 | May players see venue prices? | Signed-in only, attributed; drop a venue whose terms forbid it | Thu 1 Oct 18:00 |
| DEC-8 | `vm.sh public on`? | Never | Thu 8 Oct 12:00 (Go) |
| DEC-9 | Which private book? | The in-app DB book; the crowd stays with the demo | Wed 30 Sep 18:00 (A) |
| DEC-10 | Role meaning and lock? | Hard lock with a reasoned admin override; Lab, promotion and syncs staff-only | Thu 1 Oct 18:00 |
| DEC-11 | Settlement? | Hybrid: the tick from results and venue resolution, admin queue for the rest; runs while a season is open | Thu 1 Oct 18:00 |
| DEC-12 | R17 sprint markets? | Exchange takers only, if Kalshi lists them | Wed 7 Oct 12:00 (C) |
| DEC-13 | Scoring? | Separate maker and taker boards, login-only, handles only | Thu 1 Oct 18:00 |
| DEC-14 | In-play trading? | Closed at the start of the deciding session | Thu 1 Oct 18:00 |
| DEC-15 | Demo accounts after launch? | Keep, separated from players | Mon 5 Oct 18:00 (B) |
| DEC-16 | Bot protection? | Turnstile plus a Cloudflare rate-limiting rule | Mon 5 Oct 18:00 (B) |
| DEC-17 | Resize the VM? | e2-medium on Mon 5 Oct unless R16 memory stays under 60% | Mon 5 Oct 12:00 (B) |
| DEC-18 | Recovery targets? | RPO 24 h, RTO 4 h, 99% availability | Thu 1 Oct 12:00 (A) |
| DEC-19 | Backup bucket? | The new bucket in project racinglines | Thu 1 Oct 12:00 (A) |
| DEC-20 | Tradable markets? | Kalshi F1 R17 and season futures, Polymarket season futures, private-book F1 | Build scope Wed 30 Sep; final Wed 7 Oct 12:00 |
| DEC-21 | DMARC? | `p=none` to Cloudflare DMARC Management on Fri 2 Oct; `p=quarantine` once tests pass at two providers (target Tue 6 Oct, before STAGE-1, no later than the go/no-go); `p=reject` after the season | Wed 30 Sep 18:00 (A) |
| DEC-22 | Terms, privacy and age wording? | 18+ attestation, one account per person, deletion = anonymise | Tue 6 Oct 12:00 (LEGAL-2) |
| DEC-23 | Launch date and fallback? | Thu 8 Oct only if every go/no-go line is signed; else Thu 22 Oct | Thu 8 Oct 12:00 (Go) |

## Off switch

`RACINGLINES_SIGNUP=off`, `RACINGLINES_FANTASY=0`, `RACINGLINES_FANTASY_BOOK=0` and
`RACINGLINES_FANTASY_EXCHANGE=0`, then restart web: sign-up closes, the pages hide and new orders and bets are
refused within about 10 seconds, and nothing is deleted. `racinglines fantasy tick` ignores `RACINGLINES_FANTASY`
and runs while a fantasy season is open or has anything unsettled, so open positions keep settling and the health
check keeps watching the tick. Stopping the tick is a separate step, only when settlement itself is wrong. The
paste-ready blocks are in the [runbook](fantasy-runbook.md#off-switch).

## Names used across these docs

**Master copy.** The four detail docs repeat the subset they use, word for word; the runbook links here. Change a name here first.

```text
NAMES EVERY DOC USES EXACTLY (docs/fantasy-launch.md holds the master copy; the other docs repeat the subset they use, word for word)

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

REPORT: reports/2026-10-11-singapore-fantasy/report.md (+ img/), rendered with racinglines/reporting/markdown_html.render.
```

## What this doesn't cover

- **The implementation detail.** It lives in the pages listed at the top; this page sequences them.
- **Legal advice.** DEC-1, DEC-7 and DEC-22 are the owner's calls, with counsel if wanted.
- **Real money.** No deposits, withdrawals, prizes or fees, and no change to the trading flags or the order path.
- **The R16 and R17 live-test plans themselves** (tiers, the live book, the crowd, the demo taker): see
  [F1 live test](f1-live-roadmap.md) and the [weekend routine](todo.md#weekend-routine).
- **Tape-only sports, OG.com and exchange makers** beyond the NEXT-1 and NEXT-2 briefs in the runbook.
- **More than one VM,** a second tunnel connector, or a move to Cloud Run ([Google Cloud proposal](google-cloud.md)).
- **The engine roadmap** (PR #66), which is unrelated.
- **Work in flight in another thread (2026-09-29), not planned here:** the maker `/markets` calendar fix (PR #70,
  merged), the NASCAR data fetch on the VM (`racinglines nascar fetch`, 2017-2026) and its ingest, which comes next
  and needs its own `data_changes` entry. The fantasy work touches different code (auth, users, the private book,
  paper positions, new tables), but the VM is shared: check with the owner before a deploy lands during a long
  fetch or ingest.
- **The VM as of 29 Sep:** `vm.sh public on` was active (plain HTTP on :8000, with scanner traffic in the web log).
  Go/no-go line 5 ([runbook](fantasy-runbook.md#go-no-go)) requires `vm.sh public off` before any player signs up.
