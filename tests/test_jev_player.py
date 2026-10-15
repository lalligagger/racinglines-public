"""Jev as a fantasy player (racinglines/research/jev_player.py, reports/2026-10-15-jev-player/PREREG.md): synthetic data
only, no network, no database."""
import importlib.util
import json
import random
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from racinglines.pipelines import profiles as PF
from racinglines.research import jev_player as J

ROOT = Path(__file__).resolve().parent.parent
ROUNDS = list(range(1, 8))


def synth(seed=1, rounds=ROUNDS):
    rng = random.Random(seed)
    styles = {c: {r: dict(pnl=rng.uniform(-300, 400) + 1e-7 * rng.random(), bought=rng.uniform(50, 500),
                          event_key=f"2026-{r:02d}", name=f"GP {r}", format="sprint" if r % 3 == 0 else "conventional",
                          race_start=f"2026-0{min(r, 9)}-10 14:00:00")
                  for r in rounds} for c in J.CODES}
    players = []
    for uid in range(1, 13):
        code, sz = J.CODES[uid % 5], ("standard", "kelly 0.25", "kelly 0.5")[uid % 3]
        for r in rounds:
            if rng.random() < 0.7:
                players.append(dict(user_id=uid, round=r, style=code, sizing=sz, pnl=rng.uniform(-200, 300), settled=3))
    return styles, players


def mutate(styles, players, r):
    s = {c: {x: (dict(v, pnl=v["pnl"] * 7 + 13, bought=v["bought"] + 99) if x >= r else dict(v)) for x, v in d.items()}
         for c, d in styles.items()}
    p = [dict(q, pnl=q["pnl"] * -3 + 1) if q["round"] >= r else dict(q) for q in players]
    return s, p


def test_mutation_of_future_rounds_leaves_state_and_request_identical():
    styles, players = synth()
    cal = J.calendar_from_styles(styles)
    for r in ROUNDS:
        a = J.request_blob(J.state_for(styles, players, cal, r))
        s2, p2 = mutate(styles, players, r)
        b = J.request_blob(J.state_for(s2, p2, cal, r))
        assert a == b, f"round {r}"
    # and a past change does move it (the test can fail)
    s3, _ = mutate(styles, players, 1)
    assert J.request_blob(J.state_for(styles, players, cal, 5)) != J.request_blob(J.state_for(s3, players, cal, 5))


def test_canary_guard():
    styles, players = synth()
    cal = J.calendar_from_styles(styles)
    for r in ROUNDS:
        state = J.state_for(styles, players, cal, r)
        cans = J.canaries(styles, players, r)
        assert cans
        J.guard(state, cans)                                  # clean
    leaky = dict(state, extra=float(next(iter(J.canaries(styles, players, 4)))))
    with pytest.raises(RuntimeError, match="leak guard"):
        J.guard(leaky, J.canaries(styles, players, 4))


def test_canary_guard_catches_rounded_future_pnl():
    styles, players = synth()
    cal = J.calendar_from_styles(styles)
    r = 5
    cans = J.canaries(styles, players, r)
    J.guard(J.state_for(styles, players, cal, r), cans)                        # the normal state is clean
    state = J.state_for(styles, players, cal, r)
    state["season_2026_so_far"][0]["weekly_pnl"].append([r, J._r2(styles[J.CODES[0]][r]["pnl"])])
    with pytest.raises(RuntimeError, match="leak guard"):
        J.guard(state, cans)


def test_snapshot_holds_no_future_round():
    styles, players = synth()
    snap = J.snapshot(styles, players, J.calendar_from_styles(styles), 4)
    assert all(r < 4 for s in snap["series"].values() for r in s)
    assert all(p["round"] < 4 for p in snap["players"])
    assert set(snap) == {"round", "event", "raced", "series", "players"}


def test_argmax_ties_to_earlier_option():
    assert J.argmax(["a", "b", "c"], {"a": 0.3, "b": 0.3, "c": 0.2}) == "a"
    assert J.argmax(["a", "b"], {"b": 0.6, "a": 0.4}) == "b"
    assert J.argmax(["a", "b"], {}, "b") == "b"
    with pytest.raises(ValueError):
        J.argmax(["a", "b"], {}, "z")


def rec(style_p, sizing_p, basis):
    return {"style": {"choice": None, "probabilities": style_p}, "sizing": {"choice": None, "probabilities": sizing_p},
            "basis": basis}


