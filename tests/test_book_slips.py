"""`racinglines book map | price | settle` (racinglines/books/slips.py): a synthetic generic sportsbook book with legs on
F1, NASCAR and MotoGP, priced against stored model runs and linked exchange quotes inserted into the Postgres test
database (skipped without one). Every name, odds and price here is made up."""

import json
from datetime import date, datetime, timezone

import numpy as np
import pytest
from sqlalchemy import select

from racinglines.books import schema as S
from racinglines.books import slips as B

BOOK = """
[book]
venue = "book_x"
event = "2026-17"
sport = "f1"
captured_utc = "2026-10-07T09:00Z"
source = "paste"
odds = "decimal"
currency = "USD"

[aliases]
"Alpha, Ann" = "Ann Alpha"

[[lines]]                       # 1: a single, model and market
id = "win"
title = "Race Winner"
selection = "Alpha, Ann"
odds = 3.0
market = { kind = "race_win", driver = "Ann Alpha" }

[[lines]]                       # 2: head-to-head, model only
id = "h2h"
title = "Head to Head"
selection = "Bea Beta"
odds = 2.5
market = { kind = "race_h2h", driver = "Bea Beta", opponent = "Ann Alpha" }

[[lines]]                       # 3: a parlay across two other sports, priced from its legs' odds
id = "parlay"
title = "Parlay"
selection = "Cora Cup win + Dan Duke win"
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Cora Cup", sport = "nascar", event = "2026-30", odds = 2.0 },
  { kind = "race_win", driver = "Dan Duke", sport = "motogp", event = "2026-18", odds = 4.0 },
] }

[[lines]]                       # 4: same-race combo (correlated)
id = "sgp"
title = "Race Winner and Podium"
selection = "Ann Alpha"
odds = 2.6
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Ann Alpha" },
  { kind = "race_podium", driver = "Bea Beta" },
] }

[[lines]]                       # 5: a name the field doesn't have
id = "ghost"
title = "Race Winner"
selection = "Gus Ghost"
odds = 50.0
market = { kind = "race_win", driver = "Gus Ghost" }

[[lines]]                       # 6: the venue's rules matched nothing
id = "rf"
title = "Will a driver wear a hat?"
selection = "Yes"
odds = 1.9
market = "unmapped"

[[lines]]                       # 7: a parlay with one losing leg on a raced event and one leg not yet raced
id = "lose"
title = "Parlay"
selection = "Bea win + Cora win"
odds = 9.0
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Bea Beta" },
  { kind = "race_win", driver = "Cora Cup", sport = "nascar", event = "2026-30" },
] }
"""


@pytest.fixture(scope="module")
def db(test_engine):
    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, seed
    url = test_engine.url.render_as_string(hide_password=False)
    ids = {}
    made = dict(events=[], runs=[])
    with get_session(url) as s:
        seed(s)
        names = dict(ann="Ann Alpha", bea="Bea Beta", cid="Cid Cee", cora="Cora Cup", eve="Eve Echo", dan="Dan Duke",
                     fay="Fay Fox")
        ath = {k: m.Athlete(display_name=v) for k, v in names.items()}
        s.add_all(ath.values())
        s.flush()
        ids.update({k: a.id for k, a in ath.items()})

        def race(comp_code, cat_code, rnd, name, field, preds, status="scheduled"):
            comp = s.scalars(select(m.Competition).filter_by(code=comp_code)).one()
            cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code=cat_code)).one()
            season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
            ev = m.Event(season_id=season.id, source="test", source_key=f"t-{comp_code}-{rnd}", name=name,
                         start_date=date(2026, 10, 11), series_round=rnd, status=status)
            s.add(ev)
            s.flush()
            ra = m.Race(event_id=ev.id, category_id=cat.id)
            run = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="test",
                             kind="forecast")
            s.add_all([ra, run])
            s.flush()
            made["events"].append(ev.id)
            made["runs"].append(run.id)
            for k, (win, pod, extra) in preds.items():
                s.add(m.RacePrediction(model_run_id=run.id, race_id=ra.id, target=f"t{rnd}", athlete_id=ids[k],
                                       win_prob=win, podium_prob=pod, top10_prob=0.9, extra=extra))
            return comp, cat, ra, run

        f1c, f1cat, f1r, f1run = race("f1_wdc", "DRV", 17, "Testing Grand Prix", None, {
            "ann": (0.40, 0.70, {"h2h": {str(ids["bea"]): 0.65}}),
            "bea": (0.25, 0.55, {"h2h": {str(ids["ann"]): 0.35}}),
            "cid": (0.10, 0.30, {})})
        nc, ncat, nr, _ = race("nascar_cup", "DRV", 30, "Test 400", None, {"cora": (0.50, 0.8, {}), "eve": (0.1, 0.3, {})})
        mc, mcat, mr, _ = race("motogp_wc", "RDR", 18, "Test GP", None, {"dan": (0.30, 0.6, {}), "fay": (0.2, 0.5, {})})
        now = datetime(2026, 10, 7, 8, tzinfo=timezone.utc)

        def link(exchange, comp, cat, ra, a, bid, ask, token):
            s.add(m.MarketLink(exchange=exchange, question="q", token_id=token, outcome="Yes", competition_id=comp.id,
                               category_id=cat.id, athlete_id=ids[a], race_id=ra.id, prediction="race_win",
                               last_bid=bid, last_ask=ask, last_price=(bid + ask) / 2, synced_at=now))

        link("kalshi", f1c, f1cat, f1r, "ann", 0.30, 0.34, "tok-f1-ann")
        link("kalshi", nc, ncat, nr, "cora", 0.40, 0.44, "tok-nc-cora")
        link("polymarket", mc, mcat, mr, "dan", 0.22, 0.26, "tok-mg-dan")
        # the F1 race has run: Ann wins, Bea third
        rd = m.Round(race_id=f1r.id, kind="race", ordinal=2)
        s.add(rd)
        s.flush()
        for k, pos in (("ann", 1), ("cid", 2), ("bea", 3)):
            s.add(m.Result(round_id=rd.id, athlete_id=ids[k], position=pos, status="OK"))
        s.commit()
        ids.update(f1_race=f1r.id, nascar_race=nr.id, motogp_race=mr.id, f1_run=f1run.id, f1_comp=f1c.code)
    yield ids
    # leave the shared test database as found: other modules count races, runs and links
    from sqlalchemy import text
    athletes = [ids[k] for k in names]
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE athlete_id = ANY(:a)"), dict(a=athletes))
        c.execute(text("DELETE FROM model_runs WHERE id = ANY(:r)"), dict(r=made["runs"]))
        c.execute(text("DELETE FROM events WHERE id = ANY(:e)"), dict(e=made["events"]))
        c.execute(text("DELETE FROM athletes WHERE id = ANY(:a)"), dict(a=athletes))


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "book.toml"
    p.write_text(BOOK)
    return S.load_book(p)


