# Current forecast: 2026 Men Elite

The model is fit on everything through 2026 round 7 (Les Gets, 21–23 Aug), using
2021–2026 elite and junior history.

<!-- readme: forecast-summary -->

2026 title odds with 2 rounds left: **Williams 72.7%**, Vermette 18.5%, Pierron 4.2%,
Iles 2.8% ([full forecast](#projected-final-standings)).

<!-- /readme -->

```
python predictor.py season --data splits.csv --out-dir season_out --walk-forward   # 10k sims, seed 42
```

!!! warning "Placeholder points"
    Expected points, standings and champion odds use placeholder points tables.
    Win, podium, top-10 and make-Final odds don't.

## Each remaining round (8 and 9)

Venues aren't known yet, so both rounds get the same odds. The field is every
rider who started any of the last 3 rounds, with attendance weighted by how often
they started. The format is the 2026 Q1/Q2 format.

| Rider | Attend | Win | Podium | Top 10 | Make Final | Exp pts |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 100% | 6.8% | 17.7% | 44.7% | 80.7% | 98 |
| ALRAN Max | 100% | 6.3% | 16.4% | 42.0% | 78.4% | 93 |
| VERMETTE Asa | 100% | 6.3% | 15.7% | 39.7% | 78.3% | 90 |
| PIERRON Amaury | 100% | 5.3% | 13.3% | 36.8% | 74.0% | 82 |
| ALRAN Till | 100% | 4.7% | 13.2% | 36.8% | 74.2% | 82 |
| VERGIER Loris | 100% | 4.2% | 12.1% | 34.8% | 73.2% | 78 |
| PINKERTON Ryan | 100% | 4.4% | 12.4% | 34.4% | 73.0% | 78 |
| BROSNAN Troy | 100% | 4.1% | 11.9% | 33.9% | 71.2% | 77 |

## Projected final standings

| Rider | Rank now | Pts now | Exp final pts | p10–p90 | Champion | Top 3 |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 1 | 1177 | 1372 | 1215–1543 | 72.7% | 99.4% |
| VERMETTE Asa | 2 | 1042 | 1222 | 1070–1392 | 18.5% | 84.2% |
| PIERRON Amaury | 4 | 928 | 1093 | 948–1258 | 4.2% | 43.1% |
| ILES Finn | 3 | 962 | 1071 | 962–1232 | 2.8% | 32.4% |
| GOLDSTONE Jackson | 5 | 822 | 970 | 836–1132 | 0.7% | 13.7% |
| ALRAN Max | 6 | 773 | 958 | 808–1123 | 0.6% | 12.9% |
| BROSNAN Troy | 7 | 760 | 911 | 777–1068 | 0.3% | 6.3% |
| PINKERTON Ryan | 8 | 743 | 900 | 761–1061 | 0.2% | 5.6% |

Iles has only a 67% chance of starting each remaining round (he missed one of the
last three), which caps his upside.

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