def test_basis_answers_never_change_the_pick():
    sp = {"T1": 0.2, "T2": 0.2, "T8": 0.3, "T6": 0.15, "T5": 0.15}
    zp = {"standard": 0.3, "kelly_0.25": 0.4, "kelly_0.5": 0.3}
    picks = set()
    rng = random.Random(3)
    for _ in range(50):
        b = {k: rng.random() for k in J.BASIS_TEXT}
        p = J.decide(rec(sp, zp, b))
        picks.add((p["code"], p["sizing"], p["kelly"], p["runner_up"]))
    assert picks == {("T8", "kelly", 0.25, "T1")}                  # T1 / T2 tie for runner-up: the earlier wins
    tie = J.decide(rec({c: 0.2 for c in J.CODES}, {o: 1 / 3 for o in J.SIZING_OPTIONS}, {}))
    assert (tie["code"], tie["sizing"], tie["kelly"]) == ("T1", "standard", None)


def test_note_template():
    styles, players = synth()
    state = J.state_for(styles, players, J.calendar_from_styles(styles), 5)
    p = J.decide(rec({"T1": 0.1, "T2": 0.1, "T8": 0.5, "T6": 0.2, "T5": 0.1}, {"standard": 0.7, "kelly_0.25": 0.2,
                                                                                "kelly_0.5": 0.1}, {}))
    n = J.note(p, {"basis_2026": 0.71, "basis_2025": 0.32, "basis_players": 0.1, "basis_steady": 0.5}, state)
    assert n.startswith(f"[{J.SELF_REPORT}]")
    assert "picked T8 Early bird (0.50); runner-up T6 (0.20)" in n
    assert "leans on the 2026 record (0.71) more than steadiness (0.50), the 2025 backtest (0.32)" in n
    s = next(x for x in state["season_2026_so_far"] if x["code"] == "T8")
    assert f"2026 to date ${s['total']:+,.2f}, {s['weeks_up']} of 4 weeks up" in n


def test_packages_are_capped_by_whole_tail_records(monkeypatch):
    styles, players = synth(rounds=list(range(1, 24)))
    state = J.state_for(styles, players, J.calendar_from_styles(styles), 23, live=True)
    for k in ("cards", "season_2026_so_far"):
        assert len(json.dumps(state[k])) <= J.PKG_CAP
    assert "cards_cut" not in state["notes"]
    monkeypatch.setattr(J, "PKG_CAP", 1500)
    small = J.state_for(styles, players, J.calendar_from_styles(styles), 23)
    assert len(json.dumps(small["season_2026_so_far"])) <= 1500
    assert "season_2026_so_far_cut" in small["notes"] and "tail records" in small["notes"]["season_2026_so_far_cut"]
    codes = [x["code"] for x in small["season_2026_so_far"]]
    assert codes == list(J.CODES[:len(codes)])                     # whole records, from the tail


def test_cards_show_2025_only_before_live():
    styles, players = synth()
    cal = J.calendar_from_styles(styles)
    back = J.state_for(styles, players, cal, 3)
    assert all("backtest_2026_dollars" not in c for c in back["cards"])
    assert {c["code"]: c["backtest_2025_dollars"] for c in back["cards"]} == \
        {c: PF.ALPHA_STYLES[c]["backtest"][1] for c in J.CODES}
    blob = json.dumps(back["cards"])
    assert all(str(PF.ALPHA_STYLES[c]["backtest"][0]) not in blob for c in J.CODES)
    live = J.state_for(styles, players, cal, 3, live=True)
    assert [c["backtest_2026_dollars"] for c in live["cards"]] == [PF.ALPHA_STYLES[c]["backtest"][0] for c in J.CODES]


def test_jev_is_kept_out_of_the_players_evidence():
    styles, players = synth()
    cal = J.calendar_from_styles(styles)
    with_j = players + [dict(user_id=999, round=r, style="T1", sizing="standard", pnl=12345.678, settled=1) for r in ROUNDS]
    assert J.request_blob(J.state_for(styles, players, cal, 6)) == \
        J.request_blob(J.state_for(styles, with_j, cal, 6, exclude_users=(999,)))


