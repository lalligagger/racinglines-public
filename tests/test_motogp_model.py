import pandas as pd

from racinglines.core import walk_forward as WF
from racinglines.models import race_model as RM
from racinglines.models.motogp_model import MotoGPRaceChallenger


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
    model = RM.challenger("motogp", "motogp_recent_form")()
    data = _motogp_data()
    settings = model.Settings.from_dict({"sims": 200, "shrink": 2.0, "noise": 0.75, "seed": 7})

    out = WF.run(model, data, settings, seasons=[2025, 2026], kinds=["race_win", "race_podium", "race_h2h"])

    assert set(out["events"]["season"]) == {2025, 2026}
    assert len(out["events"]) >= 2
    assert out["calibration"].query("season == 'all' and kind == 'race_win'")["n"].iloc[0] > 0


def test_motogp_challenger_runs_and_tracks_recent_form():
    data = _motogp_data()
    baseline = RM.challenger("motogp", "motogp_recent_form")()
    challenger = MotoGPRaceChallenger()

    base_settings = baseline.Settings.from_dict({"sims": 200, "shrink": 2.0, "noise": 0.75, "seed": 7})
    chal_settings = challenger.Settings.from_dict({"sims": 200, "recent_races": 4, "team_bias": 0.5,
                                                "noise": 0.75, "seed": 7})

    base_out = WF.run(baseline, data, base_settings, seasons=[2025, 2026], kinds=["race_win"])
    chal_out = WF.run(challenger, data, chal_settings, seasons=[2025, 2026], kinds=["race_win"])

    base_win = base_out["calibration"].query("season == 'all' and kind == 'race_win'").iloc[0]
    chal_win = chal_out["calibration"].query("season == 'all' and kind == 'race_win'").iloc[0]

    assert int(chal_out["events"].shape[0]) >= 2
    assert chal_win["n"] > 0
    assert chal_win["logloss"] <= 0.25
    assert chal_out["rows"].query("kind == 'race_win'").shape[0] > 0


def test_motogp_challenger_accepts_broader_history_window():
    challenger = MotoGPRaceChallenger()
    settings = challenger.Settings.from_dict({"sims": 200, "recent_races": 4, "history_races": 12,
                                            "team_bias": 0.5, "noise": 0.75, "seed": 7})

    assert settings["history_races"] == 12
    assert settings["recent_races"] == 4


def test_motogp_search_grid_ranks_candidates_by_logloss():
    data = _motogp_data()
    candidates = [
        {"sims": 200, "recent_races": 2, "history_races": 4, "recency_decay": 1.5, "team_bias": 0.2, "noise": 0.75, "seed": 7},
        {"sims": 200, "recent_races": 4, "history_races": 12, "recency_decay": 2.5, "team_bias": 0.5, "noise": 1.0, "seed": 8},
    ]

    rows = MotoGPRaceChallenger().search_grid(data, seasons=[2025, 2026], settings_list=candidates, kinds=["race_win", "race_podium"])

    assert len(rows) == 2
    assert {"score", "race_win", "race_podium"}.issubset(rows.columns)
    assert rows["score"].notna().all()
