"""Jev universe: synthetic runs only, no DB, no network."""
import copy
import json
import math

import numpy as np
import pytest

from racinglines.research import jev_universe as U

R25, R26 = 10, 6
NAMES25 = [f"GP{i}" for i in range(1, R25 + 1)]
NAMES26 = [f"GP{i}" for i in range(3, 3 + R26)]   # 2026 rounds 1..6 are the 2025 events GP3..GP8
MODES = ("update", "hold", "early", "last")
EVENTS = {f"2026-{i:02d}": {"name": NAMES26[i - 1], "date": f"2026-0{i}-15"} for i in range(1, R26 + 1)}


def wk(rnd, name, key, pnls, fmt, bought):
    d = {"round": rnd, "event_key": key, "event": name, "format": fmt}
    for m in MODES:
        d[f"{m}_pnl"] = pnls[m]
        d[f"{m}_bought"] = bought
    d["maker_pnl"] = 999.0
    return d


def run(rid, year, base, kelly=None, n_sims=1000, variant="v", min_edge=0.1, scale=1.0, seed=0):
    rng = np.random.default_rng(seed)
    n = R25 if year == 2025 else R26
    names = NAMES25 if year == 2025 else NAMES26
    ws = []
    for i in range(n):
        pnls = {m: float(base[i] * scale * (1 + 0.1 * k) + rng.normal(0, 120)) for k, m in enumerate(MODES)}
        fmt = "sprint" if i % 3 == 0 else "conventional"
        ws.append(wk(i + 1, names[i], f"{year}-{i + 1:02d}", pnls, fmt, 100.0 + 1.2345 * i + rid))
    return {"id": rid, "year": year, "weekends": ws,
            "params": {"year": year, "mode": "update", "kelly": kelly, "n_sims": n_sims, "variant": variant,
                       "label": f"l{rid}", "rounds": 9, "min_edge": min_edge}}


def synth_runs(n_cfg=8, seed=5):
    rng = np.random.default_rng(seed)
    runs = []
    rid = 1
    for c in range(n_cfg):
        b25 = rng.normal(40, 150, R25)
        b26 = rng.normal(40, 150, R26)
        kelly = [None, None, 0.25, 0.5][c % 4]
        for yr, b in ((2025, b25), (2026, b26)):
            runs.append(run(rid, yr, b, kelly=kelly, variant=f"v{c}", min_edge=0.1 + 0.01 * c, seed=rid))
            rid += 1
    return runs


def mutate(runs, r):
    """Change EVERY 2026 value at rounds >= r: NaN, None, huge, negative, per cell."""
    out = copy.deepcopy(runs)
    bad = [float("nan"), 1e12, -7.77e6, 123456.789]
    k = 0
    for run_ in out:
        if run_["year"] != 2026:
            continue
        for w in run_["weekends"]:
            if w["round"] < r:
                continue
            for m in MODES:
                k += 1
                w[f"{m}_bought"] = bad[k % 4]
                # None only on odd rounds, so a strategy never loses all of its 2026 rounds
                w[f"{m}_pnl"] = None if (w["round"] % 2 == 1 and k % 3 == 0 and w["round"] < R26) else bad[(k + 1) % 4]
    return out


def uni(runs=None):
    return U.Universe.from_runs(runs or synth_runs(), EVENTS)


# ---------------------------------------------------------------- accounting

def test_flat_return_is_pnl_over_reference_regardless_of_bankroll():
    runs = [run(1, 2025, [10] * R25), run(2, 2026, [100, 200, -50, 30, 10, 5])]
    u = U.Universe.from_runs(runs)
    sid = [s for s in u.ids if u.describe(s).find("update mode") >= 0][0]
    pnl = {w["round"]: w["update_pnl"] for w in runs[1]["weekends"]}
    for r, p in pnl.items():
        assert u.ret(sid, 2026, r) == pytest.approx(p / 10_000.0)
    assert U.REFERENCE_BANKROLL == 10_000.0


def test_kelly_return_uses_own_start_of_week_balance():
    r26 = run(2, 2026, [0] * R26, kelly=0.25)
    pnls = [1000.0, -2000.0, 500.0, 0.0, 0.0, 0.0]
    for w, p in zip(r26["weekends"], pnls):
        w["update_pnl"] = p
    r25 = run(1, 2025, [10] * R25, kelly=0.25)
    u = U.Universe.from_runs([r25, r26])
    sid = [s for s in u.ids if "update mode" in u.describe(s)][0]
    assert u.ret(sid, 2026, 1) == pytest.approx(1000 / 10000)
    assert u.ret(sid, 2026, 2) == pytest.approx(-2000 / 11000)
    assert u.ret(sid, 2026, 3) == pytest.approx(500 / 9000)
    assert u.total(sid, 2026, upto=3) == pytest.approx(1000 / 10000 - 2000 / 11000)
    assert u.total(sid, 2026) == pytest.approx(1000 / 10000 - 2000 / 11000 + 500 / 9000)


