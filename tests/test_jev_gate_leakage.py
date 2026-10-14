"""Leakage and cache rules of the Jev gate research module (no network, no database)."""

import json
import types

import pytest

from racinglines.research import jev_gate as jg

SIGNAL = {"kind": "race_win", "subject": "George Russell", "side": "YES", "fair": 0.3, "price": 0.2, "edge": 0.1,
          "signal_ts": "2026-09-25T13:30:00+00:00", "event_start": "2026-09-26"}


def sess(kind, date="2026-09-24 08:30:00", pos=3):
    return {"kind": kind, "session_date": date, "position": pos, "status": "OK", "field": 22, "gap_to_p1_ms": None}


ALL = [sess(k) for k in ("fp1", "fp2", "fp3", "sprint_qual", "sprint", "qual", "race")]


@pytest.mark.parametrize("stage", list(jg.STAGE_SESSIONS))
def test_only_allowed_sessions_and_never_race(stage):
    st = jg.build_state({**SIGNAL, "stage": stage}, ALL, [])
    assert set(st["sessions"]) == set(jg.STAGE_SESSIONS[stage])
    assert "race" not in st["sessions"]
    assert "race" not in json.dumps(st["sessions"])


def test_unknown_stage_gets_no_sessions():
    assert jg.build_state({**SIGNAL, "stage": "after Race"}, ALL, [])["sessions"] == {}


def test_session_dated_after_signal_is_excluded():
    rows = [sess("fp1"), sess("fp2", date="2026-09-25 14:00:00")]
    st = jg.build_state({**SIGNAL, "stage": "after Quali"}, rows, [])
    assert set(st["sessions"]) == {"fp1"}


def test_prior_races_strictly_earlier_and_capped():
    prior = [{"start_date": d, "position": p} for d, p in
             [("2026-09-26", 1), ("2026-09-27", 2), ("2026-09-13", 5), ("2026-08-30", 4), ("2026-08-01", 3), ("2026-07-01", 9)]]
    st = jg.build_state({**SIGNAL, "stage": "after Quali"}, [], prior)
    assert [r["position"] for r in st["recent_races"]] == [5, 4, 3]


def test_state_has_no_outcome():
    st = jg.build_state({**SIGNAL, "stage": "after Quali", "outcome": True}, ALL, [])
    assert "outcome" not in json.dumps(st)


def test_unmatched_subject_is_null_sessions():
    st = jg.build_state({**SIGNAL, "stage": "after Quali"}, None, [])
    assert st["sessions"] is None and st["recent_races"] is None


def test_athlete_lookup_is_exact_only():
    sql = str(jg._ATHLETES).lower()
    assert "= :n" in sql and "like" not in sql and "~" not in sql


class FakeClient:
    def __init__(self):
        self.calls = 0

    def system_one(self, state, questions, model=None):
        self.calls += 1
        noul = types.SimpleNamespace(noul=0.4)
        ch = types.SimpleNamespace(choice="unclear", confidence=0.1, probabilities={"unclear": 0.4, "thin_book": 0.6})
        return types.SimpleNamespace(model="jev-x", nouls={"model_missing": noul, "stale_edge": noul},
                                     choices={"gap_cause": ch})


def test_cache_second_ask_makes_no_call(tmp_path):
    st = jg.build_state({**SIGNAL, "stage": "after FP1"}, [sess("fp1")], [])
    c = FakeClient()
    a = jg.ask(st, client=c, cache_dir=tmp_path)
    b = jg.ask(dict(st), client=c, cache_dir=tmp_path)
    assert c.calls == 1 and a == b
    assert set(a["answers"]) == set(jg.QUESTIONS)
    assert a["answers"]["gap_cause"]["probabilities"]["thin_book"] == 0.6


def test_plan_counts_without_client(tmp_path, monkeypatch):
    monkeypatch.setattr(jg, "make_client", lambda: pytest.fail("network"))
    s1 = jg.build_state({**SIGNAL, "stage": "after FP1"}, [sess("fp1")], [])
    s2 = jg.build_state({**SIGNAL, "stage": "after FP2"}, [sess("fp1"), sess("fp2")], [])
    assert jg.plan([1, 2, 3], states=[s1, s1, s2], cache_dir=tmp_path) == \
        {"signals": 3, "unique_states": 2, "cached": 0, "api_calls": 2}
    jg.ask(s1, client=FakeClient(), cache_dir=tmp_path)
    assert jg.plan([1, 2, 3], states=[s1, s1, s2], cache_dir=tmp_path)["api_calls"] == 1
