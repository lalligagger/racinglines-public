"""The bundled demo of `racinglines book --demo` (racinglines/books/demo/): its book priced, mapped and settled by the real
code on a synthetic F1 database built here, so the stored results stay what the code returns. The grid is Mario Kart's;
every odds and price is made up. Skipped without the Postgres test database.

When a result field changes, regenerate the stored results:
    RACINGLINES_WRITE_DEMO=1 python -m pytest tests/test_book_demo.py
"""

import json
import os
import re
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from racinglines.books import schema as S
from racinglines.books import slips as B

DEMO = Path(B.__file__).parent / "demo"
DB_IDS = ("race_id", "races", "athlete_id", "opponent_id", "run_id", "link_id", "token_id")
DRIVERS = {  # key: (name, team, win, podium, top10, extra)
    "mario": ("Mario", "mushroom", 0.36, 0.68, 0.95, dict(pole_prob=0.40, fl_prob=0.22, top5_prob=0.82, mover_prob=0.03,
                                                    sprint_win_prob=0.38)),
    "luigi": ("Luigi", "mushroom", 0.22, 0.52, 0.92, dict(pole_prob=0.24, fl_prob=0.18, top5_prob=0.70, mover_prob=0.05)),
    "peach": ("Peach", "royal", 0.16, 0.44, 0.88, dict(pole_prob=0.15, fl_prob=0.15, top5_prob=0.62, mover_prob=0.08)),
    "toad": ("Toad", "royal", 0.12, 0.34, 0.85, dict(pole_prob=0.11, fl_prob=0.14, top5_prob=0.55, mover_prob=0.10)),
    "bowser": ("Bowser", "koopa", 0.08, 0.20, 0.78, dict(pole_prob=0.06, fl_prob=0.12, top5_prob=0.36, mover_prob=0.18)),
    "yoshi": ("Yoshi", "koopa", 0.06, 0.15, 0.70, dict(pole_prob=0.04, fl_prob=0.10, top5_prob=0.28, mover_prob=0.22)),
}
H2H = {("peach", "toad"): 0.58}
RESULT = ("mario", "peach", "luigi", "toad", "yoshi", "bowser")             # round 21's finishing order


