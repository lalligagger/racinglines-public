"""The coverage counter (racinglines/pipelines/coverage.py, `racinglines backtest coverage`): races linked, settled and
taped per sport x exchange x kind x season, counted in Postgres and the Parquet archive; the parity tiers; season
futures; and the results depth and sources per sport, read from the schemas. Built on a far-future season so the
shared test database's other rows don't count."""

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines import sports
from racinglines.markets import store
from racinglines.pipelines import coverage as COV

SEASON = 2099


def test_tier_bar():
    assert COV.tier([8, 9]) == "parity-2"
    assert COV.tier([8, 3]) == "parity-1"
    assert COV.tier([0, 7]) == "thin"
    assert COV.tier([0, 0]) == "missing"


def test_modeled_reads_the_schema():
    assert COV.modeled("f1", "race_win") and COV.modeled("nascar", "race_top20") is False   # not a kinds.py kind
    assert COV.modeled("indycar", "race_win") is False          # no pricing_model
    assert COV.modeled("motogp", "race_podium") is False        # not in the schema's kind lists
    assert COV.modeled("f1", "race_h2h") and COV.modeled("motogp", "race_win")


@pytest.fixture
def season(test_engine):
    """Two F1 rounds in 2099, one with a result; three race links and a futures link; tape in Postgres."""
    code = sports.load("f1")["competition"]["code"]
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=code)).scalar()
        if comp is None:
            sport = c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') "
                                   "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id")).scalar()
            league = c.execute(text("INSERT INTO leagues (code, name) VALUES ('fia', 'FIA') "
                                    "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id")).scalar()
            comp = c.execute(text("INSERT INTO competitions (code, name, league_id, sport_id) "
                                  "VALUES (:c, 'F1', :l, :s) RETURNING id"), dict(c=code, l=league, s=sport)).scalar()
        cat = c.execute(text("INSERT INTO categories (competition_id, code, name) VALUES (:c, 'COV', 'Coverage test') "
                             "RETURNING id"), dict(c=comp)).scalar()
        sid = c.execute(text("INSERT INTO seasons (competition_id, year) VALUES (:c, :y) RETURNING id"),
                        dict(c=comp, y=SEASON)).scalar()
        races = []
        for rnd in (1, 2):
            ev = c.execute(text("INSERT INTO events (season_id, source, source_key, name, start_date, series_round) "
                                "VALUES (:s, 'test', :k, 'GP', :d, :r) RETURNING id"),
                           dict(s=sid, k=f"cov-{rnd}", d=date(SEASON, 3, 7 * rnd), r=rnd)).scalar()
            races.append(c.execute(text("INSERT INTO races (event_id, category_id) VALUES (:e, :c) RETURNING id"),
                                   dict(e=ev, c=cat)).scalar())
        ath = c.execute(text("INSERT INTO athletes (display_name) VALUES ('Coverage Driver') RETURNING id")).scalar()
        rd = c.execute(text("INSERT INTO rounds (race_id, kind, ordinal) VALUES (:r, 'final', 1) RETURNING id"),
                       dict(r=races[0])).scalar()
        c.execute(text("INSERT INTO results (round_id, athlete_id, position, status) VALUES (:r, :a, 1, 'OK')"),
                  dict(r=rd, a=ath))
        for tok, ex, race, pred, params, resolved, end in (
                ("cov-p1", "polymarket", races[0], "race_win", None, True, None),
                ("cov-p2", "polymarket", races[1], "race_win", None, None, None),
                ("cov-k1", "kalshi", races[0], "unmodeled", '{"kind": "race_top5"}', False, None),
                ("cov-c1", "polymarket", None, "champion", None, None, f"{SEASON}-12-01")):
            c.execute(text("""INSERT INTO market_links (token_id, exchange, prediction, question, outcome, competition_id,
                                  race_id, params, resolved_yes, closed, end_date)
                              VALUES (:t, :x, :p, 'q', 'Yes', :c, :r, CAST(:pa AS jsonb), :ry, :cl, :e)"""),
                      dict(t=tok, x=ex, p=pred, c=comp, r=race, pa=params, ry=resolved, cl=resolved is not None, e=end))
        c.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES ('cov-p2', :t, 0.4)"),
                  dict(t=f"{SEASON}-03-13T12:00:00+00:00"))
        c.execute(text("INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks) "
                       "VALUES ('cov-k1', :t, 0.2, 0.3, '[]', '[]')"), dict(t=f"{SEASON}-03-06T12:00:00+00:00"))
    yield test_engine
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_price_history WHERE token_id LIKE 'cov-%'"))
        c.execute(text("DELETE FROM market_book_snapshots WHERE token_id LIKE 'cov-%'"))
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'cov-%'"))
        c.execute(text("DELETE FROM results WHERE athlete_id = :a"), dict(a=ath))
        c.execute(text("DELETE FROM athletes WHERE id = :a"), dict(a=ath))
        c.execute(text("DELETE FROM events WHERE season_id = :s"), dict(s=sid))
        c.execute(text("DELETE FROM seasons WHERE id = :s"), dict(s=sid))
        c.execute(text("DELETE FROM categories WHERE id = :c"), dict(c=cat))


