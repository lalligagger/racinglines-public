"""C51 `racinglines data pull SPORT` and C53 `racinglines remote` (owner, 2026-10-14: raw exchange history may reach
signed-in users; the terms-pending warning stays): a pull through the hosted server on the test database into a second,
fresh database and data folder, the same rows and ids on both sides, a top-up, and what a pull never holds."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from test_book_slips import hosted  # noqa: F401  (the hosted MCP server fixture)

from racinglines import paths
from racinglines.cli import remote as RM
from racinglines.db import pull as PL
from racinglines.markets import store as MS

KEY = "pull-test-1"


@pytest.fixture
def target(test_engine):
    """A second database built from the migrations and seeded like `racinglines db init`: its registry ids differ from
    the served one's, as on a user's machine."""
    from alembic import command
    from alembic.config import Config

    from conftest import ROOT
    from racinglines.db import ingest
    from sqlalchemy.orm import sessionmaker
    url = test_engine.url.set(database="racinglines_test_pull").render_as_string(hide_password=False)
    admin = create_engine(test_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text('DROP DATABASE IF EXISTS "racinglines_test_pull" WITH (FORCE)'))
        c.execute(text('CREATE DATABASE "racinglines_test_pull"'))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    with eng.begin() as c:                               # ids the served database doesn't use
        c.execute(text("SELECT setval(pg_get_serial_sequence('sports', 'id'), 500)"))
    with sessionmaker(eng)() as s:
        ingest.seed(s)
        s.commit()
    from racinglines.db import config
    config.get_engine.cache_clear()
    yield url, eng
    eng.dispose()
    config.get_engine.cache_clear()
    with admin.connect() as c:
        c.execute(text('DROP DATABASE IF EXISTS "racinglines_test_pull" WITH (FORCE)'))


@pytest.fixture
def served(test_engine, tmp_path, monkeypatch):
    """One F1 event with a result, a model run, a candidate, a Kalshi market link with prices in Postgres and in the
    archive, and a user's paper position, on the served database; the server's and the client's data folders apart."""
    from racinglines.db import ingest
    from sqlalchemy.orm import sessionmaker
    server_data, client_data = tmp_path / "server", tmp_path / "client"
    monkeypatch.setattr(paths, "DATA", server_data)
    monkeypatch.setattr(MS, "ROOT", server_data / "archive" / "markets" / "polymarket")
    monkeypatch.setattr(PL, "DIR", client_data / "pulls")
    monkeypatch.setattr(PL, "STATE", client_data / "pulls" / "state.json")
    monkeypatch.setattr(PL, "SERVER_DIR", server_data / "pulls" / "server")
    with sessionmaker(test_engine)() as s:
        ingest.seed(s)
        s.commit()
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        cat = c.execute(text("SELECT id FROM categories WHERE competition_id = :c ORDER BY id LIMIT 1"), dict(c=comp)).scalar()
        sea = c.execute(text("""INSERT INTO seasons (competition_id, year) VALUES (:c, 2026)
                                ON CONFLICT (competition_id, year) DO UPDATE SET year = 2026 RETURNING id"""), dict(c=comp)).scalar()
        ev = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date) VALUES (:s, 'test', :k,
                               'Pull GP', :d) ON CONFLICT (season_id, source, source_key) DO UPDATE SET name = 'Pull GP'
                               RETURNING id"""), dict(s=sea, k=KEY, d=date.today() - timedelta(days=3))).scalar()
        race = c.execute(text("""INSERT INTO races (event_id, category_id) VALUES (:e, :c)
                                 ON CONFLICT (event_id, category_id) DO UPDATE SET event_id = :e RETURNING id"""),
                         dict(e=ev, c=cat)).scalar()
        rnd = c.execute(text("""INSERT INTO rounds (race_id, kind, ordinal) VALUES (:r, 'race', 1)
                                ON CONFLICT (race_id, kind) DO UPDATE SET ordinal = 1 RETURNING id"""), dict(r=race)).scalar()
        ath = c.execute(text("INSERT INTO athletes (display_name) VALUES ('Pull Driver') RETURNING id")).scalar()
        c.execute(text("""INSERT INTO results (round_id, athlete_id, position, status) VALUES (:r, :a, 1, 'OK')
                          ON CONFLICT (round_id, athlete_id) DO NOTHING"""), dict(r=rnd, a=ath))
        run = c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                                VALUES (:c, 'pull', 'forecast', '{"a": 1}', '{}') RETURNING id"""), dict(c=comp)).scalar()
        c.execute(text("""INSERT INTO race_predictions (model_run_id, race_id, athlete_id, target, win_prob)
                          VALUES (:m, :r, :a, 'race', 0.4)"""), dict(m=run, r=race, a=ath))
        cand = c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                                 VALUES (:c, 'pull', 'candidate', '{}', '{}') RETURNING id"""), dict(c=comp)).scalar()
        c.execute(text("""INSERT INTO market_links (exchange, question, token_id, outcome, competition_id, race_id, prediction)
                          VALUES ('kalshi', 'q', 'PULL-TOK', 'Yes', :c, :r, 'race_win')"""), dict(c=comp, r=race))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        c.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES ('PULL-TOK', :t, 0.41)"), dict(t=now))
        uid = c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('pull_user', 'x', 'pro') RETURNING id")).scalar()
        c.execute(text("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, yes_shares, cash, venue)
                          VALUES (:u, :k, 'PULL-TOK', 'race_win', 1, -0.4, 'kalshi')"""), dict(u=uid, k=KEY))
    MS._write("prices", pd.DataFrame([dict(token_id="PULL-TOK", ts=pd.Timestamp("2026-09-19T12:00Z"), price=0.38)]),
              root=MS.root_for("kalshi"))
    real_load = PL.load

    def load(engine, folder, **kw):                     # the client writes its own data folder
        monkeypatch.setattr(paths, "DATA", client_data)
        monkeypatch.setattr(MS, "ROOT", client_data / "archive" / "markets" / "polymarket")
        try:
            return real_load(engine, folder, **kw)
        finally:
            monkeypatch.setattr(paths, "DATA", server_data)
            monkeypatch.setattr(MS, "ROOT", server_data / "archive" / "markets" / "polymarket")
    monkeypatch.setattr(PL, "load", load)
    yield dict(ev=ev, race=race, ath=ath, run=run, cand=cand, client=client_data)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM paper_positions WHERE user_id = :u"), dict(u=uid))
        c.execute(text("DELETE FROM users WHERE id = :u"), dict(u=uid))
        c.execute(text("DELETE FROM market_price_history WHERE token_id = 'PULL-TOK'"))
        c.execute(text("DELETE FROM market_links WHERE token_id = 'PULL-TOK'"))
        c.execute(text("DELETE FROM model_runs WHERE model = 'pull'"))
        c.execute(text("DELETE FROM events WHERE id = :e"), dict(e=ev))