@pytest.fixture(scope="module")
def demo_db(test_engine):
    """Two F1 races (rounds 21 and 22 of 2026) with a forecast run each, exchange links, a stored combo run, and round
    21's classification; removed afterwards."""
    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, seed
    url = test_engine.url.render_as_string(hide_password=False)
    made = dict(events=[], runs=[], athletes=[])
    with get_session(url) as s:
        seed(s)
        comp = s.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
        ath = {k: m.Athlete(display_name=v[0]) for k, v in DRIVERS.items()}
        s.add_all(ath.values())
        s.flush()
        ids = {k: a.id for k, a in ath.items()}
        made["athletes"] = list(ids.values())

        def race(rnd, name, metrics):
            ev = m.Event(season_id=season.id, source="test", source_key=f"demo-f1-{rnd}", name=name,
                         start_date=date(2026, 10, 25), series_round=rnd, status="scheduled")
            s.add(ev)
            s.flush()
            ra = m.Race(event_id=ev.id, category_id=cat.id)
            run = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="demo",
                             kind="forecast", metrics=metrics)
            s.add_all([ra, run])
            s.flush()
            made["events"].append(ev.id)
            made["runs"].append(run.id)
            return ra, run

        r21, run21 = race(21, "Rainbow Road Grand Prix", {})
        for k, (_, _, win, pod, top10, extra) in DRIVERS.items():
            h2h = {str(ids[o]): p for (a, o), p in H2H.items() if a == k}
            h2h.update({str(ids[a]): 1 - p for (a, o), p in H2H.items() if o == k})
            s.add(m.RacePrediction(model_run_id=run21.id, race_id=r21.id, target="t21", athlete_id=ids[k], win_prob=win,
                                   podium_prob=pod, top10_prob=top10, extra=dict(extra, h2h=h2h)))
        r22, run22 = race(22, "Bowser's Castle Grand Prix", {})
        for k, (_, _, win, pod, top10, _) in DRIVERS.items():
            s.add(m.RacePrediction(model_run_id=run22.id, race_id=r22.id, target="t22", athlete_id=ids[k],
                                   win_prob=win * 0.95, podium_prob=pod, top10_prob=top10, extra={}))

        def link(exchange, kind, bid, ask, token, at, athlete=None, params=None, ra=r21):
            s.add(m.MarketLink(exchange=exchange, question="demo", token_id=token, outcome="Yes",
                               competition_id=comp.id, category_id=cat.id,
                               athlete_id=None if athlete is None else ids[athlete], race_id=ra.id, prediction=kind,
                               params=params, last_bid=bid, last_ask=ask, last_price=(bid + ask) / 2, synced_at=at))

        t1, t2 = datetime(2026, 10, 20, 8, tzinfo=timezone.utc), datetime(2026, 10, 20, 8, 55, tzinfo=timezone.utc)
        link("kalshi", "race_win", 0.29, 0.33, "demo-k-win-mario", t1, "mario")
        link("polymarket", "race_win", 0.30, 0.32, "demo-p-win-mario", t2, "mario")          # fresher: the one used
        link("kalshi", "race_win", 0.18, 0.21, "demo-k-win-luigi", t2, "luigi")
        link("kalshi", "race_podium", 0.40, 0.45, "demo-k-pod-peach", t2, "peach")
        link("polymarket", "race_pole", 0.36, 0.40, "demo-p-pole-mario", t2, "mario")
        link("polymarket", "race_h2h", 0.44, 0.48, "demo-p-h2h-toad-peach", t2, "toad", {"opponent_id": ids["peach"]})
        link("kalshi", "race_p2", 0.20, 0.24, "demo-k-p2-luigi", t2, "luigi")                # no model price: market only
        link("kalshi", "race_win", 0.31, 0.35, "demo-k-win-mario-22", t2, "mario", ra=r22)
        rd = m.Round(race_id=r21.id, kind="race", ordinal=2)
        s.add(rd)
        s.flush()
        for pos, k in enumerate(RESULT, 1):
            s.add(m.Result(round_id=rd.id, athlete_id=ids[k], position=pos, status="OK"))
        s.commit()
    legs = [dict(kind="race_win", athlete=ids["mario"], side="yes", marginal=0.36),
            dict(kind="race_podium", athlete=ids["luigi"], side="yes", marginal=0.52)]
    metrics = dict(combos=[dict(name="mario win + luigi podium", fair=0.15, legs=legs, calibrated=True, flags=[])])
    with test_engine.begin() as c:
        made["runs"].append(c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                                              SELECT id, 'f1_sector_sim', 'combo', CAST(:p AS jsonb), CAST(:m AS jsonb)
                                              FROM competitions WHERE code = 'f1_wdc' RETURNING id"""),
                                      dict(p=json.dumps(dict(event_key="2026-21")), m=json.dumps(metrics))).scalar())
    yield ids
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'demo-%'"))
        c.execute(text("DELETE FROM model_runs WHERE id = ANY(:r)"), dict(r=made["runs"]))
        c.execute(text("DELETE FROM events WHERE id = ANY(:e)"), dict(e=made["events"]))
        c.execute(text("DELETE FROM athletes WHERE id = ANY(:a)"), dict(a=made["athletes"]))


def _no_ids(v):
    """A result with the database's row ids dropped: they depend on insertion order, not on the code."""
    if isinstance(v, dict):
        return {k: _no_ids(x) for k, x in v.items() if k not in DB_IDS}
    if isinstance(v, list):
        return [_no_ids(x) for x in v]
    if isinstance(v, str):
        return re.sub(r"\brun \d+", "run N", v)
    return v


def _results(test_engine):
    book = S.validate_book(tomllib.loads((DEMO / "book.toml").read_text()), "demo")
    with test_engine.connect() as c:
        B.readonly(c)
        out = dict(map=B.map_book(c, book), price=B.price_book(c, book), settle=B.settle_book(c, book))
        c.rollback()
    return {k: json.loads(json.dumps(v, default=str, sort_keys=True)) for k, v in out.items()}


def test_demo_bundle_is_what_the_code_returns(test_engine, demo_db):
    from racinglines.cli import book as CLI
    fresh = _results(test_engine)
    if os.environ.get("RACINGLINES_WRITE_DEMO"):
        for cmd, got in fresh.items():
            (DEMO / f"{cmd}.json").write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    for cmd, got in fresh.items():
        assert _no_ids(got) == _no_ids(CLI.demo(cmd)), cmd


def test_demo_shows_every_f1_pricing_feature(test_engine, demo_db):
    """The demo is worth showing only if it exercises each feature: guard against a quiet regression to '-'."""
    price = {r["id"]: r for r in _results(test_engine)["price"]["lines"]}
    modeled = ("win", "win-no", "podium", "top5", "top10", "pole", "fl", "h2h", "mover", "spr-win", "spr-pole")
    assert all(price[i]["model_prob"] is not None for i in modeled), [i for i in modeled if price[i]["model_prob"] is None]
    assert price["win-no"]["model_prob"] == pytest.approx(1 - 0.22)                            # the "no" side
    assert price["win"]["legs"][0]["market_exchange"] == "polymarket"                          # the fresher quote
    assert price["h2h"]["market_prob"] == pytest.approx(1 - 0.46)                              # listed the other way
    assert price["spr-pole"]["model_prob"] == pytest.approx(0.24)                              # sprint pole <- pole
    assert price["p2"]["model_prob"] is None and price["p2"]["market_prob"] is not None        # exchange only
    assert price["red"]["model_prob"] is None and "race prop" in price["red"]["legs"][0]["model_note"]
    assert price["sgp-joint"]["model_method"].startswith("joint: stored combo run")
    assert any("correlated" in f for f in price["sgp-product"]["flags"])
    assert any("independent across races" in f for f in price["parlay"]["flags"])
    assert price["typo"]["status"] == "unmapped"


def test_demo_and_defaults_need_no_database(tmp_path, monkeypatch, capsys):
    """--demo runs with nothing set up; the defaults file picks the mode when no flag does, and flags win over it."""
    from racinglines.cli import book as CLI
    from racinglines.cli import config as C
    monkeypatch.setenv("RACINGLINES_CLI_CONFIG", str(tmp_path / "cli.toml"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert CLI.main(["price", "--demo", "--json"]) == 0
    assert {r["id"] for r in json.loads(capsys.readouterr().out)["lines"]} >= {"win", "sgp-joint", "parlay", "typo"}
    assert CLI.main(["--demo", "map", "--json"]) == 0                          # the mode before the command too
    assert json.loads(capsys.readouterr().out)["unmapped"] == ["typo"]
    assert CLI.main(["price", "book.toml", "--demo"]) == 2                     # the demo takes no FILE
    with pytest.raises(SystemExit):
        CLI.main(["--demo", "price", "--remote"])                              # one mode only
    assert CLI.main(["config", "source", "demo"]) == 0
    assert CLI.main(["config", "db", "postgresql+psycopg://u:secret@h/db"]) == 0
    capsys.readouterr()
    assert CLI.main(["config"]) == 0
    shown = capsys.readouterr().out
    assert "source" in shown and "secret" not in shown                         # a db URL can hold a password
    assert oct((tmp_path / "cli.toml").stat().st_mode & 0o777) == "0o600"
    assert CLI.main(["settle", "--json"]) == 0                                 # source = demo, no flag
    assert json.loads(capsys.readouterr().out)["book"]["venue"] == "book_demo"
    assert CLI.main(["settle", "--local"]) == 2                                # the flag wins: local needs a FILE
    assert CLI.main(["config", "source", "nowhere"]) == 2
    assert CLI.main(["config", "colour", "red"]) == 2
    assert CLI.main(["config", "source", "--unset"]) == 0 and "source" not in C.load()


def test_demo_without_rich_prints_plain_text(tmp_path, monkeypatch, capsys):
    """Right after `pip install -e .` (no requirements.txt) rich may be missing: the demo still prints."""
    import importlib.util
    from racinglines.cli import book as CLI
    monkeypatch.setenv("RACINGLINES_CLI_CONFIG", str(tmp_path / "cli.toml"))
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "rich" else real(name, *a))
    assert CLI.main(["price", "--demo"]) == 0
    out = capsys.readouterr()
    assert "Lines" in out.out and "pip install rich" in out.err
