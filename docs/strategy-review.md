# Strategy review (2026-10-06)

Profile A on Kalshi turned out to rest on two weekends a season ([Kalshi history](kalshi-history.md)), so the
owner asked for every F1 strategy so far to be backtested on Polymarket and Kalshi side by side, with rolling Kelly
sizing on a $10,000 bankroll, and sorted into steady and lumpy. This page is that review: 80 jobs (19 settings sets
× 2 venues × 2 seasons, plus 4 baselines) at 16,000 simulations, 342 strategy rows, run on the VM from 2026-10-05
23:46Z (queue `sweeps/strategy-review.toml`, report `racinglines f1 search-report sweeps/strategy-review.toml`).

**Verdict: A (T1) stays the core taker, on Polymarket only.** It is steady there: up in both seasons, and still up
without each season's two best weekends. On Kalshi no taker is steady. Every taker is up in 2026 because of
Australia and down in 2025 once the two best weekends are removed, so Kalshi taking waits for more evidence. The
best Kalshi option is maker K, still small and concentrated. Kelly sizing multiplies the dollars but not the
evidence: its totals come mostly from two compounding weekends and assume fills the books can't carry.

## How to read it

- **2026** is the target season, **2025** the held-out one. P&L is in dollars at the touch (Kalshi bid/ask since
  PR #55), after fees.
- **Without best 2**: the season's P&L minus its two best weekends.
- **Shape** describes the record, not the risk (PR #62). **Steady**: up in both seasons, even without each season's
  best two weekends. **Concentrated**: up in both, but not without the best two in at least one. **Mixed**: up in
  one season, down in the other. **Losing**: down in both.
- Takers T2 to T6 and T10 are each job's `update` row. T8 and T9 are the `early` rows of the T1 and T7 jobs. M1 is
  the baseline's maker row. TB is half T1 and half T8.

## Polymarket, flat sizing

| Profile | Shape | 2026 | without best 2 | weekends up | 2025 | without best 2 | weekends up | Best 2026 weekend |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **T1 (A)** | steady | +1,375 | +112 | 10/16 | +1,432 | +350 | 14/23 | British |
| T7 | steady | +1,257 | +67 | 10/16 | +1,456 | +374 | 14/23 | British |
| C | steady | +652 | +237 | 9/16 | +629 | +86 | 14/23 | Japanese |
| K | steady | +535 | +24 | 8/16 | +1,033 | +195 | 14/23 | Italian |
| T9 | concentrated | +2,794 | +508 | 10/16 | +570 | −2 | 13/23 | British |
| T8 | concentrated | +2,707 | +421 | 10/16 | +546 | −26 | 13/23 | British |
| T2 | concentrated | +1,243 | −47 | 10/16 | +1,400 | +335 | 14/23 | British |
| T3 | concentrated | +948 | −313 | 7/16 | +900 | −84 | 13/23 | British |
| T5 | concentrated | +859 | −333 | 7/16 | +816 | −269 | 13/23 | British |
| T10 | concentrated | +728 | −681 | 7/16 | +757 | −373 | 12/23 | British |
| T4 | concentrated | +726 | −325 | 9/16 | +881 | −230 | 11/23 | British |
| T6 | concentrated | +688 | −447 | 7/16 | +608 | −223 | 13/23 | British |
| M3 | concentrated | +555 | −129 | 7/16 | +1,139 | +403 | 15/23 | Italian |
| M2 | mixed | +906 | +265 | 9/16 | −131 | −750 | 9/23 | Monaco |
| M1 | mixed | +500 | −203 | 8/16 | −203 | −796 | 9/23 | Italian |
| default taker | mixed | −615 | −1,744 | 5/16 | +181 | −896 | 9/23 | British |

TB (half T1, half T8): +2,041 in 2026, +989 in 2025.

## Kalshi, flat sizing

| Profile | Shape | 2026 | without best 2 | weekends up | 2025 | without best 2 | weekends up | Best 2026 weekend |
|---|---|---:|---:|---:|---:|---:|---:|---|
| T7 | concentrated | +2,605 | +428 | 8/16 | +1,620 | −637 | 6/24 | Australian |
| T2 | concentrated | +2,449 | +83 | 8/16 | +1,208 | −1,065 | 6/24 | Australian |
| T3 | concentrated | +2,366 | −80 | 8/16 | +1,206 | −1,060 | 6/24 | Australian |
| **T1 (A)** | concentrated | +2,332 | −117 | 8/16 | +1,257 | −1,025 | 5/24 | Australian |
| T6 | concentrated | +2,322 | −22 | 9/16 | +505 | −928 | 6/24 | Australian |
| T5 | concentrated | +2,278 | −93 | 8/16 | +1,072 | −1,204 | 6/24 | Australian |
| T10 | concentrated | +2,115 | −352 | 7/16 | +1,059 | −1,181 | 5/24 | Australian |
| T4 | concentrated | +1,626 | −312 | 7/16 | +1,473 | −1,207 | 6/24 | Australian |
| default taker | concentrated | +1,391 | −961 | 5/16 | +1,141 | −1,087 | 9/24 | Australian |
| K | concentrated | +453 | −552 | 5/16 | +741 | +66 | 13/24 | Italian |
| M3 | concentrated | +87 | −534 | 9/16 | +723 | −84 | 13/24 | Italian |
| T9 | mixed | +1,885 | +166 | 8/16 | −746 | −1,154 | 5/24 | British |
| T8 | mixed | +1,678 | +120 | 8/16 | −672 | −1,104 | 5/24 | British |
| C | mixed | −32 | −329 | 7/16 | +383 | −206 | 12/24 | Japanese |
| M2 | losing | −568 | −1,178 | 6/16 | −953 | −1,451 | 8/24 | Hungarian |
| M1 | losing | −1,261 | −1,856 | 6/16 | −185 | −632 | 10/24 | Italian |

TB: +2,005 in 2026, +292 in 2025.

## Rolling Kelly on $10,000

Half-Kelly (HK) and quarter-Kelly (QK) at the touch, $500 a market (scaled with the balance) and $2,500 deployed a
weekend.

| Profile | Venue | Shape | 2026 | without best 2 | weekends up | 2025 | without best 2 | weekends up |
|---|---|---|---:|---:|---:|---:|---:|---:|
| QK T1 | Polymarket | steady | +15,551 | +2,063 | 9/16 | +10,776 | +3,613 | 14/23 |
| QK T8 | Polymarket | steady | +23,508 | +3,806 | 9/16 | +4,942 | +959 | 12/23 |
| HK T8 | Polymarket | steady | +31,217 | +841 | 9/16 | +6,288 | +1,014 | 12/23 |
| HK T9 | Polymarket | steady | +30,811 | +641 | 9/16 | +6,686 | +1,413 | 12/23 |
| HK T1 | Polymarket | concentrated | +12,647 | −313 | 7/16 | +10,078 | +2,583 | 11/23 |
| HK T7 | Polymarket | concentrated | +10,691 | −2,154 | 7/16 | +10,436 | +2,942 | 11/23 |
| HK T6 | Polymarket | concentrated | +3,933 | −6,070 | 6/16 | +7,363 | −2,080 | 10/23 |
| QK T1 | Kalshi | concentrated | +33,499 | +7,092 | 10/16 | +2,328 | −10,077 | 8/24 |
| HK T6 | Kalshi | concentrated | +16,711 | +3,455 | 8/16 | +137 | −10,469 | 7/24 |
| HK T1 | Kalshi | mixed | +24,715 | +4,818 | 10/16 | −1,013 | −9,610 | 7/24 |
| HK T9 | Kalshi | mixed | +19,914 | +4,648 | 9/16 | −5,961 | −8,539 | 7/24 |
| HK T8 | Kalshi | mixed | +16,078 | +2,082 | 7/16 | −5,650 | −8,598 | 7/24 |
| QK T8 | Kalshi | mixed | +11,985 | +1,938 | 8/16 | −5,283 | −8,445 | 7/24 |
| HK T7 | Kalshi | mixed | +10,924 | −1,915 | 8/16 | −1,149 | −6,975 | 8/24 |

**Read these as rankings, not dollars.** Three reasons:

1. **Compounding makes the best weekends huge.** HK T8 on Polymarket makes +31,217 in 2026 but only +841 without
   its two best weekends, so 97% of the season is two weekends. "Steady" still applies, because what's left is
   positive, but the label understates how lumpy Kelly is in dollars.
2. **The replay has no depth limit.** A $500 to $2,000 stake fills at the touch in the backtest. F1 books on
   Polymarket and Kalshi rarely show that much at one price.
3. **Half-Kelly overbets an overconfident model.** QK T1 beats HK T1 on Polymarket in both "without best 2"
   columns, and on Kalshi in 2026. That is the usual sign that the fair prices are sharper than they really are.

**Quarter-Kelly T1 on Polymarket is the most defensible Kelly row.** It is steady, has the best 2025 of any
row (+10,776), and 14 of 23 2025 weekends are up. On Kalshi every Kelly row loses about
$7,000 to $10,500 in 2025 once its two best weekends are removed.

## Every market kind

Adding Kalshi's top 10 markets changes only Kalshi 2026: T1 goes from +2,332 to +3,969, with Monaco now its best
weekend. 2025 is identical, so no 2025 top-10 market reached the replay. Polymarket lists no top 10 market, so its
rows are identical. It's promising but rests on one season. It needs a 2025 top-10 tape before any profile uses it.

## What this means for this weekend

- **Polymarket: trade A (T1) as is.** If sized off a bankroll, use quarter-Kelly with a cap the book can carry,
  not half-Kelly. T7 is a near twin of A (the podium coherence tolerance hardly matters). T8 and T9 earn more in
  2026 but are flat in 2025 once the best two weekends are removed.
- **Kalshi: no taker at size.** If anything trades there, it's maker K, small. The 2026 taker gains rest on
  Australia.
- **Makers on Polymarket**: C and K are steady but small, about +$500 to +$1,000 a season.

## What this doesn't show

- **No OG.com**: there are only one or two weekends of data.
- **No sprint or both-cars-in-points markets**: these aren't modelled yet. No best-price-across-venues mode.
- **One replicate per combo.** The noise floor is the configured ±150, not measured from seed replicates.
- **Fills at the touch with no depth model.** The Kelly totals are the most exposed to this.
- **Singapore (round 17)**: Kalshi has no linked markets yet, and our stored Polymarket tape shows zero 24-hour
  volume ([Strategy preview](strategy-preview.md)). Check the venue's own volume before trading.

## Sources

Built from `data/runs/search/strategy-review/ranking.csv` on the VM (`f1 search-report` at commit `abac3e9`,
2026-10-06 02:20Z). There is one saved sweep run per job in `model_runs`. A database backup was taken before the
run (`racinglines-before-strategy-review-*`) and copied to the owner's Mac.
