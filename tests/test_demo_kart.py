"""`racinglines demo` (racinglines/demo/kart.py, racinglines/cli/demo.py): the Mario Kart pipeline in four steps, on
small settings so it runs in seconds. Everything synthetic; no network, no database."""

import json

import numpy as np
import pytest

from racinglines.demo import kart as K

pytestmark = pytest.mark.quick


def test_engine_prices_a_coherent_race():
    cfg = K.load()
    races = K.history(cfg, seed=3, seasons=2)
    assert len(races) == 2 * len(cfg["tracks"])
    pace = K.fit(races, 4.0, 0.0)
    true = K.true_pace(cfg, 3, 2)[1]
    assert np.corrcoef(pace, true)[0, 1] > 0.6                   # the fit finds the fast karts
    pr = K.probs(K.finish(np.zeros(len(pace)), 0, cfg, cfg["tracks"]["mario-circuit"], pace, 4000,
                          np.random.default_rng(0)))
    assert pr["race_win"].sum() == pytest.approx(1.0) and pr["race_podium"].sum() == pytest.approx(3.0)
    assert int(np.argmax(pr["race_win"])) == int(np.argmax(pace))
    bt = K.backtest(cfg, races, sims=200, warmup=4, seed=3)
    assert bt["races"] == len(races) - 4 and len(bt["leaderboard"]) == len(K.HALF_LIVES) * len(K.SHRINKS)
    lb = bt["leaderboard"]
    assert all(a["win_logloss"] + a["podium_logloss"] <= b["win_logloss"] + b["podium_logloss"] for a, b in zip(lb, lb[1:]))


def test_the_four_steps_run_and_repeat(tmp_path, capsys):
    from racinglines.cli import demo as CLI
    out = str(tmp_path / "kart")
    with pytest.raises(SystemExit, match="demo backtest"):
        CLI.main(["forecast", "--out", out])                               # no model yet: says which step comes first
    assert CLI.main(["backtest", "--out", out, "--seasons", "2", "--sims", "100"]) == 0
    text = capsys.readouterr().out
    assert "Step 1 of 4" in text and "Walk-forward" in text and "baseline" in text
    model = json.loads((tmp_path / "kart" / "model.json").read_text())
    assert len(model["pace"]) == len(K.load()["drivers"])
    assert CLI.main(["forecast", "--out", out, "--sims", "20000"]) == 0
    fc = json.loads((tmp_path / "kart" / "forecast.json").read_text())
    assert sum(fc["race_win"]) == pytest.approx(1.0)
    assert "Rainbow Road: before the start" in capsys.readouterr().out
    assert CLI.main(["race", "--out", out, "--delay", "0"]) == 0
    text = capsys.readouterr().out
    assert "Finish" in text and "Wario's book" in text and "racinglines book price --demo" in text
    run = tmp_path / "kart" / "runs" / "live" / "kart-rainbow-road-7"
    snaps = sorted((run / "snaps").glob("*.json.gz"))
    assert len(snaps) == K.n_sectors(K.load()) + 1                         # the start, every sector
    latest = json.loads((run / "latest.json").read_text())
    assert latest["done"] and len(latest["outcomes"]) == 16
    assert sum(o["yes"] for o in latest["outcomes"]) == 1 + 3              # one winner, three on the podium
    md = (run / "report" / "report.md").read_text()
    assert "Wario's own book" in md and "100 simulated anonymous takers (Toads)" in md
    assert "demo taker" not in md                                          # no demo taker in this one
    pnl = latest["maker_pnl"]["total"]
    assert CLI.main(["race", "--out", out, "--delay", "0"]) == 0           # the same seed: the same race and fills
    assert json.loads((run / "latest.json").read_text())["maker_pnl"]["total"] == pytest.approx(pnl)
    assert len(sorted((run / "snaps").glob("*.json.gz"))) == len(snaps)    # a re-run starts clean
