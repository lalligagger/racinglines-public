# Live events

A race followed live in the web app's **Live** tab: official timing as it happens, the model re-run after
every update, a maker re-quoting every market, and takers trading against those quotes. The first run was
the **UCI Downhill World Cup final at Whistler, 27 September 2026**, as a demo experiment. The next test
is **Formula 1: the Bahrain GP at Sepang, Malaysia (2–4 October 2026)**; see below.

!!! note "A demo experiment"
    The timing is real. The quotes, the private book and its takers are simulated, with play money:
    nothing is traded anywhere.

| | |
|---|---|
| Code | The shared live core (`pipelines/live.py`, `markets/crowd.py`, `markets/quoting.py`) and the downhill adapter `racinglines/pipelines/live_dh.py`; the page is `/live` (`racinglines/web/views.py`, `templates/live.html` + `live_mtb_dh.html`) |
| Settings | `sports/mtb_dh.toml` `[live]`: cadence, market kinds, spreads, crowd size and budgets (`live_dh`'s constants read them) |
| Command | `racinglines mtb_dh live --slug 20260925_mtb --final 3 --quali 2,91 --conditions "clear, rutted"` |
| Updates | The engine polls the timing feed every 5 s (`--interval`); the page refreshes itself every 15 s |
| Tab | **Live** is in the nav for every signed-in user once an event has been recorded: a **green** dot while it runs (not over, updated in the last 6 hours), **grey** once it is over, when the page is a replay |
| Replay | After the final, `/live` shows the event as it stood at any saved snapshot (`?t=20260927T223221`, default the end): a timeline slider, step ◀ ▶, and play at 10× / 30× / 60× real time. Timing, rank probabilities, quotes, the win-probability chart and the private book (rebuilt from the crowd's fills up to that moment: `live_dh.book_at`) are all as they were then |

## How a live final is priced

Each poll reads the final's live JSON from UCI's timing provider (ChronoRace): who has finished and in what
time, who is on course with their latest split and position at that split, the start order of those still
to come, and DNF / DNS.

1. **Pace of riders still to start.** A blend of:
    - this weekend's **qualifying** (the best run; later sessions rescaled onto the first with the riders who
      ran both, since Whistler's Q2 ran about 2% slower than Q1): 60%;
    - the **season model's** pre-final view (its podium-probability rank mapped onto the field's qualifying
      times): 40%.

    Scaled by how the final is running against qualifying so far: the median ratio of clean runs (crashes and
    big mistakes, more than 12% off, are left out), shrunk toward a small prior.
2. **"Safe" riders.** Riders who were mathematically safe to qualify (the season model's make-the-final
   probability in the top quarter of the field, fading to none at the median) may have cruised. When their
   run came out slower than their season rank implies, the gap becomes **extra uncertainty** (a wider spread,
   capped), not a faster expected time. A fast run is genuine pace whoever sets it.
3. **Riders on course** are projected from their latest split with the split-to-finish ratio (from this
   final's finishers, else qualifying), with less noise the less track is left.
4. **Conditions** ("rutted", "wet") widen the spread and raise the crash / DNF risk.
5. **Monte Carlo.** 20,000 simulated finishes give each rider's probability of every top rank: 1st, 2nd, 3rd,
   top 3, top 5, top 10. Never a single predicted position.

## The maker's quotes

On every update the maker quotes YES on **"wins"** and **"on the podium"** for every rider:

- fair ± 3¢, **wider while the rider is on course** (+2¢) and just before they start (+1¢);
- **leaning against inventory**, and no more selling (or buying) once a market holds 2,500 shares either way;
- no quote once the outcome is certain, a rider is past the last split, or an inventory limit removes that side.

All remaining valid markets are re-priced and re-published on every poll through the final. When three riders
remain to start, the engine moves to 2-second polling and gives each simulated private taker a fresh late-window cap.
There is no global early close: a rider's market is pulled only when that specific market is no longer safe to price.

A long shot's YES often has no bid (it would be below 1¢), so the crowd can only buy it: the maker builds
large short positions in unlikely winners, up to the cap. That's a real risk of this setup; a surprise
winner would cost the full cap.

## The private book and its takers

- **1,000 anonymous private takers.** Each has an event budget of $10–200 (log-uniform; about $64,000 in
  total), fixed once and seeded. On every poll each quoted market is hit by each taker with a small
  probability, on a random side, for 20–80% of what the taker has left. They have **no accounts**: each is a
  UUID in the book file, so their results can be tracked (up, down, median, best, worst, and one random
  taker spotlighted) without identifying anyone.
- **The demo taker** (a tracked account) bought a dozen YES bets on the maker's quotes before the fast
  riders started, picked on hype (big names, home riders, fan favourites) from a one-time read of the start
  list and qualifying. 11 went through at $25 each.
- **P&L by venue.** The engine writes both demo accounts' private-book positions to `paper_positions` with
  `venue = 'private'` on every update, so the **Positions** page sorts P&L into **Polymarket (paper)** and
  **Private book**. The bankroll banner stays Polymarket-only, with the private book shown next to it.

## What each account sees

| | Maker | Taker |
|---|---|---|
| Timing | Leaderboard with gaps, riders on course and their position at each split, who's up next | The same |
| Model | Every rider's rank probabilities; a chart of the favourites' win probability through the final | None: prices only |
| Book | Its quotes (▲▼ since the last update), event P&L split between the crowd and the demo taker, crowd fills and volume, biggest positions, recent fills, the crowd's results | Its picks: price paid, price now, P&L, hype and why |
| At the end | A results card: winner, the demo taker's settled picks, the maker's event P&L, crowd volume | The winner and its settled picks |

Demo-only explanations are in `demo_context` info bubbles ([Web app](webapp.md)).

## Kept for replay

Everything is logged permanently under `data/runs/live/<slug>_<key>/`, so an event replayer can re-run or
re-score the final later:

| File | What |
|---|---|
| `raw/<ts>.json.gz` | Every raw timing-feed response, as received |
| `snaps/<ts>.json.gz` | Every full snapshot: riders, rank probabilities, quotes, P&L |
| `history.jsonl` | One line per poll: every market's fair value and quote |
| `meta.json`, `meta_<ts>.json` | The model inputs and parameters (qualifying on one scale, split ratios, season priors, conditions, crowd settings), each version kept |
| `book.json` | The private book: position and cash per market, the crowd's budgets, ids and positions, every poll's random seed |
| `crowd.jsonl` | Every crowd fill, per poll, with the taker's id, that poll's seed and (since 2026-09-28) its rate (`intensity`) |
| `picks.json` | The demo taker's picks |
| `book_superseded*.json`, `crowd_superseded*.jsonl` | Earlier crowd runs during the Whistler final, before the budget and id rules were set |
| `replay.json` | Only where needed: how polls ran when the run's own record doesn't say (below) |

**Replaying a run** (`venue_replay.PrivateBook.from_run`) re-draws every poll's crowd from its seed, quotes
and rate, and must give the recorded book exactly. Two things can stop it, and `replay.json` records them
without touching the record:

- **Rates not logged** (runs before 2026-09-28): the rate is re-derived with today's rule (poll interval / 5 s,
  x the late pace). If the rule changed during the run, `unscaled_until` (ISO) marks the polls that ran at 1
  whatever their interval; `intensity` {"<ts>#<n>": rate} sets single polls.
- **Two polls in the same second** (two loops overlapping after a restart): they share one snapshot file, so
  their quotes come from `history.jsonl`, the n-th line of that second for the n-th poll.

Whistler has both: the interval scaling arrived with the 22:37:58 restart (the 62 polls of 22:11–22:32 logged
20 s but ran at rate 1), and the old 5 s loop overlapped the new 2 s one until 22:39:06, twice in the same
second. With its `replay.json` the replay gives the recorded book fill for fill (7,703 fills,
`test_whistler_book_replays_as_a_backtest`). Since then the downhill loop takes the same lock F1's step takes
(`.lock` in the run folder, `fcntl.flock`, non-blocking): a second `live run` or `mtb_dh live` for the same
final says `another loop is polling this final (its lock is held); not started` and exits instead of polling
alongside the first. The OS drops the lock with the process, so a killed loop leaves nothing stale; a restart
still stops the old loop first, and now can't run two by accident (`test_run_folder_lock_stops_a_second_loop`).

## The live core: one engine, one adapter per sport

Everything around a sport's data stream is shared. Each sport adds an **adapter** for its stream and pricing.

| Layer | Where | Per sport |
|---|---|---|
| Settings | `sports/<code>.toml` `[live]` | Everything: adapter, cadence, market kinds, spreads, crowd, freeze and close |
| The book and the crowd | `markets/crowd.py` | Only the crowd's settings. Downhill trades per poll (`fills`), F1 in one batch per update (`window`: fills timed across the window, in order) |
| Quotes | `markets/quoting.py` | The half-spread (downhill widens on course; F1 tightens by stage) |
| Run folder, snapshots, replay, live / replay state | `pipelines/live.py` | Nothing |
| The event registry | `pipelines/live.py` `events()`: every run folder, its sport from `meta.json` | Nothing |
| The adapter | `pipelines/live_dh.py`, `pipelines/live_f1.py` | `markets`, `step`, `outcomes`, `view` |
| The Live tab | `templates/live.html` (status, replay bar, polling) over `live_<sport>.html` | The body partial |

- `live_dh.py` keeps every public name: its constants read `sports/mtb_dh.toml`, and the moved functions are imported back.
- `tests/test_live_core.py` pins downhill's numbers: quotes, crowd fills, book, P&L and the crowd's results, as a digest from before the split.
- Where the Whistler run folder is present (the data bucket), the same test re-derives its book from `crowd.jsonl` and checks six replay pages byte for byte.
- `/live` shows the most recently updated event; `/live?event=<run or event key>` shows any other.

## Running an event: `racinglines live`

One CLI for every sport. A **launch spec** (`live/<sport>/<event>.toml`, committed config) names the event, its
feed and any overrides of the sport's `[live]` settings.

| Command | What it does |
|---|---|
| `racinglines live new f1 2026-16` | Write a launch spec from the schedule, with the sport's defaults and the demo taker's hype picks |
| `racinglines live new mtb_dh <slug> --final 3 --quali 2,91` | The same for a downhill final (its feed arguments) |
| `racinglines live step <spec>` | One idempotent update. F1: acts only when an update is due and its stage run is in; downhill: one poll |
| `racinglines live run <spec>` | Step at the sport's cadence until the event is settled (F1: every 5 min; downhill: the poll loop, under the run folder's lock: one loop per final) |
| `racinglines live run <spec> --simulate --no-fetch` | F1: the whole weekend on a simulated clock (a rehearsal) |
| `racinglines live agent <spec> [--install / --remove]` | A macOS LaunchAgent for the spec (`bet.racinglines.live.<run>`): F1 steps every 5 minutes; a lock stops overlapping steps; log in the run folder |
| `racinglines live status` | Every event: live / replay / settled, last update, next update, lateness |
| `racinglines live reprice <spec> [--every n] [--label x]` | Downhill: re-price every logged raw feed response with today's code and the final's recorded inputs (`meta.json`), no network; writes `reprice/<label>.jsonl` and scores it against what was quoted live |
| `racinglines live settle <spec>` | Record the event in the database (`live_events`: dates, the book's P&L, the crowd's totals), so the demo accounts' story and the web app don't need the run folder. Idempotent |
| `racinglines live report <spec> [--pdf]` | The event report in the run folder's `report/`: the book's P&L by update, the crowd, the demo taker's picks, and the fair-price scorecard (Brier score and log loss per market kind at each update; the biggest moves). Markdown, HTML, SVG charts, and a PDF through headless Chrome |