@pytest.fixture
def archive(tmp_path):
    """One exchange tree with an archived price for cov-p1 (not in Postgres)."""
    root = tmp_path / "polymarket"
    store._write("prices", pd.DataFrame(dict(token_id=["cov-p1"], ts=[f"{SEASON}-03-06T12:00:00Z"], price=[0.3])), root)
    return root


def test_coverage_counts_links_settlements_and_tape(season, archive):
    with season.connect() as c:
        res = COV.run(c, root=archive, seasons=[SEASON])
    combos = res["combos"].set_index(["sport", "exchange", "kind", "season"])
    win = combos.loc[("f1", "polymarket", "race_win", SEASON)]
    assert (win["links"], win["races"], win["settled_races"], win["price_races"], win["trade_races"],
            win["book_races"]) == (2, 2, 1, 2, 0, 0)          # one price archived, one still in Postgres
    assert (win["tier"], win["maker_tier"], win["modeled"], win["unmodeled_links"]) == ("thin", "missing", "yes", 0)
    top5 = combos.loc[("f1", "kalshi", "race_top5", SEASON)]   # an unmodeled link counts under its params kind
    assert (top5["links"], top5["settled_races"], top5["price_races"], top5["book_races"]) == (1, 1, 0, 1)
    assert (top5["tier"], top5["maker_tier"], top5["modeled"], top5["unmodeled_links"]) == ("missing", "thin", "no", 1)
    assert len(combos) == 2

    fut = res["futures"].set_index(["sport", "exchange", "kind"])
    assert fut.loc[("f1", "polymarket", "champion"), ["links", "open", "settled", "price_links"]].tolist() == [1, 1, 0, 0]

    r = res["results"].set_index("sport")
    assert list(r.index) == list(sports.SPORT_CODES)
    f1 = r.loc["f1"]
    assert (f1["events"], f1["events_with_results"], f1["first_season"], f1["last_season"]) == (2, 1, SEASON, SEASON)
    assert (f1["results_source"], f1["source_modules"], f1["cleared"]) == ("f1timing", "fastf1", "yes")
    assert r.loc["nascar", "fallbacks"] == "wikipedia (summary_only)"
    assert (r.loc["indycar", "cleared"], r.loc["indycar", "source_modules"]) == ("no", "indycar")
    assert r.loc["mtb_dh", "cleared"] == "yes"                  # no declared source, but its pricing model trains on it

    w = res["where"]
    assert w["trees"] == [str(archive)] and w["prices"]["parquet"] == 1 and w["books"]["postgres"] >= 1
    out = COV.format_text(res)
    assert "=== Race markets" in out and "=== Results depth and sources" in out


def test_coverage_writes_nothing(season, archive, tmp_path):
    def snapshot(c):
        return [c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                for t in ("market_links", "market_price_history", "market_book_snapshots", "results", "data_changes")]
    with season.connect() as c:
        before = snapshot(c)
        res = COV.run(c, root=archive, seasons=[SEASON])
        assert snapshot(c) == before
    out = COV.write(res, tmp_path / "out")
    assert sorted(p.name for p in out.iterdir()) == ["coverage_combos.csv", "coverage_futures.csv", "coverage_results.csv"]