def test_questions_are_task_and_fields_only():
    qs = J.questions()
    assert list(qs) == ["style", "sizing", "basis_2026", "basis_2025", "basis_players", "basis_steady"]
    assert list(qs["style"]["criteria"]) == list(PF.ALPHA_ORDER)
    assert list(qs["sizing"]["criteria"]) == list(J.SIZING_OPTIONS)
    for k in ("style", "sizing"):
        t = qs[k]["instructions"].lower()
        for w in ("should", "better", "avoid", "prefer", "good", "risk", "safe", "best"):
            assert w not in t, (k, w)
    for k in J.BASIS_TEXT:
        t = qs[k]["instructions"].lower()
        for w in ("diversif", "prefer", "avoid", "momentum", "should"):
            assert w not in t, (k, w)


def test_baselines_hand_computed():
    # three rounds; T1 has the best 2025 card (1,432)
    pn = {"T1": [10, 10, 10], "T2": [0, 0, 0], "T8": [150, -50, 0], "T6": [0, 0, 500], "T5": [-10, -10, -10]}
    styles = {c: {r + 1: dict(pnl=float(v)) for r, v in enumerate(vs)} for c, vs in pn.items()}
    rounds = [1, 2, 3]
    bp = J.baseline_picks(styles, rounds)
    assert bp["B1"] == {1: "T1", 2: "T1", 3: "T1"}
    # before 2: T8 150 > T1 10 + 100 -> switch; before 3: T8 100, still best
    assert bp["B2"] == {1: "T1", 2: "T8", 3: "T8"}
    assert bp["H1"] == {1: "T8", 2: "T1", 3: "T6"}
    assert bp["H2"] == {1: "T6", 2: "T6", 3: "T6"}                  # T6 500 > T8 100
    assert J.equal_weight(styles, rounds) == [30.0, -10.0, 100.0]
    picks = {r: {"code": c, "kelly": None, "sizing": "standard", "note": ""} for r, c in zip(rounds, ("T8", "T8", "T6"))}
    res = J.analyse(styles, picks, rounds, n_boot=200)
    assert res["jev"] == [150.0, -50.0, 500.0]
    assert res["base"]["B2"] == [10.0, -50.0, 0.0]
    assert res["desc"]["Jev"]["total"] == 600.0 and res["desc"]["Jev"]["weeks_up"] == 2
    assert set(res["beats"].values()) <= {"YES", "NOT SHOWN"}


def test_b2_margin_is_storys():
    from racinglines.pipelines import story
    assert J.SWITCH_MARGIN == story.SWITCH_MARGIN


def test_placement():
    players = [dict(user_id=u, round=1, pnl=v) for u, v in ((1, 50.0), (2, -10.0), (3, 200.0))]
    assert J.placement(players)["rank"] is None
    p = J.placement(players + [dict(user_id=9, round=1, pnl=60.0)], jev_user_id=9)
    assert (p["rank"], p["of"]) == (2, 4)


def test_deadline():
    race, fp1 = pd.Timestamp("2026-10-25 20:00"), pd.Timestamp("2026-10-23 17:30")
    J.check_deadline("2026-10-20 12:00", race, fp1)                       # before the window: fine
    for t in ("2026-10-21 20:00", "2026-10-24 09:00", "2026-10-26 19:00"):
        with pytest.raises(ValueError, match="too late"):
            J.check_deadline(t, race, fp1)
    with pytest.raises(ValueError, match="after FP1"):
        J.check_deadline("2026-10-27 12:00", race, fp1)


def test_lock_file_parses_and_keeps_the_template():
    tpl = (ROOT / "paper/locks/TEMPLATE.toml").read_text()
    note = f"[{J.SELF_REPORT}] picked T8 Early bird (0.41); runner-up T1 (0.22); leans on the 2026 record (0.71)."
    t = J.lock_text(tpl, year=2026, rnd=18, name="United States Grand Prix", first_session_utc="2026-10-23T17:30:00Z",
                    code="T8", settings_key="6f7085d5d9e0", code_commit="abc123", bankroll=1234.5,
                    stake_rule="kelly 0.25 (fantasy/sizing.py)", note_text=note, locked_at_utc="2026-10-19T10:00:00Z")
    d = tomllib.loads(t)
    assert d["event"] == "2026-18" and d["locked_by"] == "jev" and d["first_session_utc"] == "2026-10-23T17:30:00Z"
    s = d["strategy"]
    assert (s["profile"], s["settings_key"], s["code_commit"], s["bankroll"]) == ("T8", "6f7085d5d9e0", "abc123", 1234.5)
    assert s["stake_rule"].startswith("kelly 0.25") and s["venues"] == ["polymarket"]
    assert d["line"] == [dict(book="", market="", selection="", odds="", quoted_at_utc="", bet=False, stake=0.0)]
    lines = t.splitlines()
    i = next(n for n, x in enumerate(lines) if x.startswith("[strategy]"))
    assert lines[i + 1] == f"# note: {note}"
    from racinglines.pipelines import sweep_settings as SS
    assert SS.Settings.from_dict(PF.PROFILES["T8"]["settings"]).key == "6f7085d5d9e0"


