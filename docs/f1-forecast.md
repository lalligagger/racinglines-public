# F1 forecast

Current forecast: 2026 season, rounds 18–23. **Updated 2026-10-14** from the run production serves.

Model run **9929** (`kind='forecast'`, saved 2026-10-11 21:43 UTC on code `2b7b410`), cutoff 2026-10-11 21:43 UTC,
with data through the Singapore Grand Prix (round 17, 11 Oct). Default model settings, 10,000 simulated seasons.
How accurate the model has been: [F1 evaluation](f1-evaluation.md). The model itself: [F1 model](f1.md). The
numbers below are what `get_forecast(competition="f1_wdc")` on the MCP server returned on 2026-10-14; the web app's
Markets page and the race pages read the same run, and the per-weekend live prices (stage runs 9952 to 9954 for
rounds 18 to 20, re-run on the VM 2026-10-13) sit on top of it.

!!! note "Pre-weekend odds"
    No session of the next race has run yet, so every race below is priced
    before practice, the least sharp stage. In the backtest, win odds at this
    stage are too flat: favourites win more often than priced (see
    [calibration](f1-evaluation.md#calibration)). The signal engine re-prices
    after each session during the weekend.

## Next race: United States Grand Prix (round 18, 25 Oct)

| Driver | Win | Podium | Top 10 | Exp. points |
|---|---|---|---|---|
| Max Verstappen | 14.1% | 36.8% | 79.9% | 10.5 |
| Charles Leclerc | 12.6% | 34.0% | 78.2% | 9.9 |
| George Russell | 11.6% | 32.0% | 79.8% | 9.7 |
| Lando Norris | 11.2% | 31.5% | 75.6% | 9.3 |
| Kimi Antonelli | 10.8% | 31.1% | 79.4% | 9.5 |
| Lewis Hamilton | 10.8% | 30.7% | 76.1% | 9.2 |
| Oscar Piastri | 9.6% | 28.8% | 73.8% | 8.8 |
| Isack Hadjar | 9.1% | 27.6% | 75.3% | 8.7 |

Polymarket lists this race (266 linked markets on production, 2026-10-14); Kalshi lists a Grand Prix 2 to 4 days
out. The race page compares these prices with both venues as they trade.

## Remaining races

| Round | Grand Prix | Date | Favourite (win) | Next two |
|---|---|---|---|---|
| 18 | United States | 25 Oct | Verstappen 14.1% | Leclerc 12.6%, Russell 11.6% |
| 19 | Mexico City | 1 Nov | Russell 13.4% | Antonelli 12.2%, Verstappen 11.4% |
| 20 | São Paulo | 8 Nov | Russell 12.8% | Leclerc 11.3%, Antonelli 10.9% |
| 21 | Las Vegas | 21 Nov | on the Markets page | |
| 22 | Qatar | 29 Nov | on the Markets page | |
| 23 | Abu Dhabi | 6 Dec | on the Markets page | |

`get_forecast` returns the next three races; rounds 21 to 23 are priced in the same run and shown on the Markets
page. Polymarket has race markets for rounds 18, 19 and 20 (266 links each) and none yet for 21 to 23.

## Drivers' championship

Six races and no sprint left. Current points are left out here on purpose (the owner watches sessions delayed);
they are on the Markets page.

| Driver | Exp. final pts | p10–p90 | Champion | Top 3 |
|---|---|---|---|---|
| Kimi Antonelli | 392 | 364–421 | 99.97% | 100% |
| George Russell | 297 | 270–326 | 0.02% | 81.6% |
| Lewis Hamilton | 273 | 246–301 | 0.01% | 41.1% |
| Max Verstappen | 269 | 241–297 | 0% | 35.8% |
| Charles Leclerc | 264 | 235–292 | 0% | 25.8% |
| Lando Norris | 253 | 226–282 | 0% | 15.7% |
| Oscar Piastri | 188 | 161–216 | 0% | 0.01% |
| Isack Hadjar | 143 | 117–170 | 0% | 0% |

The constructors' table is on the Markets page and in `get_forecast(competition="f1_wdc", category=...)` for the
constructors' category; it is not repeated here. The championship markets are open and deep on both venues; the
2026 championship checkpoints lost in the replays (every variant), so the sleeve stays paper only
([Championship markets](championship-markets.md)).

## How to refresh it

The VM does this on its own: `racinglines-schedule-sync.timer` keeps the sessions current every 6 hours (#169), the
signals pass re-prices each stage during a race weekend, and `racinglines-forecast-refresh.timer` re-runs the
championship forecast once per new race result. By hand, after each session:

```
# LOCAL (Mac) or VM
racinglines data fetch f1 --years 2026
racinglines data ingest f1 --years 2026
racinglines model forecast f1 --year 2026 --save     # live: cutoff = now; remaining races + championships
```

A saved forecast becomes the one the web app uses. `racinglines data pm-sync f1` (or
the **Refresh** button on `/markets/polymarket`) picks up new Polymarket markets
once they are listed.
