# Eneco Tour 2026: report helpers (2026-10-13)

For the Eneco Tour paper-picks report. Book names stay out of this folder.

- `prologue_noise_backtest.py` -> `prologue_noise_backtest.csv`: walk-forward of the ITT model (fit on all TTs before
  each month) scored on TTs since 2023. On the 17 TTs of 15 km or less, noise_scale 2.0 scored best (win_ll 3.302,
  pair_ll 0.624) against 0.657 at the ITT default 1.15 (a coin flip is 0.693). On the 29 longer TTs, 1.15 stays best
  (pair_ll 0.546). A model fit only on short TTs scored pair_ll 0.702, worse than a coin, so it is not used. This is
  [model.gc] short_tt_noise_scale.
- `joint_all.py <data dir> <gc-price out dir> <prologue event>`: one joint quarter-Kelly sizing on $1,000 over the
  prologue (winner, h2h) and GC (winner, matchups) books. It reads `gc_sims.npz` from `gc-price`, settling the
  prologue bets on the simulated prologue stage (stage_0) and the GC bets on the simulated GC, so the correlation is
  the model's own. Candidates have model EV of 5% or more. Writes all_lines.csv, picks.csv, summary.json and pnl.npy.
- `diagram.py out.svg` -> `diagram.svg`: the data and model diagram (grey existing, blue new today, red missing).

Timeline (the owner's screenshots were sent within a minute of capture, 15:15:12Z and 15:17:29Z):
- Overall and stage matchup boards showed "Starts in 46:48 / 46:26 / 46:19". The winner boards show 10/13/2026
  9:00 AM, which is 16:00Z if the book shows PDT (inferred). So betting closed at about 16:00-16:02Z.
- 15:20:59Z: prologue picks with joint quarter-Kelly stakes posted, about 39-41 min before the close.
- 15:30:55Z: the same picks reposted for placing ("place asap" 15:27:32Z).
- 15:44:30Z: the owner chose not to place in this window; the picks become paper picks.
- The GC model was not ready before the close; GC prices are paper only.