def test_round_key_r_is_accepted_and_ids_are_stable_and_sorted():
    runs = synth_runs()
    for run_ in runs:
        for w in run_["weekends"]:
            w["r"] = w.pop("round")
    u = uni(runs)
    assert u.ids == [f"S{i:04d}" for i in range(1, len(u.ids) + 1)]
    assert len(u.ids) == 8 * 4
    assert u.ids == uni().ids
    assert u.rounds() == list(range(1, R26 + 1))
    assert u.rounds(2025) == list(range(1, R25 + 1))
    assert u.meta()["strategies"] == 32 and u.meta()["kelly"] == 16


# ---------------------------------------------------------------- leak guards

@pytest.mark.parametrize("r", range(1, R26 + 1))
def test_mutation_leak(r):
    runs = synth_runs()
    a, b = uni(runs), uni(mutate(runs, r))
    pa, pb = a.view(r).packages, b.view(r).packages
    assert json.dumps(pa) == json.dumps(pb)
    assert json.dumps(a.view(r).shortlist_ids) == json.dumps(b.view(r).shortlist_ids)
    assert pa["shortlist"]    # not vacuous


def test_future_values_would_change_the_shortlist_if_they_leaked():
    runs = synth_runs()
    r = 3
    a, b = uni(runs), uni(mutate(runs, r))
    # a naive "2026 total including the future" ranking differs, so the byte equality above is a real test
    top = lambda u: sorted(u.ids, key=lambda s: (-(u.total(s, 2026) if math.isfinite(u.total(s, 2026)) else -9), s))[:10]
    assert top(a) != top(b)


@pytest.mark.parametrize("r", range(1, R26 + 1))
def test_canaries_absent_from_packages(r):
    u = uni()
    can = u.canaries(r)
    assert can
    blob = json.dumps(u.view(r).packages)
    assert not [c for c in can if c in blob]


def test_canary_guard_can_fail():
    u = uni()
    r = 2
    leaky = copy.deepcopy(u.view(r).packages)
    sid = u.ids[0]
    leaky["notes"]["oops"] = repr(float(u.ret(sid, 2026, r)))
    blob = json.dumps(leaky)
    assert [c for c in u.canaries(r) if c in blob]


def test_view_has_no_reference_to_universe_or_future():
    u = uni()
    r = 3
    v = u.view(r)
    assert set(vars(v)) == {"round_no", "packages", "shortlist_ids"}
    blob = json.dumps(v.packages)
    before = json.dumps(v.packages)
    for c in u.canaries(r):
        assert c not in blob
    del u
    assert json.dumps(v.packages) == before
    import gc
    gc.collect()
    assert not any(isinstance(o, U.Universe) for o in gc.get_referents(v, *vars(v).values()))


def test_event_package_has_only_calendar_facts_for_round_r():
    u = uni()
    e = u.view(1).packages["event"]
    assert e == {"name": "GP3", "round": 1, "date": "2026-01-15", "format": "sprint", "raced_last_season": True,
                 "rounds_raced": 0}
    e4 = u.view(4).packages["event"]
    assert e4["rounds_raced"] == 3 and e4["round"] == 4


# ---------------------------------------------------------------- shortlist

def test_shortlist_cap_size_and_deterministic():
    runs = synth_runs(n_cfg=40, seed=2)
    u = uni(runs)
    v1, v2 = u.view(5), u.view(5)
    assert json.dumps(v1.packages) == json.dumps(v2.packages)
    sl = v1.packages["shortlist"]
    assert 0 < len(sl) <= 40
    assert [r["id"] for r in sl] == v1.shortlist_ids
    for k in ("event", "family_summary", "shortlist", "notes"):
        assert len(json.dumps(v1.packages[k])) <= 8000
    assert v1.packages["notes"]["shortlist_cut_by_size_cap"] > 0 or len(sl) == v1.packages["notes"]["criteria_hit_pool"]
    # ordered by criteria hit, then 2025 total
    keys = [(-len(r["c"]), -r["y25"]["tot"], r["id"]) for r in sl]
    assert keys == sorted(keys)


