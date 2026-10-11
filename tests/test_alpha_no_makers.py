"""Alpha Fantasy Launch (owner, 2026-10-11 22:29Z): maker strategies are closed to users until Beta
(profiles.MAKERS_OPEN). Nothing is deleted; the demo maker keeps running."""

from contextlib import contextmanager

import pytest

from racinglines.pipelines import profiles as PF
from racinglines.pipelines import signals as SG
from racinglines.web import roles as R


@pytest.mark.quick
def test_makers_are_told_apart_from_takers_and_blends():
    assert PF.is_maker(PF.PROFILES["C"]) and PF.is_maker(PF.PROFILES["K"])
    assert not PF.is_maker(PF.PROFILES["T1"]) and not PF.is_maker(PF.PROFILES["TB"])
    assert not PF.is_maker(None)
    assert PF.is_maker(dict(name="x", members=[dict(code="T1", weight=0.5), dict(code="C", weight=0.5)]))


@pytest.mark.quick
def test_closed_makers_leave_the_pick_list_and_only_admin_may_assign_one(monkeypatch):
    monkeypatch.setattr(PF, "MAKERS_OPEN", False)
    assert PF.open_codes(("T7", "TB", "C")) == ("T7", "TB")
    assert not R.allowed_profile("pro", PF.PROFILES["C"]) and not R.allowed_profile("basic", PF.PROFILES["K"])
    assert R.allowed_profile("admin", PF.PROFILES["C"]) and R.allowed_profile("pro", PF.PROFILES["T1"])
    assert R.allowed_profile("pro", None)                                # stopping is always allowed
    monkeypatch.setattr(PF, "MAKERS_OPEN", True)                         # Beta: back as before
    assert PF.open_codes(("T7", "TB", "C")) == ("T7", "TB", "C") and R.allowed_profile("pro", PF.PROFILES["C"])


@pytest.mark.quick
def test_the_signal_engine_runs_makers_only_for_the_demo_accounts(monkeypatch):
    monkeypatch.setattr(PF, "MAKERS_OPEN", False)
    rows = [(2, "maker", "admin", dict(PF.PROFILES["C"])), (3, "taker", "basic", dict(PF.PROFILES["A"])),
            (7, "ada", "pro", dict(PF.PROFILES["C"]))]
    monkeypatch.setattr(PF, "assigned", lambda c, venue="polymarket": rows)
    ran = []
    monkeypatch.setattr(SG, "compute", lambda *a, **k: dict(stages=[]))
    monkeypatch.setattr(SG, "_run_one", lambda e, u, prof, out, uids, *a: ran.append((prof["name"], uids)))

    class Engine:
        @contextmanager
        def connect(self):
            yield None
    said = []
    SG.run_all(Engine(), "", echo=said.append)
    assert sorted(ran) == sorted([(PF.PROFILES["C"]["name"], [2]), (PF.PROFILES["A"]["name"], [3])])
    assert "skipped ada" in said[0]
