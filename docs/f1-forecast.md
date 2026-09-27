# F1 forecast

Current forecast: 2026 season, rounds 16–23.

Model run **3** (`kind='forecast'`, 2026-09-27), cutoff 2026-09-27 18:42 UTC, with
data through the Azerbaijan Grand Prix (round 15, 26 Sep). Default model
settings (no variant), 10,000 simulated seasons. How accurate the model has been:
[F1 evaluation](f1-evaluation.md). The model itself: [F1 model](f1.md).

!!! note "Pre-weekend odds"
    No session of the next race has run yet, so every race below is priced
    before practice, the least sharp stage. In the backtest, win odds at this
    stage are too flat: favourites win more often than priced (see
    [calibration](f1-evaluation.md#calibration)). Re-run the forecast after
    each session.

## Next race: Bahrain Grand Prix (round 16, 4 Oct)

| Driver | Team | Win | Podium | Top 10 | Pole | DNF |
|---|---|---|---|---|---|---|
| George Russell | Mercedes | 13.4% | 35.4% | 78.4% | 11.3% | 9.6% |
| Kimi Antonelli | Mercedes | 11.9% | 32.1% | 76.3% | 8.7% | 9.2% |
| Charles Leclerc | Ferrari | 11.1% | 29.6% | 72.7% | 9.3% | 13.2% |
| Lando Norris | McLaren | 10.8% | 29.5% | 71.7% | 9.5% | 14.4% |
| Max Verstappen | Red Bull | 9.9% | 28.5% | 71.1% | 9.0% | 13.4% |
| Oscar Piastri | McLaren | 9.6% | 27.0% | 70.5% | 8.9% | 14.1% |
| Lewis Hamilton | Ferrari | 9.0% | 26.5% | 69.5% | 8.2% | 13.7% |
| Isack Hadjar | Red Bull | 6.8% | 21.9% | 66.0% | 6.5% | 12.4% |

Top-scoring constructor: Mercedes 26.0%, McLaren 20.5%, Ferrari 20.3%, Red Bull
17.1%.

## Remaining races

| Round | Grand Prix | Date | Favourite (win) | Next two |
|---|---|---|---|---|
| 16 | Bahrain | 4 Oct | Russell 13.4% | Antonelli 11.9%, Leclerc 11.1% |
| 17 | Singapore (sprint) | 11 Oct | Russell 14.0% | Antonelli 11.6%, Norris 11.0% |
| 18 | United States | 25 Oct | Verstappen 13.7% | Norris 12.0%, Leclerc 12.0% |
| 19 | Mexico City | 1 Nov | Russell 14.2% | Antonelli 11.8%, Norris 11.5% |
| 20 | São Paulo | 8 Nov | Russell 14.4% | Antonelli 11.4%, Norris 10.9% |
| 21 | Las Vegas | 21 Nov | Russell 13.2% | Verstappen 11.8%, Leclerc 11.4% |
| 22 | Qatar | 29 Nov | Russell 13.9% | Antonelli 11.9%, Leclerc 11.1% |
| 23 | Abu Dhabi | 6 Dec | Russell 14.2% | Antonelli 11.9%, Leclerc 10.8% |

Polymarket had not listed markets for rounds 16–17 as of 27 Sep 2026, so there
is nothing yet to compare these prices with.

## Drivers' championship

| Driver | Rank now | Pts now | Exp final pts | p10–p90 | Champion | Top 3 | Wins now | Exp wins |
|---|---|---|---|---|---|---|---|---|
| Kimi Antonelli | 1 | 302 | 380 | 347–414 | 96.2% | 100% | 8 | 8.9 |
| George Russell | 2 | 236 | 321 | 287–355 | 3.5% | 96.5% | 3 | 4.1 |
| Lewis Hamilton | 3 | 199 | 267 | 236–300 | 0.2% | 41.4% | 1 | 1.7 |
| Lando Norris | 4 | 186 | 260 | 227–294 | 0.1% | 32.8% | 2 | 2.9 |
| Charles Leclerc | 5 | 179 | 253 | 220–287 | 0.04% | 19.6% | 1 | 1.9 |
| Max Verstappen | 6 | 163 | 235 | 203–269 | 0% | 9.5% | 0 | 0.8 |
| Oscar Piastri | 7 | 120 | 189 | 158–222 | 0% | 0.2% | 0 | 0.8 |
| Isack Hadjar | 8 | 86 | 146 | 116–177 | 0% | 0.01% | 0 | 0.6 |

- **Antonelli leads by 66 points** with 8 races and one sprint left; the only
  real threat is his teammate.
- Antonelli wins 9+ Grands Prix in 60.7% of simulations and 10+ in 23.2%.
  Norris (2 wins now) reaches 3+ in 59.6%.

## Constructors' championship

| Team | Rank now | Pts now | Exp final pts | Champion | Top 3 |
|---|---|---|---|---|---|
| Mercedes | 1 | 538 | 701 | 99.8% | 100% |
| Ferrari | 2 | 378 | 520 | 0.2% | 99.1% |
| McLaren | 3 | 306 | 449 | 0% | 81.3% |
| Red Bull Racing | 4 | 263 | 395 | 0% | 19.5% |
| Racing Bulls | 5 | 83 | 157 | 0% | 0% |
| Alpine | 6 | 68 | 130 | 0% | 0% |

The web app's Markets page, race pages and quotes use this run for live fair
prices; the Polymarket page compares them with the market
([Polymarket alignment](f1.md#polymarket-alignment)).

## How to refresh it

After each session: fetch, ingest and re-run.

```
racinglines f1 fetch --years 2026
racinglines f1 ingest --years 2026
racinglines f1 forecast --year 2026 --save     # live: cutoff = now; remaining races + championships
```

A saved forecast becomes the one the web app uses. `racinglines f1 pm-sync` (or
the **Refresh** button on `/markets/polymarket`) picks up new Polymarket markets
once they are listed.
