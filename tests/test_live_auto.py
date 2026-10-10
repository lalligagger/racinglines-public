"""racinglines live auto: the F1 events whose window is open are stepped, so none has to be started by hand."""
import pandas as pd


def _spec(d, event, open_, results):
    (d / f"{event}.toml").write_text(f'sport = "f1"\nevent = "{event}"\ntitle = "{event}"\n[window]\nopen = "{open_}"\n'
                                     f'close = "{results}"\nresults = "{results}"\n')


def test_only_events_in_their_window_are_due(tmp_path, monkeypatch):
    from racinglines.cli import live as L
    from racinglines.pipelines import live as LV
    d = tmp_path / "f1"
    d.mkdir()
    _spec(d, "2026-16", "2026-10-02T03:30:00", "2026-10-04T10:00:00")
    _spec(d, "2026-17", "2026-10-09T07:30:00", "2026-10-11T15:00:00")
    _spec(d, "2026-18", "2026-10-23T16:30:00", "2026-10-25T23:00:00")
    monkeypatch.setattr(LV, "SPECS", tmp_path)
    due = lambda t: [s["event"] for s in L.due_specs("f1", pd.Timestamp(t))]      # noqa: E731
    assert due("2026-10-10T09:30") == ["2026-17"]                  # mid-weekend: Singapore only
    assert due("2026-10-09T06:45") == ["2026-17"]                  # an hour before the book opens
    assert due("2026-10-12T14:00") == ["2026-17"]                  # a day after the results: the settlement
    assert due("2026-10-12T16:00") == []                           # done: nothing runs, nothing to turn off
    assert due("2026-10-05T09:00") == ["2026-16"]


def test_auto_steps_each_due_event_and_one_failure_does_not_stop_the_rest(tmp_path, monkeypatch, capsys):
    from racinglines.cli import live as L
    from racinglines.pipelines import live as LV
    d = tmp_path / "f1"
    d.mkdir()
    _spec(d, "2026-17", "2026-10-09T07:30:00", "2026-10-11T15:00:00")
    _spec(d, "2026-99", "2026-10-09T07:30:00", "2026-10-11T15:00:00")
    monkeypatch.setattr(LV, "SPECS", tmp_path)
    stepped = []

    def fake_step(args):
        stepped.append(args.spec)
        if "2026-17" in args.spec:
            raise RuntimeError("boom")
    monkeypatch.setattr(L, "cmd_step", fake_step)
    assert L.main(["auto", "--now", "2026-10-10T09:30"]) == 1
    assert [p.rsplit("/", 1)[1] for p in stepped] == ["2026-17.toml", "2026-99.toml"]
    assert "2026-17: step FAILED: RuntimeError: boom" in capsys.readouterr().out
    assert L.main(["auto", "--now", "2026-11-30T00:00"]) == 0
