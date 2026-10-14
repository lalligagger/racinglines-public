<!-- Captured by scripts/docs/capture_examples.py (id book-price-demo, scripts/docs/examples.toml) on 2026-10-14 05:07 UTC, commit 4313bf1+dirty, 2.1 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines book price --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
demo: the demo store's synthetic data (made-up names, results and prices); nothing is traded
                                             book price

                                                                                        model
  id            selection    odds    book   model       market   EV model   EV market   method
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  win           Super        3.20   31.2%   26.4%        65.4%     -15.6%     +109.3%   single
                Mario
  win-no        Luigi not    1.30   76.9%   81.2%        87.2%      +5.6%      +13.4%   single
                to win
  podium        Peach        2.40   41.7%   33.1%        11.6%     -20.5%      -72.2%   single
  top5          Daisy        1.90   52.6%   50.2%            –      -4.6%           –   single
  top10         Bowser       1.25   80.0%   82.2%            –      +2.7%           –   single
  p2            Luigi        4.50   22.2%       –        32.8%          –      +47.6%   single
  pole          Mario        2.75   36.4%   35.0%        66.3%      -3.9%      +82.3%   single
  fl            Luigi        5.00   20.0%       –            –          –           –   single
  h2h           Daisy v      2.10   47.6%   47.0%        41.5%      -1.4%      -12.8%   single
                Peach
  mover         Yoshi        6.00   16.7%    8.6%            –     -48.5%           –   single
  spr-win       Mario        2.90   34.5%   24.8%            –     -28.0%           –   single
  spr-pole      Luigi        4.00   25.0%   16.1%            –     -35.6%           –   single
  red           No           1.45   69.0%       –            –          –           –   single
  sgp-joint     Mario win    4.20   23.8%   13.1%        40.0%     -44.9%      +68.1%   product
                + Luigi
                podium
  └ 14.1        race_win                –   26.4%        65.4%
                Mario  (f1                          polymarket
                2026-10)
  └ 14.2        race_podi…              –   49.7%        61.2%
                Luigi  (f1                          polymarket
                2026-10)
  sgp-product   Peach        2.50   40.0%   28.0%            –     -30.1%           –   product
                podium +
                Daisy top
                10
  └ 15.1        race_podi…              –   33.1%        11.6%
                Peach  (f1                          polymarket
                2026-10)
  └ 15.2        race_top10              –   84.4%            –
                Daisy  (f1
                2026-10)
  parlay        Mario wins   9.60   10.4%    6.4%        35.9%     -38.2%     +244.7%   single x
                Rainbow                                                                 single
                Road and
                Wario
                Stadium
  └ 16.1        race_win      3.2   31.2%   26.4%        65.4%
                Mario  (f1                          polymarket
                2026-10)
  └ 16.2        race_win      3.0   33.3%   24.4%        54.9%
                Mario  (f1                          polymarket
                2026-11)
  typo          Maryo           –       –       –            –          –           –

          book_demo · event 2026-10 · f1 · captured 2026-10-15T09:00Z · odds decimal · USD
╭───────────────────────────────────── flags ──────────────────────────────────────╮
│ sgp-joint: race 34: 2 legs on one race, correlated: EV approximate               │
│ sgp-joint: market: product of leg prices on one race, correlated: EV approximate │
│ sgp-product: race 34: 2 legs on one race, correlated: EV approximate             │
│ parlay: legs on 2 races: independent across races (product)                      │
╰──────────────────────────────────────────────────────────────────────────────────╯
╭────────────────── unmapped lines ───────────────────╮
│ typo                                                │
│ exact keys only: fix the book file or its [aliases] │
╰─────────────────────────────────────────────────────╯
╭────────────────────────────────────────── assumptions ───────────────────────────────────────────╮
│ • EV is per unit staked: probability x decimal payout - 1; decimal payout = 1 / the book's       │
│ implied probability.                                                                             │
│ • Legs on different races are independent: the slip probability is the product of their          │
│ probabilities.                                                                                   │
│ • Legs on the same race are priced jointly from simulations when they are available (passed in,  │
│ or a stored combo run with exactly these legs); otherwise the product of the marginals, flagged  │
│ 'correlated: EV approximate'.                                                                    │
│ • The market's slip probability is the product of its legs' prices: no exchange lists the slip   │
│ itself.                                                                                          │
│ • Model and market are shown side by side, never blended (owner, 2026-10-07).                    │
│ • The market price is the freshest linked exchange's mid (bid/ask midpoint, else its last price, │
│ else the tape's).                                                                                │
│ blend: none (owner, 2026-10-07; docs/sportsbook/slips.md)                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
<!-- --8<-- [end:output] -->
