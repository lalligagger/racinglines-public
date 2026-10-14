"""Jev desk: synthetic data only, no DB, no network."""
import copy
import math
from types import SimpleNamespace

import pytest

from racinglines.research import jev_desk as D

EVENTS = ["Aus", "Chi", "Jap", "Brit", "Ita"]


def wk(rnd, ev, pnl):
    d = {"round": rnd, "event_key": f"y-{rnd}", "event": ev}
    for m in D.TAKER_MODES:
        d[f"{m}_pnl"] = pnl if m == "update" else pnl * 2
        d[f"{m}_bought"] = 10.0
    d["maker_pnl"] = 999.0
    return d


def run(rid, year, pnls, kelly=None, n_sims=1000, variant="v", events=EVENTS):
    return {"id": rid, "year": year,
            "params": {"year": year, "mode": "update", "kelly": kelly, "n_sims": n_sims, "variant": variant,
                       "label": f"l{rid}", "rounds": 9, "min_edge": 0.1},
            "weekends": [wk(i + 1, events[i], p) for i, p in enumerate(pnls)]}


def runs_basic():
    return [run(1, 2025, [10, -5, 20, 0, 5]), run(2, 2026, [100, 200, -50, 30, 10])]


def test_menu_needs_both_years_and_four_modes():
    menu, rep = D.build_menu(runs_basic() + [run(3, 2026, [1, 2], variant="solo")], 10000)
    assert {c["mode"] for c in menu} == set(D.TAKER_MODES)
    assert len(menu) == 4 and rep["candidates"] == 4
    assert any("only current" in s for s in rep["skipped"])


def test_menu_highest_nsims_and_kelly_separate():
    runs = runs_basic() + [run(4, 2026, [7, 7, 7, 7, 7], n_sims=5000), run(5, 2025, [1, 1, 1, 1, 1], n_sims=5000)]
    runs += [run(6, 2025, [10, -5, 20, 0, 5], kelly=0.5), run(7, 2026, [100, 200, -50, 30, 10], kelly=0.5)]
    menu, rep = D.build_menu(runs, 10000)
    assert len(menu) == 8 and rep["kelly_candidates"] == 4
    flat = [c for c in menu if c["kelly"] is None and c["mode"] == "update"][0]
    assert flat["n_sims"] == 5000 and flat["series"][2026][1]["pnl"] == 7
    assert "maker" not in str(flat["series"])
    hold = [c for c in menu if c["kelly"] is None and c["mode"] == "hold"][0]
    assert hold["series"][2026][1]["pnl"] == 14


def test_flat_accounting_dollars_unchanged_and_bankroll():
    for b in (10000, 20000):
        menu, _ = D.build_menu(runs_basic(), b)
        c = [c for c in menu if c["mode"] == "update"][0]
        weeks = D.weeks_of(menu)
        ans = {(rd, x["key"]): 1.0 if x is c else 0.0 for rd, _ in weeks for x in menu}
        walk, _ = D.run_walk_forward(menu, ans, b, 1, weeks, 2026)
        assert walk["Jev"]["weekly_pnl"] == [100, 200, -50, 30, 10]
        assert c["series"][2026][1]["ret"] == pytest.approx(100 / b)


def test_kelly_return_on_running_balance():
    r = [run(1, 2025, [0] * 5, kelly=0.5), run(2, 2026, [1000, -550, 330, 0, 0], kelly=0.5)]
    menu, _ = D.build_menu(r, 10000)
    c = [c for c in menu if c["mode"] == "update"][0]
    s = c["series"][2026]
    assert s[1]["ret"] == pytest.approx(0.10)
    assert s[2]["ret"] == pytest.approx(-550 / 11000)       # -5%
    assert s[3]["ret"] == pytest.approx(330 / 10450)        # balance 10450
    # applied to a 20000 bankroll running balance (not stored dollars)
    menu2, _ = D.build_menu(r, 20000)
    c2 = [c for c in menu2 if c["mode"] == "update"][0]
    assert c2["series"][2026][1]["ret"] == pytest.approx(0.05)
    weeks = D.weeks_of(menu)
    ans = {(rd, x["key"]): 1.0 if x is c else 0.0 for rd, _ in weeks for x in menu}
    p = D.run_walk_forward(menu, ans, 20000, 1, weeks, 2026)[0]["Jev"]["path"]
    assert p[1] == pytest.approx(20000 * 1.10)              # Kelly: return applied to the running bankroll
    assert p[2] == pytest.approx(p[1] * (1 - 550 / 11000))


def test_leakage_future_rounds_do_not_change_state():
    menu, _ = D.build_menu(runs_basic(), 10000)
    c = [x for x in menu if x["mode"] == "update"][0]
    base = D.week_state(c, 3, "Jap")
    mut = copy.deepcopy(c)
    for r in (3, 4, 5):
        mut["series"][2026][r].update(pnl=-12345.0, ret=-0.9, event="ZZZ")
    assert D.week_state(mut, 3, "Jap") == base
    assert "12345" not in str(base) and "ZZZ" not in str(base)
    assert base["season_current_so_far"]["rounds"] == [1, 2]
    # same event in the previous season comes only from that season
    assert base["same_event_previous_season_return_pct"] == pytest.approx(100 * 20 / 10000)
    assert D.week_state(c, 3, "Nope")["same_event_previous_season_return_pct"] is None


