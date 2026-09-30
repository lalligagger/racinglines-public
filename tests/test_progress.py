"""The progress heartbeat (racinglines/progress.py): owner rule 2026-09-30, a line at least every 5 minutes."""

import io
import time

from racinglines import progress as PG


def test_line_reports_counter_and_time_left():
    PG.start("f1 sweep", every=0)
    t0 = PG._state["t0"]
    PG.update(done=0, total=4)
    PG._state["t_done"] = t0
    PG.update(done=1, item="race 2 of 4 (2026-12)")
    line = PG.line(now=t0 + 600)
    assert line.startswith("progress f1 sweep: 10 min elapsed · race 2 of 4 (2026-12)")
    assert line.endswith("about 30 min left")


def test_track_yields_everything_and_counts():
    PG.start("x", every=0)
    assert list(PG.track([1, 2, 3], "race")) == [1, 2, 3]
    assert PG._state["done"] == 3 and PG._state["total"] == 3


def test_heartbeat_prints_to_its_stream_only():
    PG.stop()
    buf = io.StringIO()
    PG.start("demo", every=0.05, stream=buf)
    try:
        time.sleep(0.2)
    finally:
        PG.stop()
    assert "progress demo:" in buf.getvalue()


def test_default_interval_is_five_minutes(monkeypatch):
    monkeypatch.delenv("RACINGLINES_PROGRESS_SEC", raising=False)
    assert PG.interval() == 300