def _line(out, lid):
    return next(r for r in out["lines"] if r["id"] == lid)


def _price(test_engine, book, **kw):
    with test_engine.connect() as c:
        B.readonly(c)
        out = B.price_book(c, book, **kw)
        c.rollback()
    return out


def test_map_resolves_exact_keys_and_lists_unmapped(test_engine, db, book):
    with test_engine.connect() as c:
        out = B.map_book(B.readonly(c), book)
    assert out["unmapped"] == ["ghost", "rf"]
    win = _line(out, "win")["legs"][0]
    assert (win["status"], win["athlete_id"], win["race_id"], win["sport"], win["event_key"]) == \
        ("mapped", db["ann"], db["f1_race"], "f1", "2026-17")
    h2h = _line(out, "h2h")["legs"][0]
    assert (h2h["athlete_id"], h2h["opponent_id"]) == (db["bea"], db["ann"])
    parlay = _line(out, "parlay")
    assert [lg["sport"] for lg in parlay["legs"]] == ["nascar", "motogp"]
    assert parlay["races"] == sorted([db["nascar_race"], db["motogp_race"]])
    ghost = _line(out, "ghost")
    assert ghost["status"] == "unmapped" and "'Gus Ghost' is not an exact name" in ghost["reason"]
    assert _line(out, "rf")["reason"] == "the book file marks this line unmapped"


def test_map_never_guesses_a_name(test_engine, db, tmp_path):
    p = tmp_path / "b.toml"
    p.write_text(BOOK.replace('driver = "Ann Alpha" }\n\n[[lines]]                       # 2',
                              'driver = "ann alpha" }\n\n[[lines]]                       # 2'))
    with test_engine.connect() as c:
        out = B.map_book(B.readonly(c), S.load_book(p))
    assert "win" in out["unmapped"]                           # case differs: unmapped, not matched


def test_single_leg_ev_against_model_and_market(test_engine, db, book):
    out = _price(test_engine, book)
    win = _line(out, "win")
    leg = win["legs"][0]
    assert leg["model_prob"] == pytest.approx(0.40) and leg["run_id"] == db["f1_run"]
    assert (leg["market_exchange"], leg["market_bid"], leg["market_ask"]) == ("kalshi", 0.30, 0.34)
    assert win["book_prob"] == pytest.approx(1 / 3)
    assert win["ev_model"] == pytest.approx(0.40 * 3 - 1)            # +0.20
    assert win["ev_market"] == pytest.approx(0.32 * 3 - 1)           # -0.04
    assert win["model_method"] == "single" and win["market_method"] == "single" and win["flags"] == []
    h2h = _line(out, "h2h")
    assert h2h["model_prob"] == pytest.approx(0.35) and h2h["market_prob"] is None and h2h["ev_market"] is None
    assert h2h["ev_model"] == pytest.approx(0.35 * 2.5 - 1)
    assert out["blend"].startswith("none")