`racinglines mtb_dh live …` still works as before. `step` options: `--now` (a simulated UTC time), `--no-fetch`,
`--no-sync` (don't write positions), `--no-alert`, `--unfreeze`.

## Formula 1: a weekend's private book

`pipelines/live_f1.py`, settings in `sports/f1.toml` `[live]`. The plan and its decisions: [F1 live test](f1-live-roadmap.md).

| | |
|---|---|
| Updates | Pre-weekend (the book opens), after each session (FP1, FP2, FP3; sprint weekends SQ and Sprint; Quali), lights out (the book closes), results (everything settles) |
| Pricing | The demo maker's profile C (`gbm`): the stage run the signal engine also uses (`signals.price_stages_now`, reused when stored) |
| Markets | Winner, podium, pole (22 each), head-to-head (the last listed race's pairs), top constructor (11): 99 for round 16 |
| Quotes | Fair ± 3¢ pre-weekend, 2.5¢ after FP1 and FP2, 2¢ after FP3 and qualifying; leaning against inventory; 2,500 shares per market; frozen as posted after qualifying (pole markets unquoted: decided); none after lights out. Optional, off by default: a per-market loss cap (`max_loss`, $) and a 1¢ floor bid on long shots (`floor_bid`) |
| Crowd | The same 1,000 takers; one batch per update for the window since the last one, at 0.0006 hits per taker, per market, per hour, timed across the window; the pre-race window at 3× with fresh $100 caps |
| Settlement | Pole from the qualifying classification at the after-Quali update; everything else from the race classification (`private_book.outcome_for`) |
| Late data | An update waits for its stage run; one more than 2 hours late sends an alert. Missed updates merge into the next |
| Files | `data/runs/live/<event>/`: as above, plus `state.json` (the engine's state) |

## Adding a sport

1. A `[live]` section in `sports/<code>.toml`: `adapter`, `poll` (cadence, `stale_h`), `markets.kinds`, `quoting`, `crowd`.
2. An adapter module with `markets`, `step(spec, now, echo, **kw)`, `outcomes` and `view(run, snap, picks, hist, mode, maker)`. Its snapshots carry `done` (and `next_at` if updates are far apart); it writes them through `pipelines/live.py`, and its book through `markets/crowd.py`.
3. A body partial, `templates/live_<code>.html`, rendered with the adapter's `view()` output.
4. A launch spec, `live/<code>/<event>.toml`.

Nothing in the core, the book, the crowd or the Live tab's shell changes. `tests/test_live_toy.py` proves it with a
synthetic third sport (`tests/live_toy.py`: a toy sprint with its own schema, spec and body partial), run through
the CLI's locked step, the registry, the replay and the Live tab.

Launch specs committed so far: `live/f1/2026-16.toml` (round 16), `live/f1/2026-17.toml` (Singapore, the sprint
weekend), `live/f1/2026-18.toml` … `2026-23.toml` (Austin, Mexico City, São Paulo, Las Vegas, Qatar, Abu Dhabi: all
conventional weekends per the saved FastF1 schedule, used only where no venue lists the race; Las Vegas's Saturday-night
cut-offs are noted in its spec), `live/f1/2026-15.toml` and `2026-12.toml` (the Baku and Dutch GP rehearsals),
`live/mtb_dh/20260925_mtb.toml` (Whistler as it was run; over, so `step` leaves it alone). No downhill event
after Whistler is in the data: it was the World Cup final.

## First F1 test: round 16

**The Bahrain GP at Sepang, Malaysia (2–4 October 2026)**, launch spec `live/f1/2026-16.toml`. Polymarket hasn't
listed it, so it's a mock private book like Whistler's: 99 of Polymarket's usual race markets, priced from the
model's stage runs, updated at session ends, with the same crowd and demo taker. Plan and status:
[F1 live test](f1-live-roadmap.md); priorities: the [Roadmap](todo.md#priorities).