def test_size_cap_cuts_tail_and_says_so_without_truncating_records():
    u = uni(synth_runs(n_cfg=40, seed=2))
    pk = u.view(6).packages
    n = pk["notes"]
    assert n["shortlist_cut_by_size_cap"] + len(pk["shortlist"]) == min(n["criteria_hit_pool"], 40)
    assert n["shortlist_cut_by_size_cap"] > 0
    json.loads(json.dumps(pk["shortlist"]))     # whole records only
    assert all(set(r) >= {"id", "set", "cl", "y25", "y26", "l4", "ly", "spr", "con", "w25", "w26"}
               for r in pk["shortlist"])


def test_clone_collapse_keeps_highest_nsims_then_lowest_id_and_shows_cluster_size():
    runs = synth_runs(n_cfg=4)
    # config 0 gets a clone: same pnl shape x2, different variant name, higher n_sims
    base25 = [r for r in runs if r["year"] == 2025 and r["params"]["variant"] == "v0"][0]
    base26 = [r for r in runs if r["year"] == 2026 and r["params"]["variant"] == "v0"][0]
    for src, rid in ((base25, 900), (base26, 901)):
        c = copy.deepcopy(src)
        c["id"] = rid
        c["params"]["variant"] = "clone"
        c["params"]["n_sims"] = 5000
        for w in c["weekends"]:
            for m in MODES:
                w[f"{m}_pnl"] = w[f"{m}_pnl"] * 2.0 + 1.0
        runs.append(c)
    u = uni(runs)
    clone_ids = [s for s in u.ids if "variant clone" in u.describe(s)]
    orig_ids = [s for s in u.ids if "variant v0," in u.describe(s)]
    pk = u.view(4).packages
    shown = {r["id"]: r for r in pk["shortlist"]}
    for m_c, m_o in zip(clone_ids, orig_ids):
        assert m_o not in shown                 # lower n_sims member is collapsed away
    in_list = [r for r in pk["shortlist"] if r["id"] in clone_ids]
    assert in_list and all(r["cl"] == 2 for r in in_list)
    assert pk["notes"]["collapsed_as_clones"] == 4


def test_clone_needs_eight_common_weeks():
    runs = synth_runs(n_cfg=2)
    # rounds before r=1: only 2025 (10 weeks) so clustering is possible; fewer than 8 weeks -> not clustered
    base = runs[0]
    c25 = copy.deepcopy(base)
    c25["id"], c25["params"]["variant"] = 800, "twin"
    c25["weekends"] = c25["weekends"][:5]
    ids = ["a", "b"]
    s = {"a": {(2025, i): 0.01 * i for i in range(1, 6)}, "b": {(2025, i): 0.02 * i for i in range(1, 6)}}
    assert U._clusters(ids, s) == {"a": "a", "b": "b"}
    s = {"a": {(2025, i): 0.01 * i for i in range(1, 9)}, "b": {(2025, i): 0.02 * i for i in range(1, 9)}}
    assert U._clusters(ids, s) == {"a": "a", "b": "a"}


def test_week_one_skips_2026_criteria_and_uses_2025_final_four():
    u = uni()
    pk = u.view(1).packages
    assert "t26" in pk["notes"]["criteria_skipped"]
    for r in pk["shortlist"]:
        assert "t26" not in r["c"]
        assert r["y26"] is None and r["w26"] == []
        sid = r["id"]
        last4 = [round(100 * u.ret(sid, 2025, k), 1) for k in range(R25 - 3, R25 + 1)]
        assert r["l4"] == last4
    pk2 = u.view(2).packages
    assert "t26" not in pk2["notes"]["criteria_skipped"]


def test_same_event_last_season_and_format_means():
    u = uni()
    pk = u.view(3).packages     # round 3 = GP5, which was 2025 round 5
    for r in pk["shortlist"]:
        assert r["ly"] == round(100 * u.ret(r["id"], 2025, 5), 1)


# ---------------------------------------------------------------- family summary