def test_a_pull_copies_one_sport_with_its_ids_and_nothing_of_the_accounts(test_engine, hosted, served, target,  # noqa: F811
                                                                           monkeypatch, capsys):
    from racinglines.cli import pull as CLI
    monkeypatch.setattr(RM, "_warned", False)
    url, tok = hosted
    db, eng = target
    monkeypatch.setenv("RACINGLINES_MCP_TOKEN", tok)
    monkeypatch.setattr(PL, "CHUNK", 700)               # several chunks per file
    assert CLI.main(["f1", "--db", db, "--mcp-url", url]) == 0
    err = capsys.readouterr().err
    assert "#aintcare" in err and "fresh-database load" in err             # the warning stays (owner, 2026-10-14)
    with eng.connect() as c:
        assert c.execute(text("SELECT id FROM events WHERE source_key = :k"), dict(k=KEY)).scalar() == served["ev"]
        assert c.execute(text("SELECT count(*) FROM results r JOIN rounds ro ON ro.id = r.round_id WHERE ro.race_id = :r"),
                         dict(r=served["race"])).scalar() == 1
        assert c.execute(text("SELECT params FROM model_runs WHERE id = :i"), dict(i=served["run"])).scalar() == {"a": 1}
        assert c.execute(text("SELECT count(*) FROM model_runs WHERE id = :i"), dict(i=served["cand"])).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM users WHERE username = 'pull_user'")).scalar() == 0  # never accounts
        assert c.execute(text("SELECT count(*) FROM paper_positions")).scalar() == 0          # nor positions
        assert c.execute(text("SELECT count(*) FROM market_links WHERE token_id = 'PULL-TOK'")).scalar() == 1
    got = MS.read(None, "prices", tokens=["PULL-TOK"], root=served["client"] / "archive" / "markets" / "kalshi")
    assert sorted(got["price"]) == [0.38, 0.41]                     # the archive's row and Postgres' recent one
    assert PL.last_pull(db, "f1") is not None
    # a top-up: upserts by id (no fresh-database load), from where the last pull stopped
    with test_engine.begin() as c:
        c.execute(text("UPDATE events SET name = 'Pull GP (renamed)' WHERE id = :e"), dict(e=served["ev"]))
    assert CLI.main(["f1", "--since", "last", "--no-markets", "--db", db, "--mcp-url", url]) == 0
    assert "fresh-database load" not in capsys.readouterr().err
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM events WHERE id = :e"), dict(e=served["ev"])).scalar() == "Pull GP (renamed)"


