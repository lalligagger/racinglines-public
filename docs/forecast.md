# Downhill forecast

Current forecast: 2026 Men Elite.

Model run **1287** (2026-09-27), with data through Whistler Timed Training and the
Q1 start list. The model is fit on everything before the Whistler weekend, using
2021–2026 elite and junior history. How accurate the model has been:
[Downhill evaluation](evaluation.md). For Formula 1, see
[F1 forecast](f1-forecast.md).

<!-- readme: forecast-summary -->

2026 title odds with 2 rounds left (Whistler in progress, then one more round):
**Williams 71.4%**, Vermette 18.6%, Iles 4.3%, Pierron 4.0%
([full forecast](#projected-final-standings)).

<!-- /readme -->

!!! warning "Placeholder points"
    Expected points, standings, champion odds and rank-movement probabilities use
    placeholder points tables. Win, podium, top-10 and make-Final odds don't.

## Next round: Whistler (DHI #8, 25–27 Sep), in progress

There are 109 starters from the Q1 start list. Timed Training was **ignored** by the
safety check (residual IQR 0.71): riders were held on track, so finish times don't
reflect pace. These odds therefore carry no Whistler-specific information.

| Rider | Win | Podium | Top 10 | Make Final | Exp pts | Rank now | Rank up | Rank down |
|---|---|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 6.7% | 16.8% | 40.2% | 75.3% | 91 | 1 | 0.0% | 18.9% |
| VERMETTE Asa | 5.6% | 14.9% | 37.3% | 73.7% | 84 | 2 | 13.9% | 34.8% |
| ALRAN Max | 5.6% | 15.1% | 39.2% | 73.1% | 86 | 6 | 28.7% | 49.8% |
| BRUNI Loic | 5.1% | 13.4% | 35.4% | 71.0% | 80 | 26 | 48.4% | 33.0% |
| ILES Finn | 5.0% | 12.6% | 34.1% | 69.3% | 76 | 3 | 20.1% | 45.5% |
| PINKERTON Ryan | 4.5% | 12.5% | 33.5% | 69.0% | 75 | 8 | 46.7% | 24.9% |
| PIERRON Amaury | 4.3% | 12.4% | 33.9% | 69.5% | 76 | 4 | 33.5% | 30.7% |
| ALRAN Till | 4.3% | 12.5% | 34.5% | 69.5% | 77 | 11 | 39.8% | 38.7% |

## Projected final standings

| Rider | Rank now | Pts now | Exp final pts | p10–p90 | Champion | Top 3 |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 1 | 1177 | 1364 | 1209–1532 | 71.4% | 99.2% |
| VERMETTE Asa | 2 | 1042 | 1215 | 1065–1383 | 18.6% | 82.6% |
| ILES Finn | 3 | 962 | 1091 | 962–1252 | 4.3% | 40.3% |
| PIERRON Amaury | 4 | 928 | 1085 | 944–1243 | 4.0% | 40.4% |
| GOLDSTONE Jackson | 5 | 822 | 962 | 822–1122 | 0.7% | 12.4% |
| ALRAN Max | 6 | 773 | 952 | 798–1118 | 0.5% | 12.2% |
| BROSNAN Troy | 7 | 760 | 905 | 770–1060 | 0.2% | 5.4% |
| PINKERTON Ryan | 8 | 743 | 898 | 759–1061 | 0.2% | 5.6% |

The remaining unknown round uses the attendance model (riders who started the last
3 completed rounds).

## 2026 so far: how this season's rounds were called

Each round was predicted from everything before it (walk-forward backtest run 938,
the same numbers as [Downhill evaluation](evaluation.md#per-event-walk-forward)):

| Round | Spearman | Brier make-Final (model / base) | Top-10 hits | Winner (win prob) |
|---|---|---|---|---|
| Mona Yongpyong | 0.646 | 0.135 / 0.231 | 6 | Vermette (21.3%) |
| Loudenvielle | 0.611 | 0.128 / 0.210 | 4 | Shaw (3.1%) |
| Leogang | 0.671 | 0.113 / 0.202 | 4 | Iles (2.6%) |
| Lenzerheide | 0.679 | 0.111 / 0.204 | 5 | Iles (4.9%) |
| La Thuile | 0.674 | 0.100 / 0.194 | 5 | Williams (4.0%) |
| Pal Arinsal | 0.679 | 0.121 / 0.222 | 6 | Williams (4.6%) |
| Les Gets | 0.701 | 0.106 / 0.201 | 7 | M. Alran (4.5%) |

## Holdout: rounds 6–7 and the standings, predicted from data up to round 5

| Rider | Pts after R5 | Exp pts after R7 | Leader after R7 | Top 3 | Actual pts | Actual rank |
|---|---|---|---|---|---|---|
| PIERRON Amaury | 844 | 1027 | 51.0% | 93.7% | 928 | 4 |
| VERMETTE Asa | 755 | 926 | 20.7% | 67.1% | 1042 | 2 |
| WILLIAMS Jordan | 752 | 916 | 18.7% | 64.1% | 1177 | 1 |
| ILES Finn | 782 | 866 | 6.7% | 45.7% | 962 | 3 |
| BROSNAN Troy | 539 | 681 | 0.8% | 7.3% | 760 | 7 |
| VERGIER Loris | 508 | 669 | 0.9% | 6.8% | 627 | 9 |

Standings Spearman: 0.962. Williams took the lead by scoring 425 points in rounds
6–7 (a win at Pal Arinsal and 7th at Les Gets), which the model gave an 18.7%
chance.

This table is from the 2026-09-26 forecast run, before the database was rebuilt;
per-rider holdout rows aren't stored. Backtest run 938's holdout of the same
rounds gives the same standings Spearman (0.962) and Pierron 51.0%, and Williams
17.7% (see [Downhill evaluation](evaluation.md#per-season-walk-forward-means-plus-a-standings-holdout-of-the-last-2-rounds)).

## How to refresh it

After each session: re-download, ingest and re-run (see
[Web app](webapp.md#getting-predictions-for-an-event-weekend)).

```
racinglines mtb_dh ingest data/raw/mtb_dh/chronorace
racinglines mtb_dh forecast --db --save --backtest 0 --remaining 2   # 10k sims, seed 42
```
