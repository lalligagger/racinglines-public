<!-- Captured by scripts/docs/capture_examples.py (id live-run-kart-demo, scripts/docs/examples.toml) on 2026-10-14 05:07 UTC, commit 4313bf1+dirty, 35.9 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. 79 of 146 output lines cut (head=39, tail=28). Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines live run kart/demo-2026-09 --demo --simulate --no-fetch
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
  pre-weekend: priced (run #3)
2026-10-02T10:30:00+00:00 2026-09 pre-weekend: 80 markets, 54 quoted, 0 crowd fills, maker P&L +24.73
╭─ 🚦 Bowser's Castle Grand Prix 2026 (synthetic) · pre-weekend (1 of 7 · 2026-10-02T10:30 UTC) ─╮
│                                                                                                │
│  driver          fair                  move     bid     ask   Polymarket   Kalshi   inventory  │
│  ────────────────────────────────────────────────────────────────────────────────────────────  │
│  Mario          27.6%   ███▎                  24.0%   31.0%        32.5%    36.0%         -81  │
│  Luigi          21.4%   ██▌                   18.0%   25.0%        11.1%     8.0%           –  │
│  Daisy          20.5%   ██▍                   17.0%   24.0%         6.1%     5.7%           –  │
│  Peach          18.2%   ██▏                   15.0%   22.0%        10.4%    11.2%           –  │
│  Bowser          3.6%   ▍                      1.0%    8.0%        10.2%    10.5%        -357  │
│  Bowser Jr.      2.1%   ▎                         –    6.0%         1.8%     2.1%           –  │
│  Yoshi           1.6%   ▏                         –    5.0%         1.6%     1.9%           –  │
│  Koopa Troopa    1.2%   ▏                         –    5.0%         7.2%    11.2%           –  │
│                                                                                                │
│ 👥 crowd: 0 fills this update · 0 in all · $0 traded · 0 of 100 takers still betting           │
│ 💰 maker P&L +24.73  (crowd +0.00, picks +24.73)                                               │
│ next: after FP1 at 2026-10-02T13:00 UTC                                                        │
╰────────────────────────────────────────────────────────────────────────────────────────────────╯
  after FP1: priced (run #4)
2026-10-02T13:00:00+00:00 2026-09 after FP1: 80 markets, 44 quoted, 4 crowd fills, maker P&L -75.09
╭─ 🔄 Bowser's Castle Grand Prix 2026 (synthetic) · after FP1 (2 of 7 · 2026-10-02T13:00 UTC) ─────╮
│                                                                                                  │
│  driver          fair                    move     bid     ask   Polymarket   Kalshi   inventory  │
│  ──────────────────────────────────────────────────────────────────────────────────────────────  │
│  Mario          29.1%   ███▍            ▲ 1.5   26.0%   32.0%        32.5%    36.0%         -66  │
│  Bowser         20.1%   ██▍            ▲ 16.4   17.0%   23.0%        10.2%    10.5%        -357  │
│  Luigi          19.3%   ██▎             ▼ 2.1   16.0%   22.0%        11.1%     8.0%           –  │
│  Peach          16.0%   █▉              ▼ 2.2   13.0%   19.0%        10.4%    11.2%           –  │
│  Daisy          11.1%   █▎              ▼ 9.5    8.0%   14.0%         6.1%     5.7%           –  │
│  Koopa Troopa    1.9%   ▏               ▲ 0.6       –    5.0%         7.2%    11.2%           –  │
│  Yoshi           0.7%                   ▼ 0.9       –    4.0%         1.6%     1.9%           –  │
│  King Boo        0.5%                   ▼ 0.6       –    4.0%         2.3%     1.8%           –  │
│                                                                                                  │
│ 👥 crowd: 4 fills this update · 4 in all · $294 traded · 4 of 100 takers still betting           │
│ 💰 maker P&L -75.09  (crowd -51.91, picks -23.17)                                                │
│ 🏁 fp1: P1 Mario · P2 Bowser · P3 Luigi                                                          │
│ next: after FP2 at 2026-10-02T16:30 UTC                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
… 79 lines cut (showing the first 39 and last 28 of 146) …
2026-10-04T17:00:00+00:00 2026-09 results: 80 markets, 0 quoted, 0 crowd fills, maker P&L -222.25
╭─ 🏁 Bowser's Castle Grand Prix 2026 (synthetic) · results (7 of 7 · 2026-10-04T17:00 UTC) ──────╮
│                                                                                                 │
│  driver             fair                    move   bid   ask   Polymarket   Kalshi   inventory  │
│  ─────────────────────────────────────────────────────────────────────────────────────────────  │
│  Luigi ✅          31.4%   ███▊            ▲ 4.5     –     –        11.1%     8.0%         -13  │
│  Daisy ❌          20.5%   ██▍             ▲ 8.5     –     –         6.1%     5.7%         -66  │
│  Mario ❌          20.4%   ██▍             ▼ 2.2     –     –        32.5%    36.0%         -66  │
│  Bowser ❌         20.0%   ██▍             ▲ 5.3     –     –        10.2%    10.5%      -1,058  │
│  Peach ❌           6.5%   ▊              ▼ 12.8     –     –        10.4%    11.2%        -132  │
│  King Boo ❌        0.5%                   ▼ 0.3     –     –         2.3%     1.8%      -2,338  │
│  Koopa Troopa ❌    0.4%                   ▼ 1.4     –     –         7.2%    11.2%           –  │
│  Donkey Kong ❌     0.2%                       =     –     –         0.8%        –           –  │
│                                                                                                 │
│ 👥 crowd: 0 fills this update · 176 in all · $6,048 traded · 52 of 100 takers still betting     │
│ 💰 maker P&L -222.25  (crowd -72.25, picks -150.00)                                             │
│ 🏁 race: P1 Luigi · P2 Daisy · P3 Donkey Kong                                                   │
╰─────────────────────────────────────────────────────────────────────────────────────────────────╯
simulated 2026-09 to 2026-10-04 17:00:00: 7 updates
╭─ 🏁 Bowser's Castle Grand Prix 2026 (synthetic) ─────────────────────╮
│ opened             2026-10-02T10:30 UTC                              │
│ settled            2026-10-04T17:00 UTC                              │
│ 💰 maker P&L       -222.25                                           │
│    from the crowd  -72.25                                            │
│    from the picks  -150.00                                           │
│ 👥 fills           176  ($6,048 traded)                              │
│    bettors         83: 31 up, 52 down, best +1,297.32, worst -184.03 │
╰──────────────────────────────────────────────────────────────────────╯
```
<!-- --8<-- [end:output] -->
