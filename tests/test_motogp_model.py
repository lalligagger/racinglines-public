import pandas as pd

from racinglines.core import walk_forward as WF
from racinglines.models import race_model as RM


def _motogp_data():
    rows = []
    riders = [f"r{i:02d}" for i in range(1, 11)]
    for season in (2024, 2025, 2026):
        for race_idx in range(1, 5):
            base = [0.7 * (i % 5) + 0.25 * (season - 2024) for i in range(len(riders))]
            order = sorted(range(len(riders)), key=lambda i: base[i] + (race_idx * 0.05 * i))
            for pos, rider_idx in enumerate(order, 1):
                date = pd.Timestamp(f"{season}-04-{1 + race_idx * 7}")
                rows.append(dict(
                    season=season,
                    race=f"{season}-{race_idx}",
                    date=date,
                    rider=riders[rider_idx],
                    position=pos,
                    team=f"team-{(rider_idx % 3) + 1}",
                    status="OK",
                    points=25 if pos == 1 else 0,
                ))
    return pd.DataFrame(rows)


def test_motogp_model_runs_through_the_backtest_engine():
    model = RM.get("motogp")
    data = _motogp_data()
    settings = model.Settings.from_dict({"sims": 200, "shrink": 2.0, "noise": 0.75, "seed": 7})

    out = WF.run(model, data, settings, seasons=[2025, 2026], kinds=["race_win", "race_podium", "race_h2h"])

    assert set(out["events"]["season"]) == {2025, 2026}
    assert len(out["events"]) >= 2
    assert out["calibration"].query("season == 'all' and kind == 'race_win'")["n"].iloc[0] > 0
