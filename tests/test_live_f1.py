"""F1 live private book (pipelines/live_f1.py): the market set, quotes, picks and the update plan on synthetic
data; and Baku's weekend (2026-15) run through the engine on a simulated clock, where the database has its
stage runs (skipped otherwise)."""

import json
import re

import numpy as np
import pandas as pd
import pytest

from racinglines import paths
from racinglines.markets import crowd as C
from racinglines.markets import quoting as Q
from racinglines.pipelines import live as LV
from racinglines.pipelines import live_f1 as F


def _preds(n=22, seed=0):
    rng = np.random.default_rng(seed)
    w = rng.dirichlet(np.ones(n) * 0.7)
    order = np.argsort(-w)
    ids = list(range(100, 100 + n))
    teams = [f"team{i // 2}" for i in range(n)]
    strength = {ids[i]: w[i] for i in range(n)}
    h2h = {a: {str(b): strength[a] / (strength[a] + strength[b]) for b in ids if b != a} for a in ids}
    return pd.DataFrame(dict(athlete_id=ids, driver=[f"Driver {chr(65 + i)}" for i in range(n)], team_key=teams,
                             win_prob=w, podium_prob=np.minimum(1, 3 * w / w.sum()), pole_prob=w[order][np.argsort(order)],
                             h2h=[h2h[i] for i in ids])), {t: 1 / (n // 2) for t in set(teams)}


@pytest.mark.quick
def test_market_set_sums_and_pairs():
    preds, ctor = _preds()
    pairs = [(100, 101), (102, 103), (104, 999)]                  # 999 isn't in the field: left out
    m = F.market_set(preds, ctor, pairs)
    kinds = pd.Series([x["kind"] for x in m]).value_counts().to_dict()
    assert kinds == {"race_win": 22, "race_podium": 22, "race_pole": 22, "race_h2h": 2, "race_constructor_top": 11}
    sums, dev = F.group_sums(m)
    assert sums["race_win"] == pytest.approx(1) and sums["race_pole"] == pytest.approx(1)
    assert sums["race_constructor_top"] == pytest.approx(1) and dev < 1e-12
    h = next(x for x in m if x["key"] == "race_h2h:100:101")
    assert h["params"] == {"opponent_id": 101} and h["subject"] == "Driver A vs Driver B"
    assert len({x["key"] for x in m}) == len(m)
    only = F.market_set(preds, ctor, pairs, kinds=("race_win",))
    assert {x["kind"] for x in only} == {"race_win"}


@pytest.mark.quick
def test_quotes_skip_decided_and_lean_against_the_takers_picks():
    preds, ctor = _preds()
    m = F.market_set(preds, ctor, [])
    book = C.new_book(C.Params(takers=10))
    qp = Q.Params()
    q0 = {q["key"]: q for q in F.quotes_for(m, book, [], qp, 0.02)}
    top = max(m, key=lambda x: x["fair"] if x["kind"] == "race_win" else -1)
    picks = [dict(key=top["key"], shares=500.0, stake=100.0)]
    q1 = {q["key"]: q for q in F.quotes_for(m, book, picks, qp, 0.02, decided={f"race_pole:{top['athlete_id']}"})}
    assert q1[top["key"]]["inv"] == -500 and q1[top["key"]]["ask"] >= q0[top["key"]]["ask"]      # short: quotes move up
    assert q1[f"race_pole:{top['athlete_id']}"]["bid"] is None and q1[f"race_pole:{top['athlete_id']}"]["ask"] is None


@pytest.mark.quick
def test_hype_picks_are_bought_at_the_ask():
    preds, ctor = _preds()
    m = F.market_set(preds, ctor, [(100, 101)])
    quotes = F.quotes_for(m, C.new_book(C.Params(takers=10)), [], Q.Params(), 0.03)
    spec = [dict(name="Driver A", market="race_win", hype=5, why="x"),
            dict(name="Driver A", market="race_h2h", vs="Driver B", hype=3, why="y"),
            dict(name="team3", market="race_constructor_top", hype=4, why="z"),
            dict(name="Nobody", market="race_win", hype=1, why="not entered")]
    picks = F.make_picks(m, quotes, spec, 25.0, "2026-10-02T03:30:00+00:00")
    qs = {q["key"]: q for q in quotes}
    assert [p["key"] for p in picks] == ["race_win:100", "race_h2h:100:101", "race_constructor_top:team3"]
    for p in picks:
        assert p["price"] == qs[p["key"]]["ask"] and p["shares"] == pytest.approx(25.0 / p["price"], abs=0.01)


@pytest.mark.quick
def test_live_market_prices_include_exchange_links():
    mkts = [
        dict(key="race_win:100", kind="race_win", athlete_id=100, params=None, subject="Driver A", fair=0.33),
        dict(key="race_h2h:100:101", kind="race_h2h", athlete_id=100, params={"opponent_id": 101},
             subject="Driver A vs Driver B", fair=0.58),
    ]
    links = pd.DataFrame([
        dict(exchange="polymarket", prediction="race_win", athlete_id=100, params=None, last_price=0.45,
             last_bid=0.42, last_ask=0.48),
        dict(exchange="kalshi", prediction="race_win", athlete_id=100, params=None, last_price=0.41,
             last_bid=0.39, last_ask=0.43),
        dict(exchange="coinbase", prediction="race_h2h", athlete_id=100, params={"opponent_id": 101},
             last_price=0.60, last_bid=0.58, last_ask=0.62),
    ])
    out = F.attach_exchange_prices(mkts, links)
    assert {v["code"] for v in out[0]["exchange_prices"]} == {"polymarket", "kalshi"}
    assert out[1]["exchange_prices"][0]["code"] == "coinbase"
    assert out[0]["exchange_prices"][0]["mid"] == pytest.approx(0.45)


@pytest.mark.quick
def test_coinbase_kalshi_market_diffs_are_logged():
    links = pd.DataFrame([
        dict(exchange="coinbase", prediction="race_win", athlete_id=100, params=None, last_price=0.44),
        dict(exchange="kalshi", prediction="race_win", athlete_id=100, params=None, last_price=0.53),
        dict(exchange="coinbase", prediction="race_win", athlete_id=101, params=None, last_price=0.22),
        dict(exchange="kalshi", prediction="race_win", athlete_id=101, params=None, last_price=0.20),
    ])
    diffs = F.compare_exchange_prices(links, threshold=0.05)
    assert len(diffs) == 1
    assert diffs[0]["diff"] == pytest.approx(0.09)
    assert diffs[0]["coinbase"] == pytest.approx(0.44) and diffs[0]["kalshi"] == pytest.approx(0.53)


@pytest.mark.quick
def test_update_plan_due_and_late():
    t = pd.Timestamp("2026-10-02 03:30")
    ups = [dict(label="pre-weekend", kind="open", at=t, qual=False),
           dict(label="after FP1", kind="stage", at=t + pd.Timedelta("2.5h"), qual=False),
           dict(label="after Quali", kind="stage", at=t + pd.Timedelta("30h"), qual=True),
           dict(label="lights out", kind="close", at=t + pd.Timedelta("51.5h"), qual=False)]
    st = dict(done=[dict(label="pre-weekend")])
    assert F.due(ups, st, t + pd.Timedelta("1h")) == []
    assert [u["label"] for u in F.due(ups, st, t + pd.Timedelta("31h"))] == ["after FP1", "after Quali"]   # merged into one
    assert F.late(ups, st, t + pd.Timedelta("4h")) is None
    assert F.late(ups, st, t + pd.Timedelta("5h"))["label"] == "after FP1"
    assert F.next_update(ups, st)["label"] == "after FP1"


@pytest.mark.quick
def test_f1_live_settings_are_data():
    live = LV.settings("f1")
    assert live["adapter"] == "racinglines.pipelines.live_f1" and live["poll"]["mode"] == "session_end"
    assert set(live["markets"]["kinds"]) == set(F.KINDS)
    hs = live["quoting"]["half_spread"]
    assert (hs["pre-weekend"], hs["after FP1"], hs["after FP2"], hs["after FP3"], hs["after Quali"]) == (0.03, 0.025, 0.025, 0.02, 0.02)
    assert "freeze" not in live                     # live books never freeze (owner rule, 2026-10-04)


# --- Baku through the engine (the local database's stored stage runs) ----------------------------------

def _baku_ready():
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    try:
        st = SS.Settings.from_dict(PF.PROFILES["C"]["settings"], strict=False)
        with get_engine().connect() as c:
            n = c.execute(text("""SELECT count(DISTINCT params->>'sweep_stage') FROM model_runs WHERE kind = 'diagnostic'
                                   AND params->>'model_key' = :m AND params->>'event_key' = '2026-15'"""),
                          dict(m=st.model_key)).scalar()
    except Exception as ex:                              # noqa: BLE001
        pytest.skip(f"no database: {ex}")
    if n < 5:
        pytest.skip("Baku's stage runs for profile C aren't in this database (the data bucket's dump has them)")


def test_baku_weekend_on_a_simulated_clock(tmp_path, monkeypatch):
    _baku_ready()
    monkeypatch.setattr(paths, "DATA", tmp_path)
    spec = LV.load_spec(paths.ROOT / "live" / "f1" / "2026-15.toml")
    ups, _ = F.plan("2026-15")
    assert [u["label"] for u in ups] == ["pre-weekend", "after FP1", "after FP2", "after FP3", "after Quali",
                                         "lights out", "results"]
    cache, snaps = {}, []
    t = ups[0]["at"] - pd.Timedelta("10min")
    while t <= ups[-1]["at"] + pd.Timedelta("1h"):
        s = F.step(spec, now=t, fetch=False, sync=False, alert=False, cache=cache, echo=lambda m: None)
        if s is not None:
            snaps.append(s)
        t += pd.Timedelta("30min")
    assert [s["update"]["label"] for s in snaps] == [u["label"] for u in ups]           # all seven, in order
    by = {s["update"]["label"]: s for s in snaps}
    assert by["pre-weekend"]["markets"] and len(by["pre-weekend"]["markets"]) >= 99
    assert by["pre-weekend"]["crowd"]["fills"] == 0
    kinds_at = lambda lab: {o["key"].split(":")[0] for o in by[lab]["outcomes"]}   # noqa: E731
    assert kinds_at("after FP3") == set() and kinds_at("after Quali") == {"race_pole"}             # pole after qualifying
    assert kinds_at("results") == set(F.KINDS) and by["results"]["done"]
    assert all("frozen" not in s for s in snaps)                                                  # never frozen
    assert all(m["bid"] is None and m["ask"] is None for m in by["lights out"]["markets"])        # closed at lights out
    quals = {m["key"]: (m["bid"], m["ask"]) for m in by["after Quali"]["markets"]}
    assert all(quals[k] == (None, None) for k in quals if k.startswith("race_pole:"))            # decided: not quoted
    assert any(b is not None for k, (b, a) in quals.items() if k.startswith("race_win:"))        # the rest requoted
    run = spec["run"]
    book = json.loads((LV.folder(run) / "book.json").read_text())
    rebuilt, polls = LV.book_at(run)
    assert set(rebuilt) == set(book["markets"])                                                   # the book reconciles
    for k, mk in book["markets"].items():
        assert rebuilt[k]["inv"] == pytest.approx(mk["inv"]) and rebuilt[k]["cash"] == pytest.approx(mk["cash"])
    assert sum(len(p["fills"]) for p in polls) == book["crowd"]["fills"] > 0
    res = by["results"]
    assert res["maker_pnl"]["crowd"] == pytest.approx(-res["crowd"]["results"]["total"])         # the crowd's loss
    assert F.step(spec, now=t + pd.Timedelta("1d"), fetch=False, sync=False, cache=cache) is None   # settled: idle
    assert len(LV.snap_times(run)) == 7 and LV.find(run)["sport"] == "f1"
    # the Live tab's F1 body, every update, maker and taker (takers never see fair values)
    from racinglines.web.app import templates
    from racinglines.web.views import live_context
    for t in LV.snap_times(run):
        for maker in (True, False):
            ctx = live_context(run, t, maker, 1)
            assert ctx["sport"] == "f1" and ctx["mode"] == "replay"
            html = templates.get_template("live_partial.html").render(ctx)
            assert "Top constructor" in html and not re.search(r">\s*nan\b|\bnan\s*<|None</td>", html, re.I)
            assert ("<th>Fair</th>" in html) == maker


# --- operations: the lock, the LaunchAgent, frozen settings, the lateness alert ---------------------------

@pytest.mark.quick
def test_lock_stops_overlapping_steps(tmp_path, monkeypatch):
    from racinglines.cli import live as CL
    monkeypatch.setattr(paths, "DATA", tmp_path)
    with CL.lock("ev") as a:
        with CL.lock("ev") as b:
            assert a and not b                           # a second step while one runs: skipped
    with CL.lock("ev") as c:
        assert c                                         # released


@pytest.mark.quick
def test_launch_agent_steps_every_five_minutes():
    from racinglines.cli import live as CL
    spec = LV.load_spec(paths.ROOT / "live" / "f1" / "2026-16.toml")
    xml = CL.plist(spec, root="/Users/x/racinglines")
    assert "<string>bet.racinglines.live.2026-16</string>" in xml
    assert "<key>StartInterval</key><integer>300</integer>" in xml
    assert "<string>live</string><string>step</string><string>live/f1/2026-16.toml</string>" in xml
    assert "/Users/x/racinglines/data/runs/live/2026-16/agent.log" in xml
    import plistlib
    assert plistlib.loads(xml.encode())["Label"] == "bet.racinglines.live.2026-16"


@pytest.mark.quick
def test_round_16_spec():
    spec = LV.load_spec("f1/2026-16")
    assert spec["event"] == spec["run"] == "2026-16" and spec["sport"] == "f1"
    assert len(spec["picks"]) == 12 and all(p["market"] in F.KINDS for p in spec["picks"])
    ups, w = F.plan("2026-16")
    assert w["name"] == "Bahrain Grand Prix" and [u["at"].isoformat() for u in ups] == [
        "2026-10-02T03:30:00", "2026-10-02T06:00:00", "2026-10-02T09:30:00", "2026-10-03T06:00:00",
        "2026-10-03T09:30:00", "2026-10-04T07:00:00", "2026-10-04T10:00:00"]      # the plan's times (UTC)
    assert spec["window"]["open"] == "2026-10-02T03:30:00" and spec["window"]["close"] == "2026-10-04T07:00:00"


@pytest.mark.quick
def test_settings_freeze_at_the_opening(tmp_path):
    spec = LV.load_spec(paths.ROOT / "live" / "f1" / "2026-16.toml")
    assert F.frozen_settings(spec, tmp_path) == spec["live"]                      # not opened yet: the spec's
    (tmp_path / "meta.json").write_text(json.dumps(dict(settings=spec["live"])))
    changed = LV.merge(spec, dict(live=dict(quoting=dict(max_pos=10.0))))
    said = []
    assert F.frozen_settings(changed, tmp_path, echo=said.append)["quoting"]["max_pos"] == 2500.0
    assert "frozen" in said[0]
    assert F.frozen_settings(changed, tmp_path, unfreeze=True, echo=said.append)["quoting"]["max_pos"] == 10.0


def test_lateness_alert_once_per_update(tmp_path, monkeypatch):
    try:
        from racinglines.db.config import get_engine
        with get_engine().connect():
            pass
    except Exception as ex:                              # noqa: BLE001
        pytest.skip(f"no database: {ex}")
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(F, "_stage_runs", lambda *a, **k: [])          # the stage run never arrives
    spec = LV.load_spec(paths.ROOT / "live" / "f1" / "2026-16.toml")
    said = []
    assert F.step(spec, now="2026-10-02T04:00", fetch=False, alert=False, echo=said.append) is None
    assert not any("LATE" in m for m in said)                                   # 30 min: waiting, not late
    assert F.step(spec, now="2026-10-02T05:45", fetch=False, alert=False, echo=said.append) is None
    assert sum("LATE" in m for m in said) == 1 and "pre-weekend" in said[-1]
    F.step(spec, now="2026-10-02T05:50", fetch=False, alert=False, echo=said.append)
    assert sum("LATE" in m for m in said) == 1                                  # once per update
    assert F.status(spec, "2026-10-02T06:30")["late_h"] == 3.0


@pytest.mark.quick
def test_singapore_is_a_sprint_weekend():
    ups, w = F.plan("2026-17")
    assert [u["label"] for u in ups] == ["pre-weekend", "after FP1", "after SQ", "after Sprint", "after Quali",
                                         "lights out", "results"]
    assert [u["label"] for u in ups if u["qual"]] == ["after Quali"]
    hs = LV.settings("f1")["quoting"]["half_spread"]
    assert all(u["label"] in hs for u in ups if u["kind"] in ("open", "stage"))    # a spread for every stage
    spec = LV.load_spec("f1/2026-17")
    assert spec["window"]["open"] == "2026-10-09T07:30:00" and spec["window"]["close"] == "2026-10-11T12:00:00"


@pytest.mark.quick
@pytest.mark.parametrize("path", sorted((paths.ROOT / "live" / "f1").glob("2026-*.toml")), ids=lambda p: p.stem)
def test_every_2026_launch_spec_loads(path):
    """Every committed 2026 spec loads, names its own event, has picks on known markets and, when it has a
    window, matches the schedule's plan (opening at the pre-weekend cut-off, closing at lights out)."""
    spec = LV.load_spec(path)
    assert spec["sport"] == "f1" and spec["event"] == path.stem
    assert spec["picks"] and all(p["market"] in F.KINDS for p in spec["picks"])
    ups, w = F.plan(spec["event"])
    assert ups[0]["label"] == "pre-weekend" and ups[-2]["label"] == "lights out" and ups[-1]["label"] == "results"
    assert all(u["at"] < w["race_start"] for u in ups if u["kind"] in ("open", "stage"))   # no stage after lights out
    if "window" in spec:
        assert spec["window"]["open"] == ups[0]["at"].isoformat()
        assert spec["window"]["close"] == ups[-2]["at"].isoformat() == w["race_start"].isoformat()
        assert spec["window"]["results"] == ups[-1]["at"].isoformat()