class FakeClient:
    def __init__(self):
        self.calls = 0

    def system_one(self, state, questions, model):
        self.calls += 1
        ch = lambda opts: SimpleNamespace(choice=opts[0], confidence=0.5, probabilities={o: 1 / len(opts) for o in opts})  # noqa: E731
        return SimpleNamespace(model="jev-1", choices={"style": ch(list(J.CODES)), "sizing": ch(list(J.SIZING_OPTIONS))},
                               nouls={k: SimpleNamespace(noul=0.6) for k in J.BASIS_TEXT},
                               usage=SimpleNamespace(input_tokens=10, output_tokens=2))


def test_ask_caches(tmp_path):
    styles, players = synth()
    state = J.state_for(styles, players, J.calendar_from_styles(styles), 3)
    fc = FakeClient()
    a = J.ask(state, client=fc, cache_dir=tmp_path)
    b = J.ask(state, client=fc, cache_dir=tmp_path)
    assert fc.calls == 1 and a["cached"] is False and b["cached"] is True
    assert b["basis"] == {k: 0.6 for k in J.BASIS_TEXT}
    assert J.decide(b)["code"] == "T1"


def _script():
    spec = importlib.util.spec_from_file_location("jev_player_cli", ROOT / "scripts/research/jev_player.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _files(tmp_path, stand_in=False):
    styles, players = synth()
    sp = tmp_path / "styles.json"
    sp.write_text(json.dumps({"meta": {"STAND_IN": stand_in}, "styles": {c: {str(r): v for r, v in d.items()}
                                                                          for c, d in styles.items()}}))
    pp = tmp_path / "players.csv"
    pp.write_text("user_id,round,event_key,style,sizing,positions,settled,pnl\n" + "".join(
        f"{p['user_id']},{p['round']},2026-{p['round']:02d},{p['style']},{p['sizing']},3,3,{p['pnl']}\n" for p in players))
    return sp, pp


def test_dry_run_makes_no_client(tmp_path, monkeypatch):
    cli = _script()
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(J, "make_client", lambda: (_ for _ in ()).throw(AssertionError("a client was made")))
    monkeypatch.setattr(J, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ask was called")))
    sp, pp = _files(tmp_path, stand_in=True)
    assert cli.main(["backtest", "--rounds", "1-7", "--styles", str(sp), "--players", str(pp), "--dry-run"]) == 0
    d = tmp_path / "out" / "dry-run"
    picks = json.loads((d / "picks.json").read_text())
    assert len(picks["rounds"]) == 7 and picks["meta"]["dry_run"] is True
    assert all(r["note"].startswith(f"[{J.SELF_REPORT}]") for r in picks["rounds"].values())
    assert "DRY RUN" in (d / "results.txt").read_text() and "pre-registered self-report" in (d / "results.txt").read_text()
    assert len((d / "transcript.jsonl").read_text().splitlines()) == 7


def test_live_now_is_refused_without_dry_run(tmp_path, monkeypatch):
    cli = _script()
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(J, "make_client", lambda: (_ for _ in ()).throw(AssertionError("a client was made")))
    monkeypatch.setattr(J, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ask was called")))
    sp, pp = _files(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(["live", "--round", "5", "--lock", "--bankroll", "1000", "--now", "2026-01-01T00:00:00", "--yes",
                  "--styles", str(sp), "--players", str(pp)])
    assert e.value.code == 2


def test_real_run_refuses_a_stand_in_styles_file(tmp_path, monkeypatch):
    cli = _script()
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    sp, pp = _files(tmp_path, stand_in=True)
    with pytest.raises(SystemExit, match="STAND-IN"):
        cli.main(["backtest", "--rounds", "1-7", "--styles", str(sp), "--players", str(pp), "--yes"])