def test_picks_tiebreak_and_k_split():
    r = [run(1, 2025, [1, 1, 1, 1, 1]), run(2, 2026, [100, 100, 100, 100, 100]),
         run(3, 2025, [1, 1, 1, 1, 1], variant="w"), run(4, 2026, [10, 10, 10, 10, 10], variant="w")]
    menu, _ = D.build_menu(r, 10000)
    weeks = D.weeks_of(menu)
    answers = {(rd, c["key"]): 0.5 for rd, _ in weeks for c in menu}
    w1, _ = D.run_walk_forward(menu, answers, 10000, 1, weeks)
    assert w1["Jev"]["picks"][0] == [sorted(c["key"] for c in menu)[0]]
    w2, _ = D.run_walk_forward(menu, answers, 10000, 2, weeks)
    assert len(w2["Jev"]["picks"][0]) == 2
    top2 = w2["Jev"]["picks"][0]
    exp = sum(next(c for c in menu if c["key"] == k)["series"][2026][1]["pnl"] for k in top2) / 2
    assert w2["Jev"]["weekly_pnl"][0] == pytest.approx(exp)


def test_auc_and_bootstrap():
    assert D.week_auc([3, 2, 1, 0], [1, 1, 0, 0]) == 1.0
    assert D.week_auc([0, 1, 2, 3], [1, 1, 0, 0]) == 0.0
    assert D.week_auc([1, 1, 1, 1], [1, 0, 1, 0]) == 0.5
    assert math.isnan(D.week_auc([1, 2], [1, 1]))
    m, (lo, hi) = D.boot_mean([0.8, 0.9, 0.85, 0.95, 0.9, 0.8, 0.88, 0.92])
    assert lo > 0.5
    m, (lo, hi) = D.boot_mean([0.2, 0.9, 0.4, 0.8, 0.5, 0.3, 0.7, 0.55])
    assert lo < 0.5 < hi
    m, _ = D.boot_mean([float("nan"), 0.6, 0.8])
    assert m == pytest.approx(0.7)


def test_analyse_skips_one_class_weeks_and_decisions():
    r = []
    pn25 = [1, 1, 1, 1, 1]
    for i in range(6):
        pn = [50, -50, 50, -50, 50][: 5]
        r += [run(10 * i + 1, 2025, pn25, variant=f"v{i}"), run(10 * i + 2, 2026, pn if i % 2 else [50] * 5, variant=f"v{i}")]
    menu, _ = D.build_menu(r, 10000)
    weeks = D.weeks_of(menu)
    answers = {(rd, c["key"]): 1.0 if c["series"][2026][rd]["pnl"] > 0 else 0.0 for rd, _ in weeks for c in menu}
    walk, _ = D.run_walk_forward(menu, answers, 10000, 1, weeks)
    res = D.analyse(menu, answers, weeks, walk, 10000, 1, n_boot=500)
    assert res["weeks_valid"] == 2  # rounds 2 and 4 are the mixed weeks
    assert res["jev"][0] == 1.0
    assert "Not shown by this design" in D.format_report(res)


def test_plan_no_network_and_cache_hits(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "make_client", lambda: (_ for _ in ()).throw(AssertionError("network")))
    menu, _ = D.build_menu(runs_basic(), 10000)
    weeks = D.weeks_of(menu)
    p = D.plan(menu, weeks, cache_dir=tmp_path)
    assert p["requests"] == 20 and p["cached"] == 0
    rnd, key, state = D.requests_for(menu, weeks)[0]
    fake = SimpleNamespace(system_one=lambda **kw: SimpleNamespace(
        nouls={"profit": SimpleNamespace(noul=0.7)}, usage=SimpleNamespace(input_tokens=5, output_tokens=1), model="m"))
    D.ask_desk(state, client=fake, cache_dir=tmp_path)
    assert D.plan(menu, weeks, cache_dir=tmp_path)["cached"] == 1


def test_ask_desk_second_call_cached(tmp_path):
    calls = []

    def so(**kw):
        calls.append(1)
        return SimpleNamespace(nouls={"profit": SimpleNamespace(noul=0.7)},
                               usage=SimpleNamespace(input_tokens=5, output_tokens=1), model="m")
    client = SimpleNamespace(system_one=so)
    state = {"a": 1}
    a = D.ask_desk(state, client=client, cache_dir=tmp_path)
    b = D.ask_desk(state, client=None, cache_dir=tmp_path)
    assert a["p"] == b["p"] == 0.7 and len(calls) == 1
    assert a["usage"] == {"input_tokens": 5, "output_tokens": 1}
