# Market vocabulary (draft, 2026-10-06)

Generated from `schemas/kinds-vocabulary.toml`. Status: exists = in `racinglines/markets/kinds.py`; props = in `props.py`, not in the registry; proposed = a new code in the same style; no_data = no data source known. Venue keys: `book_a` (a decimal-odds sportsbook, USDT), `book_b` and `book_c` (American-odds sportsbooks), `kalshi`, `polymarket`, `og`.

| Code | Label | Subject | Status | Venues |
|---|---|---|---|---|
| `race_win` | Race winner | driver | exists | **book_a**: Race Winner; **book_c**: Odds to win F1 - Singapore GP 2026; **book_b**: Odds to Win Singapore Grand Prix; **kalshi**: KXF1RACE; **polymarket**: <GP>: Driver Winner; **og**: Race Winner |
| `race_podium` | Podium finish | driver | exists | **kalshi**: KXF1RACEPODIUM; **polymarket**: <GP>: Driver Podium Finish |
| `race_top5` | Top 5 finish | driver | exists | **kalshi**: KXF1TOP5 |
| `race_top10` | Top 10 finish | driver | exists | **kalshi**: KXF1TOP10 |
| `race_h2h` | Race head-to-head (finishes ahead) | pair | exists | **book_a**: Head-to-head (ledger, Malaysia 2026); **kalshi**: KXF1H2H; **polymarket**: <GP>: Head-to-Head |
| `race_pole` | Pole position (qualifying winner) | driver | exists | **book_a**: Qualifying Winner; **kalshi**: KXF1POLE; **polymarket**: <GP>: Driver Pole Position |
| `race_fastest_lap` | Fastest lap (driver) | driver | exists | **book_a**: Fastest Lap; **kalshi**: KXF1FASTLAP; **polymarket**: <GP>: Driver Fastest Lap |
| `race_biggest_mover` | Biggest mover (grid to finish) | driver | exists | **kalshi**: KXF1BIGGESTMOVER |
| `race_classified` | Driver classified | driver | exists | **book_a**: <Driver> To Be Classified? |
| `race_last_classified` | Last classified finisher | driver | exists | **book_a**: Classified As Last Finisher |
| `race_first_retirement` | First driver to retire | driver | proposed | **book_a**: First Driver Retirement; **kalshi**: retirement titles, unmodeled (kalshi/sync.py:95) |
| `race_grand_slam` | Win, pole and fastest lap by one driver | none | proposed | **book_a**: Any Driver To Win Race, Pole Position And Fastest Lap |
| `race_constructor_top` | Most team points in the race | team | exists | **book_a**: Most Team Points; **kalshi**: KXF1TOPCONSTRUCTOR; **polymarket**: <GP>: Which Constructor Scores 1st? |
| `race_constructor_win` | Winning constructor | team | exists | **book_a**: Race Winning Constructor |
| `race_team_both_classified` | Both cars classified | team | exists | **book_a**: <Team> Both Cars Classified? |
| `race_team_both_points` | Both cars in the points | team | proposed | **book_a**: <Team> both cars in points (ledger, Malaysia 2026) |
| `race_first_retirement_team` | First constructor to retire (or no retirement) | team | proposed | **book_a**: First Constructor Retirement |
| `race_fastest_lap_team` | Fastest lap (team) | team | proposed | **book_a**: Car To Set The Fastest Lap; **polymarket**: constructor fastest lap (unmodeled, docs/f1.md:180) |
| `race_fastest_pit_team` | Fastest pit stop (team) | team | no_data | **book_a**: Fastest Team Pit Stop |
| `race_pair_podium` | Named pair both on the podium | pair | proposed | **book_a**: Podium pair (ledger, Malaysia 2026) |
| `race_n_classified` | Number of classified drivers (over/under) | line | exists | **book_a**: Number Of Classified Drivers |
| `race_safety_car` | Safety car during the race | none | props | **book_a**: Will There Be A Safety Car Period During Race?; **polymarket**: Will there be a safety car during the <GP>? |
| `race_red_flag` | Red flag during the race | none | props | **book_a**: Will There Be A Red Flag During Race?; **polymarket**: red flag question (docs/f1.md:178) |
| `race_rain` | Rain during the race | none | props | **polymarket**: Rain during the <GP>? |
| `race_vsc` | Virtual safety car during the race | none | proposed | **book_a**: Will There Be A Virtual Safety Car Period During Race? |
| `race_sc_and_vsc` | Both a safety car and a virtual safety car | none | proposed | **book_a**: Will There Be A Safety Car And A Virtual Safety Car Period During Race? |
| `race_n_safety_cars` | Number of safety cars (over/under) | line | proposed | **book_a**: Number Of Safety Cars; Safety cars Under 1.5 (ledger, Malaysia 2026) |
| `race_n_vsc` | Number of virtual safety cars (over/under) | line | proposed | **book_a**: Number Of Virtual Safety Cars |
| `race_win_margin` | Winning margin (buckets) | line | proposed | **book_a**: Race Winning Margin |
| `race_n_leaders` | Number of race leaders (buckets) | line | proposed | **book_a**: Number Of Race Leaders |
| `race_win_nation` | Winning nationality | line | proposed | **book_a**: Winning Nationality |
| `race_sprint_win` | Sprint race winner | driver | exists | **book_a**: Sprint Race Winner; Sprint winner (ledger); **book_c**: Odds to win F1 Sprint - Singapore GP 2026; **kalshi**: KXF1RACESPRINT |
| `race_sprint_pole` | Sprint qualifying winner | driver | exists | **book_a**: Sprint Qualifying Winner; sprint qualifying winner (ledger); **kalshi**: KXF1SPRINTPOLE |
| `race_sprint_constructor_win` | Sprint winning constructor | team | proposed | **book_a**: Sprint Race Winning Constructor; **kalshi**: sprint top constructor (unmodeled) |
| `qual_constructor_win` | Qualifying winning constructor | team | proposed | **book_a**: Qualifying Winning Constructor |
| `fp1_win` | FP1 fastest driver | driver | proposed | **book_a**: 1st Practice Winner; FP1 winner (ledger, Singapore 2026); **polymarket**: fastest lap in practice (docs/f1-live-roadmap.md:178) |
| `fp1_constructor_win` | FP1 fastest constructor | team | proposed | **book_a**: 1st Practice Winning Constructor |
| `session_win_margin` | Session winning margin (buckets), parameter: session | line | proposed | **book_a**: 1st Practice Winning Margin; Qualifying Winning Margin; Sprint Qualifying Winning Margin; Sprint Race Winning Margin |
| `champion` | Drivers' champion | driver | exists | **kalshi**: KXF1; **polymarket**: F1 Drivers' Champion; **og**: F1-00001-2026 |
| `constructors_champion` | Constructors' champion | team | exists | **kalshi**: KXF1CONSTRUCTORS; **polymarket**: F1 Constructors' Champion; **og**: F1-00002-2026 |
| `standings_h2h` | Season head-to-head, drivers (finishes ahead in the standings) | pair | exists | **book_c**: F1 season matchup - Drivers Championship 2026; **polymarket**: Will A finish ahead of B in the YYYY Drivers' Championship? |
| `standings_h2h_constructors` | Season head-to-head, constructors | pair | proposed | **book_c**: F1 season matchup - Constructors Championship 2026 |
| `season_wins_ge` | Season wins at least N | driver | exists | **polymarket**: Will X win N+ Grands Prix in YYYY? |
| `standings_top3` | Top 3 in the standings | driver | exists | none seen |
