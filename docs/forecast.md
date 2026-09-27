# Current forecast: 2026 Men Elite

Model run **#4** (2026-09-26), with data through Whistler Timed Training and the Q1
start list. The model is fit on everything before the Whistler weekend, using
2021–2026 elite and junior history.

<!-- readme: forecast-summary -->

2026 title odds with 2 rounds left (Whistler in progress, then one more round):
**Williams 71.1%**, Vermette 18.8%, Pierron 4.2%, Iles 4.1%
([full forecast](#projected-final-standings)).

<!-- /readme -->

```
racinglines mtb_dh ingest data/raw/mtb_dh/chronorace
racinglines mtb_dh forecast --db --save --backtest 0 --remaining 2   # 10k sims, seed 42
```

!!! warning "Placeholder points"
    Expected points, standings, champion odds and rank-movement probabilities use
    placeholder points tables. Win, podium, top-10 and make-Final odds don't.

## Whistler (DHI #8, 25–27 Sep): in progress

There are 109 starters from the Q1 start list. Timed Training was **ignored** by the
safety check (residual IQR 0.71): riders were held on track, so finish times don't
reflect pace. These odds therefore carry no Whistler-specific information.

| Rider | Win | Podium | Top 10 | Make Final | Exp pts | Rank now | Rank up | Rank down |
|---|---|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 6.9% | 16.7% | 41.2% | 75.2% | 91 | 1 | 0.0% | 18.5% |
| VERMETTE Asa | 5.8% | 15.0% | 38.2% | 74.1% | 85 | 2 | 13.7% | 34.9% |
| ALRAN Max | 5.4% | 14.5% | 39.0% | 73.9% | 86 | 6 | 29.0% | 50.1% |
| BRUNI Loic | 4.9% | 13.6% | 34.5% | 70.9% | 78 | 26 | 47.7% | 33.2% |
| ALRAN Till | 4.7% | 13.1% | 35.0% | 70.1% | 78 | 11 | 39.9% | 39.1% |
| GOLDSTONE Jackson | 4.6% | 11.7% | 31.7% | 66.7% | 71 | 5 | 17.8% | 59.6% |
| PINKERTON Ryan | 4.6% | 12.0% | 32.9% | 69.0% | 74 | 8 | 46.0% | 25.4% |
| VERGIER Loris | 4.4% | 12.4% | 33.5% | 68.1% | 75 | 9 | 19.9% | 59.3% |

Refresh after each session: re-download, ingest and re-run (see
[Web app](webapp.md#getting-predictions-for-an-event-weekend)).

## Projected final standings

| Rider | Rank now | Pts now | Exp final pts | p10–p90 | Champion | Top 3 |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 1 | 1177 | 1365 | 1207–1539 | 71.1% | 99.3% |
| VERMETTE Asa | 2 | 1042 | 1218 | 1067–1387 | 18.8% | 83.5% |
| ILES Finn | 3 | 962 | 1090 | 962–1252 | 4.1% | 39.6% |
| PIERRON Amaury | 4 | 928 | 1086 | 945–1248 | 4.2% | 40.2% |
| GOLDSTONE Jackson | 5 | 822 | 967 | 822–1130 | 0.8% | 12.6% |
| ALRAN Max | 6 | 773 | 951 | 800–1118 | 0.6% | 11.5% |
| BROSNAN Troy | 7 | 760 | 903 | 771–1060 | 0.2% | 5.4% |
| PINKERTON Ryan | 8 | 743 | 896 | 758–1056 | 0.2% | 5.6% |

The remaining unknown round uses the attendance model (riders who started the last
3 completed rounds).

## 2026 walk-forward: how this season's rounds were called

Each round was predicted from everything before it:

| Round | Spearman | Brier make-Final (model / base) | Top-10 hits | Winner (win prob) |
|---|---|---|---|---|
| Mona Yongpyong | 0.642 | 0.135 / 0.231 | 6 | Vermette (20.9%) |
| Loudenvielle | 0.615 | 0.127 / 0.210 | 4 | Shaw (3.0%) |
| Leogang | 0.674 | 0.113 / 0.202 | 4 | Iles (3.0%) |
| Lenzerheide | 0.680 | 0.111 / 0.204 | 6 | Iles (4.8%) |
| La Thuile | 0.674 | 0.101 / 0.194 | 5 | Williams (4.3%) |
| Pal Arinsal | 0.684 | 0.120 / 0.222 | 6 | Williams (5.3%) |
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