def test_two_leg_parlay_across_sports(test_engine, db, book):
    p = _line(_price(test_engine, book), "parlay")
    assert p["decimal_odds"] == pytest.approx(8.0) and p["book_prob"] == pytest.approx(0.125)
    assert p["model_prob"] == pytest.approx(0.50 * 0.30) and p["model_method"] == "single x single"
    assert p["market_prob"] == pytest.approx(0.42 * 0.24)
    assert p["ev_model"] == pytest.approx(0.15 * 8 - 1)
    assert p["ev_market"] == pytest.approx(0.42 * 0.24 * 8 - 1)
    assert any("independent across races" in f for f in p["flags"])
    assert not any(B.CORRELATED in f for f in p["flags"])
    assert [lg["ev_model"] for lg in p["legs"]] == [pytest.approx(0.0), pytest.approx(0.2)]


def test_same_race_legs_are_flagged_without_simulations(test_engine, db, book):
    sgp = _line(_price(test_engine, book), "sgp")
    assert sgp["model_method"] == "product"
    assert sgp["model_prob"] == pytest.approx(0.40 * 0.55)
    assert any(B.CORRELATED in f for f in sgp["flags"])


def test_same_race_legs_priced_jointly_from_simulations(test_engine, db, book, tmp_path):
    from racinglines.models import outcomes as O
    a, b, c = db["ann"], db["bea"], db["cid"]
    # four simulations: Ann wins in 2 of them, and Bea is on the podium (top 3 of 3) in all
    rank = np.array([[1, 2, 3], [1, 3, 2], [2, 1, 3], [3, 1, 2]], float)
    sims = O.OutcomeSims(entrants=[a, b, c], rank=rank, finished=np.ones((4, 3), bool))
    O.save_sims(sims, tmp_path / "s.npz")
    from racinglines.cli.book import _sims
    loaded = _sims([f"{db['f1_race']}={tmp_path / 's.npz'}"])
    sgp = _line(_price(test_engine, book, sims=loaded), "sgp")
    assert sgp["model_method"] == "joint: simulations passed in"
    assert sgp["model_prob"] == pytest.approx(0.5)
    assert not any(f.startswith("race ") for f in sgp["flags"])                  # the model side is joint
    assert any(f.startswith("market:") for f in sgp["flags"]) or sgp["market_prob"] is None


def test_settle_from_the_stored_classification(test_engine, db, book):
    with test_engine.connect() as c:
        out = B.settle_book(B.readonly(c), book)
    win, h2h, lose, parlay = (_line(out, x) for x in ("win", "h2h", "lose", "parlay"))
    assert (win["result"], win["payout"], win["profit"]) == ("won", 3.0, 2.0)
    assert h2h["legs"][0]["result"] == "lost" and h2h["payout"] == 0.0
    assert [lg["result"] for lg in lose["legs"]] == ["lost", "pending"] and lose["result"] == "lost"
    assert parlay["result"] == "pending" and parlay["payout"] is None
    assert _line(out, "ghost")["result"] is None


def test_cli_json_is_stable(test_engine, db, book, tmp_path, capsys):
    from racinglines.cli import book as CLI
    p = tmp_path / "book.toml"
    p.write_text(BOOK)
    url = test_engine.url.render_as_string(hide_password=False)
    assert CLI.main(["price", str(p), "--json", "--db", url]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"book", "lines", "unmapped", "assumptions", "blend"}
    for r in out["lines"]:
        assert set(r) == set(B.LINE_FIELDS) | {"legs"}
        for lg in r["legs"]:
            assert set(lg) == set(B.LEG_FIELDS) | set(B.PRICE_FIELDS) | {"quotes"}
    assert CLI.main(["map", str(p), "--db", url]) == 0
    assert "Unmapped lines: ghost, rf" in capsys.readouterr().out
    assert CLI.main(["settle", str(p), "--json", "--db", url]) == 0
    assert _line(json.loads(capsys.readouterr().out), "win")["result"] == "won"


def test_same_race_legs_from_a_stored_combo_run(test_engine, db, book):
    """A stored f1_combo run (model_runs kind "combo") holding exactly the slip's legs prices it jointly."""
    from sqlalchemy import text
    legs = [dict(kind="race_win", athlete=db["ann"], side="yes", marginal=0.4),
            dict(kind="race_podium", athlete=db["bea"], side="yes", marginal=0.55)]
    metrics = dict(combos=[dict(name="x", fair=0.18, legs=legs, calibrated=False,
                                flags=[dict(note="test flag")])])
    with test_engine.begin() as c:
        rid = c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                                SELECT id, 'f1_sector_sim', 'combo', CAST(:p AS jsonb), CAST(:m AS jsonb)
                                FROM competitions WHERE code = 'f1_wdc' RETURNING id"""),
                        dict(p=json.dumps(dict(event_key="2026-17")), m=json.dumps(metrics))).scalar()
    try:
        sgp = _line(_price(test_engine, book), "sgp")
        assert sgp["model_method"] == f"joint: stored combo run {rid}"
        assert sgp["model_prob"] == pytest.approx(0.18)
        assert any("not calibrated" in f and "test flag" in f for f in sgp["flags"])
        assert sgp["ev_model"] == pytest.approx(0.18 * 2.6 - 1)
    finally:
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM model_runs WHERE id = :i"), dict(i=rid))