def test_family_summary_groups_by_mode_and_sizing_and_is_as_of():
    u = uni()
    r = 4
    fam = u.view(r).packages["family_summary"]
    assert {(f["mode"], f["sizing"]) for f in fam} == {(m, s) for m in MODES for s in ("flat", "kelly 0.25", "kelly 0.5")}
    for f in fam:
        ids = [s for s in u.ids if f"{f['mode']} mode" in u.describe(s) and
               (("flat stake" in u.describe(s)) if f["sizing"] == "flat" else (f["sizing"].replace("kelly", "Kelly fraction") in u.describe(s)))]
        assert f["n"] == len(ids)
        t26 = [u.total(s, 2026, upto=r) for s in ids]
        assert f["y26"]["best"] == round(100 * max(t26), 2)
        assert f["y26"]["worst"] == round(100 * min(t26), 2)
        assert f["y26"]["med"] == round(100 * float(np.median(t26)), 2)
        assert f["y26"]["pos"] == round(sum(t > 0 for t in t26) / len(t26), 2)
    assert all(f["y26"] is None for f in u.view(1).packages["family_summary"])


# ---------------------------------------------------------------- profile A

def _a(r):                                           # the documented profile A thresholds
    r["params"].update(min_edge_h2h=0.05, min_volume_24h=50.0)
    return r


def test_find_profile_a_only_for_exactly_one_match():
    def rs(extra_variant_runs=()):
        runs = [_a(run(1, 2025, [5] * R25, variant="gridq+pretrain+reset", n_sims=16000)),
                _a(run(2, 2026, [5] * R26, variant="gridq+pretrain+reset", n_sims=16000))]
        return runs + list(extra_variant_runs)
    u = uni(rs())
    sid = u.find_profile_a()
    assert sid and "update mode" in u.describe(sid) and "flat stake" in u.describe(sid)
    assert "venue polymarket" in u.describe(sid) and "min 24h volume 50" in u.describe(sid)
    # the same config on Kalshi, or with another volume floor, is not profile A
    k = [_a(run(5, 2025, [5] * R25, variant="gridq+pretrain+reset", n_sims=16000)),
         _a(run(6, 2026, [5] * R26, variant="gridq+pretrain+reset", n_sims=16000))]
    for e in k:
        e["params"]["settings"] = {"venue": "kalshi"}
        e["params"]["taker_fee"] = 0.07
    assert uni([*k]).find_profile_a() is None
    assert "venue kalshi" in uni([*k]).describe(uni([*k]).ids[0]) and "taker fee 0.07" in uni([*k]).describe(uni([*k]).ids[0])
    # a second matching config (another param differs, so another config) -> ambiguous -> None
    extra = [_a(run(3, 2025, [7] * R25, variant="gridq+pretrain+reset", n_sims=16000)),
             _a(run(4, 2026, [7] * R26, variant="gridq+pretrain+reset", n_sims=16000))]
    for e in extra:
        e["params"]["extra"] = "x"
    assert uni(rs(extra)).find_profile_a() is None
    assert uni(synth_runs()).find_profile_a() is None


def test_meta_reports_counts():
    m = uni().meta()
    assert m["strategies"] == 32 and "Blends" in m["note"] and "makers" in m["note"]
    assert m["n_sims"] == {"1000": 32}


def test_flat_sizing_drops_kelly_strategies():
    runs = synth_runs()
    allu, flat = uni(runs), U.Universe.from_runs(runs, None, sizing="flat")
    assert len(flat.ids) <= len(allu.ids)
    assert all("Kelly" not in flat.describe(s) for s in flat.ids)
    with pytest.raises(ValueError):
        U.Universe.from_runs(runs, None, sizing="half")


def test_untuned_subset_keeps_only_label_equals_variant_and_renumbers():
    runs = synth_runs()
    keep = {"v1", "v2", "v5"}
    for r in runs:
        if r["params"]["variant"] in keep:
            r["params"]["label"] = r["params"]["variant"]
    allu, sub = uni(runs), U.Universe.from_runs(runs, None, subset="untuned")
    assert allu.untuned_ids() and allu.untuned_ids() < set(allu.ids)
    assert len(sub.ids) == len(allu.untuned_ids()) == 12   # 3 variants x 4 taker modes
    assert sub.ids == [f"S{n:04d}" for n in range(1, len(sub.ids) + 1)]
    assert sub.untuned_ids() == set(sub.ids)
    assert {sub.describe(s).split(",")[0][8:] for s in sub.ids} <= keep
    assert sub.meta()["subset"] == "untuned" and allu.meta()["subset"] == "all"
    assert U.Universe.from_runs(runs, None, subset="all").ids == allu.ids


def test_untuned_subset_empty_when_no_label_matches_and_bad_value_raises():
    assert uni().untuned_ids() == set()
    assert U.Universe.from_runs(synth_runs(), None, subset="untuned").ids == []
    with pytest.raises(ValueError):
        U.Universe.from_runs(synth_runs(), None, subset="tuned")