def test_a_first_pull_refuses_a_database_with_model_runs(hosted, served, target, monkeypatch, capsys):  # noqa: F811
    from racinglines.cli import pull as CLI
    url, tok = hosted
    db, eng = target
    monkeypatch.setenv("RACINGLINES_MCP_TOKEN", tok)
    with eng.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        c.execute(text("INSERT INTO model_runs (competition_id, model, kind) VALUES (:c, 'mine', 'forecast')"), dict(c=comp))
    assert CLI.main(["f1", "--no-markets", "--db", db, "--mcp-url", url]) == 2
    assert "fresh database" in capsys.readouterr().err
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM model_runs WHERE model = 'mine'")).scalar() == 1   # left alone


def test_pull_files_are_only_the_manifests(test_engine, served):
    with test_engine.connect() as c:
        m = PL.manifest(c, "f1")
        with pytest.raises(ValueError, match="not a file"):
            PL.build(c, m["pull_id"], "../../etc/passwd")
        with pytest.raises(ValueError, match="unknown or expired"):
            PL.build(c, "f1-0000", "tables/events.parquet")
    names = {f["name"] for f in m["files"]}
    assert "tables/events.parquet" in names and not {n for n in names if "users" in n or "positions" in n}
    assert any(n.startswith("markets/kalshi/prices/month=2026-09") for n in names)


def test_remote_call_and_its_typed_arguments(hosted, served, monkeypatch, tmp_path, capsys):  # noqa: F811
    url, tok = hosted
    monkeypatch.setenv("RACINGLINES_MCP_TOKEN", tok)
    monkeypatch.setattr(RM, "_warned", False)
    assert RM.main(["call", "get_market_history", "--tokens", "PULL-TOK", "--series", "prices", "--mcp-url", url]) == 0
    got = capsys.readouterr()
    assert '"PULL-TOK"' in got.out and "#aintcare" in got.err               # raw exchange prices (owner, 2026-10-14)
    out = tmp_path / "rows.csv"
    assert RM.main(["call", "list_markets", "--race-id", str(served["race"]), "--csv", str(out), "--mcp-url", url]) == 0
    assert out.exists() and "rows ->" in capsys.readouterr().err
    assert RM.main(["call", "list_markets", "--nope", "1", "--mcp-url", url]) == 2
    assert "not an argument" in capsys.readouterr().err
    assert RM.main(["call", "no_such_tool", "--mcp-url", url]) == 2


@pytest.mark.quick
def test_job_knobs_come_from_the_servers_catalog():
    cat = [dict(job_type="f1_sweep", knobs=[dict(name="year"), dict(name="settings")]),
           dict(job_type="f1_diagnostic", knobs=[dict(name="event"), dict(name="cutoff"), dict(name="half_life")])]
    assert RM.knob_params("f1_sweep", ["--year", "2025", "--set", "min_edge=0.05", "--remote"], cat) == \
        ("f1_sweep", dict(year="2025", settings=dict(min_edge=0.05)))
    assert RM.knob_params("f1_diagnostic", ["--event=2026-15", "--half-life", "90"], cat)[1] == \
        dict(event="2026-15", half_life="90")
    with pytest.raises(RM.RemoteError, match="--cutoff"):
        RM.knob_params("f1_diagnostic", ["--sims", "10"], cat)
    with pytest.raises(RM.RemoteError, match="no job"):
        RM.knob_params("f1_nope", [], cat)
    assert "strategy sweep f1" in RM.runs_remotely() and "model diagnostic f1" in RM.runs_remotely()
