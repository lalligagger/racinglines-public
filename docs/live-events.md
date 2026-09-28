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
| Code | `racinglines/pipelines/live_dh.py`; the page is `/live` (`racinglines/web/views.py`, `templates/live*.html`) |
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
| `crowd.jsonl` | Every crowd fill, per poll, with the taker's id and that poll's seed |
| `picks.json` | The demo taker's picks |
| `book_superseded*.json`, `crowd_superseded*.jsonl` | Earlier crowd runs during the Whistler final, before the budget and id rules were set |

## Next: Formula 1

First test: **round 16, the Bahrain GP at Sepang, Malaysia (2–4 October 2026)**. Polymarket hasn't
listed it, so it's a mock private book like Whistler's:
- all 100 of Polymarket's usual race markets, priced from the model's stage runs;
- updated at session ends, not from a live feed;
- the same crowd and demo taker.

It's built as a shared live core (book, crowd, quoting, replay, the tab's shell) plus an F1 adapter, so each
sport keeps its own data stream. Plan and status: [F1 live test](f1-live-roadmap.md); priorities: the
[Roadmap](todo.md#priorities).
