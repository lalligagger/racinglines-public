# Demo: the pipeline in four steps

The `--demo` flag runs the whole pipeline end to end on a synthetic sport, in the terminal, with no database, network
or account: a Mario Kart season. Every driver's pace, every item and every bet is made up
(`racinglines/demo/kart.toml`); it is play money and nothing is traded anywhere. Each step is the miniature of a real
one, with the same shared code where it exists: the live race uses the private book's quoting and crowd
(`markets/quoting.py`, `markets/crowd.py`) and writes the run folder `racinglines live report` reads, as the Whistler
downhill final did ([Live events](live-events.md)).

```
# LOCAL (Mac), or any machine with the package and requirements.txt installed (model ... --demo: with the CLI tree's
# task groups, option A, owner 2026-10-11; the tour's code is racinglines/demo/tour.py)
racinglines model backtest --demo
racinglines model forecast --demo
racinglines live run --demo --pdf
racinglines book price --demo
```

| Step | Command | What it does | The real pipeline's version |
|---|---|---|---|
| 1 | `model backtest --demo` | Builds five seasons of history (four tracks a season, 20 races), then fits each driver's pace and sweeps the fit's settings walk-forward: every race after the first four priced before the start by Monte Carlo (2,500 runs) with each of 12 settings, scored by Brier score and log loss against an everyone-equal baseline. Prints the leaderboard and the fitted pace beside the hidden truth (a synthetic sport can show it). About 6 s, with a progress bar | `racinglines backtest walk-forward`, the sweeps ([F1 evaluation](f1-evaluation.md)) |
| 2 | `model forecast --demo` | The next race at Rainbow Road from the chosen setting: 400,000 simulated races, win / podium / top-5 probabilities and fair odds, with the Monte Carlo error. About 5 s, with a progress bar | `racinglines f1 forecast --save` ([F1 forecast](f1-forecast.md)) |
| 3 | `live run --demo` | The race live, sector by sector (3 laps x 6 sectors): the model re-prices the rest of the race (4,000 runs per update), **Wario**, the one bookie, re-quotes win and podium on every driver, and **100 Toads** (simulated anonymous takers, $10-200 each, a random side each time) trade against him. Ends with the podium, Wario's settled P&L, the Toads' results and the event report (Markdown, HTML, and a PDF with `--pdf`) | `racinglines live run`, `racinglines live report` ([Live events](live-events.md)) |
| 4 | `book price --demo` | Sportsbook lines and slips against the model and the exchanges: EV against each, side by side | `racinglines book price` ([Sportsbook slips](sportsbook/slips.md)) |

**The race model.** Each sector every driver takes the track's sector time, minus their pace, plus noise, plus the
items: a mushroom boost (likelier the further back), a banana, a red shell (anyone but the leader), a blue shell (the
leader). The true pace drifts a little from season to season, so the backtest's sweep has something to find (how much
to weight recent races, how far to shrink toward an average kart). The fit uses the clean sectors only (the feed
says where an item hit) and the simulation adds the items back.

**Why Wario wins.** The Toads bet at random, with no view of their own, so the book's edge is its spread (2 cents
each side of fair, leaning against inventory), kept centred by the model. A crowd with an edge would be a different
demo.

**Options.** `--seed N` (default 7) makes the history, the race and every fill repeat exactly; `--track` picks the
forecast and race track (`rainbow-road`, `bowsers-castle`, `mario-circuit`, `moo-moo-meadows`); `--out DIR` (default
`data/demo/kart`) holds `model.json`, `forecast.json` and the race's run folder (`runs/live/kart-<track>-<seed>/`,
with `report/`); `--sims` sets the Monte Carlo runs; `--delay S` the pause between race updates on screen (0.6 s).
Rich draws every step (`pip install -r requirements.txt`).

**Checks.** `python -m pytest tests/test_demo_kart.py` runs all three tour steps on small settings (seconds, no database).
