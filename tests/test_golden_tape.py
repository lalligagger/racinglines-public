"""The golden check on a second tape (pipelines/golden_tape.py) and the store's tape switch (RACINGLINES_TAPE): with a
tape set, every read goes to that tree only; the pass marks are the owner's proposed ones."""
import pandas as pd
import pytest

from racinglines.markets import store as MS
from racinglines.pipelines import golden_tape as GT


def _prices(rows):
    return pd.DataFrame(rows, columns=["token_id", "ts", "price"]).assign(ts=lambda d: pd.to_datetime(d["ts"], utc=True))


def test_tape_switch_reads_only_the_tape_tree(tmp_path, monkeypatch):
    ours, theirs = tmp_path / "ours", tmp_path / "theirs"
    MS._write("prices", _prices([("t1", "2026-06-01 10:00", 0.40)]), ours / "polymarket")
    MS._write("prices", _prices([("t1", "2026-06-01 10:00", 0.41)]), theirs / "polymarket")
    monkeypatch.setattr(MS.paths, "archive_markets", lambda exchange="polymarket": ours / exchange)
    monkeypatch.delenv(MS.TAPE, raising=False)
    assert MS.read(None, "prices", tokens=["t1"])["price"].tolist() == [0.40]
    with GT.on_tape(theirs):
        assert MS.read(None, "prices", tokens=["t1"])["price"].tolist() == [0.41]
        # an exchange's own root maps to the same exchange inside the tape
        assert MS.read(None, "prices", tokens=["t1"], root=ours / "polymarket")["price"].tolist() == [0.41]
        assert MS.last_before(None, ["t1"], "2026-06-02") == {"t1": 0.41}
    assert MS.tape() is None


def test_tape_switch_never_reads_postgres(tmp_path):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("Postgres read on a second tape")
    (tmp_path / "polymarket").mkdir()
    with GT.on_tape(tmp_path):
        assert MS._on_tape(Boom(), None) == (None, None)
        assert len(MS.read(None, "trades", tokens=["x"])) == 0


def test_compare_mids_buckets_and_tolerance():
    ours = _prices([("a", "2026-06-01 10:01", 0.30), ("a", "2026-06-01 10:04", 0.31), ("a", "2026-06-01 10:06", 0.50),
                    ("b", "2026-06-01 10:00", 0.20)])
    theirs = _prices([("a", "2026-06-01 10:02", 0.32), ("a", "2026-06-01 10:07", 0.53), ("c", "2026-06-01 10:00", 0.1)])
    r = GT.compare_mids(ours, theirs)
    assert (r["matched"], r["within"], r["ours_only"], r["theirs_only"]) == (2, 1, 1, 1)
    assert r["share"] == 0.5 and r["worst"] == pytest.approx(0.03)
    assert GT.compare_mids(ours.iloc[:0], theirs)["share"] is None


@pytest.mark.parametrize("ours,theirs,ok", [(100.0, 109.0, True), (100.0, 111.0, False), (10.0, 14.9, True),
                                            (10.0, 15.2, False), (None, None, True), (5.0, None, False)])
def test_pnl_mark_is_ten_percent_or_five_dollars(ours, theirs, ok):
    assert GT.within(ours, theirs, GT.PNL_REL, GT.PNL_ABS) is ok


def test_compare_weekends_and_report():
    a = pd.DataFrame(dict(event_key=["2026-10", "2026-11"], event=["A", "B"], update_pnl=[50.0, -20.0],
                          update_trades=[40, 20]))
    b = pd.DataFrame(dict(event_key=["2026-10", "2026-11"], update_pnl=[53.0, -40.0], update_trades=[41, 20]))
    m = GT.compare_weekends(a, b)
    assert m["pnl_ok"].tolist() == [True, False] and m["trades_ok"].tolist() == [True, True]
    assert m["pass"].tolist() == [True, False]
    tapes = pd.DataFrame([dict(event_key="2026-10", event="A", tokens=3, matched=10, within=10, share=1.0, ours_only=0,
                               theirs_only=0, worst=0.0, **{"pass": True})])
    text = GT.report(tapes, m.assign(seed="default"), "probalytics", 2026, [10, 11])
    assert "Tapes: **PASS**" in text and "Golden sweep: **FAIL** (1 of 2" in text


def test_golden_settings_come_from_the_queue():
    st = GT.golden_settings(2026)
    assert st["min_edge"] == 0.1 and st["min_edge_h2h"] == 0.05 and st["variant"] == "gridq+pretrain+reset"
    assert "note" not in st and "replicates" not in st and "year" not in st
    assert GT.seeds(3) == [None, 1, 2]
    with pytest.raises(ValueError):
        GT.golden_settings(1999)
