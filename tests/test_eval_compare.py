"""`racinglines eval compare` (racinglines/pipelines/eval_compare.py, engine roadmap E5): two saved runs paired by
event on their prediction records, scored with log loss and Brier, B - A with ±2 SE over events. Synthetic records
and results; no database (the end-to-end test prices the toy sport of tests/toy_backtest.py twice)."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from racinglines import sports
from racinglines.core import calibration as CAL
from racinglines.core import walk_forward as WF
from racinglines.db import records as REC
from racinglines.models import race_model as RM
from racinglines.pipelines import eval_compare as EC

pytestmark = pytest.mark.quick

EVENTS = {1: 2025, 2: 2025, 3: 2025, 4: 2026, 5: 2026}     # event 5 has no official result in the tests
ATHLETES = [10, 11, 12, 13]
KINDS = ("race_win", "race_podium")


def results_of(event_id):
    """Athlete 10 + (event mod 4) wins, then the others in id order (a classification in markets.kinds.settle's shape)."""
    order = [ATHLETES[(event_id + i) % 4] for i in range(4)]
    return pd.DataFrame(dict(athlete_id=order, position=[1.0, 2.0, 3.0, 4.0], status="OK", qual_position=np.nan,
                             team_id=None, points=0.0))


def results_for(sport, event_id):
    return None if str(event_id) == "5" else results_of(int(event_id))


def records(run_id, seed, drop=()):
    rng = np.random.default_rng(seed)
    rows = [dict(run_id=run_id, sport="toy", model_id="m", season=season, event_id=ev, event=f"e{ev}", stage="pre_race",
                 cutoff=pd.NaT, kind=kind, subject=str(a), params="{}", fair=float(rng.uniform(.02, .9)), se=.01, n_sims=1000)
            for ev, season in EVENTS.items() for kind in KINDS for a in ATHLETES]
    df = pd.DataFrame(rows)
    gone = df.apply(lambda r: (r["event_id"], r["kind"], r["subject"]) in drop, axis=1)
    return df[~gone].reset_index(drop=True)


def frames():
    a = records(1, seed=1)
    b = records(2, seed=2, drop={(3, "race_podium", "13")})              # B lacks one row ...
    extra = a[(a["event_id"] == 1) & (a["kind"] == "race_win") & (a["subject"] == "10")].assign(subject="99", fair=.5)
    return a, pd.concat([b, extra], ignore_index=True)                  # ... and has one A lacks


def test_pairing_counts_what_it_leaves_unpaired():
    a, b = frames()
    paired, counts = EC.pair(a, b)
    assert len(a) == len(b) == 40 and counts["paired"] == 39 == len(paired)
    assert counts["only_a"] == 1 and counts["only_a_kinds"] == {"race_podium": 1}
    assert counts["only_b"] == 1 and counts["only_b_kinds"] == {"race_win": 1}
    assert not ((paired["event_id"] == "3") & (paired["kind"] == "race_podium") & (paired["subject"] == "13")).any()
    # params compare as canonical JSON: a head-to-head's key order or a dict value is the same pair
    h = pd.DataFrame([dict(sport="toy", season=2025, event_id=1, event="e1", stage="s", kind="race_h2h", subject="10",
                           params=p, fair=.5, se=.01) for p in ('{"opponent_id": 11, "x": 1}',)])
    h2 = h.assign(params=[{"x": 1, "opponent_id": 11}])
    assert EC.pair(h, h2)[1]["paired"] == 1
    with pytest.raises(ValueError, match="share an"):
        EC.pair(pd.concat([a, a.iloc[:1]]), b)


def test_per_event_log_loss_is_the_hand_computation():
    a, b = frames()
    out = EC.settle_rows(EC.pair(a, b)[0], results_for)
    ev = EC.compare(out)
    one = out[(out["event_id"] == "1") & (out["kind"] == "race_win")]
    won = {int(s): float(int(s) == results_of(1)["athlete_id"].iloc[0]) for s in one["subject"]}
    assert sum(won.values()) == 1
    by = {s: (p, y) for s, p, y in zip(one["subject"], one["fair_a"], one["y"])}
    assert all(by[str(s)][1] == w for s, w in won.items())
    # athlete by athlete, with the clip of core/calibration.py
    ll = np.mean([-(y * np.log(np.clip(p, CAL.EPS, 1 - CAL.EPS)) + (1 - y) * np.log(1 - np.clip(p, CAL.EPS, 1 - CAL.EPS)))
                  for p, y in by.values()])
    br = np.mean([(p - y) ** 2 for p, y in by.values()])
    row = ev[(ev["event_id"] == "1") & (ev["kind"] == "race_win")].iloc[0]
    assert row["logloss_a"] == pytest.approx(ll) and row["brier_a"] == pytest.approx(br) and row["n"] == 4
    assert row["logloss_diff"] == pytest.approx(row["logloss_b"] - row["logloss_a"])
    # the event with no official result is counted as unsettled, not scored
    assert out["y"].isna().sum() == 8                  # event 5: 2 kinds x 4 athletes, paired but with no result
    assert "5" not in set(ev["event_id"])


def test_paired_se_over_events_is_the_std_of_the_differences():
    a, b = frames()
    out = EC.settle_rows(EC.pair(a, b)[0], results_for)
    ev, s = EC.compare(out), EC.summarize(EC.compare(out))
    d = ev[(ev["kind"] == "race_win") & (ev["season"] == 2025)]["logloss_diff"].to_numpy()
    r = s[(s["kind"] == "race_win") & (s["season"] == "2025")].iloc[0]
    assert len(d) == 3 == r["n_events"]
    assert r["logloss_se"] == pytest.approx(np.std(d, ddof=1) / np.sqrt(3))
    assert r["logloss_diff"] == pytest.approx(d.mean())
    assert r["logloss_outside"] == bool(abs(d.mean()) > 2 * np.std(d, ddof=1) / np.sqrt(3))
    pooled = ev[ev["kind"] == "race_win"]["brier_diff"].to_numpy()                   # all seasons: events 1-4
    p = s[(s["kind"] == "race_win") & (s["season"] == "all")].iloc[0]
    assert p["n_events"] == 4 == len(pooled) and p["brier_se"] == pytest.approx(np.std(pooled, ddof=1) / np.sqrt(4))
    one = s[(s["kind"] == "race_win") & (s["season"] == "2026")].iloc[0]            # a single event: no SE, never "outside"
    assert one["n_events"] == 1 and np.isnan(one["logloss_se"]) and not one["logloss_outside"]


def test_run_prints_the_table_and_writes_the_files(tmp_path, monkeypatch):
    a, b = frames()
    monkeypatch.setattr(REC, "read", lambda rid: {1: a, 2: b}[rid])
    lines = []
    res = EC.run(1, 2, kinds=["race_win"], out_dir=tmp_path / "o", echo=lines.append, results_for=results_for)
    text = "\n".join(lines)
    assert "| kind | season | n events | logloss A | logloss B | diff ± 2 SE | Brier A | Brier B | diff ± 2 SE |" in text
    assert "| race_win | all | 4 |" in text and "only in B: 1" in text
    assert set(res["summary"]["kind"]) == {"race_win"} and res["counts"]["paired"] == 20
    assert (tmp_path / "o" / "compare.csv").exists() and "| race_win |" in (tmp_path / "o" / "compare.md").read_text()
    with pytest.raises(ValueError, match="no prediction records"):
        monkeypatch.undo()
        EC.run(98765, 98766, write=False)


def test_cli_parses_eval_compare(monkeypatch):
    from racinglines import cli
    seen = {}
    monkeypatch.setattr(EC, "run", lambda *a, **k: seen.update(args=a, kw=k))
    assert cli.main(["eval", "compare", "1", "2", "--kinds", "race_win", "--stage", "pre_race", "--out", "x"]) == 0
    assert seen["args"] == (1, 2) and seen["kw"]["kinds"] == ["race_win"] and seen["kw"]["stage"] == "pre_race"
    assert seen["kw"]["out_dir"] == "x"


def test_mcp_helper_returns_the_summary_columns(monkeypatch):
    from racinglines.mcp import tools as T
    a, b = frames()
    monkeypatch.setattr(REC, "read", lambda rid: {1: a, 2: b}[rid])
    monkeypatch.setattr(EC, "db_results", lambda url=None: results_for)
    monkeypatch.setattr(T.data, "model_run", lambda conn, rid: dict(id=rid, competition="toy_cup"))
    monkeypatch.setattr(T, "_guard", lambda *a, **k: None)
    conn = SimpleNamespace(engine=SimpleNamespace(url=SimpleNamespace(render_as_string=lambda hide_password=False: "x")))
    out = T.compare_runs(conn, 1, 2, kinds="race_win, race_podium")
    assert out["paired"] == 39 and out["only_a"] == 1 and out["only_b"] == 1 and out["kinds"] == ["race_win", "race_podium"]
    rows = out["summary"]["rows"]
    assert set(EC.SUMMARY_COLUMNS) <= set(rows[0]) and {r["kind"] for r in rows} == {"race_win", "race_podium"}
    json.dumps(out)


# --- end to end on the toy sport: the outcomes are the walk-forward's own ---------------------------------------------

SCHEMA = """
[sport]
code = "toy_race"
name = "Toy race"
result_kind = "time"
model_family = "toy"
display_order = 9
pricing_model = "toy_backtest:ToyRace"

[competition]
code = "toy_cup"
name = "Toy Cup"
"""


@pytest.fixture
def toy(tmp_path, monkeypatch):
    (tmp_path / "sports").mkdir()
    for f in sports.SCHEMAS.glob("*.toml"):
        (tmp_path / "sports" / f.name).write_text(f.read_text())
    (tmp_path / "sports" / "toy_race.toml").write_text(SCHEMA)
    monkeypatch.setattr(sports, "SCHEMAS", tmp_path / "sports")
    monkeypatch.setenv(REC.ROOT_ENV, str(tmp_path / "records"))
    sports.load.cache_clear()
    yield tmp_path
    sports.load.cache_clear()


def test_outcomes_match_the_walk_forward_on_the_toy_sport(toy):
    m = RM.get("toy_race")
    data = m.load()
    kinds = ["race_win", "race_podium", "race_h2h"]
    outs = {}
    for run_id, seed in ((1, 3), (2, 4)):
        out = WF.run(m, data, m.Settings.from_dict(dict(seed=seed, sims=300)), kinds=kinds, echo=lambda s: None,
                     keep_sims=True)
        frames_ = [s.to_records(run_id, "toy_race", "toy_race", ev.season, ev.id, ev.name, "pre_race", ev.cutoff, kinds=kinds)
                   for ev, s in out["sims"]]
        REC.write(run_id, REC.concat(frames_))
        outs[run_id] = out
    res = EC.run(1, 2, out_dir=toy / "eval", echo=lambda s: None, results_for=EC.db_results())
    assert res["unsettled"] == 0 and res["counts"]["only_a"] == res["counts"]["only_b"] == 0
    truth = outs[1]["rows"].assign(opponent=lambda d: d["opponent"].where(d["opponent"].notna(), None))
    y = res["paired"].set_index(["kind", "event_id", "subject", "params"])["y"]
    for r in truth.itertuples():
        params = json.dumps({"opponent_id": r.opponent}) if r.kind == "race_h2h" else "{}"
        assert y[(r.kind, str(r.event_id), str(r.athlete_id), params)] == float(r.y)
    s = res["summary"]
    assert set(s["kind"]) == set(kinds) and (s["season"] == "all").sum() == 3
    assert (toy / "eval" / "compare.csv").exists()
